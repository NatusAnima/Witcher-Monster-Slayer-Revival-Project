#!/usr/bin/env python3
"""Loopback FeatureTile server that converts OpenStreetMap data for any XYZ address.

Unlike the fixed tile pack, this sidecar answers every valid address. Road
geometry comes from an Overpass API query for the enclosing "fetch tile"
(zoom 15 by default), which is cached on disk and reused for all descendant
tiles. The encoder and road classification are the same authored test mapping
used by osm_tile_codec.py; they are not recovered historical game data.

Privacy: event records never contain tile addresses, coordinates, request
paths or bodies. The on-disk cache necessarily contains OSM data for the
visited areas and must stay local (server/data/ is excluded from Git).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from osm_live_codec import build_area_canary, build_grid_canary, build_live_tile, build_river_canary
from osm_tile_codec import validate_tile_address


HERE = Path(__file__).resolve().parent
DEFAULT_CACHE = HERE.parent.parent / "data" / "osm-live-cache-01"
DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "MonsterSlayerRevivalLab-osm-live-sidecar/1 (personal non-commercial test)"
IDENTITY = "osm-live-overpass-sidecar-v1"
MIN_SERVED_ZOOM = 12
MAX_SERVED_ZOOM = 20
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
TILE_MEMORY_LIMIT = 2048
QUERY_TEMPLATE = (
    "[out:json][timeout:60];"
    "way[\"highway\"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});"
    "out geom;"
)


def tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return south, west, north, east in degrees for a north-origin XYZ tile."""
    scale = 1 << zoom

    def lat(row: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / scale))))

    west = x / scale * 360.0 - 180.0
    east = (x + 1) / scale * 360.0 - 180.0
    return lat(y + 1), west, lat(y), east


def fetch_key(zoom: int, x: int, y: int, fetch_zoom: int) -> tuple[int, int, int]:
    """Choose the cached Overpass area that contains the requested tile."""
    if zoom <= fetch_zoom:
        return zoom, x, y
    shift = zoom - fetch_zoom
    return fetch_zoom, x >> shift, y >> shift


