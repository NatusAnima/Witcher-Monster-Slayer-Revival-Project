#!/usr/bin/env python3
"""Build a local SQLite R-tree of OSM map features from an .osm.pbf extract.

Stored feature classes:
  ways        highway lines (roads, paths) and waterway=river/canal lines
  areas       parks, forests, beaches, water bodies and buildings, including
              multipolygon relations (one row per outer ring with its holes)
  coastlines  natural=coastline ways (land on their left): OSM has no sea areas,
              so the reader makes the sea of a tile from them (sea_rings)

The live sidecar then answers any tile inside the extract without a network
request. Building requires pyosmium (`pip install osmium`); reading uses only
the standard library.

Example:
  python osm_extract_index.py --input server/data/osm-extract-01/region.osm.pbf \
      --output server/data/osm-extract-01/region-features.sqlite
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import threading
import time

from osm_tile_codec import HIGHWAY_FEATURE_TYPES

SCHEMA_VERSION = "osm-feature-index-v4"
COORDINATE_SCALE = 10_000_000
WATER_LINE_CLASSES = {"river", "canal"}

# The client paints a soft band tens of metres wide around every region, so only features
# that Google's data showed as parks are kept; ubiquitous lawns, meadows, playgrounds,
# pitches, allotments and cemeteries would merge into one green blanket over a city.
PARK_TAGS = {
    "leisure": {"park", "garden", "golf_course", "recreation_ground", "common"},
    "landuse": {"recreation_ground"},
}
FOREST_TAGS = {"landuse": {"forest"}, "natural": {"wood"}}
BEACH_TAGS = {"natural": {"beach"}}
WATER_TAGS = {"natural": {"water"}, "landuse": {"reservoir", "basin"},
              "waterway": {"riverbank", "dock"}}
AREA_FILTER_VERSION = "google-like-regions-v1"
MIN_AREA_M2 = {"park": 2500.0, "forest": 2500.0, "beach": 1000.0, "water": 150.0, "building": 0.0}


def ring_area_m2(ring) -> float:
    """Approximate planar area of a (lat, lon) ring in square metres."""
    if len(ring) < 3:
        return 0.0
    mean_lat = sum(p[0] for p in ring) / len(ring)
    kx = 111320.0 * math.cos(math.radians(mean_lat))
    ky = 110540.0
    total = 0.0
    for index, (lat0, lon0) in enumerate(ring):
        lat1, lon1 = ring[(index + 1) % len(ring)]
        total += (lon0 * kx) * (lat1 * ky) - (lon1 * kx) * (lat0 * ky)
    return abs(total) / 2


# OSM maps sidewalks, crossings and parking lanes as separate ways; the original Google
# tiles drew one line per street, so these would show up as doubled or tripled paths.
ROAD_FILTER_VERSION = "no-sidewalks-v1"
SKIPPED_ROAD_SUBTAGS = {
    "footway": {"sidewalk", "crossing", "traffic_island", "access_aisle"},
    "service": {"parking_aisle", "driveway", "drive-through", "emergency_access"},
}


# Extra highway tags kept for the tile encoder's road classification.
WAY_ATTRIBUTES = ("surface", "width")


def skip_road(tags) -> bool:
    """True for highway ways that duplicate a street (sidewalks, crossings, parking lanes)."""
    for key, values in SKIPPED_ROAD_SUBTAGS.items():
        if tags.get(key) in values:
            return True
    # Pedestrian squares and other highway areas would otherwise draw their outline as a path.
    return tags.get("area") == "yes"


def classify_area(tags) -> str | None:
    """Map OSM area tags to the stored kind; buildings win over land cover."""
    building = tags.get("building")
    if building and building != "no":
        return "building"
    for kind, table in (("water", WATER_TAGS), ("forest", FOREST_TAGS),
                        ("beach", BEACH_TAGS), ("park", PARK_TAGS)):
        for key, values in table.items():
            if tags.get(key) in values:
                return kind
    return None


def pack_coordinates(points) -> bytes:
    """Pack (lat, lon) pairs as little-endian int32 degrees * 1e7."""
    flat = []
    for lat, lon in points:
        flat.append(round(lat * COORDINATE_SCALE))
        flat.append(round(lon * COORDINATE_SCALE))
    return struct.pack(f"<{len(flat)}i", *flat)


def unpack_coordinates(blob: bytes) -> list[tuple[float, float]]:
    values = struct.unpack(f"<{len(blob) // 4}i", blob)
    return [(values[i] / COORDINATE_SCALE, values[i + 1] / COORDINATE_SCALE)
            for i in range(0, len(values), 2)]


def pack_rings(rings) -> bytes:
    """Ring count, per-ring vertex counts, then all coordinates (outer ring first)."""
    header = struct.pack(f"<I{len(rings)}I", len(rings), *(len(r) for r in rings))
    return header + b"".join(pack_coordinates(r) for r in rings)


def unpack_rings(blob: bytes) -> list[list[tuple[float, float]]]:
    (count,) = struct.unpack_from("<I", blob)
    sizes = struct.unpack_from(f"<{count}I", blob, 4)
    offset = 4 + 4 * count
    rings = []
    for size in sizes:
        rings.append(unpack_coordinates(blob[offset:offset + 8 * size]))
        offset += 8 * size
    return rings


def _mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _mercator_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def clip_ring(ring, box, mercator=False):
    """Sutherland-Hodgman clip of one (lat, lon) ring to a (south, west, north, east) box.

    Vertices inside the box are kept as they are and in order; the ring may come back empty. A cut point lies on its
    edge as a straight line in lat/lon, or with [mercator] in Web Mercator, which is how a tile draws the edge: a long
    edge cut in lat/lon would bend inside the tile (hundreds of tile units for 20 km edges at 65 degrees).
    """
    south, west, north, east = box
    for axis, limit, keep_above in ((1, west, True), (1, east, False), (0, south, True), (0, north, False)):
        if not ring:
            break
        out = []
        previous = ring[-1]
        previous_in = previous[axis] >= limit if keep_above else previous[axis] <= limit
        for current in ring:
            current_in = current[axis] >= limit if keep_above else current[axis] <= limit
            if current_in != previous_in:
                if axis == 1:
                    t = (limit - previous[1]) / (current[1] - previous[1])
                    lat = (_mercator_lat(_mercator_y(previous[0]) + t * (_mercator_y(current[0]) - _mercator_y(previous[0])))
                           if mercator else previous[0] + t * (current[0] - previous[0]))
                    out.append((lat, limit))
                else:
                    t = ((_mercator_y(limit) - _mercator_y(previous[0])) / (_mercator_y(current[0]) - _mercator_y(previous[0]))
                         if mercator else (limit - previous[0]) / (current[0] - previous[0]))
                    out.append((limit, previous[1] + t * (current[1] - previous[1])))
            if current_in:
                out.append(current)
            previous, previous_in = current, current_in
        ring = out
    return ring


def clip_rings(rings, box, mercator=False):
    """Clip an outer ring and its holes to a box; None when nothing of the outer ring is left."""
    outer = clip_ring(rings[0], box, mercator)
    if len(outer) < 3:
        return None
    clipped = [outer]
    for hole in rings[1:]:
        hole = clip_ring(hole, box, mercator)
        if len(hole) >= 3:
            clipped.append(hole)
    return clipped


def _clip_line(points, x0, y0, x1, y1):
    """The parts of a polyline inside an (x0, y0, x1, y1) box (Liang-Barsky); a part ends on the box where it was cut."""
    parts, part = [], None
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if p == 0:
                if q < 0:
                    t0, t1 = 1.0, 0.0  # parallel to that edge and outside it
            elif p < 0:
                t0 = max(t0, q / p)
            else:
                t1 = min(t1, q / p)
        if t0 > t1:
            part = None
            continue
        start = a if t0 == 0 else (a[0] + t0 * dx, a[1] + t0 * dy)
        end = b if t1 == 1 else (a[0] + t1 * dx, a[1] + t1 * dy)
        if part is None or part[-1] != start:
            part = [start]
            parts.append(part)
        part.append(end)
        if t1 < 1:
            part = None
    return [p for p in parts if len(set(p)) > 1]


def _signed_area(ring) -> float:
    """Twice the signed area of an (x, y) ring: positive when it turns counter-clockwise (y up)."""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _inside(point, ring) -> bool:
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > point[1]) != (by > point[1]) and point[0] < ax + (point[1] - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def sea_rings(lines, box, seaward):
    """The sea inside a (south, west, north, east) box, from coastline ways ((lat, lon) lists, land on their left), as
    areas [[outer, *holes], ...] of (lat, lon) rings.

    The coastline is cut to the box in Web Mercator (as a tile draws it) and its pieces joined where they meet. The sea
    lies to the right of a piece, so from where one leaves the box the sea follows the box's edge clockwise to where the
    next one enters. A closed ring inside the box is an island (a hole), or water where it turns clockwise. A box no
    coastline crosses is all sea or all land: seaward(lat, lon) says which, for its north-west corner. A coastline that
    ends inside the box (where the extract was cut) leaves its side unknown, so the box gets no sea.
    """
    south, west, north, east = box
    x0, x1, y0, y1 = math.radians(west), math.radians(east), _mercator_y(south), _mercator_y(north)
    eps = (x1 - x0) * 1e-9

    def on_edge(p):
        return min(abs(p[0] - x0), abs(p[0] - x1), abs(p[1] - y0), abs(p[1] - y1)) <= eps

    def around(p):  # clockwise along the box's edge from its north-west corner, 0 <= t < 4
        x, y = p
        if abs(y - y1) <= eps and x < x1 - eps:
            return (x - x0) / (x1 - x0)
        if abs(x - x1) <= eps and y > y0 + eps:
            return 1 + (y1 - y) / (y1 - y0)
        if abs(y - y0) <= eps and x > x0 + eps:
            return 2 + (x1 - x) / (x1 - x0)
        return 3 + (y - y0) / (y1 - y0)

    parts = [part for line in lines
             for part in _clip_line([(math.radians(lon), _mercator_y(lat)) for lat, lon in line], x0, y0, x1, y1)]
    following = {part[0]: part for part in parts if not on_edge(part[0])}

    def follow(chain):  # on to the box's edge or back to its start; None at a loose end
        while not on_edge(chain[-1]):
            if len(chain) > 2 and chain[-1] == chain[0]:
                return chain
            nxt = following.pop(chain[-1], None)
            if nxt is None:
                return None
            chain.extend(nxt[1:])
        return chain

    crossing, closed = [], []
    for part in parts:
        if on_edge(part[0]):
            chain = follow(list(part))
            if chain is None:
                return []
            crossing.append(chain)
    while following:
        chain = follow(list(following.popitem()[1]))
        if chain is None or on_edge(chain[-1]):
            return []  # a coastline that begins inside the box
        closed.append(chain[:-1])

    corners = [(0, (x0, y1)), (1, (x1, y1)), (2, (x1, y0)), (3, (x0, y0))]
    starts = [(around(c[0]), n) for n, c in enumerate(crossing)]
    ends = [around(c[-1]) for c in crossing]
    outers, done = [], set()
    for first in range(len(crossing)):
        if first in done:
            continue
        ring, n = [], first
        while n not in done:
            done.add(n)
            ring.extend(crossing[n])
            t = ends[n]
            gap, n = min(((s - t) % 4, m) for s, m in starts)
            if any(0 < (e - t) % 4 < gap for e in ends):
                return []  # another piece leaves before the next one enters: a broken coastline
            ring.extend(point for d, point in sorted(((k - t) % 4, point) for k, point in corners) if 0 < d < gap)
        if n != first:
            return []
        outers.append(ring)
    if not crossing and seaward(north, west):
        outers.append([corner for _, corner in corners])
    outers += [ring for ring in closed if _signed_area(ring) < 0]
    areas = [[outer] for outer in outers]
    for hole in (ring for ring in closed if _signed_area(ring) > 0):
        area = next((a for a in areas if _inside(hole[0], a[0])), None)
        if area is not None:
            area.append(hole)
    return [[[(_mercator_lat(y), math.degrees(x)) for x, y in ring] for ring in area] for area in areas]


def coast_side(lines, lat: float, lon: float):
    """(metres to the nearest segment of the coastline ways, whether the point is on its sea side), or None without one.
    The sea is right of a coastline way; at a vertex both segments decide: right of either where the coast turns left,
    right of both where it turns right."""
    kx, ky = 111_320.0 * math.cos(math.radians(lat)), 110_540.0
    found = []  # (distance, position on the segment, cross product, direction)
    for line in lines:
        points = [((p_lon - lon) * kx, (p_lat - lat) * ky) for p_lat, p_lon in line]  # the point is the origin
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
            found.append((math.hypot(ax + t * dx, ay + t * dy), t, -dx * ay + dy * ax, (dx, dy)))
    if not found:
        return None
    nearest = min(f[0] for f in found)
    near = [f for f in found if f[0] <= nearest + 1e-6]
    middle = next((f for f in near if 0 < f[1] < 1), None)
    into, out = next((f for f in near if f[1] == 1), None), next((f for f in near if f[1] == 0), None)
    if middle is None and into is not None and out is not None:
        turn = into[3][0] * out[3][1] - into[3][1] * out[3][0]
        right = (into[2] < 0 or out[2] < 0) if turn > 0 else (into[2] < 0 and out[2] < 0)
        return nearest, right
    return nearest, (middle or near[0])[2] < 0


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE ways(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, class TEXT NOT NULL,
                          name TEXT, attrs TEXT, coords BLOB NOT NULL);
        CREATE VIRTUAL TABLE ways_rtree USING rtree(id, min_lon, max_lon, min_lat, max_lat);
        CREATE TABLE areas(row INTEGER PRIMARY KEY, osm_area INTEGER NOT NULL, kind TEXT NOT NULL,
                           name TEXT, rings BLOB NOT NULL);
        CREATE VIRTUAL TABLE areas_rtree USING rtree(row, min_lon, max_lon, min_lat, max_lat);
        CREATE TABLE coastlines(id INTEGER PRIMARY KEY, coords BLOB NOT NULL);
        CREATE VIRTUAL TABLE coastlines_rtree USING rtree(id, min_lon, max_lon, min_lat, max_lat);
    """)


