#!/usr/bin/env python3
"""FeatureTile encoder for the live OSM sidecar.

Differences from osm_tile_codec.build_osm_tile (which stays unchanged for the
pinned tile packs):

* every feature carries a unique place ID (Feature field 1). The 1.1.116 client
  keeps one GameObject per (tile, place ID) in GameObjectManager and skips
  features whose ID is already loaded for that tile (IsFeatureLoadedFromTile).
  Without IDs only the first road of each tile was drawn;
* all clipped pieces of one OSM way form one feature with several lines, and the
  ID ``osm-way-<id>`` is stable across tiles;
* parks, forests, beaches and water are Region/Water features with triangulated
  areas, rivers are Water lines, and buildings are Structure features with one
  extruded area (see osm_area_geometry.py).

The highway classification is the same authored test mapping as
osm_tile_codec.HIGHWAY_FEATURE_TYPES; it is not recovered historical game data.
"""
from __future__ import annotations

import math
from collections import Counter

from osm_area_geometry import clip_polygon, encode_area, encode_extruded_area
from osm_tile_codec import (
    ATTRIBUTION,
    HIGHWAY_FEATURE_TYPES,
    _tile_coordinates,
    _tile_point,
    validate_tile_address,
    way_paths,
)
from road_tile_codec import _bytes_field, _packed_sint64_field, _string_field, _varint_field

VERSION_ID = "osm-live-01"
PLACE_ID_FIELD = 1
TYPE_FIELD = 2
GEOMETRY_FIELD = 3
DISPLAY_NAME_FIELD = 4

# FeatureType values from the 1.1.116 metadata; the decoder dispatches on the top nibble
# (1 Structure, 2 Segment, 3 Region, 4 Water) and DecodeRegion maps 49/50/51.
AREA_FEATURE_TYPES = {"building": 1, "park": 49, "beach": 50, "forest": 51, "water": 4}
WATER_FEATURE_TYPE = 4
# Classes whose areas carry external-edge flags; the client draws an outline band along
# flagged edges. Adjusted from device comparisons against reference gameplay screenshots.
AREA_EXTERNAL_EDGES = {"building": True, "park": True, "beach": True, "forest": True, "water": True}
# Draw order hint for overlapping land cover (Area.z_order).
AREA_Z_ORDER = {"forest": 1, "park": 2, "beach": 3, "water": 4, "building": 5}


def _line(points: tuple[tuple[int, int], ...]) -> bytes:
    """Encode Line.vertex_offsets (field 1) as packed x and y deltas from the tile origin."""
    x_offsets, y_offsets = [], []
    previous_x = previous_y = 0
    for x, y in points:
        x_offsets.append(x - previous_x)
        y_offsets.append(y - previous_y)
        previous_x, previous_y = x, y
    vertices = _packed_sint64_field(1, tuple(x_offsets)) + _packed_sint64_field(2, tuple(y_offsets))
    return _bytes_field(1, vertices)


def encode_feature(place_id: str, feature_type: int, lines, display_name: str | None = None,
                   geometry: bytes | None = None) -> bytes:
    if geometry is None:
        geometry = b"".join(_bytes_field(2, _line(points)) for points in lines)  # Geometry.lines
    feature = _string_field(PLACE_ID_FIELD, place_id)
    feature += _varint_field(TYPE_FIELD, feature_type)
    feature += _bytes_field(GEOMETRY_FIELD, geometry)
    if display_name:
        feature += _string_field(DISPLAY_NAME_FIELD, display_name)
    return feature


def encode_tile(zoom: int, x: int, y: int, features) -> bytes:
    """features: iterable of (place_id, feature_type, lines, display_name[, geometry])."""
    raw = _string_field(1, f"tiles/@{x},{y},{zoom}z")
    raw += _bytes_field(2, _tile_coordinates(zoom, x, y))
    for place_id, feature_type, lines, display_name, *geometry in features:
        raw += _bytes_field(3, encode_feature(place_id, feature_type, lines, display_name,
                                              geometry[0] if geometry else None))
    raw += _bytes_field(5, _string_field(1, ATTRIBUTION))
    raw += _string_field(9, VERSION_ID)
    return raw


