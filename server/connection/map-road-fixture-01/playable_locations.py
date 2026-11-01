#!/usr/bin/env python3
"""Pedestrian-safe spawn points per S2 cell, from the local OSM feature index.

The 1.1.116 client placed monsters, herbs and quest nodes at Google Playable Locations
(client strings: playablelocations.googleapis.com, generatedPlayableLocations/,
curatedPlayableLocations/): points a pedestrian can reach, away from carriageways.
This service is the OSM stand-in used by the game server:

  GET /cells?ids=<id>,<id>&epoch=<n>
      -> {"<id>": {"center": [lat, lng], "places": [{"id", "lat", "lng", "biomes", "kind"}, ...]}}

Points lie on footways, paths, tracks, cycleways and pedestrian streets, beside streets (bigger ones only among houses), or
inside parks and forests; never within the street clearance of a road for cars (MAJOR_ROAD_CLEARANCE_M for main
roads), inside or next to a building, in water or on its shoreline. Biome ids follow the client's
BiomeType (1 Forest, 4 Grassland, 7 Urban, 9 Barren, 10 Water). The selection is random per
(cell, epoch), so each epoch gives new spots, and follows the place mix: each ground (paths, parks, woods, water-side,
urban) gets its share of a cell's places, so no ground crowds out the rest. The mix, the number of places, their spacing
and the street clearance are the player's dashboard settings (--tuning names the file that holds them).
Coordinates are never logged. Standard library only.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import Future
import hashlib
import heapq
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import random
import threading
import time

import placement_policy
from urllib.parse import parse_qs, urlparse

from osm_extract_index import FeatureIndex, open_indexes
import s2cells

WALK_CLASSES = {"footway", "path", "pedestrian", "cycleway", "bridleway", "track"}
STREET_CLASSES = {"residential", "living_street", "service"}  # quiet streets: places beside them when the clearance allows
TOWN_STREET_CLASSES = {"tertiary", "unclassified"}  # the same, but only where houses stand (rural ones often have no pavement)
MAJOR_ROAD_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                      "secondary", "secondary_link"}
CARRIAGEWAY_CLASSES = MAJOR_ROAD_CLASSES | {"tertiary", "tertiary_link", "unclassified", "residential",
                                            "living_street", "service", "road"}
CARRIAGEWAY_CLEARANCE_M = 20.0     # from the centre line of a street, under a scheduled placement policy (its days keep it)
STREET_CLEARANCE_M = 12.0          # the default draw's, which the dashboard changes: below STREET_SIDE_M, places line the streets
MAJOR_ROAD_CLEARANCE_M = 30.0      # wide multi-lane roads
STREET_SIDE_M = 13.0               # places beside streets, used only when the street clearance is below this
OFF_PATH_M = 12.0                  # how far beside a path a place stands, and beyond STREET_SIDE_M beside a street (the
                                   # default draw's, which the dashboard changes; field round 2026-10-31: 6-9 m into parks
                                   # and woods only before, which a scheduled policy's days keep)
BUILDING_CLEARANCE_M = 8.0
SHORE_CLEARANCE_M = 3.0            # off the shoreline and river centre lines (bridges)
WATER_NEAR_M = 60.0
URBAN_NEAR_M = 60.0
PATH_STEP_M = 25.0
AREA_STEP_M = 35.0
MIN_SPACING_M = 50.0
MAX_PER_CELL = 32
# The place mix, in shares of a cell's places. Parks and woods are a grid over their whole area and paths only a line of points,
# so a draw evenly from every candidate filled each cell with whichever area it touched (93-99% woods around a big forest on the
# Israel extract, parks in towns). The defaults are the maintainer's (2026-10-09): paths first, and town streets ("urban": within
# 60 m of a building) as many as paths, so the streets of a town get monsters in plenty, not just its parks. The dashboard
# changes them.
MIX = {"paths": 40, "parks": 25, "woods": 15, "water": 10, "urban": 40}
CELL_LEVEL = 14
NEST_SPACING_M = 300.0  # below the minimum width of a level-14 S2 cell (~366 m)
CLIP_MARGIN_M = 150.0   # beyond the cell; must exceed every clearance and "near" radius above
PLACEMENT_VERSION = 6   # ids carry it, so places chosen under an older rule never share an id with these

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

    def unique_segments(self):
        """Each segment once (a long one sits in several buckets), in bucket order."""
        seen = set()
        for bucket in self.segments.values():
            for ax, ay, bx, by in bucket:
                segment = min((ax, ay, bx, by), (bx, by, ax, ay))
                if segment not in seen:
                    seen.add(segment)
                    yield ax, ay, bx, by


def _cell_polygon(cell_id: int, proj: Projection):
    return [proj.xy(lat, lng) for lat, lng in s2cells.corners(cell_id)]


def candidates(document: dict, cell_id: int, policy=None, diagnostics=None,
               clearance: float = CARRIAGEWAY_CLEARANCE_M, off_path: float | None = None) -> list[dict]:
    """Every safe point in the cell with its biomes and ground (deterministic, unsampled). [clearance] is kept from
    ordinary streets; below STREET_SIDE_M, quiet streets get points beside them too. [off_path]: how far beside a path
    a point moves (parks and woods first, then any safe ground) and how much farther than STREET_SIDE_M beside a street;
    None keeps the scheduled policies' rule (6-9 m, into parks and woods only)."""
    lat0, lng0 = s2cells.center(cell_id)
    proj = Projection(lat0, lng0)
    cell = _cell_polygon(cell_id, proj)
    walk, roads, streets, town_streets, major, buildings, water, parks, forests, beaches = (_Shapes() for _ in range(10))
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
                if tags.get("highway") in STREET_CLASSES:
                    streets.add_line(points)
                elif tags.get("highway") in TOWN_STREET_CLASSES:
                    town_streets.add_line(points)
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
        if roads.near(x, y, clearance): return "road"
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
    for ax, ay, bx, by in walk.unique_segments():
        steps = max(1, int(math.hypot(bx - ax, by - ay) // PATH_STEP_M))
        length = math.hypot(bx - ax, by - ay)
        for k in range(steps):
            x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
            # Only move a safe path anchor into mapped open ground. Unknown verges retain
            # their path anchor; a blind offset could land inside a garden or carriageway.
            if length and safe(x, y) and off_path is None:
                distance = 6.0 if k % 2 == 0 else 9.0
                dx, dy = -(by - ay) / length * distance, (bx - ax) / length * distance
                for sign in ((1, -1) if k % 2 == 0 else (-1, 1)):
                    ox, oy = x + sign * dx, y + sign * dy
                    if (parks.contains(ox, oy) or forests.contains(ox, oy)) and safe(ox, oy):
                        x, y = ox, oy
                        break
            elif length and safe(x, y) and off_path > 0:
                # off the path, so a monster does not stand on it: open ground first, else any safe ground (kept from
                # roads, buildings and water like every point); none safe keeps the path point
                distance = off_path if k % 2 == 0 else off_path * 1.5
                dx, dy = -(by - ay) / length * distance, (bx - ax) / length * distance
                sides = [(x + sign * dx, y + sign * dy) for sign in ((1, -1) if k % 2 == 0 else (-1, 1))]
                open_ground = [p for p in sides if (parks.contains(*p) or forests.contains(*p)) and safe(*p)]
                x, y = (open_ground or [p for p in sides if safe(*p)] or [(x, y)])[0]
            raw.append(((x, y), "path"))
    # Towns often map no footways of their own, only streets: with a small enough clearance, both sides of a street get
    # points (still kept from buildings and water like any other); bigger streets only where houses stand.
    if clearance < STREET_SIDE_M:
        for shapes, town_only in ((streets, False), (town_streets, True)):
            for ax, ay, bx, by in shapes.unique_segments():
                length = math.hypot(bx - ax, by - ay)
                if not length:
                    continue
                steps = max(1, int(length // PATH_STEP_M))
                side = STREET_SIDE_M if off_path is None else STREET_SIDE_M + off_path / 3
                dx, dy = -(by - ay) / length * side, (bx - ax) / length * side
                for k in range(steps):
                    x, y = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
                    raw += [(side, "street") for side in ((x + dx, y + dy), (x - dx, y - dy))
                            if not town_only or buildings.near(*side, URBAN_NEAR_M)]
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
        # the share of the place mix the point counts toward
        ground = ("woods" if biomes[0] == FOREST else "water" if WATER in biomes else
                  "parks" if parks.contains(x, y) else "urban" if biomes[0] == URBAN else "paths")
        lat, lng = proj.latlng(x, y)
        points.append({"lat": round(lat, 6), "lng": round(lng, 6), "biomes": biomes, "kind": kind, "ground": ground})
    stats["safe"] = len(points)
    return points


def sample(points: list[dict], cell_id: int, epoch: int, policy=None, tuning=None) -> list[dict]:
    """The cell's places, random per (cell, epoch), at least the spacing apart. The default draw follows the place mix of
    [tuning] (Tuning.values()): each place comes from the ground furthest behind its share among the grounds that still
    have a point at the spacing, so a ground with none left gives its share to the others. A scheduled policy keeps its
    own count, spacing and spread (its past days must stay reproducible)."""
    rng = random.Random(f"{cell_id}:{epoch}")
    order = points[:]
    rng.shuffle(order)
    proj = Projection(*s2cells.center(cell_id))
    chosen, xy = [], []
    tuning = tuning or Tuning.defaults()
    spacing = policy["spacingMeters"] if policy else tuning["places.spacing"]
    maximum = policy["maxPoints"] if policy else int(tuning["places.perCell"])

    def take(point):
        x, y = proj.xy(point["lat"], point["lng"])
        if any(math.hypot(x - cx, y - cy) < spacing for cx, cy in xy):
            return False
        chosen.append(dict(point, id=f"lab-{cell_id:016x}-{epoch}-{(3 if policy else PLACEMENT_VERSION) * 1000 + len(chosen)}"))
        xy.append((x, y))
        return True

    if policy:
        # New schedules spread anchors across all reachable ground, instead of filling a
        # random cluster first. Preferred anchors have priority but retain the same spacing.
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
        for point in order:
            if take(point) and len(chosen) == maximum:
                break
        return chosen
    shares = {ground: tuning["places." + ground] for ground in MIX}
    if not any(shares.values()):
        shares = dict(MIX)  # all zero would leave the map empty
    pools = {ground: [p for p in order if p["ground"] == ground] for ground in MIX}
    credit = dict.fromkeys(MIX, 0.0)  # smooth weighted round-robin: the counts track the shares as places are taken
    while len(chosen) < maximum:
        open_grounds = [ground for ground in MIX if pools[ground] and shares[ground] > 0]
        if not open_grounds:
            break
        for ground in open_grounds:
            credit[ground] += shares[ground]
        ground = max(open_grounds, key=credit.get)
        credit[ground] -= sum(shares[g] for g in open_grounds)
        pool = pools[ground]
        while pool and not take(pool.pop()):
            pass  # a point too close to a chosen one stays too close: drop it
    return chosen


class Tuning:
    """The player's numbers from the dashboard (the game server writes world/tuning.json), looked at about once a second.
    A missing file means the defaults, a damaged one keeps the last good numbers, an impossible number its default. The
    game server's WorldTuning holds the same keys and refuses bad values when they are saved."""

    SETTINGS = {  # key: (default, lowest, highest)
        "places.perCell": (MAX_PER_CELL, 4, 48), "places.spacing": (MIN_SPACING_M, 30, 200),
        "places.streetClearance": (STREET_CLEARANCE_M, 10, 30), "places.offPath": (OFF_PATH_M, 0, 30),
        **{"places." + ground: (share, 0, 100) for ground, share in MIX.items()},
    }

    def __init__(self, path=None):
        self.path, self._values, self._checked, self._seen = path, self.defaults(), 0.0, None

    @classmethod
    def defaults(cls) -> dict:
        return {key: default for key, (default, _, _) in cls.SETTINGS.items()}

    def values(self) -> dict:
        if self.path is None:
            return self._values
        now = time.monotonic()
        if now - self._checked >= 1.0:
            self._checked = now
            try:
                stat = self.path.stat()
                if (stat.st_mtime_ns, stat.st_size) != self._seen:
                    saved = json.loads(self.path.read_bytes())["values"]
                    self._values = {key: value if type(value) in (int, float) and low <= value <= high else default
                                    for key, (default, low, high) in self.SETTINGS.items()
                                    for value in [saved.get(key, default)]}
                    self._seen = (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                self._values, self._seen = self.defaults(), None
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass  # a half-written file settles on the next look: keep the last values
        return self._values


class PlayableLocations:
    def __init__(self, index: FeatureIndex, policy_path=None, tuning_path=None):
        self.index = index
        self.tuning = Tuning(tuning_path)
        self.policy = placement_policy.PolicyStore(policy_path)
        # Placement is CPU-bound Python under the GIL: two computations at a time keep the
        # pace and bound the cell geometry alive at once (this runs on the phone with the game).
        self._raw = _BoundedMemo(entries=256, points=100_000, inflight=2)
        self._sampled = _BoundedMemo(entries=1024, points=64 * 1024, inflight=2)

    def walk(self, origin, targets, limit):
        """walking_metres over the roads within reach of origin."""
        lat, lng = origin
        pad = limit + WALK_SNAP_M
        dlat, dlng = pad / 110_540.0, pad / (111_320.0 * math.cos(math.radians(lat)))
        return walking_metres(self.index.roads(lat - dlat, lng - dlng, lat + dlat, lng + dlng), origin, targets, limit)

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

    def _rules(self, epoch: int):
        """The epoch's scheduled policy (None for the default draw), its cache key, and the tuning."""
        # Epoch zero is a transactional request for current quest-relocation geometry.
        # Dated epochs remain immutable and reproducible, including after restarts.
        from_epoch, policy = self.policy.at(int(time.time() // 86400) if epoch == 0 else epoch)
        active = policy if from_epoch else None
        return active, json.dumps(active, sort_keys=True, separators=(",", ":")), self.tuning.values()

    def points(self, cell_id: int, epoch: int) -> list[dict]:
        """The cell's candidate points under the epoch's rules, before the day's draw."""
        if s2cells.level(cell_id) != CELL_LEVEL:
            raise ValueError("unsupported cell level")
        active, key, tuning = self._rules(epoch)
        clearance = self.clearance(active, tuning)
        off_path = None if active else tuning["places.offPath"]
        def geometry():
            document = self.document(cell_id)
            return candidates(document, cell_id, active, clearance=clearance, off_path=off_path) if document is not None else []
        return self._raw.get((key, clearance, off_path, cell_id), geometry)

    def cell(self, cell_id: int, epoch: int) -> list[dict]:
        if s2cells.level(cell_id) != CELL_LEVEL:
            raise ValueError("unsupported cell level")
        active, key, tuning = self._rules(epoch)
        return self._sampled.get((key, tuple(sorted(tuning.items())), cell_id, epoch),
            lambda: sample(self.points(cell_id, epoch), cell_id, epoch, active, tuning))

    @staticmethod
    def clearance(active, tuning):
        """The street clearance: the player's, except under a scheduled policy, whose days keep the rules they were drawn with."""
        return CARRIAGEWAY_CLEARANCE_M if active else tuning["places.streetClearance"]

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
            tuning = self.tuning.values()
            points = candidates(document, cell_id, active, stats, self.clearance(active, tuning),
                                None if active else tuning["places.offPath"]) if document is not None else []
            chosen = sample(points, cell_id, epoch, active, tuning)
            spacing = active["spacingMeters"] if active else tuning["places.spacing"]
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
        """A potential nemeton anchor, independent of request order and player: one of the cell's candidate points, chosen
        by its position alone, so the same every day and whatever the place mix draws (a rebuilt map can move it)."""
        points = self.points(cell_id, epoch)
        def rank(point):
            return hashlib.sha256(f"nest-v3:{point['lat']:.6f},{point['lng']:.6f}".encode()).digest()
        return min(points, key=rank) if points else None

    def nest_place(self, cell_id: int, epoch: int):
        """The cell's nemeton anchor, unless a neighbour's anchor of higher priority stands within the nest spacing."""
        candidate = self.nest_candidate(cell_id, epoch)
        if candidate is None:
            return None
        priority = lambda cid: (hashlib.sha256(f"nest-v3:{cid}".encode()).digest(), cid)
        own_priority = priority(cell_id)
        for neighbor in s2cells.neighbors(cell_id):
            if priority(neighbor) >= own_priority:
                continue
            other = self.nest_candidate(neighbor, epoch)
            if other and _distance_m(candidate, other) < NEST_SPACING_M:
                return None
        return candidate

    def payload(self, ids: list[int], epoch: int) -> dict:
        self.policy.refresh()
        active, _, tuning = self._rules(epoch)
        spacing = active["spacingMeters"] if active else tuning["places.spacing"]
        cells = {}
        for i in ids:
            places = self.cell(i, epoch)
            nest = self.nest_place(i, epoch)
            if nest is not None:
                # The game shows a nemeton only on a place of the cell's reply: the anchor joins the day's places, under the
                # day's id format (WorldSpawns.CellOf/EpochOf read it), and the places too close to it give way.
                nest = dict(nest, id=f"lab-{i:016x}-{epoch}-{PLACEMENT_VERSION * 1000 + 999}")
                places = [p for p in places if _distance_m(p, nest) >= spacing] + [nest]
            cells[str(i)] = {"center": [round(v, 6) for v in s2cells.center(i)], "places": places,
                             "nest_place_id": nest and nest["id"]}
        return cells


def _distance_m(a: dict, b: dict) -> float:
    """Great-circle metres, including cells touching the antimeridian."""
    phi1, phi2 = math.radians(a['lat']), math.radians(b['lat'])
    dphi, dlambda = phi2 - phi1, math.radians(b['lng'] - a['lng'])
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(min(1.0, h)))


NO_WALK_CLASSES = {"motorway", "motorway_link"}  # no pedestrians
# The index leaves out pavements mapped beside their street (osm_extract_index.skip_road), so a footway that met one would end
# in the air: a loose end joins the nearest other point of the network this close.
WALK_LINK_M = 25.0
WALK_SNAP_M = 150.0   # the player or a place farther than this from every road and path has no walking distance
WALK_GRID_M = 50.0


def walking_metres(roads, origin, targets, limit):
    """Metres walked along the roads and paths from origin to each target ((lat, lng) pairs): None for one farther than
    limit, or off the network. roads: (way id, class, flat lat/lon × 1e7), as FeatureIndex.roads gives them."""
    proj = Projection(*origin)
    ids, xy, adj, segments = {}, [], [], []

    def node(lat, lon):
        i = ids.get((lat, lon))
        if i is None:
            i = ids[(lat, lon)] = len(xy)
            xy.append(proj.xy(lat / 1e7, lon / 1e7))
            adj.append([])
        return i

    def join(a, b, d):
        adj[a].append((b, d))
        adj[b].append((a, d))

    for _, klass, flat in roads:
        if klass in NO_WALK_CLASSES:
            continue
        previous = None
        for k in range(0, len(flat) - 1, 2):
            i = node(flat[k], flat[k + 1])
            if previous is not None and i != previous:
                d = math.dist(xy[previous], xy[i])
                join(previous, i, d)
                segments.append((previous, i, d))
            previous = i
    grid = {}

    def index(s):
        a, b, _ = segments[s]
        (ax, ay), (bx, by) = xy[a], xy[b]
        for gx in range(int(min(ax, bx) // WALK_GRID_M), int(max(ax, bx) // WALK_GRID_M) + 1):
            for gy in range(int(min(ay, by) // WALK_GRID_M), int(max(ay, by) // WALK_GRID_M) + 1):
                grid.setdefault((gx, gy), []).append(s)

    for s in range(len(segments)):
        index(s)

    def nearest(px, py, radius, away_from=None):
        """The nearest point of a segment (not one of away_from's) within radius: (metres off it, segment, metres to its
        start, metres to its end, the point)."""
        reach, best, seen = math.ceil(radius / WALK_GRID_M), None, set()
        for gx in range(int(px // WALK_GRID_M) - reach, int(px // WALK_GRID_M) + reach + 1):
            for gy in range(int(py // WALK_GRID_M) - reach, int(py // WALK_GRID_M) + reach + 1):
                for s in grid.get((gx, gy), ()):
                    if s in seen:
                        continue
                    seen.add(s)
                    a, b, d = segments[s]
                    if away_from in (a, b):
                        continue
                    (ax, ay), (bx, by) = xy[a], xy[b]
                    t = 0.0 if d == 0 else min(1.0, max(0.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / (d * d)))
                    point = (ax + t * (bx - ax), ay + t * (by - ay))
                    off = math.dist((px, py), point)
                    if off <= radius and (best is None or off < best[0]):
                        best = (off, s, t * d, (1 - t) * d, point)
        return best

    for i in range(len(xy)):   # loose ends join the nearest path beside them, which is split there (a junction)
        if len(adj[i]) == 1 and (near := nearest(*xy[i], WALK_LINK_M, away_from=i)) is not None:
            off, s, to_a, to_b, point = near
            a, b, _ = segments[s]
            p = len(xy)
            xy.append(point)
            adj.append([])
            join(i, p, off)
            join(p, a, to_a)
            join(p, b, to_b)
            segments[s] = (a, p, to_a)   # the grid keeps listing s over the whole stretch: nearest() measures what it is now
            segments.append((p, b, to_b))
            index(len(segments) - 1)

    def snap(lat, lng):
        """The nearest point of the network: (metres off it, segment, metres to its start, metres to its end)."""
        found = nearest(*proj.xy(lat, lng), WALK_SNAP_M)
        return None if found is None else found[:4]

    start = snap(*origin)
    if start is None:
        return [None] * len(targets)
    off, s0, to_a, to_b = start
    a0, b0, _ = segments[s0]
    walked = {}
    heap = []
    for i, d in ((a0, off + to_a), (b0, off + to_b)):
        if d < walked.get(i, math.inf):
            walked[i] = d
            heapq.heappush(heap, (d, i))
    while heap:
        d, i = heapq.heappop(heap)
        if d > limit:
            break
        if d > walked[i]:
            continue
        for j, w in adj[i]:
            if (n := d + w) < walked.get(j, math.inf) and n <= limit:
                walked[j] = n
                heapq.heappush(heap, (n, j))

    result = []
    for lat, lng in targets:
        end = snap(lat, lng)
        if end is None:
            result.append(None)
            continue
        t_off, s, t_a, t_b = end
        a, b, _ = segments[s]
        metres = min(walked.get(a, math.inf) + t_a, walked.get(b, math.inf) + t_b) + t_off
        if s == s0:   # the same stretch of path: straight along it
            metres = min(metres, off + abs(to_a - t_a) + t_off)
        result.append(round(metres) if metres <= limit else None)
    return result


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
            if self.path == "/walk":
                # {"from": [lat, lng], "to": [[lat, lng], ...], "limit": metres} -> {"metres": [m or null, ...]}
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536: raise ValueError
                    value = json.loads(self.rfile.read(length))
                    origin, targets, limit = tuple(map(float, value["from"])), value["to"], float(value["limit"])
                    if len(origin) != 2 or not 0 < len(targets) <= 1024 or not 0 < limit <= 10_000: raise ValueError
                    self.respond(200, {"metres": service.walk(origin, [tuple(map(float, t)) for t in targets], limit)})
                except (ValueError, TypeError, KeyError):
                    self.respond(400, {"error": "Invalid walking request."})
                return
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
    parser.add_argument("--index", type=Path, action="append", required=True, help="a feature index, once per map area")
    parser.add_argument("--port", type=int, default=18093)
    parser.add_argument("--policy", type=Path, help="Shared world/placement-policy.json schedule")
    parser.add_argument("--tuning", type=Path, help="The dashboard's world/tuning.json (place mix, places per cell, spacing, street clearance)")
    args = parser.parse_args()
    service = PlayableLocations(open_indexes(args.index), args.policy, args.tuning)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    print(f"playable locations on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