class OverpassSource:
    """Serialised, cached Overpass reader keyed by fetch-tile address."""

    def __init__(self, cache_dir: Path, endpoints, *, offline: bool = False,
                 opener=None, min_interval: float = 1.0, emit=lambda _row: None):
        self.cache_dir = cache_dir
        self.endpoints = tuple(endpoints)
        self.offline = offline
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.min_interval = min_interval
        self.emit = emit
        self.network_lock = threading.Lock()
        self.key_locks: dict[tuple[int, int, int], threading.Lock] = {}
        self.key_locks_guard = threading.Lock()
        self.pending: set[tuple[int, int, int]] = set()
        self.documents: collections.OrderedDict = collections.OrderedDict()
        self.last_request = 0.0
        self.stats = collections.Counter()

    def _path(self, key: tuple[int, int, int]) -> Path:
        z, x, y = key
        return self.cache_dir / f"z{z}" / str(x) / f"{y}.json.gz"

    def _key_lock(self, key):
        with self.key_locks_guard:
            return self.key_locks.setdefault(key, threading.Lock())

    def available(self, key: tuple[int, int, int]) -> bool:
        return key in self.documents or self._path(key).is_file()

    def prefetch(self, key: tuple[int, int, int]) -> None:
        """Start one background fetch per missing area; never block the game's request."""
        with self.key_locks_guard:
            if key in self.pending or self.available(key):
                return
            self.pending.add(key)

        def worker():
            try:
                self.document(key)
            except Exception as exc:
                self.emit({"event": "osm_live_prefetch_failed", "error_type": type(exc).__name__})
            finally:
                with self.key_locks_guard:
                    self.pending.discard(key)

        threading.Thread(target=worker, daemon=True).start()

    def document(self, key: tuple[int, int, int]) -> dict:
        with self._key_lock(key):
            cached = self.documents.get(key)
            if cached is not None:
                self.documents.move_to_end(key)
                self.stats["memory_hits"] += 1
                return cached
            path = self._path(key)
            if path.is_file():
                document = json.loads(gzip.decompress(path.read_bytes()))
                self.stats["disk_hits"] += 1
            else:
                if self.offline:
                    raise LookupError("area is not cached and network fetches are disabled")
                document = self._fetch(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(gzip.compress(json.dumps(
                    document, separators=(",", ":")).encode("utf-8")))
                temporary.replace(path)
                self.stats["network_fetches"] += 1
            self.documents[key] = document
            while len(self.documents) > 64:
                self.documents.popitem(last=False)
            return document

    def _fetch(self, key: tuple[int, int, int]) -> dict:
        south, west, north, east = tile_bounds(*key)
        query = QUERY_TEMPLATE.format(south=south, west=west, north=north, east=east)
        body = urllib.parse.urlencode({"data": query}).encode("ascii")
        failures = []
        with self.network_lock:
            for attempt in range(2):
                for endpoint in self.endpoints:
                    wait = self.last_request + self.min_interval - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    self.last_request = time.monotonic()
                    request = urllib.request.Request(endpoint, data=body, headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded",
                    })
                    started = time.monotonic()
                    try:
                        with self.opener.open(request, timeout=45) as response:
                            raw = response.read(MAX_DOCUMENT_BYTES + 1)
                        if len(raw) > MAX_DOCUMENT_BYTES:
                            raise ValueError("Overpass response too large")
                        document = json.loads(raw)
                        if not isinstance(document, dict) or not isinstance(
                                document.get("elements"), list):
                            raise ValueError("unexpected Overpass document")
                        if "remark" in document and "runtime error" in str(document["remark"]):
                            raise ValueError("Overpass runtime error")
                        self.emit({"event": "osm_live_fetch", "status": "ok",
                                   "bytes": len(raw), "ways": len(document["elements"]),
                                   "ms": round((time.monotonic() - started) * 1000)})
                        return document
                    except (OSError, ValueError, urllib.error.URLError) as exc:
                        failures.append(type(exc).__name__)
                        self.stats["fetch_failures"] += 1
                        self.emit({"event": "osm_live_fetch", "status": "failed",
                                   "error_type": type(exc).__name__,
                                   "http_status": getattr(exc, "code", None),
                                   "endpoint": urllib.parse.urlsplit(endpoint).hostname,
                                   "ms": round((time.monotonic() - started) * 1000)})
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("all Overpass endpoints failed: " + ",".join(failures))


class LocalIndexSource:
    """Serve areas inside a local SQLite feature index; defer others to an optional fallback."""

    per_tile = True

    def __init__(self, index, fallback: OverpassSource | None = None):
        self.index = index
        self.fallback = fallback
        self.offline = fallback is None or fallback.offline
        self.documents: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.local_stats = collections.Counter()

    @property
    def stats(self):
        combined = collections.Counter(self.local_stats)
        if self.fallback is not None:
            combined.update({"fallback_" + k: v for k, v in self.fallback.stats.items()})
        return combined

    def covers(self, key) -> bool:
        return self.index.covers(*tile_bounds(*key))

    def available(self, key) -> bool:
        if self.covers(key):
            return True
        return self.fallback is not None and self.fallback.available(key)

    def prefetch(self, key) -> None:
        if not self.covers(key) and self.fallback is not None:
            self.fallback.prefetch(key)

    def document(self, key) -> dict:
        if not self.covers(key):
            if self.fallback is None:
                raise LookupError("area outside the local extract")
            return self.fallback.document(key)
        with self.lock:
            cached = self.documents.get(key)
            if cached is not None:
                self.documents.move_to_end(key)
                self.local_stats["index_memory_hits"] += 1
                return cached
        document = self.index.document(*tile_bounds(*key))
        self.local_stats["index_queries"] += 1
        with self.lock:
            self.documents[key] = document
            while len(self.documents) > 64:
                self.documents.popitem(last=False)
        return document


