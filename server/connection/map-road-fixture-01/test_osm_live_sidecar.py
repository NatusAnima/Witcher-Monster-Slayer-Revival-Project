#!/usr/bin/env python3
"""Loopback tests for the live OSM sidecar with an in-memory source (no network)."""
import http.client
import json
import threading
import time
import unittest

from osm_live_sidecar import GridCanarySource, LiveTileServer, fetch_key, tile_bounds
from test_osm_live_codec import decode_features, document

TILE = (17, 70000, 42000)


class FakeSource:
    """Mimics OverpassSource: areas become available after an explicit prefetch."""

    offline = False

    def __init__(self, ready=True):
        self.ready = set()
        self.ready_all = ready
        self.prefetched = []
        self.stats = {}

    def available(self, key):
        return self.ready_all or key in self.ready

    def prefetch(self, key):
        self.prefetched.append(key)
        self.ready.add(key)

    def document(self, key):
        return document()


class LiveSidecarTests(unittest.TestCase):
    def start(self, source, blocking=False):
        events = []
        server = LiveTileServer(0, source, fetch_zoom=15, emit=events.append, blocking=blocking)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, events

    def get(self, server, path):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_health_and_backlog(self):
        server, _ = self.start(FakeSource())
        status, body = self.get(server, "/health")
        health = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(health["feature_routing"], "any_valid_xyz")
        self.assertEqual(health["attribution"], "© OpenStreetMap contributors")
        self.assertGreaterEqual(server.request_queue_size, 1024)

    def test_any_address_is_served_with_place_ids(self):
        server, events = self.start(FakeSource())
        status, body = self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(status, 200)
        ids = [feature["place_id"] for feature in decode_features(body)]
        self.assertEqual(ids, ["osm-way-11", "osm-way-12", "osm-way-13"])
        rendered = json.dumps(events)
        self.assertNotIn(str(TILE[1]), rendered)
        self.assertNotIn(str(TILE[2]), rendered)

    def test_missing_area_answers_503_at_once_then_200(self):
        source = FakeSource(ready=False)
        server, _ = self.start(source)
        started = time.monotonic()
        status, _ = self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(status, 503)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(source.prefetched, [fetch_key(*TILE, 15)])
        status, _ = self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(status, 200)

    def test_google_style_paths_from_patched_client(self):
        server, events = self.start(FakeSource())
        status, body = self.get(server, "/v1/featuretiles/@%d,%d,%dz?key=SECRET&v=1" % (TILE[1], TILE[2], TILE[0]))
        self.assertEqual(status, 200)
        self.assertEqual([f["place_id"] for f in decode_features(body)],
                         ["osm-way-11", "osm-way-12", "osm-way-13"])
        self.assertNotIn("SECRET", json.dumps(events))
        self.assertEqual(self.get(server, "/v1/featuretiles/@1,2z")[0], 404)

    def test_allow_client_closes_other_peers(self):
        events = []
        server = LiveTileServer(0, FakeSource(), fetch_zoom=15, emit=events.append,
                                allow_clients=("192.0.2.7",))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises((http.client.RemoteDisconnected, ConnectionError)):
            self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(server.stats["refused_client"], 1)
        self.assertEqual(events, [])
        server.allow_clients = frozenset({"127.0.0.1"})
        self.assertEqual(self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)[0], 200)

    def test_invalid_and_out_of_range_addresses(self):
        server, _ = self.start(FakeSource())
        for path in ("/lab/feature-tile/17/131072/1", "/lab/feature-tile/5/1/1",
                     "/other", "/lab/feature-tile/a/b/c", "/v1/featuretiles/@1,1,5z"):
            self.assertEqual(self.get(server, path)[0], 404, path)

    def test_grid_canary_source(self):
        server, _ = self.start(GridCanarySource(types=(33, 532, 530)))
        status, body = self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(status, 200)
        self.assertEqual(len(decode_features(body)), 17)

    def test_only_kinds_keeps_selected_classes(self):
        events = []
        server = LiveTileServer(0, FakeSource(), fetch_zoom=15, emit=events.append, only_kinds=("road",))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        status, body = self.get(server, "/lab/feature-tile/%d/%d/%d" % TILE)
        self.assertEqual(status, 200)
        self.assertEqual([f["place_id"] for f in decode_features(body)],
                         ["osm-way-11", "osm-way-12", "osm-way-13"])

    def test_fetch_key_and_bounds(self):
        self.assertEqual(fetch_key(17, 71700, 43052, 15), (15, 17925, 10763))
        self.assertEqual(fetch_key(14, 8962, 5381, 15), (14, 8962, 5381))
        south, west, north, east = tile_bounds(0, 0, 0)
        self.assertAlmostEqual(west, -180)
        self.assertAlmostEqual(east, 180)
        self.assertAlmostEqual(north, 85.0511287798, places=6)
        self.assertAlmostEqual(south, -85.0511287798, places=6)


if __name__ == "__main__":
    unittest.main()
