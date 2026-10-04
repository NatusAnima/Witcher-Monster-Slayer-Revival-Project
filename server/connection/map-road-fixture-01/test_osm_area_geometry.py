#!/usr/bin/env python3
"""Tests polygon clipping, earcut triangulation and Area encoding (stdlib only)."""
import math
import unittest

from osm_area_geometry import _ring_area, clip_polygon, earcut, encode_area, encode_extruded_area
from osm_live_codec import build_area_canary, build_live_tile, build_river_canary
from test_osm_live_codec import TILE_X, TILE_Y, ZOOM, fields, geo, zigzag_list, varint


def packed_ints(data):
    values, index = [], 0
    while index < len(data):
        value, index = varint(data, index)
        values.append(value)
    return values


def decode_area(data):
    parts = {}
    for field, value in fields(data):
        parts.setdefault(field, []).append(value)
    vertices_msg = dict(fields(parts[2][0]))
    xs, ys = zigzag_list(vertices_msg[1]), zigzag_list(vertices_msg[2])
    vertices, x, y = [], 0, 0
    for dx, dy in zip(xs, ys):
        x, y = x + dx, y + dy
        vertices.append((x, y))
    return {
        "vertices": vertices,
        "type": parts[3][0],
        "triangles": packed_ints(parts[4][0]),
        "z_order": parts.get(5, [0])[0],
        "breaks": packed_ints(parts[6][0]),
        "external": parts[7][0],
        "internal": packed_ints(parts[8][0]) if 8 in parts else [],
    }


def triangle_area(vertices, triangles):
    total = 0
    for k in range(0, len(triangles), 3):
        (ax, ay), (bx, by), (cx, cy) = (vertices[i] for i in triangles[k:k + 3])
        total += abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
    return total


