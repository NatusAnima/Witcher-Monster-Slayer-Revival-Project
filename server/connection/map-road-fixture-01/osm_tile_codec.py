#!/usr/bin/env python3
"""Convert one bounded Overpass JSON extract into a legacy FeatureTile subset.

The converter never contacts a network. Input and output paths and the tile
address are explicit so a caller controls which local OSM extract is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from collections import Counter

from road_tile_codec import (
    _bytes_field,
    _road_feature,
    _string_field,
    _varint_field,
)


ATTRIBUTION = "© OpenStreetMap contributors"
LICENSE = "Open Database License (ODbL) v1.0"
VERSION_ID = "osm-poznan-core-01"
MAX_ZOOM = 22
EXTENT = 4096
MERCATOR_MAX_LAT = 85.0511287798066

# This is a deliberately coarse rendering mapping for the client probe. It is
# not a historical Monster Slayer classification table.
HIGHWAY_FEATURE_TYPES = {
    "motorway": 532,
    "motorway_link": 532,
    "trunk": 532,
    "trunk_link": 532,
    "primary": 532,
    "primary_link": 532,
    "secondary": 531,
    "secondary_link": 531,
    "tertiary": 531,
    "tertiary_link": 531,
    "unclassified": 531,
    "residential": 530,
    "living_street": 530,
    "service": 530,
    "road": 530,
    "track": 530,
    "footway": 34,
    "path": 34,
    "pedestrian": 34,
    "steps": 34,
    "cycleway": 34,
    "bridleway": 34,
}


def validate_tile_address(zoom: int, x: int, y: int) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (zoom, x, y)):
        raise ValueError("zoom, x, and y must be integers")
    if not 0 <= zoom <= MAX_ZOOM:
        raise ValueError("zoom is outside the supported test range")
    limit = 1 << zoom
    if not 0 <= x < limit or not 0 <= y < limit:
        raise ValueError("tile x/y are outside the zoom range")


def _tile_point(lat: float, lon: float, zoom: int, x: int, y: int) -> tuple[float, float]:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("OSM coordinates must be finite")
    if not -MERCATOR_MAX_LAT <= lat <= MERCATOR_MAX_LAT or not -180 <= lon <= 180:
        raise ValueError("OSM coordinate is outside Web Mercator bounds")
    scale = 1 << zoom
    global_x = (lon + 180.0) / 360.0 * scale
    latitude_radians = math.radians(lat)
    global_y = (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2.0 * scale
    return (global_x - x) * EXTENT, (global_y - y) * EXTENT


def _clip_segment(first: tuple[float, float], second: tuple[float, float]):
    """Clip a segment to the inclusive 0..4096 tile rectangle."""
    x0, y0 = first
    x1, y1 = second
    dx, dy = x1 - x0, y1 - y0
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, EXTENT - x0), (-dy, y0), (dy, EXTENT - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return None
    return ((x0 + lower * dx, y0 + lower * dy),
            (x0 + upper * dx, y0 + upper * dy))


def _rounded(point: tuple[float, float]) -> tuple[int, int]:
    return (max(0, min(EXTENT, round(point[0]))),
            max(0, min(EXTENT, round(point[1]))))


def way_paths(geometry: list[dict], zoom: int, x: int, y: int) -> list[tuple[tuple[int, int], ...]]:
    """Project and clip one Overpass way geometry to the requested tile."""
    projected = []
    for point in geometry:
        try:
            projected.append(_tile_point(float(point["lat"]), float(point["lon"]), zoom, x, y))
        except (KeyError, TypeError, ValueError):
            projected.append(None)

    paths: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []

    def flush():
        nonlocal current
        compact = []
        for point in current:
            if not compact or compact[-1] != point:
                compact.append(point)
        if len(compact) >= 2:
            paths.append(tuple(compact))
        current = []

    for index in range(len(projected) - 1):
        first, second = projected[index:index + 2]
        if first is None or second is None:
            flush()
            continue
        clipped = _clip_segment(first, second)
        if clipped is None:
            flush()
            continue
        start, end = map(_rounded, clipped)
        if start == end:
            continue
        if not current or current[-1] != start:
            flush()
            current = [start, end]
        elif current[-1] != end:
            current.append(end)
    flush()
    return paths


def _tile_coordinates(zoom: int, x: int, y: int) -> bytes:
    # Recovered subset fields are x=1, y=2, zoom=3.
    return _varint_field(1, x) + _varint_field(2, y) + _varint_field(3, zoom)


def _feature_tile(name: str, zoom: int, x: int, y: int,
                  features: list[tuple[int, tuple[tuple[int, int], ...]]]) -> bytes:
    raw = _string_field(1, name) + _bytes_field(2, _tile_coordinates(zoom, x, y))
    for feature_type, points in features:
        raw += _bytes_field(3, _road_feature(feature_type, points))
    raw += _bytes_field(5, _string_field(1, ATTRIBUTION))
    raw += _string_field(9, VERSION_ID)
    return raw


def build_osm_tile(document: dict, zoom: int, x: int, y: int) -> tuple[bytes, dict]:
    validate_tile_address(zoom, x, y)
    if not isinstance(document, dict) or not isinstance(document.get("elements"), list):
        raise ValueError("Input must be an Overpass JSON object with an elements array")

    features: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    input_ways = 0
    mapped_ways = set()
    seen_way_ids = set()
    tags_seen = Counter()

    for element in document["elements"]:
        if not isinstance(element, dict) or element.get("type") != "way":
            continue
        input_ways += 1
        way_id = element.get("id")
        if way_id is not None and way_id in seen_way_ids:
            continue
        if way_id is not None:
            seen_way_ids.add(way_id)
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue
        highway = tags.get("highway")
        tags_seen[highway if isinstance(highway, str) else "unknown"] += 1
        feature_type = HIGHWAY_FEATURE_TYPES.get(highway)
        geometry = element.get("geometry")
        if feature_type is None or not isinstance(geometry, list):
            continue
        paths = way_paths(geometry, zoom, x, y)
        if paths:
            mapped_ways.add(way_id if way_id is not None else id(element))
            features.extend((feature_type, points) for points in paths)

    name = f"tiles/@{x},{y},{zoom}z"
    raw = _feature_tile(name, zoom, x, y, features)
    timestamp = None
    osm3s = document.get("osm3s")
    if isinstance(osm3s, dict):
        timestamp = osm3s.get("timestamp_osm_base")
    summary = {
        "status": "OSM_DERIVED_LOCAL_RENDERER_CANDIDATE",
        "tile": {"zoom": zoom, "x": x, "y": y},
        "tile_name": name,
        "input_way_count": input_ways,
        "mapped_way_count": len(mapped_ways),
        "feature_count": len(features),
        "feature_type_counts": dict(sorted(Counter(t for t, _ in features).items())),
        "source_highway_tag_counts": dict(sorted(tags_seen.items())),
        "osm_base_timestamp": timestamp,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "attribution": ATTRIBUTION,
        "license": LICENSE,
        "conversion_scope": "OSM highway lines clipped to one Web Mercator tile; authored enum mapping, not historical game data",
        "client_rendering": "unverified",
    }
    return raw, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Local Overpass JSON extract")
    parser.add_argument("--output", type=Path, required=True, help="New local FeatureTile output")
    parser.add_argument("--zoom", type=int, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh output path; existing files are never overwritten.")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    raw, summary = build_osm_tile(document, args.zoom, args.x, args.y)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(raw)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
