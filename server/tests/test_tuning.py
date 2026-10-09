"""The dashboard's tuning page: the file it saves, the limits it enforces and the audit trail it leaves."""
import json
import unittest
import urllib.request

import test_admin as admin


class TuningApiTests(unittest.TestCase):
    setUp = admin.AdminTests.setUp
    restart = admin.AdminTests.restart
    request = admin.AdminTests.request

    def body(self, values, revision):
        return {'revision': revision, 'document': {'schemaVersion': 1, 'values': values}}

    def test_values_save_validate_and_survive_a_restart(self):
        status, first = self.request('tuning')
        self.assertEqual((status, first['revision']), (200, 'missing'))
        defaults = {d['key']: d['default'] for d in first['definitions']}
        self.assertEqual(first['values'], defaults)
        self.assertIn('woods.maxPlaces', defaults)
        self.assertFalse((self.world / 'tuning.json').exists())

        status, saved = self.request('tuning', 'PUT', self.body({'woods.maxPlaces': 6, 'exp.percent': 200}, 'missing'))
        self.assertEqual((status, saved['receipt']['outcome'], saved['receipt']['action']), (200, 'applied', 'tuning'))
        written = json.loads((self.world / 'tuning.json').read_text())
        self.assertEqual(written, {'schemaVersion': 1, 'values': dict(defaults, **{'woods.maxPlaces': 6, 'exp.percent': 200})})
        status, now = self.request('tuning')
        self.assertEqual((now['revision'], now['values']), (saved['revision'], written['values']))

        # a stale page cannot overwrite, and nothing impossible is saved
        self.assertEqual(self.request('tuning', 'PUT', self.body({}, 'missing'))[0], 409)
        for bad in ({'woods.maxPlaces': 25}, {'woods.maxPlaces': -1}, {'exp.percent': 5}, {'herbs.perCell': 2.5},
                    {'exp.percent': 'lots'}, {'nonsense': 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.request('tuning', 'PUT', self.body(bad, now['revision']))[0], 400)
        self.assertEqual(self.request('tuning', 'PUT', {'revision': now['revision'], 'document': {'values': {}}})[0], 400)
        self.assertEqual(json.loads((self.world / 'tuning.json').read_text()), written)

        self.restart()
        self.assertEqual(self.request('tuning')[1]['values'], written['values'])
        self.assertIn('tuning', [r['action'] for r in self.request('receipts')[1]])

    def test_the_panel_has_the_page(self):
        for name, needle in (('', 'view-tuning'), ('app.js', 'renderTuning')):
            req = urllib.request.Request(self.origin + '/' + name, headers={'X-Monster-Admin-Key': admin.SYNTHETIC_KEY})
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertIn(needle, response.read().decode())


if __name__ == '__main__':
    unittest.main()