def area_geometry(element: dict, zoom: int, x: int, y: int) -> bytes | None:
    """Project, clip and encode one stored area element as Geometry bytes, or None."""
    kind = element.get("kind")
    try:
        rings = [[_tile_point(lat, lon, zoom, x, y) for lat, lon in ring]
                 for ring in element.get("rings") or ()]
    except (TypeError, ValueError):
        return None
    clipped = clip_polygon(rings)
    if clipped is None:
        return None
    area = encode_area(clipped, AREA_Z_ORDER.get(kind, 0),
                       external_edges=AREA_EXTERNAL_EDGES.get(kind, True))
    if area is None:
        return None
    if kind == "building":
        return _bytes_field(3, encode_extruded_area(area))  # Geometry.extruded_areas
    return _bytes_field(1, area)  # Geometry.areas


def _name(tags_or_element) -> str | None:
    name = tags_or_element.get("name")
    return name if isinstance(name, str) and name else None


FOOTPATH_TYPE = 34
ARTERIAL_TYPE = 531
LOCAL_ROAD_TYPE = 530
LOCAL_ROAD_CLASSES = {"tertiary", "tertiary_link", "unclassified"}
STREET_TYPES = {33, 530, 531, 532, 8513}
# OSM classes treated as paths: candidates for the street-parallel filter.
PATH_CLASSES = {"footway", "path", "cycleway", "steps", "bridleway"}
PAVED_SURFACES = {"asphalt", "paving_stones", "concrete", "concrete:plates", "paved", "sett",
                  "concrete:lanes", "chipseal"}


def _width_m(value) -> float:
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return 0.0


def road_feature_type(tags) -> int | None:
    """FeatureType for an OSM highway, promoting main park alleys and cycle paths.

    Only ArterialRoad and Highway segments are moved to the client's big-road layer
    (MapPresentationLayer segment DidCreate: layer 16 for usage 3 or 4), which draws the
    wide paved band. Reference screenshots from the Silesian Park show main alleys and a
    cycle path drawn that way, while ordinary paths stay thin.
    """
    highway = tags.get("highway")
    if highway in ("pedestrian", "cycleway"):
        return ARTERIAL_TYPE
    if highway in LOCAL_ROAD_CLASSES:
        # Reference screenshots show most town streets as thin paths; only county,
        # regional and national roads get the wide paved band.
        return LOCAL_ROAD_TYPE
    if highway in ("footway", "path", "bridleway") and tags.get("surface") in PAVED_SURFACES and (
            tags.get("name") or _width_m(tags.get("width")) >= 3):
        return ARTERIAL_TYPE
    return HIGHWAY_FEATURE_TYPES.get(highway)
PARALLEL_DISTANCE_M = 15.0
PARALLEL_MAX_ANGLE = math.radians(25)
PARALLEL_SHARE = 0.6


def _tile_metres_per_unit(zoom: int, y: int) -> float:
    latitude = math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / (1 << zoom))))
    return 40075016.686 * math.cos(latitude) / (1 << zoom) / 4096


def _segments(lines):
    for line in lines:
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            if (x0, y0) != (x1, y1):
                yield x0, y0, x1, y1


