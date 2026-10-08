#!/usr/bin/env python3
"""Tests the SQLite highway index reader with an invented database (no pyosmium needed)."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from osm_extract_index import (
    SCHEMA_VERSION,
    FeatureIndex,
    classify_area,
    clip_ring,
    clip_rings,
    create_schema,
    pack_coordinates,
    pack_rings,
    ring_area_m2,
    skip_road,
    unpack_coordinates,
    unpack_rings,
)
from osm_live_sidecar import LocalIndexSource, tile_bounds


def make_index(path: Path):
    db = sqlite3.connect(path)
    create_schema(db)
    ways = [
        (1, "road", "residential", "Pierwsza", None, [(52.40, 16.90), (52.41, 16.91)]),
        (2, "road", "footway", None, '{"surface":"asphalt","width":"4"}',
         [(52.405, 16.905), (52.406, 16.906)]),
        (3, "road", "primary", "Daleka", None, [(50.0, 20.0), (50.01, 20.01)]),
        (4, "water_line", "river", "Rzeka", None, [(52.401, 16.901), (52.402, 16.902)]),
    ]
    for way_id, kind, klass, name, attrs, points in ways:
        db.execute("INSERT INTO ways VALUES (?,?,?,?,?,?)",
                   (way_id, kind, klass, name, attrs, pack_coordinates(points)))
        lats, lons = [p[0] for p in points], [p[1] for p in points]
        db.execute("INSERT INTO ways_rtree VALUES (?,?,?,?,?)",
                   (way_id, min(lons), max(lons), min(lats), max(lats)))
    park = [[(52.402, 16.902), (52.402, 16.904), (52.404, 16.904), (52.404, 16.902)],
            [(52.4025, 16.9025), (52.4035, 16.9025), (52.4035, 16.9035)]]
    db.execute("INSERT INTO areas VALUES (?,?,?,?,?)", (7, 1234, "park", "Park", pack_rings(park)))
    db.execute("INSERT INTO areas_rtree VALUES (?,?,?,?,?)", (7, 16.902, 16.904, 52.402, 52.404))
    db.executemany("INSERT INTO meta VALUES (?,?)", [("schema", SCHEMA_VERSION),
                                                    ("source_timestamp", "test-time"),
                                                    ("ways", "3")])
    db.commit()
    db.close()


class ExtractIndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "index.sqlite"
        make_index(self.path)
        self.index = FeatureIndex(self.path)
        self.addCleanup(self.index.db.close)

    def test_coordinates_round_trip(self):
        points = [(10.1234567, 20.7654321), (-33.5, 151.25)]
        for (lat, lon), (lat2, lon2) in zip(points, unpack_coordinates(pack_coordinates(points))):
            self.assertAlmostEqual(lat, lat2, places=6)
            self.assertAlmostEqual(lon, lon2, places=6)

    def test_clip_keeps_inside_vertices_and_cuts_on_the_box(self):
        square = [(0.0, 0.0), (0.0, 4.0), (4.0, 4.0), (4.0, 0.0)]
        box = (1.0, -1.0, 3.0, 5.0)  # south, west, north, east: cuts the top and bottom off
        clipped = clip_ring(square, box)
        self.assertEqual(sorted(clipped), [(1.0, 0.0), (1.0, 4.0), (3.0, 0.0), (3.0, 4.0)])
        self.assertIsNone(clip_rings([[(9.0, 9.0), (9.0, 9.5), (9.5, 9.5)]], box))
        # a hole outside the box goes, the outer ring stays
        self.assertEqual(len(clip_rings([square, [(3.5, 1.0), (3.5, 2.0), (3.8, 2.0)]], box)), 1)

    def test_clipped_query_cuts_only_areas_reaching_outside(self):
        south, west, north, east = 52.4021, 16.9021, 52.4031, 16.9031
        whole = self.index.document(south, west, north, east)
        cut = self.index.document(south, west, north, east, clip=(52.4026, 16.9020, 52.4040, 16.9040))
        self.assertEqual([e["id"] for e in whole["elements"]], [e["id"] for e in cut["elements"]])
        rings = [e for e in cut["elements"] if e["type"] == "area"][0]["rings"]
        self.assertTrue(all(lat >= 52.4026 for lat, _ in rings[0]))
        self.assertEqual(self.index.document(south, west, north, east, clip=(50, 16, 54, 18)), whole)

    def test_rings_round_trip(self):
        rings = [[(1.0, 2.0), (3.0, 4.0), (5.0, 6.5)], [(1.5, 2.5), (2.5, 3.5), (3.5, 2.5)]]
        self.assertEqual(unpack_rings(pack_rings(rings)), rings)

    def test_ring_area_in_square_metres(self):
        # About 100 m x 100 m near 52 N.
        ring = [(52.0, 16.0), (52.0, 16.0014617), (52.0009047, 16.0014617), (52.0009047, 16.0)]
        self.assertAlmostEqual(ring_area_m2(ring), 10000, delta=50)

    def test_sidewalks_and_parking_lanes_are_skipped(self):
        self.assertTrue(skip_road({"highway": "footway", "footway": "sidewalk"}))
        self.assertTrue(skip_road({"highway": "footway", "footway": "crossing"}))
        self.assertTrue(skip_road({"highway": "service", "service": "parking_aisle"}))
        self.assertTrue(skip_road({"highway": "service", "service": "driveway"}))
        self.assertTrue(skip_road({"highway": "footway", "area": "yes"}))
        self.assertTrue(skip_road({"highway": "pedestrian", "area": "yes"}))
        self.assertFalse(skip_road({"highway": "pedestrian"}))
        self.assertFalse(skip_road({"highway": "footway"}))
        self.assertFalse(skip_road({"highway": "service", "service": "alley"}))
        self.assertFalse(skip_road({"highway": "residential", "sidewalk": "separate"}))

    def test_area_classification(self):
        self.assertEqual(classify_area({"building": "yes", "landuse": "forest"}), "building")
        self.assertIsNone(classify_area({"building": "no"}))
        self.assertEqual(classify_area({"natural": "water"}), "water")
        self.assertEqual(classify_area({"landuse": "forest"}), "forest")
        self.assertEqual(classify_area({"natural": "wood"}), "forest")
        self.assertEqual(classify_area({"leisure": "park"}), "park")
        self.assertEqual(classify_area({"natural": "beach"}), "beach")
        for lawn in ({"landuse": "grass"}, {"landuse": "meadow"}, {"leisure": "playground"},
                     {"leisure": "pitch"}, {"landuse": "cemetery"}, {"landuse": "allotments"},
                     {"leisure": "swimming_pool"}):
            self.assertIsNone(classify_area(lawn), lawn)
        self.assertIsNone(classify_area({"amenity": "parking"}))

    def test_bbox_query_returns_overpass_shaped_elements(self):
        document = self.index.document(52.399, 16.899, 52.407, 16.907)
        ids = sorted(element["id"] for element in document["elements"] if element["type"] == "way")
        self.assertEqual(ids, [1, 2, 4])
        river = [e for e in document["elements"] if e.get("id") == 4][0]
        self.assertEqual(river["tags"], {"waterway": "river", "name": "Rzeka"})
        park = [e for e in document["elements"] if e["type"] == "area"][0]
        self.assertEqual((park["id"], park["osm_area"], park["kind"], park["name"]), (7, 1234, "park", "Park"))
        self.assertEqual(len(park["rings"]), 2)
        path = [e for e in document["elements"] if e.get("id") == 2][0]
        self.assertEqual(path["tags"], {"highway": "footway", "surface": "asphalt", "width": "4"})
        first = [e for e in document["elements"] if e.get("id") == 1][0]
        self.assertEqual(first["tags"], {"highway": "residential", "name": "Pierwsza"})
        self.assertEqual(len(first["geometry"]), 2)
        self.assertEqual(document["osm3s"]["timestamp_osm_base"], "test-time")

    def test_coverage_and_local_source_without_fallback(self):
        inside = (17, 71680, 43040)  # Near the invented Poznań-area ways.
        source = LocalIndexSource(self.index)
        south, west, north, east = tile_bounds(*inside)
        self.assertEqual(self.index.covers(south, west, north, east),
                         source.covers(inside))
        far = (17, 1, 1)
        self.assertFalse(source.covers(far))
        self.assertFalse(source.available(far))
        with self.assertRaises(LookupError):
            source.document(far)

    def test_rejects_unknown_schema(self):
        db = sqlite3.connect(self.path)
        db.execute("UPDATE meta SET value='other' WHERE key='schema'")
        db.commit()
        db.close()
        with self.assertRaises(ValueError):
            FeatureIndex(self.path)


if __name__ == "__main__":
    unittest.main()
