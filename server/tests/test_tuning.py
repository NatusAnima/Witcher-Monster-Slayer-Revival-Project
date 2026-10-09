"""The dashboard's tuning page: the file it saves, the limits it enforces and the audit trail it leaves."""
import http.server
import json
import struct
import sys
import threading
import unittest
import urllib.request

import test_admin as admin
from test_prototype import ROOT


class TuningApiTests(unittest.TestCase):
    setUp = admin.AdminTests.setUp
    restart = admin.AdminTests.restart
    request = admin.AdminTests.request
    profile = admin.AdminTests.profile

    def body(self, values, revision):
        return {'revision': revision, 'document': {'schemaVersion': 1, 'values': values}}

    def test_values_save_validate_and_survive_a_restart(self):
        status, first = self.request('tuning')
        self.assertEqual((status, first['revision']), (200, 'missing'))
        defaults = {d['key']: d['default'] for d in first['definitions']}
        self.assertEqual(first['values'], defaults)
        self.assertIn('places.woods', defaults)
        self.assertFalse((self.world / 'tuning.json').exists())

        status, saved = self.request('tuning', 'PUT', self.body({'places.woods': 30, 'exp.percent': 200}, 'missing'))
        self.assertEqual((status, saved['receipt']['outcome'], saved['receipt']['action']), (200, 'applied', 'tuning'))
        written = json.loads((self.world / 'tuning.json').read_text())
        self.assertEqual(written, {'schemaVersion': 1, 'values': dict(defaults, **{'places.woods': 30, 'exp.percent': 200})})
        status, now = self.request('tuning')
        self.assertEqual((now['revision'], now['values']), (saved['revision'], written['values']))

        # a stale page cannot overwrite, and nothing impossible is saved
        self.assertEqual(self.request('tuning', 'PUT', self.body({}, 'missing'))[0], 409)
        for bad in ({'places.woods': 101}, {'places.perCell': 49}, {'places.spacing': -1}, {'exp.percent': 5}, {'herbs.perCell': 2.5},
                    {'exp.percent': 'lots'}, {'nonsense': 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.request('tuning', 'PUT', self.body(bad, now['revision']))[0], 400)
        self.assertEqual(self.request('tuning', 'PUT', {'revision': now['revision'], 'document': {'values': {}}})[0], 400)
        self.assertEqual(json.loads((self.world / 'tuning.json').read_text()), written)

        self.restart()
        self.assertEqual(self.request('tuning')[1]['values'], written['values'])
        self.assertIn('tuning', [r['action'] for r in self.request('receipts')[1]])

    def test_real_weather_can_be_turned_off(self):
        asked = []
        class Weather(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                asked.append(self.path)
                body = json.dumps({'current': {'weather_code': 61}}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        fake = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Weather)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.server_close); self.addCleanup(fake.shutdown)
        self.restart(Weather__Url=f'http://127.0.0.1:{fake.server_port}/v1/forecast')
        client, _ = self.profile()
        where = struct.pack('>ff', 12.3456, 45.6789)
        self.assertEqual(client.rpc(67, where), admin.I(3))                  # rain from the provider
        values = self.request('tuning')[1]
        self.assertEqual(values['values']['weather.real'], 1)
        self.request('tuning', 'PUT', self.body(dict(values['values'], **{'weather.real': 0}), values['revision']))
        self.assertEqual(client.rpc(67, where), admin.I(6))                  # off: always clear, nothing asked
        self.assertEqual(len(asked), 1)

    def test_place_settings_match_the_placement_service(self):
        # The placement service (Python) reads the same file with its own copy of the places.* defaults and limits.
        sys.path.insert(0, str(ROOT / 'connection' / 'map-road-fixture-01'))
        self.addCleanup(sys.path.remove, sys.path[0])
        import playable_locations
        served = {d['key']: (d['default'], d['min'], d['max']) for d in self.request('tuning')[1]['definitions']
                  if d['key'].startswith('places.')}
        self.assertEqual(served, {k: tuple(map(float, v)) for k, v in playable_locations.Tuning.SETTINGS.items()})

    def test_the_panel_has_the_page(self):
        for name, needle in (('', 'view-tuning'), ('app.js', 'renderTuning')):
            req = urllib.request.Request(self.origin + '/' + name, headers={'X-Monster-Admin-Key': admin.SYNTHETIC_KEY})
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertIn(needle, response.read().decode())


if __name__ == '__main__':
    unittest.main()
