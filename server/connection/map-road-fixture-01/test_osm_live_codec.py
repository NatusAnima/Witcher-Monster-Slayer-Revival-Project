#!/usr/bin/env python3
"""Tests the live OSM FeatureTile encoder with invented miniature data (stdlib only)."""
import math
import unittest

from osm_live_codec import build_grid_canary, build_live_tile
from osm_tile_codec import ATTRIBUTION

ZOOM, TILE_X, TILE_Y = 17, 70000, 42000


def varint(data, index):
    result = shift = 0
    while True:
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return result, index


def fields(data):
    """Minimal protobuf wire reader: list of (field, value) for varint/length types."""
    index, out = 0, []
    while index < len(data):
        key, index = varint(data, index)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, index = varint(data, index)
        elif wire == 2:
            length, index = varint(data, index)
            value = data[index:index + length]
            index += length
        else:
            raise AssertionError(f"unexpected wire type {wire}")
        out.append((field, value))
    return out


def zigzag_list(data):
    values, index = [], 0
    while index < len(data):
        raw, index = varint(data, index)
        values.append((raw >> 1) ^ -(raw & 1))
    return values


def decode_features(raw):
    features = []
    for field, value in fields(raw):
        if field != 3:
            continue
        record = {"lines": []}
        for sub, sub_value in fields(value):
            if sub == 1:
                record["place_id"] = sub_value.decode()
            elif sub == 2:
                record["type"] = sub_value
            elif sub == 4:
                record["name"] = sub_value.decode()
            elif sub == 3:
                for geometry_field, line in fields(sub_value):
                    assert geometry_field == 2
                    (vertex_field, vertices), = fields(line)
                    assert vertex_field == 1
                    parts = dict(fields(vertices))
                    xs, ys = zigzag_list(parts[1]), zigzag_list(parts[2])
                    points, x, y = [], 0, 0
                    for dx, dy in zip(xs, ys):
                        x, y = x + dx, y + dy
                        points.append((x, y))
                    record["lines"].append(points)
        features.append(record)
    return features


def geo(px, py):
    scale = 1 << ZOOM
    world_x, world_y = TILE_X + px / 4096, TILE_Y + py / 4096
    return {"lon": world_x / scale * 360 - 180,
            "lat": math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * world_y / scale))))}


def document():
    return {"elements": [
        # Leaves and re-enters the tile: two clipped lines, one feature.
        {"type": "way", "id": 11, "tags": {"highway": "residential", "name": "Testowa"},
         "geometry": [geo(100, 100), geo(5000, 100), geo(5000, 3000), geo(100, 3000)]},
        {"type": "way", "id": 12, "tags": {"highway": "footway"},
         "geometry": [geo(200, 200), geo(400, 900)]},
        {"type": "way", "id": 13, "tags": {"highway": "secondary"},
         "geometry": [geo(10, 2000), geo(4000, 2100)]},
        {"type": "way", "id": 14, "tags": {"highway": "proposed"},
         "geometry": [geo(1, 1), geo(2, 2)]},
        {"type": "way", "id": 12, "tags": {"highway": "footway"},
         "geometry": [geo(200, 200), geo(400, 900)]},
    ]}


class LiveCodecTests(unittest.TestCase):
    def test_every_feature_has_unique_stable_place_id(self):
        raw, summary = build_live_tile(document(), ZOOM, TILE_X, TILE_Y)
        features = decode_features(raw)
        ids = [feature["place_id"] for feature in features]
        self.assertEqual(ids, ["osm-way-11", "osm-way-12", "osm-way-13"])
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual([feature["type"] for feature in features], [530, 34, 531])
        self.assertEqual(summary["feature_count"], 3)

    def test_clipped_pieces_stay_in_one_feature(self):
        raw, summary = build_live_tile(document(), ZOOM, TILE_X, TILE_Y)
        first = decode_features(raw)[0]
        self.assertEqual(len(first["lines"]), 2)
        self.assertEqual(first["name"], "Testowa")
        self.assertEqual(summary["line_count"], 4)
        for line in first["lines"]:
            for x, y in line:
                self.assertTrue(0 <= x <= 4096 and 0 <= y <= 4096)

    def test_tile_header_and_attribution(self):
        raw, _summary = build_live_tile(document(), ZOOM, TILE_X, TILE_Y)
        top = fields(raw)
        self.assertEqual(top[0], (1, f"tiles/@{TILE_X},{TILE_Y},{ZOOM}z".encode()))
        coordinates = dict(fields(top[1][1]))
        self.assertEqual((coordinates[1], coordinates[2], coordinates[3]), (TILE_X, TILE_Y, ZOOM))
        provider = [value for field, value in top if field == 5][0]
        self.assertEqual(dict(fields(provider))[1].decode(), ATTRIBUTION)

    def test_same_way_keeps_its_id_in_neighbouring_tile(self):
        raw, _ = build_live_tile(document(), ZOOM, TILE_X + 1, TILE_Y)
        self.assertEqual([feature["place_id"] for feature in decode_features(raw)], ["osm-way-11"])

    def test_grid_canary_ids_are_unique(self):
        raw, count = build_grid_canary(ZOOM, TILE_X, TILE_Y, (33, 530, 531))
        features = decode_features(raw)
        self.assertEqual(count, 17)
        self.assertEqual(len({feature["place_id"] for feature in features}), 17)
        self.assertEqual(features[-1]["lines"], [[(0, 0), (4096, 4096)]])


