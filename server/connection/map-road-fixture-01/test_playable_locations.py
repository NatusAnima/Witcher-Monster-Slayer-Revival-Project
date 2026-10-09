import json
import math
import os
from pathlib import Path
import random
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import time
from unittest.mock import patch
import unittest

import playable_locations as pl
import s2cells


class S2CellTests(unittest.TestCase):
    def test_face_cells_and_round_trips(self):
        self.assertEqual(s2cells.from_face_ij(0, 0, 0, 0), 0x1000000000000000)
        rng = random.Random(7)
        for _ in range(500):
            lat, lng = rng.uniform(-85, 85), rng.uniform(-180, 180)
            cell = s2cells.cell_of(lat, lng, 14)
            self.assertEqual(s2cells.level(cell), 14)
            self.assertEqual(s2cells.cell_of(*s2cells.center(cell), 14), cell)
            leaf = s2cells.cell_of(lat, lng, 30)
            self.assertEqual((leaf & -(1 << 32)) | (1 << 32), cell)

    def test_rejects_non_cells(self):
        for bad in (0, 1 << 64, 0xF000000000000000, 0x1000000000000002):
            with self.assertRaises(ValueError):
                s2cells.level(bad)

    def test_neighbor_relation_is_symmetric_at_face_edges_and_corners(self):
        size = 1 << pl.CELL_LEVEL
        positions = (0, 1, size // 2, size - 2, size - 1)
        shift = s2cells.MAX_LEVEL - pl.CELL_LEVEL
        for face in range(6):
            for i in positions:
                for j in positions:
                    cell = s2cells.from_face_ij(face, i << shift, j << shift, pl.CELL_LEVEL)
                    neighbors = s2cells.neighbors(cell)
                    self.assertIn(len(neighbors), (7, 8))
                    for other in neighbors:
                        self.assertIn(cell, s2cells.neighbors(other))


class CandidateTests(unittest.TestCase):
    """A synthetic cell: a street across the middle, a footway beside it and one further away,
    a building, a pond and a wood. Coordinates are fictional."""

    def setUp(self):
        self.cell = s2cells.cell_of(10.0, 20.0, 14)
        self.proj = pl.Projection(*s2cells.center(self.cell))

    def way(self, highway, points, **tags):
        return {"type": "way", "tags": dict(highway=highway, **tags),
                "geometry": [dict(zip(("lat", "lon"), self.proj.latlng(x, y))) for x, y in points]}

    def area(self, kind, x0, y0, x1, y1):
        ring = [self.proj.latlng(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        return {"type": "area", "kind": kind, "rings": [ring]}

    def points(self, *elements):
        return [(p, self.proj.xy(p["lat"], p["lng"])) for p in pl.candidates({"elements": list(elements)}, self.cell)]

    def test_points_keep_clear_of_streets_buildings_and_water(self):
        found = self.points(
            self.way("residential", [(-300, 0), (300, 0)]),
            self.way("footway", [(-300, 8), (300, 8)]),            # sidewalk-like, too close to the street
            self.way("footway", [(-300, 120), (300, 120)]),
            self.way("path", [(-300, -150), (300, -150)], access="private"),
            self.area("building", -50, 110, 50, 130),
            self.area("water", 150, 100, 250, 140))
        self.assertTrue(found)
        for point, (x, y) in found:
            self.assertGreater(abs(y), pl.CARRIAGEWAY_CLEARANCE_M)
            self.assertFalse(-50 - pl.BUILDING_CLEARANCE_M <= x <= 50 + pl.BUILDING_CLEARANCE_M
                             and 110 - pl.BUILDING_CLEARANCE_M <= y <= 130 + pl.BUILDING_CLEARANCE_M)
            self.assertFalse(150 <= x <= 250 and 100 <= y <= 140)
            self.assertNotAlmostEqual(y, -150, delta=1)            # private path
        near_water = [p for p, (x, y) in found if x > 100]
        self.assertTrue(near_water and all(pl.WATER in p["biomes"] for p in near_water))
        self.assertTrue(all(pl.URBAN in p["biomes"] for p, (x, y) in found if abs(x) < 100))

    def test_main_roads_keep_a_wider_clearance(self):
        found = self.points(self.way("primary", [(-300, 0), (300, 0)]),
                            self.way("footway", [(-300, 25), (300, 25)]),
                            self.way("footway", [(-300, 40), (300, 40)]))
        self.assertTrue(found)
        self.assertTrue(all(y > pl.MAJOR_ROAD_CLEARANCE_M for _, (_, y) in found))

    def test_woods_give_forest_points_and_sampling_is_spaced_and_varies(self):
        found = pl.candidates({"elements": [self.area("forest", -200, -200, 200, 200)]}, self.cell)
        self.assertTrue(found and all(p["biomes"] == [pl.FOREST] and p["kind"] == "forest" for p in found))
        first, second = pl.sample(found, self.cell, 0), pl.sample(found, self.cell, 1)
        self.assertEqual(len(first), pl.FOREST_MAX_PER_CELL)  # a cell of nothing but wood still has its woods' share
        xy = [self.proj.xy(p["lat"], p["lng"]) for p in first]
        self.assertTrue(all(math.dist(a, b) >= pl.MIN_SPACING_M for i, a in enumerate(xy) for b in xy[i + 1:]))
        self.assertNotEqual({(p["lat"], p["lng"]) for p in first}, {(p["lat"], p["lng"]) for p in second})
        self.assertEqual(first, pl.sample(found, self.cell, 0))

    def test_a_big_wood_does_not_crowd_out_the_paths_and_parks_beside_it(self):
        # A wood over most of the cell is a grid of hundreds of points; a park and a footway give far fewer. Drawn evenly from
        # all of them, the wood took two thirds of the places and the paths around it were left nearly empty.
        found = pl.candidates({"elements": [
            self.area("forest", -300, -300, 300, 100), self.area("park", -300, 150, 300, 300),
            self.way("footway", [(-300, 125), (300, 125)])]}, self.cell)
        wood = lambda points: sum(p["biomes"][0] == pl.FOREST for p in points)
        self.assertGreater(wood(found), len(found) / 2)  # the wood is most of the points, far more than its half of a cell
        for epoch in range(5):
            places = pl.sample(found, self.cell, epoch)
            self.assertEqual((wood(places), len(places)), (pl.FOREST_MAX_PER_CELL, pl.MAX_PER_CELL))
            self.assertTrue(all(p["id"].startswith(f"lab-{self.cell:016x}-{epoch}-{pl.PLACEMENT_VERSION}") for p in places))
        # with no limit at all (the old draw) the wood took most of the places
        self.assertGreater(sum(wood(pl.sample(found, self.cell, e, woods=pl.MAX_PER_CELL)) for e in range(5)), 5 * pl.FOREST_MAX_PER_CELL)
        for limit in (0, 5, 24):  # and the player can set the limit anywhere in between
            self.assertLessEqual(wood(pl.sample(found, self.cell, 0, woods=limit)), limit)

    def test_path_offsets_stay_in_open_ground_and_avoid_obstacles(self):
        path = self.way('path', [(-180, 0), (180, 0)])
        plain = self.points(path)
        self.assertTrue(plain)
        self.assertTrue(all(abs(y) < 0.2 for _, (_, y) in plain))
        found = self.points(path, self.area('park', -190, -20, 190, 20),
                            self.area('water', -50, 3, 50, 20))
        offset = [(p, x, y) for p, (x, y) in found if p['kind'] == 'path']
        self.assertTrue(offset)
        self.assertTrue(all(5.8 <= abs(y) <= 9.2 for _, x, y in offset))
        self.assertTrue(all(y < 0 for _, x, y in offset if abs(x) < 50))
        self.assertTrue(all(-190 <= x <= 190 and abs(y) < 20 for _, x, y in offset))

    def test_close_nemeta_across_boundary_have_one_winner_for_every_request_subset(self):
        face, i, j, level = s2cells.to_face_ij(self.cell)
        shift = s2cells.MAX_LEVEL - level
        other = s2cells.from_face_ij(face, (i + 1) << shift, j << shift, level)
        corners = s2cells.corners(self.cell)
        lat, lng = ((a + b) / 2 for a, b in zip(corners[1], corners[2]))
        anchor = pl.Projection(lat, lng)
        points = {}
        for cell in (self.cell, other):
            x, y = anchor.xy(*s2cells.center(cell)); scale = 2 / math.hypot(x, y)
            a, b = anchor.latlng(x * scale, y * scale)
            points[cell] = dict(id=f'synthetic-{cell}', lat=a, lng=b, biomes=[pl.GRASSLAND], kind='path')
        service = pl.PlayableLocations(None)
        service.cell = lambda cell, epoch: [points[cell]] if cell in points else []
        self.assertLess(pl._distance_m(*points.values()), 5)
        for epoch in range(12):
            together = service.payload([self.cell, other], epoch)
            self.assertEqual(together, service.payload([other, self.cell], epoch))
            self.assertEqual(together, {**service.payload([self.cell], epoch), **service.payload([other], epoch)})
            self.assertEqual(sum(v['nest_place_id'] is not None for v in together.values()), 1)


class TuningTests(unittest.TestCase):
    """The woods limit comes from the dashboard's file, looked at about once a second."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tuning.json"

    def woods(self, tuning):
        tuning._checked = 0  # skip the one-second pause between looks
        return tuning.woods()

    def save(self, text):
        self.path.write_text(text)
        os.utime(self.path, ns=(time.time_ns() + self.path.stat().st_size, time.time_ns() + self.path.stat().st_size))

    def test_missing_damaged_and_impossible_values_mean_the_default_or_the_last_good_one(self):
        tuning = pl.Tuning(self.path)
        self.assertEqual(self.woods(tuning), pl.FOREST_MAX_PER_CELL)               # no file yet
        self.save(json.dumps({"schemaVersion": 1, "values": {"woods.maxPlaces": 5}}))
        self.assertEqual(self.woods(tuning), 5)
        self.save('{"schemaVersion": 1, "values": {"woods.')                        # half written: the last good value stays
        self.assertEqual(self.woods(tuning), 5)
        self.save(json.dumps({"schemaVersion": 1, "values": {"woods.maxPlaces": 99}}))  # impossible: the default
        self.assertEqual(self.woods(tuning), pl.FOREST_MAX_PER_CELL)
        self.save(json.dumps({"schemaVersion": 1, "values": {"woods.maxPlaces": 0}}))
        self.assertEqual(self.woods(tuning), 0)
        self.path.unlink()                                                          # removed: back to the default
        self.assertEqual(self.woods(tuning), pl.FOREST_MAX_PER_CELL)
        self.assertEqual(pl.Tuning(None).woods(), pl.FOREST_MAX_PER_CELL)

    def test_the_places_follow_the_file_without_a_restart(self):
        cell = s2cells.cell_of(10, 20, pl.CELL_LEVEL)
        proj = pl.Projection(*s2cells.center(cell))
        wood = [proj.latlng(x, y) for x, y in [(-250, -250), (250, -250), (250, 100), (-250, 100)]]
        park = [proj.latlng(x, y) for x, y in [(-250, 150), (250, 150), (250, 280), (-250, 280)]]

        class Index:
            def covers(self, *args): return True
            def document(self, *args, clip=None):
                return {"elements": [dict(type="area", kind="forest", rings=[wood]), dict(type="area", kind="park", rings=[park])]}

        service = pl.PlayableLocations(Index(), None, self.path)
        count = lambda: sum(p["biomes"][0] == pl.FOREST for p in service.cell(cell, 123))
        self.assertEqual(count(), pl.FOREST_MAX_PER_CELL)
        for limit in (3, 20, 0):
            self.save(json.dumps({"schemaVersion": 1, "values": {"woods.maxPlaces": limit}}))
            service.tuning._checked = 0
            self.assertEqual(count(), limit)


class CacheTests(unittest.TestCase):
    def test_lru_and_point_budget_bound_memory_without_changing_results(self):
        memo = pl._BoundedMemo(entries=2, points=5)
        calls = []
        def get(key, count):
            return memo.get(key, lambda: calls.append(key) or [key] * count)
        self.assertEqual(get('a', 2), ['a'] * 2)
        get('b', 2); get('a', 2); get('c', 2)  # b is least recently used.
        self.assertEqual(calls, ['a', 'b', 'c'])
        self.assertEqual(memo.stats()['entries'], 2)
        get('b', 4)  # The point budget, not just the entry budget, evicts both older rows.
        self.assertEqual((memo.stats()['entries'], memo.stats()['points']), (1, 4))
        get('oversized', 6); get('oversized', 6)
        self.assertEqual(calls.count('oversized'), 2)
        self.assertLessEqual(memo.stats()['points'], 5)

    def test_simultaneous_misses_compute_once_and_failures_retry(self):
        memo = pl._BoundedMemo(entries=4, points=100)
        started, release = threading.Event(), threading.Event()
        calls = []
        def compute():
            calls.append(1); started.set()
            if not release.wait(3): raise TimeoutError('synthetic gate')
            return ['same']
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(memo.get, 'one', compute) for _ in range(8)]
            self.assertTrue(started.wait(3)); release.set()
            self.assertEqual([f.result(3) for f in futures], [['same']] * 8)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            memo.get('bad', lambda: (_ for _ in ()).throw(ValueError('synthetic')))
        self.assertEqual(memo.get('bad', lambda: ['recovered']), ['recovered'])
        self.assertEqual(memo.stats()['inflight'], 0)

    def test_sample_cache_separates_epochs_and_reproduces_after_eviction(self):
        cell = s2cells.cell_of(10, 20, pl.CELL_LEVEL)
        proj = pl.Projection(*s2cells.center(cell))
        ring = [proj.latlng(x, y) for x, y in [(-200, -200), (200, -200), (200, 200), (-200, 200)]]
        class Index:
            calls = 0
            def covers(self, *args): return True
            def document(self, *args, clip=None):
                self.calls += 1
                return {'elements': [dict(type='area', kind='forest', rings=[ring])]}
        index = Index(); service = pl.PlayableLocations(index)
        service._sampled = pl._BoundedMemo(entries=2, points=48)
        with patch.object(pl, 'sample', wraps=pl.sample) as sample:
            original = service.cell(cell, 123)
            self.assertEqual(original, service.cell(cell, 123))
            service.cell(cell, 124); service.cell(cell, 125)
            self.assertEqual(original, service.cell(cell, 123))
            self.assertEqual(sample.call_count, 4)
        self.assertEqual(index.calls, 1)
        self.assertTrue(all(f'-123-' in row['id'] for row in original))
        self.assertEqual(service._sampled.stats()['entries'], 2)


if __name__ == "__main__":
    unittest.main()