def _point_segment_distance(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _undirected_angle(ax, ay, bx, by):
    angle = abs(math.atan2(ay, ax) - math.atan2(by, bx)) % math.pi
    return min(angle, math.pi - angle)


def drop_parallel_footpaths(roads, zoom: int, y: int, candidates=None):
    """Remove footpaths that mostly run alongside a street (separately mapped sidewalks).

    OSM maps many sidewalks and cycle tracks as independent ways; the original Google
    tiles drew one line per street. A footpath is dropped when at least 60 % of its
    sampled length lies within 15 m of, and within 25 degrees of, a street segment.
    """
    limit = PARALLEL_DISTANCE_M / _tile_metres_per_unit(zoom, y)
    cell = max(64, int(limit * 2))
    buckets: dict[tuple[int, int], list] = {}
    def is_candidate(road):
        return road[0] in candidates if candidates is not None else road[1] == FOOTPATH_TYPE

    for road in roads:
        _place, feature_type, lines, _name = road
        if feature_type not in STREET_TYPES or is_candidate(road):
            continue
        for segment in _segments(lines):
            x0, y0, x1, y1 = segment
            for cx in range(int(min(x0, x1) - limit) // cell, int(max(x0, x1) + limit) // cell + 1):
                for cy in range(int(min(y0, y1) - limit) // cell, int(max(y0, y1) + limit) // cell + 1):
                    buckets.setdefault((cx, cy), []).append(segment)
    if not buckets:
        drop_parallel_footpaths.last_dropped_types = Counter()
        return roads, 0
    step = max(8.0, limit / 3)
    kept, dropped = [], 0
    dropped_types = Counter()
    for road in roads:
        if not is_candidate(road):
            kept.append(road)
            continue
        samples = parallel = 0
        for x0, y0, x1, y1 in _segments(road[2]):
            length = math.hypot(x1 - x0, y1 - y0)
            count = max(1, int(length / step))
            for k in range(count):
                t = (k + 0.5) / count
                px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
                samples += 1
                for sx0, sy0, sx1, sy1 in buckets.get((int(px) // cell, int(py) // cell), ()):
                    if (_point_segment_distance(px, py, sx0, sy0, sx1, sy1) <= limit and
                            _undirected_angle(x1 - x0, y1 - y0, sx1 - sx0, sy1 - sy0) <= PARALLEL_MAX_ANGLE):
                        parallel += 1
                        break
        if samples and parallel / samples >= PARALLEL_SHARE:
            dropped += 1
            dropped_types[road[1]] += 1
        else:
            kept.append(road)
    drop_parallel_footpaths.last_dropped_types = dropped_types
    return kept, dropped


def build_live_tile(document: dict, zoom: int, x: int, y: int) -> tuple[bytes, dict]:
    """Convert an Overpass-shaped document into one FeatureTile for zoom/x/y."""
    validate_tile_address(zoom, x, y)
    areas, water_lines, roads = [], [], []
    path_ids: set[str] = set()
    seen = set()
    types = Counter()
    for element in document.get("elements", ()):
        if not isinstance(element, dict):
            continue
        if element.get("type") == "area":
            feature_type = AREA_FEATURE_TYPES.get(element.get("kind"))
            if feature_type is None or ("area", element.get("id")) in seen:
                continue
            seen.add(("area", element.get("id")))
            geometry = area_geometry(element, zoom, x, y)
            if geometry is None:
                continue
            place_id = f"osm-area-{element.get('osm_area', element.get('id'))}-{element.get('id')}"
            areas.append((place_id, feature_type, (), _name(element), geometry))
            types[feature_type] += 1
            continue
        if element.get("type") != "way":
            continue
        way_id = element.get("id")
        if ("way", way_id) in seen:
            continue
        seen.add(("way", way_id))
        tags = element.get("tags") or {}
        geometry = element.get("geometry")
        if not isinstance(geometry, list):
            continue
        feature_type = road_feature_type(tags)
        target = roads
        if feature_type is None and tags.get("waterway") in ("river", "canal"):
            feature_type, target = WATER_FEATURE_TYPE, water_lines
        if feature_type is None:
            continue
        lines = way_paths(geometry, zoom, x, y)
        if not lines:
            continue
        target.append((f"osm-way-{way_id}", feature_type, lines, _name(tags)))
        if target is roads and tags.get("highway") in PATH_CLASSES:
            path_ids.add(f"osm-way-{way_id}")
        types[feature_type] += 1
    roads, dropped_parallel = drop_parallel_footpaths(roads, zoom, y, path_ids)
    types.subtract(drop_parallel_footpaths.last_dropped_types)
    # Land cover and buildings first, then rivers, then roads.
    features = areas + water_lines + roads
    raw = encode_tile(zoom, x, y, features)
    return raw, {"feature_count": len(features),
                 "line_count": sum(len(f[2]) for f in water_lines + roads),
                 "area_count": len(areas),
                 "dropped_parallel_footpaths": dropped_parallel,
                 "feature_type_counts": dict(sorted(types.items())), "bytes": len(raw)}


def build_area_canary(zoom: int, x: int, y: int, cell: int = 512,
                      kinds=("forest", "park", "water", "building", "beach")) -> tuple[bytes, int]:
    """Invented diagnostic land cover with one shape per class; not map data.

    Forest: full cell square; park: octagon; water: triangle; building: small
    centred square; beach: plus sign. Classes rotate along each row.
    """
    features = []
    for row in range(4096 // cell):
        for column in range(4096 // cell):
            kind = kinds[(row + column) % len(kinds)]
            x0, y0 = column * cell + 48, row * cell + 48
            size = cell - 96
            if kind == "forest":
                ring = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
            elif kind == "park":
                c, r = size // 2, size // 2
                ring = [(x0 + c + round(r * math.cos(k * math.pi / 4)),
                         y0 + c + round(r * math.sin(k * math.pi / 4))) for k in range(8)]
            elif kind == "water":
                ring = [(x0, y0 + size), (x0 + size // 2, y0), (x0 + size, y0 + size)]
            elif kind == "building":
                q = size // 4
                ring = [(x0 + q, y0 + q), (x0 + 3 * q, y0 + q), (x0 + 3 * q, y0 + 3 * q), (x0 + q, y0 + 3 * q)]
            else:
                t = size // 3
                ring = [(x0 + t, y0), (x0 + 2 * t, y0), (x0 + 2 * t, y0 + t), (x0 + size, y0 + t),
                        (x0 + size, y0 + 2 * t), (x0 + 2 * t, y0 + 2 * t), (x0 + 2 * t, y0 + size),
                        (x0 + t, y0 + size), (x0 + t, y0 + 2 * t), (x0, y0 + 2 * t), (x0, y0 + t),
                        (x0 + t, y0 + t)]
            area = encode_area([ring], AREA_Z_ORDER[kind], external_edges=AREA_EXTERNAL_EDGES[kind])
            geometry = _bytes_field(3, encode_extruded_area(area)) if kind == "building" else _bytes_field(1, area)
            features.append((f"canary-{kind}-{row}-{column}", AREA_FEATURE_TYPES[kind], (), None, geometry))
    return encode_tile(zoom, x, y, features), len(features)


def build_river_canary(zoom: int, x: int, y: int) -> tuple[bytes, int]:
    """Invented diagnostic water: a strip crossing the tile like a river plus a lake inside it."""
    from osm_area_geometry import clip_polygon
    strip = clip_polygon([[(1200, -300), (2600, -300), (2600, 4400), (1200, 4400)]])
    lake = [[(3000, 400), (3900, 500), (3800, 1500), (3100, 1400)]]
    features = [("canary-river", 4, (), None, _bytes_field(1, encode_area(strip, 4))),
                ("canary-lake", 4, (), None, _bytes_field(1, encode_area(lake, 4)))]
    return encode_tile(zoom, x, y, features), len(features)


def build_grid_canary(zoom: int, x: int, y: int, types=(530, 530, 531), spacing: int = 512) -> tuple[bytes, int]:
    """Invented diagnostic grid with unique IDs; not map data."""
    horizontal, vertical, diagonal = types
    features = []
    for index, offset in enumerate(range(spacing // 2, 4096, spacing)):
        features.append((f"canary-h{index}", horizontal, [((0, offset), (4096, offset))], None))
        features.append((f"canary-v{index}", vertical, [((offset, 0), (offset, 4096))], None))
    features.append(("canary-d", diagonal, [((0, 0), (4096, 4096))], None))
    return encode_tile(zoom, x, y, features), len(features)