class GridCanarySource:
    """Synthetic diagnostic source: every tile gets the same visible road grid.

    Used to separate client rendering from real-world data density. The grid is
    invented test geometry, not map data.
    """
    offline = True

    def __init__(self, spacing: int = 512, types: tuple[int, int, int] = (530, 530, 531),
                 areas: tuple[str, ...] = (), cell: int = 512):
        self.spacing = spacing
        self.areas = areas
        self.cell = cell
        self.horizontal, self.vertical, self.diagonal = types
        self.stats = collections.Counter()

    def available(self, key) -> bool:
        return True

    def prefetch(self, key) -> None:
        return None

    def build(self, z: int, x: int, y: int) -> tuple[bytes, int]:
        self.stats["canary_tiles"] += 1
        if self.areas == ("river",):
            return build_river_canary(z, x, y)
        if self.areas:
            return build_area_canary(z, x, y, cell=self.cell, kinds=self.areas)
        return build_grid_canary(z, x, y, (self.horizontal, self.vertical, self.diagonal), self.spacing)


class LiveTileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # The client opens ~100 tile connections at once through `adb reverse`. With the
    # socketserver default backlog of 5, dropped SYNs stalled the adb host relay and every
    # request timed out on the device after 40 s, although this server answered in <1 s.
    request_queue_size = 1024

    def __init__(self, port: int, source: OverpassSource, *, fetch_zoom: int, emit,
                 terrain: bytes | None = None, blocking: bool = False,
                 only_kinds: tuple[str, ...] = (), bind: str = "127.0.0.1",
                 allow_clients: tuple[str, ...] = ()):
        self.source = source
        self.bind = bind
        self.allow_clients = frozenset(allow_clients)
        self.only_kinds = only_kinds
        self.blocking = blocking
        self.fetch_zoom = fetch_zoom
        self.emit = emit
        self.terrain = terrain
        self.tiles: collections.OrderedDict = collections.OrderedDict()
        self.tiles_lock = threading.Lock()
        self.request_number = 0
        self.counter_lock = threading.Lock()
        self.stats = collections.Counter()
        super().__init__((bind, port), LiveTileHandler)

    def verify_request(self, request, client_address) -> bool:
        # Closes connections from other peers before any byte is read; never logs the address.
        if self.allow_clients and client_address[0] not in self.allow_clients:
            with self.counter_lock:
                self.stats["refused_client"] += 1
            return False
        return True

    def next_request(self) -> int:
        with self.counter_lock:
            self.request_number += 1
            return self.request_number

    def identity(self) -> dict:
        return {
            "status": "ready",
            "identity": IDENTITY,
            "source": ("synthetic road-grid canary" if isinstance(self.source, GridCanarySource)
                       else "OpenStreetMap (local index and/or Overpass API), converted per XYZ tile"),
            "attribution": "© OpenStreetMap contributors",
            "license": "ODbL 1.0",
            "feature_routing": "any_valid_xyz",
            "fetch_zoom": self.fetch_zoom,
            "served_zooms": [MIN_SERVED_ZOOM, MAX_SERVED_ZOOM],
            "offline": self.source.offline,
            "counters": dict(self.stats),
            "source_counters": dict(self.source.stats),
            "client_rendering": "unverified",
        }

    def feature_tile(self, z: int, x: int, y: int) -> tuple[bytes, int]:
        address = (z, x, y)
        with self.tiles_lock:
            cached = self.tiles.get(address)
            if cached is not None:
                self.tiles.move_to_end(address)
                return cached
        if isinstance(self.source, GridCanarySource):
            return self.source.build(z, x, y)
        key = fetch_key(z, x, y, self.fetch_zoom)
        if getattr(self.source, "per_tile", False) and self.source.covers((z, x, y)):
            key = (z, x, y)  # The local index answers exact tile bounds quickly.
        if not self.blocking and not self.source.available(key):
            self.source.prefetch(key)
            raise LookupError("area fetch pending")
        document = self.source.document(key)
        if self.only_kinds:
            document = {**document, "elements": [
                e for e in document["elements"]
                if (e.get("kind") if e.get("type") == "area" else
                    ("road" if "highway" in (e.get("tags") or {}) else "water_line")) in self.only_kinds]}
        raw, summary = build_live_tile(document, z, x, y)
        result = (raw, summary["feature_count"])
        with self.tiles_lock:
            self.tiles[address] = result
            while len(self.tiles) > TILE_MEMORY_LIMIT:
                self.tiles.popitem(last=False)
        return result

    def handle_error(self, _request, _client_address):
        self.emit({"event": "osm_live_connection_error"})


