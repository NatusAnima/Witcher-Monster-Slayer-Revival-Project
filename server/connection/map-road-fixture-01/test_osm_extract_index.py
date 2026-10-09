#!/usr/bin/env python3
"""Tests the SQLite highway index reader with an invented database (no pyosmium needed)."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from osm_extract_index import (
    SCHEMA_VERSION,
    FeatureIndex,
    build_index,
    classify_area,
    create_schema,
    eta_seconds,
    pack_coordinates,
    pack_rings,
    parse_status,
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


class ProgressTests(unittest.TestCase):
    def test_eta_waits_for_five_percent_then_extrapolates(self):
        self.assertIsNone(eta_seconds(100, 110, 1100, 5.0))  # 1% of the features phase: too early to say
        self.assertEqual(eta_seconds(0, 250, 1000, 10.0), 30)  # a quarter in 10 s: 30 s left
        self.assertIsNone(eta_seconds(500, 500, 500, 1.0))  # nothing to read

    def test_memory_figures_are_read_from_proc_status(self):
        text = "Name:\tpython\nVmHWM:\t  204800 kB\nVmRSS:\t  102400 kB\nRssAnon:\t   51200 kB\nRssFile:\t   51200 kB\nThreads:\t2\n"
        self.assertEqual(parse_status(text), {"peak_mb": 200, "rss_mb": 100, "rss_anon_mb": 50, "rss_file_mb": 50})


MONACO = Path(__file__).resolve().parents[3] / "local" / "cache" / "monaco-latest.osm.pbf"


@unittest.skipUnless(MONACO.is_file() and importlib.util.find_spec("osmium"), "needs pyosmium and local/cache/monaco-latest.osm.pbf")
class BuildMonaco(unittest.TestCase):
    """The real builder on a 0.7 MB extract: the node index in a file builds the same map as the one in RAM."""

    def test_file_backed_node_index_builds_the_same_map(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # Windows keeps the node file mapped until exit
            built = {}
            for name, low_memory in (("memory", False), ("file", True)):
                with contextlib.redirect_stdout(io.StringIO()) as printed:
                    built[name] = build_index(MONACO, Path(tmp) / f"{name}.sqlite", low_memory)
                self.assertIn("PHASE reading the map", printed.getvalue())
            self.assertGreater(built["memory"]["roads"], 0)
            for key in ("roads", "areas", "water_lines", "skipped_roads"):
                self.assertEqual(built["file"][key], built["memory"][key], key)
            if os.name != "nt":
                self.assertFalse((Path(tmp) / "file.sqlite.nodes").exists(), "the temporary node file is removed")
            self.assertEqual(FeatureIndex(Path(tmp) / "file.sqlite").meta["schema"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
