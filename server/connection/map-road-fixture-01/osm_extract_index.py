#!/usr/bin/env python3
"""Build a local SQLite R-tree of OSM map features from an .osm.pbf extract.

Stored feature classes:
  ways        highway lines (roads, paths) and waterway=river/canal lines
  areas       parks, forests, beaches, water bodies and buildings, including
              multipolygon relations (one row per outer ring with its holes)

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


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE ways(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, class TEXT NOT NULL,
                          name TEXT, attrs TEXT, coords BLOB NOT NULL);
        CREATE VIRTUAL TABLE ways_rtree USING rtree(id, min_lon, max_lon, min_lat, max_lat);
        CREATE TABLE areas(row INTEGER PRIMARY KEY, osm_area INTEGER NOT NULL, kind TEXT NOT NULL,
                           name TEXT, rings BLOB NOT NULL);
        CREATE VIRTUAL TABLE areas_rtree USING rtree(row, min_lon, max_lon, min_lat, max_lat);
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
    stats = {"roads": 0, "skipped_roads": 0, "water_lines": 0, "areas": 0, "skipped_small_areas": 0,
             "skipped_invalid": 0}
    progress = FeatureProgress(input_path, stats, temporary)
    area_kinds: dict[str, int] = {}
    ways, way_boxes, areas, area_boxes = [], [], [], []
    next_area_row = [1]

    def flush():
        db.executemany("INSERT INTO ways VALUES (?,?,?,?,?,?)", ways)
        db.executemany("INSERT INTO ways_rtree VALUES (?,?,?,?,?)", way_boxes)
        db.executemany("INSERT INTO areas VALUES (?,?,?,?,?)", areas)
        db.executemany("INSERT INTO areas_rtree VALUES (?,?,?,?,?)", area_boxes)
        for batch in (ways, way_boxes, areas, area_boxes):
            batch.clear()

    def points_of(nodes):
        return [(node.location.lat, node.location.lon) for node in nodes]

    class Handler(osmium.SimpleHandler):
        def way(self, way):
            if progress.thread is None:
                progress.start()  # the first way means the node phase is over
            highway = way.tags.get("highway")
            waterway = way.tags.get("waterway")
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
        "areas": str(stats["areas"]),
        "area_kinds": json.dumps(area_kinds, sort_keys=True),
    }
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
        row = self.db.execute("SELECT min(min_lon), max(max_lon), min(min_lat), max(max_lat) "
                              "FROM ways_rtree").fetchone()
        self.bounds = row  # west, east, south, north

    def covers(self, south: float, west: float, north: float, east: float) -> bool:
        b_west, b_east, b_south, b_north = self.bounds
        return b_west <= west and east <= b_east and b_south <= south and north <= b_north

    def document(self, south: float, west: float, north: float, east: float) -> dict:
        """Return an Overpass-shaped document for osm_live_codec.build_live_tile."""
        with self.lock:
            return self._document((west, east, south, north))

    def _document(self, box) -> dict:
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
        for row, osm_area, kind, name, rings in self.db.execute(
                "SELECT a.row, a.osm_area, a.kind, a.name, a.rings FROM areas_rtree r "
                "JOIN areas a ON a.row = r.row "
                "WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?", box):
            elements.append({"type": "area", "id": row, "osm_area": osm_area, "kind": kind,
                             "name": name, "rings": unpack_rings(rings)})
        return {"elements": elements,
                "osm3s": {"timestamp_osm_base": self.meta.get("source_timestamp")}}


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