def _bbox(points):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return min(lons), max(lons), min(lats), max(lats)


def parse_status(text: str) -> dict:
    """Memory figures in MB from /proc/self/status: resident (VmRSS), its anonymous and file-backed parts, and the peak."""
    wanted = {"VmRSS": "rss_mb", "RssAnon": "rss_anon_mb", "RssFile": "rss_file_mb", "VmHWM": "peak_mb"}
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in wanted:
            found[wanted[key]] = int(value.split()[0]) // 1024
    return found


def eta_seconds(pos0: int, pos: int, size: int, elapsed: float):
    """Seconds left in the features phase, from the share of the file read since it began; None until 5% of it is done.
    The node phase is 65% of the file but ~1% of the time, so only the part after it is timed."""
    total, done = size - pos0, pos - pos0
    if total <= 0 or done <= 0 or done / total < 0.05:
        return None
    return round(elapsed * (total - done) / done)


class FeatureProgress:
    """Prints a PROGRESS line every few seconds once the features phase starts (the first way() call). pyosmium holds the
    GIL through the node phase, so no thread can report from there: the caller says "reading the map" until this starts."""

    def __init__(self, path: Path, stats: dict, partial: Path, every: float = 2.0):
        # resolved, because /proc/self/fd/N names the real path (on Android /data/user/0 is a link to /data/data)
        self.path, self.stats, self.partial, self.every = os.path.realpath(path), stats, partial, every
        self.size = os.path.getsize(path)
        self.thread = None
        self.pos0 = 0
        self.began = 0.0

    def position(self):
        """The reader's offset in the file: `pos` of the open descriptor of the PBF (the second pass opens its own). None where
        /proc is not there."""
        best = None
        try:
            for fd in os.listdir("/proc/self/fd"):
                try:
                    if os.readlink(f"/proc/self/fd/{fd}") != self.path:
                        continue
                    with open(f"/proc/self/fdinfo/{fd}") as info:
                        for line in info:
                            if line.startswith("pos:"):
                                best = max(best or 0, int(line.split()[1]))
                except OSError:
                    continue
        except OSError:
            return None
        return best

    def start(self):
        self.began = time.monotonic()
        self.pos0 = self.position() or 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while True:
            time.sleep(self.every)
            self.report()

    def report(self):
        pos = self.position()
        line = {"phase": "features", "roads": self.stats["roads"], "areas": self.stats["areas"]}
        if pos is not None and self.size > self.pos0:
            line["percent"] = round(100 * max(0, pos - self.pos0) / (self.size - self.pos0), 1)
            eta = eta_seconds(self.pos0, pos, self.size, time.monotonic() - self.began)
            if eta is not None:
                line["eta"] = eta
        try:
            line["index_mb"] = os.path.getsize(self.partial) // 2**20
            with open("/proc/self/status") as status:
                line.update(parse_status(status.read()))
        except OSError:
            pass
        print("PROGRESS " + json.dumps(line), flush=True)