class EarcutTests(unittest.TestCase):
    def check(self, rings):
        flat, holes = [], []
        for index, ring in enumerate(rings):
            if index:
                holes.append(len(flat) // 2)
            for x, y in ring:
                flat.extend((x, y))
        triangles = earcut(flat, holes)
        vertices = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        expected = abs(_ring_area(rings[0])) - sum(abs(_ring_area(r)) for r in rings[1:])
        self.assertAlmostEqual(triangle_area(vertices, triangles), expected, places=6)
        return triangles

    def test_square_with_hole(self):
        triangles = self.check([[(0, 0), (100, 0), (100, 100), (0, 100)],
                                [(20, 20), (20, 80), (80, 80), (80, 20)]])
        self.assertEqual(len(triangles), 24)

    def test_concave_star_and_large_hashed_polygon(self):
        star = [(50 + (40 if i % 2 == 0 else 15) * math.cos(i * math.pi / 8),
                 50 + (40 if i % 2 == 0 else 15) * math.sin(i * math.pi / 8)) for i in range(16)]
        self.check([star])
        big = [(2000 + 1500 * math.cos(2 * math.pi * i / 400) * (1 + 0.05 * math.sin(i * 0.37)),
                2000 + 1500 * math.sin(2 * math.pi * i / 400) * (1 + 0.05 * math.sin(i * 0.37)))
               for i in range(400)]
        hole = [(2000 + 200 * math.cos(2 * math.pi * i / 30), 2000 + 200 * math.sin(2 * math.pi * i / 30))
                for i in range(30)]
        self.check([big, hole])


class ClipAndEncodeTests(unittest.TestCase):
    def test_clip_keeps_inside_part_and_drops_outside_hole(self):
        rings = [[(-500, 1000), (3000, -200), (5000, 3000), (1000, 5000)],
                 [(1000, 1000), (1500, 1000), (1500, 1500), (1000, 1500)],
                 [(5000, 5000), (5100, 5000), (5100, 5100)]]
        clipped = clip_polygon(rings)
        self.assertEqual(len(clipped), 2)
        for x, y in clipped[0]:
            self.assertTrue(0 <= x <= 4096 and 0 <= y <= 4096)
        self.assertIsNone(clip_polygon([[(5000, 5000), (6000, 5000), (6000, 6000)]]))

    def test_area_message_marks_tile_border_edges_internal(self):
        clipped = clip_polygon([[(-100, -100), (2000, -100), (2000, 2000), (-100, 2000)]])
        area = decode_area(encode_area(clipped, z_order=2))
        self.assertEqual(area["type"], 1)
        self.assertEqual(area["z_order"], 2)
        self.assertEqual(area["breaks"], [len(area["vertices"])])
        self.assertEqual(area["external"], 1)
        self.assertEqual(sorted(area["vertices"]), [(0, 0), (0, 2000), (2000, 0), (2000, 2000)])
        border = []
        for index, point in enumerate(area["vertices"]):
            following = area["vertices"][(index + 1) % len(area["vertices"])]
            if (point[0] == following[0] == 0) or (point[1] == following[1] == 0):
                border.append(index)
        self.assertEqual(sorted(area["internal"]), sorted(border))
        self.assertEqual(len(border), 2)
        self.assertAlmostEqual(triangle_area(area["vertices"], area["triangles"]), 2000 * 2000)

    def test_extruded_area_uses_default_height(self):
        clipped = clip_polygon([[(10, 10), (20, 10), (20, 20), (10, 20)]])
        extruded = dict(fields(encode_extruded_area(encode_area(clipped))))
        self.assertEqual(set(extruded), {1})


class TileWithAreasTests(unittest.TestCase):
    def document(self):
        def ring(points):
            return [(g["lat"], g["lon"]) for g in (geo(px, py) for px, py in points)]
        return {"elements": [
            {"type": "area", "id": 1, "osm_area": 10, "kind": "forest", "name": "Las",
             "rings": [ring([(-200, -200), (1500, -200), (1500, 1500), (-200, 1500)])]},
            {"type": "area", "id": 2, "osm_area": 20, "kind": "building", "name": None,
             "rings": [ring([(2000, 2000), (2100, 2000), (2100, 2100), (2000, 2100)])]},
            {"type": "area", "id": 3, "osm_area": 30, "kind": "water", "name": "Staw",
             "rings": [ring([(9000, 9000), (9100, 9000), (9100, 9100)])]},
            {"type": "way", "id": 40, "tags": {"waterway": "river", "name": "Warta"},
             "geometry": [geo(0, 3000), geo(4096, 3200)]},
            {"type": "way", "id": 41, "tags": {"highway": "residential"},
             "geometry": [geo(0, 100), geo(4096, 100)]},
        ]}

    def test_feature_types_order_and_geometry_fields(self):
        raw, summary = build_live_tile(self.document(), ZOOM, TILE_X, TILE_Y)
        features = []
        for field, value in fields(raw):
            if field == 3:
                parts = dict(fields(value))
                features.append((parts[1].decode(), parts[2], {f for f, _ in fields(parts[3])}))
        self.assertEqual(features, [
            ("osm-area-10-1", 51, {1}),   # Forest region -> Geometry.areas
            ("osm-area-20-2", 1, {3}),    # Structure -> Geometry.extruded_areas
            ("osm-way-40", 4, {2}),       # Water line
            ("osm-way-41", 530, {2}),     # Road
        ])
        self.assertEqual(summary["area_count"], 2)

    def test_region_geometry_is_never_empty(self):
        raw, _ = build_live_tile(self.document(), ZOOM, TILE_X + 5, TILE_Y + 5)
        for field, value in fields(raw):
            if field == 3:
                parts = dict(fields(value))
                self.assertNotEqual(parts[3], b"")


class ExternalEdgeSwitchTests(unittest.TestCase):
    def test_area_without_external_edges_has_no_edge_fields(self):
        clipped = clip_polygon([[(-100, -100), (2000, -100), (2000, 2000), (-100, 2000)]])
        parts = dict(fields(encode_area(clipped, external_edges=False)))
        self.assertNotIn(7, parts)
        self.assertNotIn(8, parts)

    def test_river_canary_crosses_tile_with_internal_border_edges(self):
        raw, count = build_river_canary(ZOOM, TILE_X, TILE_Y)
        self.assertEqual(count, 2)
        river = [dict(fields(v)) for f, v in fields(raw) if f == 3][0]
        (geometry_field, area), = fields(river[3])
        decoded = decode_area(area)
        self.assertEqual(geometry_field, 1)
        self.assertEqual(len(decoded["internal"]), 2)


class AreaCanaryTests(unittest.TestCase):
    def test_every_class_appears_with_unique_ids(self):
        raw, count = build_area_canary(ZOOM, TILE_X, TILE_Y)
        features = []
        for field, value in fields(raw):
            if field == 3:
                parts = dict(fields(value))
                features.append((parts[1].decode(), parts[2]))
        self.assertEqual(count, 64)
        self.assertEqual(len({place for place, _ in features}), 64)
        self.assertEqual({kind for _, kind in features}, {1, 4, 49, 50, 51})

    def test_selected_class_and_cell_size(self):
        raw, count = build_area_canary(ZOOM, TILE_X, TILE_Y, cell=2048, kinds=("water",))
        self.assertEqual(count, 4)


if __name__ == "__main__":
    unittest.main()
