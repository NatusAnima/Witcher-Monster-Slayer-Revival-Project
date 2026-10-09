#!/usr/bin/env python3
"""Pedestrian-safe spawn points per S2 cell, from the local OSM feature index.

The 1.1.116 client placed monsters, herbs and quest nodes at Google Playable Locations
(client strings: playablelocations.googleapis.com, generatedPlayableLocations/,
curatedPlayableLocations/): points a pedestrian can reach, away from carriageways.
This service is the OSM stand-in used by the game server:

  GET /cells?ids=<id>,<id>&epoch=<n>
      -> {"<id>": {"center": [lat, lng], "places": [{"id", "lat", "lng", "biomes", "kind"}, ...]}}

Points lie on footways, paths, tracks, cycleways and pedestrian streets, or inside parks and
forests; never within CARRIAGEWAY_CLEARANCE_M of a road for cars (MAJOR_ROAD_CLEARANCE_M for main
roads), inside or next to a building, in water or on its shoreline. Biome ids follow the client's
BiomeType (1 Forest, 4 Grassland, 7 Urban, 9 Barren, 10 Water). The selection is random per
(cell, epoch), so each epoch gives new spots; woods hold at most FOREST_MAX_PER_CELL of a cell's places (the player can
change that in the dashboard: --tuning names the file that holds it).
Coordinates are never logged. Standard library only.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import Future
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import random
import threading
import time

import placement_policy
from urllib.parse import parse_qs, urlparse

from osm_extract_index import FeatureIndex
import s2cells

WALK_CLASSES = {"footway", "path", "pedestrian", "cycleway", "bridleway", "track"}
MAJOR_ROAD_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                      "secondary", "secondary_link"}
CARRIAGEWAY_CLASSES = MAJOR_ROAD_CLASSES | {"tertiary", "tertiary_link", "unclassified", "residential",
                                            "living_street", "service", "road"}
CARRIAGEWAY_CLEARANCE_M = 20.0     # from the centre line of a street
MAJOR_ROAD_CLEARANCE_M = 30.0      # wide multi-lane roads
BUILDING_CLEARANCE_M = 8.0
SHORE_CLEARANCE_M = 3.0            # off the shoreline and river centre lines (bridges)
WATER_NEAR_M = 60.0
URBAN_NEAR_M = 60.0
PATH_STEP_M = 25.0
AREA_STEP_M = 35.0
MIN_SPACING_M = 50.0
MAX_PER_CELL = 24
# Woods are a grid over the whole polygon, so without a limit they fill every cell they touch (93-99% of the places around a big
# forest, measured on the Israel extract) and the paths and parks beside them get none. Half a cell is the most they may hold.
FOREST_MAX_PER_CELL = MAX_PER_CELL // 2  # the default; the dashboard's tuning file overrides it
CELL_LEVEL = 14
NEST_SPACING_M = 300.0  # below the minimum width of a level-14 S2 cell (~366 m)
CLIP_MARGIN_M = 150.0   # beyond the cell; must exceed every clearance and "near" radius above
PLACEMENT_VERSION = 4   # ids carry it, so places chosen under an older rule never share an id with these

FOREST, SHRUBLAND, GRASSLAND, URBAN, BARREN, WATER = 1, 2, 4, 7, 9, 10


class _BoundedMemo:
    """LRU with bounded retained point count and coalesced, bounded concurrent misses.

    Values belong to the placement service and must not be modified by callers. Failures
    are delivered to current waiters but never cached. Eviction only drops computations;
    deterministic placement IDs and old epochs remain reproducible on a later request.
    """

    def __init__(self, entries, points, inflight=8):
        self.entries, self.points, self.inflight = entries, points, inflight
        self._values = OrderedDict()
        self._pending = {}
        self._point_count = 0
        self._condition = threading.Condition()
        self.hits = self.misses = 0

    def get(self, key, compute):
        with self._condition:
            while True:
                if key in self._values:
                    self.hits += 1
                    self._values.move_to_end(key)
                    return self._values[key]
                if key in self._pending:
                    pending, owner = self._pending[key], False
                    break
                if len(self._pending) < self.inflight:
                    pending, owner = Future(), True
                    self._pending[key] = pending
                    self.misses += 1
                    break
                self._condition.wait()
        if not owner:
            return pending.result()
        try:
            value = compute()
            with self._condition:
                if len(value) <= self.points:
                    self._values[key] = value
                    self._point_count += len(value)
                    while len(self._values) > self.entries or self._point_count > self.points:
                        _, removed = self._values.popitem(last=False)
                        self._point_count -= len(removed)
                pending.set_result(value)
            return value
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._condition:
                del self._pending[key]
                self._condition.notify_all()

    def stats(self):
        with self._condition:
            return dict(entries=len(self._values), points=self._point_count,
                        inflight=len(self._pending), hits=self.hits, misses=self.misses)


class Projection:
    """Local metres around a reference point (error well below a metre inside one cell)."""

    def __init__(self, lat0: float, lng0: float):
        self.lat0, self.lng0 = lat0, lng0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_540.0

    def xy(self, lat: float, lng: float) -> tuple[float, float]:
        return (lng - self.lng0) * self.kx, (lat - self.lat0) * self.ky

    def latlng(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.ky, self.lng0 + x / self.kx


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _inside_ring(px, py, ring) -> bool:
    inside = False
    for k in range(len(ring)):
        (ax, ay), (bx, by) = ring[k - 1], ring[k]
        if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


class _Shapes:
    """Segments and polygons of one kind, bucketed on a coarse grid for distance queries."""

    BUCKET = 50.0

    def __init__(self):
        self.segments: dict[tuple[int, int], list] = {}
        self.polygons: list[tuple[tuple[float, float, float, float], list]] = []

    def add_line(self, points):
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            for key in self._keys(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)):
                self.segments.setdefault(key, []).append((ax, ay, bx, by))

    def add_polygon(self, rings):
        outer = rings[0]
        xs, ys = [p[0] for p in outer], [p[1] for p in outer]
        self.polygons.append(((min(xs), min(ys), max(xs), max(ys)), rings))
        for ring in rings:
            self.add_line(ring + ring[:1])

    def _keys(self, x0, y0, x1, y1):
        b = self.BUCKET
        return [(i, j) for i in range(int(math.floor(x0 / b)), int(math.floor(x1 / b)) + 1)
                for j in range(int(math.floor(y0 / b)), int(math.floor(y1 / b)) + 1)]

    def near(self, x, y, radius) -> bool:
        for key in self._keys(x - radius, y - radius, x + radius, y + radius):
            for seg in self.segments.get(key, ()):
                if _segment_distance(x, y, *seg) <= radius:
                    return True
        return False

    def contains(self, x, y) -> bool:
        for (x0, y0, x1, y1), rings in self.polygons:
            if x0 <= x <= x1 and y0 <= y <= y1 and _inside_ring(x, y, rings[0]) \
                    and not any(_inside_ring(x, y, hole) for hole in rings[1:]):
                return True
        return False


def _cell_polygon(cell_id: int, proj: Projection):
    return [proj.xy(lat, lng) for lat, lng in s2cells.corners(cell_id)]


def candidates(document: dict, cell_id: int, policy=None, diagnostics=None) -> list[dict]:
    """Every safe point in the cell with its biomes (deterministic, unsampled)."""
    lat0, lng0 = s2cells.center(cell_id)
    proj = Projection(lat0, lng0)
    cell = _cell_polygon(cell_id, proj)
    walk, roads, major, buildings, water, parks, forests, beaches = (_Shapes() for _ in range(8))
    for element in document["elements"]:
        if element["type"] == "way":
            points = [proj.xy(p["lat"], p["lon"]) for p in element["geometry"]]
            tags = element["tags"]
            if tags.get("highway") in WALK_CLASSES and tags.get("access") not in ("private", "no"):
                walk.add_line(points)
            elif tags.get("highway") in MAJOR_ROAD_CLASSES:
                major.add_line(points)
            elif tags.get("highway") in CARRIAGEWAY_CLASSES:
                roads.add_line(points)
            elif "waterway" in tags:
                water.add_line(points)
        else:
            rings = [[proj.xy(lat, lng) for lat, lng in ring] for ring in element["rings"]]
            {"building": buildings, "water": water, "park": parks, "forest": forests,
             "beach": beaches}.get(element["kind"], _Shapes()).add_polygon(rings)

    stats = diagnostics if diagnostics is not None else {}
    stats.update(raw=0, safe=0, rejected={})
    excluded = [(proj.xy(row["lat"], row["lng"]), row["radiusMeters"])
                for row in (policy or {}).get("exclusions", [])]

    def reason(x, y):
        if not _inside_ring(x, y, cell): return "outside-cell"
        if major.near(x, y, MAJOR_ROAD_CLEARANCE_M): return "major-road"
        if roads.near(x, y, CARRIAGEWAY_CLEARANCE_M): return "road"
        if buildings.contains(x, y) or buildings.near(x, y, BUILDING_CLEARANCE_M): return "building"
        if water.contains(x, y) or water.near(x, y, SHORE_CLEARANCE_M): return "water"
        if any(math.hypot(x-a, y-b) <= radius for (a, b), radius in excluded): return "excluded"
        return None

    def safe(x, y):
        return reason(x, y) is None

    raw = []
    for row in (policy or {}).get("preferred", []):
        if s2cells.cell_of(row["lat"], row["lng"], CELL_LEVEL) != cell_id: continue
        x, y = proj.xy(row["lat"], row["lng"])
        if not (walk.near(x, y, 2) or parks.contains(x, y) or forests.contains(x, y)):
            stats["rejected"]["unmapped-preferred"] = stats["rejected"].get("unmapped-preferred", 0) + 1
            continue
        raw.append(((x, y), "preferred"))
    visited_segments = set()
    for key_segments in walk.segments.values():
        for ax, ay, bx, by in key_segments:
            segment = min((ax, ay, bx, by), (bx, by, ax, ay))
            if segment in visited_segments:
                continue
            visited_segments.add(segment)
            steps = max(1, int(math.hypot(bx - ax, by - ay) // PATH_STEP_M))
            length = math.hypot(bx - ax, by - ay)
            for k in range(steps):
                x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
                # Only move a safe path anchor into mapped open ground. Unknown verges retain
                # their path anchor; a blind offset could land inside a garden or carriageway.
                if length and safe(x, y):
                    distance = 6.0 if k % 2 == 0 else 9.0
                    dx, dy = -(by - ay) / length * distance, (bx - ax) / length * distance
                    for sign in ((1, -1) if k % 2 == 0 else (-1, 1)):
                        ox, oy = x + sign * dx, y + sign * dy
                        if (parks.contains(ox, oy) or forests.contains(ox, oy)) and safe(ox, oy):
                            x, y = ox, oy
                            break
                raw.append(((x, y), "path"))
    xs, ys = [p[0] for p in cell], [p[1] for p in cell]
    for shapes, kind in ((parks, "park"), (forests, "forest")):
        if not shapes.polygons:
            continue
        x = min(xs)
        while x <= max(xs):
            y = min(ys)
            while y <= max(ys):
                if shapes.contains(x, y):
                    raw.append(((x, y), kind))
                y += AREA_STEP_M
            x += AREA_STEP_M

    seen, points = set(), []
    stats["raw"] = len(raw)
    for (x, y), kind in raw:
        key = (round(x / 5), round(y / 5))
        rejection = "duplicate" if key in seen else reason(x, y)
        if _inside_ring(x, y, cell):
            seen.add(key)
        if rejection:
            stats["rejected"][rejection] = stats["rejected"].get(rejection, 0) + 1
            continue
        biomes = []
        if forests.contains(x, y):
            biomes.append(FOREST)
        elif parks.contains(x, y):
            biomes.append(GRASSLAND)
        elif beaches.contains(x, y):
            biomes.append(BARREN)
        elif buildings.near(x, y, URBAN_NEAR_M):
            biomes.append(URBAN)
        else:
            biomes.append(GRASSLAND)
        if water.near(x, y, WATER_NEAR_M):
            biomes.append(WATER)
        lat, lng = proj.latlng(x, y)
        points.append({"lat": round(lat, 6), "lng": round(lng, 6), "biomes": biomes, "kind": kind})
    stats["safe"] = len(points)
    return points


def sample(points: list[dict], cell_id: int, epoch: int, policy=None, woods: int = FOREST_MAX_PER_CELL) -> list[dict]:
    """Up to MAX_PER_CELL points at least MIN_SPACING_M apart, random per (cell, epoch), of which at most [woods]
    lie in woods (the default draw; a scheduled policy has its own spread)."""
    rng = random.Random(f"{cell_id}:{epoch}")
    order = points[:]
    rng.shuffle(order)
    proj = Projection(*s2cells.center(cell_id))
    chosen, xy = [], []
    spacing = policy["spacingMeters"] if policy else MIN_SPACING_M
    maximum = policy["maxPoints"] if policy else MAX_PER_CELL
    # New schedules spread anchors across all reachable ground, instead of filling a
    # random cluster first. Preferred anchors have priority but retain the same spacing.
    if policy:
        remaining = [(p, proj.xy(p["lat"], p["lng"])) for p in order]
        preferred = [p for p in remaining if p[0]["kind"] == "preferred"]
        order = []
        selected_xy = []
        while remaining and len(order) < maximum:
            if preferred:
                point, position = preferred.pop(0)
                if (point, position) not in remaining: continue
            elif selected_xy:
                point, position = max(remaining, key=lambda item: min(math.dist(item[1], v) for v in selected_xy))
            else:
                point, position = remaining[0]
            if all(math.dist(position, v) >= spacing for v in selected_xy):
                order.append(point); selected_xy.append(position)
            remaining = [(p, v) for p, v in remaining if p is not point and math.dist(position, v) >= spacing]
    # A scheduled policy keeps its own spread (its past days must stay reproducible); only the default draw limits the woods.
    woods_left = maximum if policy else woods
    for point in order:
        wood = point["biomes"][0] == FOREST
        if wood and not woods_left:
            continue
        x, y = proj.xy(point["lat"], point["lng"])
        if all(math.hypot(x - cx, y - cy) >= spacing for cx, cy in xy):
            chosen.append(dict(point, id=f"lab-{cell_id:016x}-{epoch}-{(3 if policy else PLACEMENT_VERSION) * 1000 + len(chosen)}"))
            xy.append((x, y))
            woods_left -= wood
            if len(chosen) == maximum:
                break
    return chosen


class Tuning:
    """The player's numbers from the dashboard (the game server writes world/tuning.json), looked at about once a second.
    A file that is missing, damaged or has an impossible number means the default."""

    KEY = "woods.maxPlaces"

    def __init__(self, path=None):
        self.path, self._woods, self._checked, self._seen = path, FOREST_MAX_PER_CELL, 0.0, None

    def woods(self) -> int:
        if self.path is None:
            return FOREST_MAX_PER_CELL
        now = time.monotonic()
        if now - self._checked >= 1.0:
            self._checked = now
            try:
                stat = self.path.stat()
                if (stat.st_mtime_ns, stat.st_size) != self._seen:
                    value = json.loads(self.path.read_bytes())["values"][self.KEY]
                    ok = type(value) in (int, float) and value == int(value) and 0 <= value <= MAX_PER_CELL
                    self._woods, self._seen = (int(value) if ok else FOREST_MAX_PER_CELL), (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                self._woods, self._seen = FOREST_MAX_PER_CELL, None
            except (OSError, ValueError, KeyError, TypeError):
                pass  # a half-written file settles on the next look: keep the last value
        return self._woods


class PlayableLocations:
    def __init__(self, index: FeatureIndex, policy_path=None, tuning_path=None):
        self.index = index
        self.tuning = Tuning(tuning_path)
        self.policy = placement_policy.PolicyStore(policy_path)
        # Placement is CPU-bound Python under the GIL: two computations at a time keep the
        # pace and bound the cell geometry alive at once (this runs on the phone with the game).
        self._raw = _BoundedMemo(entries=256, points=100_000, inflight=2)
        self._sampled = _BoundedMemo(entries=1024, points=64 * 1024, inflight=2)

    def document(self, cell_id, clip=True):
        if s2cells.level(cell_id) != CELL_LEVEL:
            raise ValueError("unsupported cell level")
        corners = s2cells.corners(cell_id)
        margin = 0.0005
        box = (min(a for a, _ in corners)-margin, min(b for _, b in corners)-margin,
               max(a for a, _ in corners)+margin, max(b for _, b in corners)+margin)
        if not self.index.covers(*box):
            return None
        if not clip:
            return self.index.document(*box)
        # Huge forests and lakes are cut to the cell plus CLIP_MARGIN_M: every point tested lies
        # in the cell and looks at most WATER_NEAR_M / URBAN_NEAR_M away, so the cut edges are
        # never seen and the placements stay the same.
        lat = (box[0] + box[2]) / 2
        dlat = CLIP_MARGIN_M / 110_540.0
        dlng = CLIP_MARGIN_M / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
        clip_box = (box[0] - dlat, box[1] - dlng, box[2] + dlat, box[3] + dlng)
        return self.index.document(*box, clip=clip_box)

    def cell(self, cell_id: int, epoch: int) -> list[dict]:
        if s2cells.level(cell_id) != CELL_LEVEL:
            raise ValueError("unsupported cell level")
        # Epoch zero is a transactional request for current quest-relocation geometry.
        # Dated epochs remain immutable and reproducible, including after restarts.
        from_epoch, policy = self.policy.at(int(time.time() // 86400) if epoch == 0 else epoch)
        active = policy if from_epoch else None
        key = json.dumps(active, sort_keys=True, separators=(",", ":"))
        def geometry():
            document = self.document(cell_id)
            return candidates(document, cell_id, active) if document is not None else []
        woods = self.tuning.woods()
        return self._sampled.get((key, woods, cell_id, epoch),
            lambda: sample(self._raw.get((key, cell_id), geometry), cell_id, epoch, active, woods))

    def validate(self, value):
        policy = placement_policy.policy(value)
        # Validate every curated point against the full safety geometry, independently of
        # sampling. A crowded valid point can still be excluded by the spacing budget.
        for row in policy["preferred"]:
            cell_id = s2cells.cell_of(row["lat"], row["lng"], CELL_LEVEL)
            document = self.document(cell_id)
            one = dict(policy, preferred=[row])
            points = candidates(document, cell_id, one) if document is not None else []
            if not any(p["kind"] == "preferred" for p in points):
                raise ValueError("preferred point fails mapped ground, coverage or safety clearance")
        return policy

    def admin_map(self, ids, epoch, proposed=None):
        self.policy.refresh()
        from_epoch, policy = self.policy.at(epoch)
        active = proposed if proposed is not None else policy if from_epoch else None
        rows, features, seen = [], [], set()
        vertices, truncated = 0, False
        for cell_id in ids:
            document = self.document(cell_id, clip=False)  # the operator map draws whole features
            stats = {}
            points = candidates(document, cell_id, active, stats) if document is not None else []
            chosen = sample(points, cell_id, epoch, active, self.tuning.woods())
            spacing = (active or placement_policy.DEFAULT)["spacingMeters"]
            blocked = sum(not any(p["lat"] == q["lat"] and p["lng"] == q["lng"] for q in chosen)
                          and any(_distance_m(p, q) < spacing for q in chosen) for p in points)
            rows.append(dict(id=str(cell_id), corners=s2cells.corners(cell_id), covered=document is not None,
                             **stats, selected=len(chosen), spacingRejected=blocked,
                             capacityRejected=max(0, len(points)-len(chosen)-blocked), points=chosen))
            for element in (document or {}).get("elements", []):
                feature_key = (element["type"], element.get("id", json.dumps(element, sort_keys=True)))
                if feature_key in seen: continue
                seen.add(feature_key)
                if element["type"] == "way":
                    kind = "waterway" if "waterway" in element["tags"] else "path" if element["tags"].get("highway") in WALK_CLASSES else "road"
                    rings = [[[p["lat"], p["lon"]] for p in element["geometry"]]]
                    name = element["tags"].get("name", "")
                else:
                    kind, rings, name = element["kind"], element["rings"], element.get("name") or ""
                size = sum(len(r) for r in rings)
                if vertices + size > 24000 or len(features) >= 4000:
                    truncated = True; continue
                vertices += size
                features.append(dict(kind=kind, rings=rings, name=name[:160]))
        return dict(source="local-osm-index", sourceTimestamp=getattr(self.index, "meta", {}).get("source_timestamp"),
                    observedAt=int(time.time()), epoch=epoch, policyStatus=self.policy.status(), cells=rows,
                    features=features, truncated=truncated, preview=proposed is not None,
                    attribution="© OpenStreetMap contributors")

    def nest_candidate(self, cell_id: int, epoch: int):
        """A potential nemeton anchor, independent of request order and player."""
        points = self.cell(cell_id, epoch)
        def rank(point):
            return hashlib.sha256(f"nest-v2:{point['id']}".encode()).digest()
        return min(points, key=rank) if points else None

    def nest_place(self, cell_id: int, epoch: int):
        candidate = self.nest_candidate(cell_id, epoch)
        if candidate is None:
            return None
        priority = lambda cid: (hashlib.sha256(f"nest-v2:{epoch}:{cid}".encode()).digest(), cid)
        own_priority = priority(cell_id)
        for neighbor in s2cells.neighbors(cell_id):
            if priority(neighbor) >= own_priority:
                continue
            other = self.nest_candidate(neighbor, epoch)
            if other and _distance_m(candidate, other) < NEST_SPACING_M:
                return None
        return candidate['id']

    def payload(self, ids: list[int], epoch: int) -> dict:
        self.policy.refresh()
        return {str(i): {"center": [round(v, 6) for v in s2cells.center(i)],
                         "places": self.cell(i, epoch), "nest_place_id": self.nest_place(i, epoch)} for i in ids}


def _distance_m(a: dict, b: dict) -> float:
    """Great-circle metres, including cells touching the antimeridian."""
    phi1, phi2 = math.radians(a['lat']), math.radians(b['lat'])
    dphi, dlambda = phi2 - phi1, math.radians(b['lng'] - a['lng'])
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(min(1.0, h)))


def make_handler(service: PlayableLocations):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/admin/policy":
                    self.respond(200, service.policy.status()); return
                if url.path not in ("/cells", "/admin/map"):
                    self.respond(404, {}); return
                ids = list(dict.fromkeys(int(part) for part in query.get("ids", [""])[0].split(",") if part))
                epoch = int(query.get("epoch", ["0"])[0])
                if not 0 < len(ids) <= 64 or not 0 <= epoch <= 365000:
                    raise ValueError
                result = service.payload(ids, epoch) if url.path == "/cells" else service.admin_map(ids, epoch)
                self.respond(200, result)
            except (ValueError, TypeError):
                self.respond(400, {"error": "Invalid placement request."})

        def do_POST(self):
            # Read-only validation/preview on loopback. Durable writes remain behind the
            # authenticated admin API with its origin, revision, receipt and backup checks.
            try:
                if self.path not in ("/admin/validate", "/admin/preview"):
                    self.respond(404, {}); return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536: raise ValueError
                value = json.loads(self.rfile.read(length))
                policy = service.validate(value["document"])
                if self.path == "/admin/validate":
                    result = dict(document=policy, **{"policyStatus": service.policy.status()})
                else:
                    ids = list(dict.fromkeys(int(i) for i in value["ids"]))
                    epoch = int(value["epoch"])
                    if not 0 < len(ids) <= 64 or not 0 <= epoch <= 365000: raise ValueError
                    result = service.admin_map(ids, epoch, policy)
                self.respond(200, result)
            except (ValueError, TypeError, KeyError):
                self.respond(400, {"error": "Invalid placement policy or unsafe preferred point."})

        def log_message(self, fmt, *args):
            pass  # Cell IDs and coordinates are private; do not log requests.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18093)
    parser.add_argument("--policy", type=Path, help="Shared world/placement-policy.json schedule")
    parser.add_argument("--tuning", type=Path, help="The dashboard's world/tuning.json (the woods limit per cell)")
    args = parser.parse_args()
    service = PlayableLocations(FeatureIndex(args.index), args.policy, args.tuning)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    print(f"playable locations on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