class RoadClassificationTests(unittest.TestCase):
    def test_main_alleys_and_cycleways_become_arterial(self):
        from osm_live_codec import road_feature_type
        self.assertEqual(road_feature_type({"highway": "pedestrian"}), 531)
        self.assertEqual(road_feature_type({"highway": "cycleway"}), 531)
        self.assertEqual(road_feature_type({"highway": "footway", "surface": "asphalt",
                                            "name": "Aleja Leśna"}), 531)
        self.assertEqual(road_feature_type({"highway": "path", "surface": "paving_stones",
                                            "width": "4"}), 531)
        self.assertEqual(road_feature_type({"highway": "footway", "surface": "asphalt"}), 34)
        self.assertEqual(road_feature_type({"highway": "footway", "surface": "ground",
                                            "name": "Leśna"}), 34)
        self.assertEqual(road_feature_type({"highway": "residential"}), 530)
        self.assertEqual(road_feature_type({"highway": "tertiary"}), 530)
        self.assertEqual(road_feature_type({"highway": "unclassified"}), 530)
        self.assertEqual(road_feature_type({"highway": "secondary"}), 531)
        self.assertEqual(road_feature_type({"highway": "primary"}), 532)

    def test_cycle_track_along_street_is_still_dropped(self):
        from osm_live_codec import build_live_tile
        street = {"type": "way", "id": 1, "tags": {"highway": "residential"},
                  "geometry": [geo(0, 2000), geo(4096, 2000)]}
        cycle_track = {"type": "way", "id": 2, "tags": {"highway": "cycleway"},
                       "geometry": [geo(300, 2170), geo(3800, 2170)]}
        park_cycleway = {"type": "way", "id": 3, "tags": {"highway": "cycleway"},
                         "geometry": [geo(300, 3500), geo(3800, 3500)]}
        raw, summary = build_live_tile({"elements": [street, cycle_track, park_cycleway]},
                                       ZOOM, TILE_X, TILE_Y)
        features = decode_features(raw)
        self.assertEqual([(f["place_id"], f["type"]) for f in features],
                         [("osm-way-1", 530), ("osm-way-3", 531)])
        self.assertEqual(summary["dropped_parallel_footpaths"], 1)
        self.assertNotIn(531, {k for k, v in summary["feature_type_counts"].items() if v < 0})


class ParallelFootpathTests(unittest.TestCase):
    def tile(self, elements):
        from osm_live_codec import build_live_tile
        raw, summary = build_live_tile({"elements": elements}, ZOOM, TILE_X, TILE_Y)
        return [f["place_id"] for f in decode_features(raw)], summary

    def test_sidewalk_along_street_is_dropped_but_crossing_path_kept(self):
        # At z17 near 52 N one tile unit is about 0.046 m, so 170 units is about 8 m.
        street = {"type": "way", "id": 1, "tags": {"highway": "residential"},
                  "geometry": [geo(0, 2000), geo(4096, 2000)]}
        sidewalk = {"type": "way", "id": 2, "tags": {"highway": "footway"},
                    "geometry": [geo(300, 2170), geo(3800, 2170)]}
        crossing_path = {"type": "way", "id": 3, "tags": {"highway": "footway"},
                         "geometry": [geo(1000, 1000), geo(1000, 3000)]}
        distant_path = {"type": "way", "id": 4, "tags": {"highway": "cycleway"},
                        "geometry": [geo(300, 3500), geo(3800, 3500)]}
        ids, summary = self.tile([street, sidewalk, crossing_path, distant_path])
        self.assertEqual(ids, ["osm-way-1", "osm-way-3", "osm-way-4"])
        self.assertEqual(summary["dropped_parallel_footpaths"], 1)

    def test_paths_without_streets_are_untouched(self):
        park_path = {"type": "way", "id": 5, "tags": {"highway": "footway"},
                     "geometry": [geo(300, 2170), geo(3800, 2170)]}
        ids, summary = self.tile([park_path])
        self.assertEqual(ids, ["osm-way-5"])
        self.assertEqual(summary["dropped_parallel_footpaths"], 0)


if __name__ == "__main__":
    unittest.main()