def build_index(input_path: Path, output_path: Path, low_memory: bool = False) -> dict:
    """low_memory keeps the node locations in a file next to the output (about twice the extract) instead of in RAM, where they
    take 16 bytes a node: a country-size extract needs several GB there, more than most phones have."""
    import osmium  # Imported here so the reader side stays dependency-free.

    if output_path.exists():
        raise SystemExit("Choose a fresh output path; existing indexes are never overwritten.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    node_index = output_path.with_suffix(output_path.suffix + ".nodes")
    if node_index.exists():
        node_index.unlink()
    db = sqlite3.connect(temporary)
    create_schema(db)
    stats = {"roads": 0, "skipped_roads": 0, "water_lines": 0, "coastlines": 0, "areas": 0, "skipped_small_areas": 0,
             "skipped_invalid": 0}
    progress = FeatureProgress(input_path, stats, temporary)
    area_kinds: dict[str, int] = {}
    ways, way_boxes, areas, area_boxes, coasts, coast_boxes = [], [], [], [], [], []
    next_area_row = [1]

    def flush():
        db.executemany("INSERT INTO ways VALUES (?,?,?,?,?,?)", ways)
        db.executemany("INSERT INTO ways_rtree VALUES (?,?,?,?,?)", way_boxes)
        db.executemany("INSERT INTO areas VALUES (?,?,?,?,?)", areas)
        db.executemany("INSERT INTO areas_rtree VALUES (?,?,?,?,?)", area_boxes)
        db.executemany("INSERT INTO coastlines VALUES (?,?)", coasts)
        db.executemany("INSERT INTO coastlines_rtree VALUES (?,?,?,?,?)", coast_boxes)
        for batch in (ways, way_boxes, areas, area_boxes, coasts, coast_boxes):
            batch.clear()

    def points_of(nodes):
        return [(node.location.lat, node.location.lon) for node in nodes]

    class Handler(osmium.SimpleHandler):
        def way(self, way):
            if progress.thread is None:
                progress.start()  # the first way means the node phase is over
            highway = way.tags.get("highway")
            waterway = way.tags.get("waterway")
            if way.tags.get("natural") == "coastline":
                try:
                    points = points_of(way.nodes)
                except osmium.InvalidLocationError:
                    stats["skipped_invalid"] += 1
                    return
                if len(points) >= 2:
                    coasts.append((way.id, pack_coordinates(points)))
                    coast_boxes.append((way.id, *_bbox(points)))
                    stats["coastlines"] += 1
                return
            if highway in HIGHWAY_FEATURE_TYPES:
                if skip_road(way.tags):
                    stats["skipped_roads"] += 1
                    return
                kind, klass = "road", highway
            elif waterway in WATER_LINE_CLASSES:
                kind, klass = "water_line", waterway
            else:
                return
            try:
                points = points_of(way.nodes)
            except osmium.InvalidLocationError:
                stats["skipped_invalid"] += 1
                return
            if len(points) < 2:
                return
            attrs = {key: way.tags.get(key) for key in WAY_ATTRIBUTES if way.tags.get(key)}
            ways.append((way.id, kind, klass, way.tags.get("name"),
                         json.dumps(attrs, separators=(",", ":")) if attrs else None,
                         pack_coordinates(points)))
            way_boxes.append((way.id, *_bbox(points)))
            stats["roads" if kind == "road" else "water_lines"] += 1
            if len(ways) >= 20000:
                flush()

        def area(self, area):
            kind = classify_area(area.tags)
            if kind is None:
                return
            name = area.tags.get("name")
            try:
                for outer in area.outer_rings():
                    rings = [points_of(outer)[:-1]]
                    for inner in area.inner_rings(outer):
                        rings.append(points_of(inner)[:-1])
                    if len(rings[0]) < 3:
                        continue
                    if ring_area_m2(rings[0]) < MIN_AREA_M2.get(kind, 0.0):
                        stats["skipped_small_areas"] += 1
                        continue
                    row = next_area_row[0]
                    next_area_row[0] += 1
                    areas.append((row, area.id, kind, name, pack_rings(rings)))
                    area_boxes.append((row, *_bbox(rings[0])))
                    stats["areas"] += 1
                    area_kinds[kind] = area_kinds.get(kind, 0) + 1
            except osmium.InvalidLocationError:
                stats["skipped_invalid"] += 1
                return
            if len(areas) >= 20000:
                flush()

    started = time.monotonic()
    print("PHASE reading the map", flush=True)
    try:
        Handler().apply_file(str(input_path), locations=True,
                             idx=f"sparse_file_array,{node_index}" if low_memory else "flex_mem")
    finally:
        try:
            node_index.unlink(missing_ok=True)
        except OSError:
            pass  # Windows keeps the mapping until the process ends; the next build removes the file first
    flush()
    header = osmium.io.Reader(str(input_path), osmium.osm.osm_entity_bits.NOTHING).header()
    timestamp = header.get("osmosis_replication_timestamp") or header.get("timestamp") or ""
    box = header.box()
    meta = {
        "schema": SCHEMA_VERSION,
        "source_file": input_path.name,
        "source_timestamp": timestamp,
        "attribution": "© OpenStreetMap contributors",
        "license": "Open Database License (ODbL) v1.0",
        "roads": str(stats["roads"]),
        "road_filter": ROAD_FILTER_VERSION,
        "area_filter": AREA_FILTER_VERSION,
        "skipped_roads": str(stats["skipped_roads"]),
        "water_lines": str(stats["water_lines"]),
        "coastlines": str(stats["coastlines"]),
        "areas": str(stats["areas"]),
        "area_kinds": json.dumps(area_kinds, sort_keys=True),
    }
    if box.valid():  # the extract's own box (west,south,east,north): the sea past the last road is in the map too
        meta["bounds"] = f"{box.bottom_left.lon},{box.bottom_left.lat},{box.top_right.lon},{box.top_right.lat}"
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.commit()
    db.close()
    temporary.replace(output_path)
    stats.update(seconds=round(time.monotonic() - started, 1), output=str(output_path.name),
                 source_timestamp=timestamp, area_kinds=area_kinds, low_memory=low_memory)
    try:
        import resource  # not on Windows
        stats["peak_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024  # kB on Linux
    except ImportError:
        pass
    return stats


class FeatureIndex:
    """Read-only query side used by osm_live_sidecar.py (standard library only)."""

    def __init__(self, path: Path):
        self.path = path
        uri = f"file:{path}?mode=ro"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        # One connection is shared by the HTTP worker threads; concurrent cursors on it
        # interleave rows, so queries are serialised (each takes a few milliseconds).
        self.lock = threading.Lock()
        self.meta = dict(self.db.execute("SELECT key, value FROM meta"))
        if self.meta.get("schema") != SCHEMA_VERSION:
            raise ValueError("unsupported feature index schema; rebuild with osm_extract_index.py")
        if "bounds" in self.meta:  # the extract's own box: the sea past the last road is in the map too
            west, south, east, north = map(float, self.meta["bounds"].split(","))
            self.bounds = west, east, south, north
        else:
            self.bounds = self.db.execute("SELECT min(min_lon), max(max_lon), min(min_lat), max(max_lat) "
                                          "FROM ways_rtree").fetchone()  # west, east, south, north
        # Maps built before the coastline was kept have the roads' box above and no sea.
        self.coast = self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'coastlines'").fetchone() is not None

    def covers(self, south: float, west: float, north: float, east: float) -> bool:
        b_west, b_east, b_south, b_north = self.bounds
        return b_west <= west and east <= b_east and b_south <= south and north <= b_north

    def document(self, south: float, west: float, north: float, east: float, clip=None, mercator=False) -> dict:
        """Return an Overpass-shaped document for osm_live_codec.build_live_tile.

        `clip` is an optional (south, west, north, east) box containing the query box. Area rings
        reaching outside it are cut to it, so a forest or lake many kilometres across costs only
        the part near the query instead of all its vertices on every request. Inside the box the
        geometry is unchanged; the new edges lie on the box, so callers keep a margin between the
        box and anything they draw or measure. With `mercator` the cuts follow edges as a tile draws them.
        """
        with self.lock:
            return self._document((west, east, south, north), clip, mercator)

    def _document(self, box, clip=None, mercator=False) -> dict:
        elements = []
        for way_id, kind, klass, name, attrs, coords in self.db.execute(
                "SELECT w.id, w.kind, w.class, w.name, w.attrs, w.coords FROM ways_rtree r "
                "JOIN ways w ON w.id = r.id "
                "WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?", box):
            key = "highway" if kind == "road" else "waterway"
            tags = {key: klass}
            if name:
                tags["name"] = name
            if attrs:
                tags.update(json.loads(attrs))
            elements.append({"type": "way", "id": way_id, "tags": tags,
                             "geometry": [{"lat": lat, "lon": lon}
                                          for lat, lon in unpack_coordinates(coords)]})
        for row, osm_area, kind, name, rings, min_lon, max_lon, min_lat, max_lat in self.db.execute(
                "SELECT a.row, a.osm_area, a.kind, a.name, a.rings, "
                "r.min_lon, r.max_lon, r.min_lat, r.max_lat FROM areas_rtree r "
                "JOIN areas a ON a.row = r.row "
                "WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?", box):
            rings = unpack_rings(rings)
            if clip is not None:
                south, west, north, east = clip
                if not (west <= min_lon and max_lon <= east and south <= min_lat and max_lat <= north):
                    rings = clip_rings(rings, clip, mercator)
                    if rings is None:
                        continue
            elements.append({"type": "area", "id": row, "osm_area": osm_area, "kind": kind,
                             "name": name, "rings": rings})
        if self.coast:  # the sea, cut to the clip box like the other areas (always as a tile draws it)
            sea_box = clip if clip is not None else (box[2], box[0], box[3], box[1])
            for n, rings in enumerate(sea_rings(self._coastlines(*sea_box), sea_box, self._seaward)):
                elements.append({"type": "area", "id": f"sea-{n}", "osm_area": "sea", "kind": "water",
                                 "name": None, "rings": rings})
        return {"elements": elements,
                "osm3s": {"timestamp_osm_base": self.meta.get("source_timestamp")}}

    def _coastlines(self, south, west, north, east):
        return [unpack_coordinates(coords) for (coords,) in self.db.execute(
            "SELECT c.coords FROM coastlines_rtree r JOIN coastlines c ON c.id = r.id "
            "WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?", (west, east, south, north))]

    def _seaward(self, lat: float, lon: float) -> bool:
        """Whether a point is on the sea side of its nearest coastline; land when none is within about 50 km."""
        kx, ky = 111_320.0 * max(0.01, math.cos(math.radians(lat))), 110_540.0

        def gap(row):  # metres from the point to a way's box
            _, west, east, south, north = row
            return math.hypot(max(west - lon, 0, lon - east) * kx, max(south - lat, 0, lat - north) * ky)

        for radius in (1_000.0, 4_000.0, 16_000.0, 50_000.0):
            dlat, dlon = radius / ky, radius / kx
            rows = self.db.execute(
                "SELECT id, min_lon, max_lon, min_lat, max_lat FROM coastlines_rtree "
                "WHERE max_lon >= ? AND min_lon <= ? AND max_lat >= ? AND min_lat <= ?",
                (lon - dlon, lon + dlon, lat - dlat, lat + dlat)).fetchall()
            # Nearest boxes first: a way whose box lies beyond the nearest segment found cannot hold a nearer one (the ways
            # meeting at that segment's end are all kept, as the side at a vertex needs both).
            lines, nearest = [], None
            for row in sorted(rows, key=gap):
                if nearest is not None and gap(row) > nearest:
                    break
                (coords,) = self.db.execute("SELECT coords FROM coastlines WHERE id = ?", (row[0],)).fetchone()
                lines.append(unpack_coordinates(coords))
                distance = coast_side(lines[-1:], lat, lon)
                if distance is not None and (nearest is None or distance[0] < nearest):
                    nearest = distance[0]
            side = coast_side(lines, lat, lon)
            if side is not None and side[0] <= radius:
                return side[1]
        return False


HighwayIndex = FeatureIndex  # Earlier name used by the sidecar and tests.


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Local .osm.pbf extract")
    parser.add_argument("--output", type=Path, required=True, help="New SQLite index path")
    parser.add_argument("--low-memory", action="store_true",
                        help="Keep node locations in a file beside the output instead of in RAM (for extracts too big for it)")
    args = parser.parse_args()
    try:
        stats = build_index(args.input, args.output, args.low_memory)
    except MemoryError:  # libosmium's bad_alloc: the caller tells the player to pick a smaller region
        print("OUT_OF_MEMORY the extract needs more memory than this phone has", flush=True)
        raise SystemExit(3)
    except sqlite3.OperationalError as e:
        if "full" in str(e):
            print("DISK_FULL there is not enough free space to build the map", flush=True)
            raise SystemExit(4)
        raise
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