# Paths requested by a client whose tile host was patched to this server (LAB 14):
# FeatureTileUrlBuilder formats "/v1/featuretiles/@{x},{y},{zoom}z" and then adds a query.
GOOGLE_FEATURE_PATH = re.compile(r"/v1/featuretiles/@([0-9]{1,7}),([0-9]{1,7}),([0-9]{1,2})z")
GOOGLE_TERRAIN_PATH = re.compile(r"/v1/terraintiles/@[0-9]{1,7},[0-9]{1,7},[0-9]{1,2}z")
LAB_FEATURE_PATH = re.compile(r"/lab/feature-tile/([0-9]{1,2})/([0-9]{1,7})/([0-9]{1,7})")


def feature_address(path: str) -> tuple[str, str, str] | None:
    """Returns (z, x, y) as strings for either path form, or None."""
    match = LAB_FEATURE_PATH.fullmatch(path)
    if match is not None:
        return match.groups()
    match = GOOGLE_FEATURE_PATH.fullmatch(path)
    if match is not None:
        x, y, z = match.groups()
        return z, x, y
    return None


class LiveTileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120

    def log_message(self, _format, *_args):
        pass

    def _reply(self, status: int, body: bytes, content_type: str = "application/x-protobuf"):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server: LiveTileServer = self.server
        if self.path == "/health":
            body = json.dumps(server.identity(), sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            self._reply(200, body, "application/json")
            return
        path = self.path.split("?", 1)[0]  # The patched client appends its API query; never read it.
        if (path == "/lab/terrain-tile" or GOOGLE_TERRAIN_PATH.fullmatch(path)) and server.terrain is not None:
            self._reply(200, server.terrain)
            server.stats["terrain_200"] += 1
            return
        address = feature_address(path)
        number = server.next_request()
        started = time.monotonic()
        if address is None:
            server.stats["unmatched_404"] += 1
            self._reply(404, b"")
            server.emit({"event": "osm_live_http", "request": number, "status": 404,
                         "reason": "unmatched"})
            return
        try:
            z, x, y = map(int, address)
            validate_tile_address(z, x, y)
            if not MIN_SERVED_ZOOM <= z <= MAX_SERVED_ZOOM:
                raise ValueError("zoom outside served range")
        except ValueError:
            server.stats["invalid_404"] += 1
            self._reply(404, b"")
            server.emit({"event": "osm_live_http", "request": number, "status": 404,
                         "reason": "invalid_address"})
            return
        try:
            body, feature_count = server.feature_tile(z, x, y)
        except Exception as exc:  # A failed fetch must not be cached as an empty tile.
            server.stats["unavailable_503"] += 1
            self._reply(503, b"")
            if not isinstance(exc, LookupError):
                server.emit({"event": "osm_live_http", "request": number, "status": 503,
                             "error_type": type(exc).__name__})
            return
        server.stats["feature_200"] += 1
        if feature_count:
            server.stats["nonempty_200"] += 1
        self._reply(200, body)
        server.emit({"event": "osm_live_http", "request": number, "status": 200,
                     "bytes": len(body), "features": feature_count, "zoom": z,
                     "ms": round((time.monotonic() - started) * 1000)})

    def send_error(self, code, message=None, explain=None):
        self._reply(code, b"")


def load_flat_terrain() -> bytes | None:
    path = HERE.parent / "map-tile-fixture-01/generated-terrain01/synthetic-terrain-tile.pb"
    return path.read_bytes() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="Listen address; loopback by default. A non-loopback address needs --allow-client.")
    parser.add_argument("--allow-client", action="append", default=[], metavar="ADDRESS",
                        help="Accept connections only from this source address; repeat for more")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--fetch-zoom", type=int, default=15,
                        help="Zoom level of the cached Overpass query area (12-17)")
    parser.add_argument("--endpoint", action="append",
                        help="Overpass interpreter URL; repeat to add fallbacks")
    parser.add_argument("--offline", action="store_true",
                        help="Never contact Overpass; serve only indexed or already cached areas")
    parser.add_argument("--grid-canary", metavar="H,V,D",
                        help="Diagnostic: serve an invented road grid for every tile instead of OSM data; "
                             "FeatureType values for horizontal, vertical and diagonal lines, e.g. 530,530,531")
    parser.add_argument("--area-canary", nargs="?", const="forest,park,water,building,beach",
                        metavar="KINDS[:CELL]",
                        help="Diagnostic: serve invented land-cover shapes (forest square, park octagon, "
                             "water triangle, building square, beach plus) for every tile")
    parser.add_argument("--only-kinds", default="",
                        help="Diagnostic: comma-separated classes to keep (road, water_line, water, park, "
                             "forest, beach, building)")
    parser.add_argument("--index", type=Path,
                        help="SQLite feature index built by osm_extract_index.py; Overpass is the fallback")
    parser.add_argument("--quiet", action="store_true", help="Emit only fetch and error events")
    parser.add_argument("--blocking", action="store_true",
                        help="Hold requests until a missing area is fetched (default: answer 503 at once)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    if not 12 <= args.fetch_zoom <= 17:
        parser.error("--fetch-zoom must be in 12..17")
    try:
        loopback = ipaddress.ip_address(args.bind).is_loopback
    except ValueError:
        parser.error("--bind must be an IP address")
    if not loopback and not args.allow_client:
        parser.error("--bind outside loopback requires --allow-client")

    def emit(row):
        if args.quiet and row.get("event") == "osm_live_http" and row.get("status") == 200:
            return
        print(json.dumps({"t": round(time.time(), 1), **row}, ensure_ascii=False,
                         sort_keys=True), flush=True)

    source = OverpassSource(args.cache_dir, args.endpoint or DEFAULT_ENDPOINTS,
                            offline=args.offline, emit=emit)
    if args.index is not None:
        from osm_extract_index import FeatureIndex
        index = FeatureIndex(args.index)
        emit({"event": "osm_live_index", "roads": index.meta.get("roads"),
              "areas": index.meta.get("areas"), "water_lines": index.meta.get("water_lines"),
              "source_timestamp": index.meta.get("source_timestamp")})
        source = LocalIndexSource(index, source)
    if args.grid_canary:
        source = GridCanarySource(types=tuple(int(v) for v in args.grid_canary.split(",")))
    if args.area_canary:
        kinds, _, cell = args.area_canary.partition(":")
        source = GridCanarySource(areas=tuple(kinds.split(",")), cell=int(cell or 512))
    with LiveTileServer(args.port, source, fetch_zoom=args.fetch_zoom, emit=emit,
                        terrain=load_flat_terrain(), blocking=args.blocking,
                        only_kinds=tuple(k for k in args.only_kinds.split(",") if k),
                        bind=args.bind, allow_clients=tuple(args.allow_client)) as server:
        emit({"event": "osm_live_ready", "bind": args.bind, "port": args.port,
              "fetch_zoom": args.fetch_zoom, "offline": args.offline})
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
