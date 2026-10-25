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
        return {'revision': revision, 'document': {'schemaVersion': 2, 'values': values}}

    def test_values_save_validate_and_survive_a_restart(self):
        status, first = self.request('tuning')
        self.assertEqual((status, first['revision']), (200, 'missing'))
        defaults = {d['key']: d['default'] for d in first['definitions']}
        self.assertEqual(first['values'], defaults)
        self.assertIn('places.woods', defaults)
        self.assertFalse((self.world / 'tuning.json').exists())

        self.assertEqual((first['preset'], [p['id'] for p in first['presets']]), ('revival', ['revival', 'vanilla']))
        status, saved = self.request('tuning', 'PUT', self.body({'places.woods': 30, 'exp.percent': 200}, 'missing'))
        self.assertEqual((status, saved['receipt']['outcome'], saved['receipt']['action']), (200, 'applied', 'tuning'))
        written = json.loads((self.world / 'tuning.json').read_text())
        # Revival is built in: the change becomes the player's own preset, which is now in use
        self.assertEqual(written, {'schemaVersion': 2, 'preset': 'custom',
                                   'values': dict(defaults, **{'places.woods': 30, 'exp.percent': 200})})
        self.assertEqual(json.loads((self.world / 'presets' / 'custom.json').read_text())['name'], 'Revival (my copy)')
        status, now = self.request('tuning')
        self.assertEqual((now['revision'], now['values']), (saved['revision'], written['values']))

        # a stale page cannot overwrite, and nothing impossible is saved
        self.assertEqual(self.request('tuning', 'PUT', self.body({}, 'missing'))[0], 409)
        for bad in ({'places.woods': 101}, {'places.perCell': 49}, {'places.spacing': -1}, {'exp.percent': 5}, {'herbs.perCell': 2.5},
                    {'exp.percent': 'lots'}, {'story.trollDefeats': 0}, {'story.trollDefeats': 11}, {'nonsense': 1}):
            with self.subTest(bad=bad):
                self.assertEqual(self.request('tuning', 'PUT', self.body(bad, now['revision']))[0], 400)
        self.assertEqual(self.request('tuning', 'PUT', {'revision': now['revision'], 'document': {'schemaVersion': 2}})[0], 400)
        tiers = self.request('tuning', 'PUT', self.body({'bestiary.common1': 30, 'bestiary.common2': 20}, now['revision']))
        self.assertEqual(tiers[0], 400)
        self.assertIn('tier 2', tiers[1]['error'])
        self.assertEqual(json.loads((self.world / 'tuning.json').read_text()), written)

        self.restart()
        self.assertEqual(self.request('tuning')[1]['values'], written['values'])
        self.assertIn('tuning', [r['action'] for r in self.request('receipts')[1]])

    def test_presets_are_built_in_copied_renamed_and_deleted(self):
        state = self.request('tuning')[1]
        vanilla = {d['key']: d['vanilla'] for d in state['definitions']}
        for d in state['definitions']:
            with self.subTest(setting=d['key']):
                self.assertTrue(d['min'] <= d['vanilla'] <= d['max'] and d['min'] <= d['default'] <= d['max'])
        self.assertEqual((vanilla['inventory.startSize'], vanilla['nests.gold'], vanilla['bestiary.common3']), (200, 50, 150))

        status, state = self.request('tuning/active', 'PUT', {'preset': 'vanilla'})
        self.assertEqual((status, state['preset'], state['values']), (200, 'vanilla', vanilla))
        self.assertEqual(json.loads((self.world / 'tuning.json').read_text())['values'], vanilla)
        self.assertEqual(self.request('tuning/presets/vanilla', 'PUT', {'name': 'Mine'})[0], 409)
        self.assertEqual(self.request('tuning/presets/vanilla', 'DELETE')[0], 409)
        self.assertEqual(self.request('tuning/presets', 'POST', {'from': 'vanilla', 'name': ' '})[0], 400)

        status, state = self.request('tuning/presets', 'POST', {'from': 'vanilla', 'name': 'Mine'})
        self.assertEqual((status, state['preset']), (200, 'custom'))
        self.assertEqual(state['values'], vanilla)
        self.assertIn({'id': 'custom', 'name': 'Mine', 'builtIn': False}, state['presets'])
        state = self.request('tuning/presets/custom', 'PUT', {'name': 'Ours'})[1]
        self.assertIn({'id': 'custom', 'name': 'Ours', 'builtIn': False}, state['presets'])
        # a second copy gets its own file; deleting the one in use falls back to Revival
        state = self.request('tuning/presets', 'POST', {'from': 'revival', 'name': 'Second'})[1]
        self.assertEqual(state['preset'], 'custom-2')
        state = self.request('tuning/presets/custom-2', 'DELETE')[1]
        self.assertEqual((state['preset'], [p['id'] for p in state['presets']]), ('revival', ['revival', 'vanilla', 'custom']))
        self.assertFalse((self.world / 'presets' / 'custom-2.json').exists())
        self.assertEqual(self.request('tuning/presets/custom-9', 'DELETE')[0], 404)

    def test_settings_saved_before_presets_become_the_preset_custom(self):
        old = dict(self.request('tuning')[1]['values'], **{'inventory.startSize': 250, 'exp.percent': 150})
        old = {k: v for k, v in old.items() if k.startswith(('places.', 'exp.', 'loot.', 'nests.gold', 'herbs.', 'weather.',
                                                             'inventory.startSize', 'story.'))}
        self.world.mkdir(parents=True, exist_ok=True)
        (self.world / 'tuning.json').write_text(json.dumps({'schemaVersion': 1, 'values': old}))
        self.restart()
        state = self.request('tuning')[1]
        self.assertEqual(state['preset'], 'custom')
        self.assertIn({'id': 'custom', 'name': 'Custom', 'builtIn': False}, state['presets'])
        self.assertEqual((state['values']['inventory.startSize'], state['values']['exp.percent']), (250, 150))
        self.assertEqual(json.loads((self.world / 'tuning.json').read_text())['schemaVersion'], 2)

    def test_the_rewards_page_saves_into_the_players_preset(self):
        status, page = self.request('rewards')
        self.assertEqual((status, page['preset'], page['builtIn']), (200, 'revival', True))
        keys = {k for g in page['catalog']['groups'] for k in g['keys']}
        self.assertEqual(set(page['rewards']['quests']), keys)
        self.assertEqual(page['vanilla']['quests']['s01mq01_margit_2.scholar_02'], {'exp': 250, 'gold': 40, 'items': [], 'slots': 0})
        self.assertEqual(page['rewards']['quests']['s01mq05_final.first_place']['slots'], 400)
        rewards = page['rewards']
        rewards['quests']['s01mq01_margit_2.scholar_02'] = {'exp': 777, 'gold': 12, 'slots': 0,
                                                             'items': [{'kind': 'oils', 'id': 302, 'amount': 2}]}
        bad = json.loads(json.dumps(rewards))
        bad['quests']['s01mq01_margit_2.scholar_02']['items'] = [{'kind': 'oils', 'id': 999, 'amount': 1}]
        status, refused = self.request('rewards', 'PUT', {'revision': page['revision'], 'rewards': bad})
        self.assertEqual(status, 400)
        self.assertIn('oils 999', refused['error'])
        status, saved = self.request('rewards', 'PUT', {'revision': page['revision'], 'rewards': rewards})
        self.assertEqual((status, saved['preset'], saved['receipt']['outcome']), (200, 'custom', 'applied'))
        page = self.request('rewards')[1]
        self.assertEqual((page['preset'], page['builtIn']), ('custom', False))
        self.assertEqual(page['rewards']['quests']['s01mq01_margit_2.scholar_02']['exp'], 777)
        self.assertEqual(self.request('rewards', 'PUT', {'revision': 'stale', 'rewards': rewards})[0], 409)

    def test_shop_prices_and_packs_live_in_the_preset(self):
        page = self.request('rewards')[1]
        revival, vanilla = page['rewards'], page['vanilla']
        bundles = (1201, 1205, 1301, 1302, 1401, 1402, 1501, 1103, 129, 2202, 3006, 4016, 95, 99, 5003, 6003, 64, 65, 66, 67)
        self.assertEqual([vanilla['prices'][str(b)] for b in bundles],
                         [30, 60, 75, 150, 150, 300, 200, 50, 80, 300, 12000, 12000, 500, 4000, 150, 250, 160, 490, 675, 750])
        self.assertEqual([revival['prices'][str(b)] for b in bundles],
                         [20, 40, 45, 90, 75, 150, 150, 30, 50, 180, 9000, 9000, 250, 2000, 120, 200, 90, 280, 400, 550])
        self.assertNotIn('77', revival['prices'])                                 # oren packs: real money, never orens
        shop = {b['id']: b for b in page['catalog']['shop']}
        self.assertEqual([(i['slug'], i['amount']) for i in shop[67]['items']],
                         [('lure_basic', 1), ('lure_draconid', 1), ('lure_necrophage', 1), ('lure_ogroid', 1), ('lure_specter', 1)])
        # every chest costs less than its parts, in both presets (herbs and roots at Fresh herbs' price)
        single = {b['items'][0]['slug']: b for b in shop.values() if len(b['items']) == 1}
        for table in (revival, vanilla):
            price = lambda bundle: table['prices'][str(bundle)]
            for chest in (64, 65, 66, 67):
                parts = sum(price(129) * i['amount'] / 15 if i['slug'] in ('ingredient_herba', 'ingredient_radix') else
                            price(single[i['slug']]['id']) * i['amount'] / single[i['slug']]['items'][0]['amount']
                            for i in shop[chest]['items'])
                self.assertLess(price(chest), parts * 0.8, chest)
        self.assertEqual((revival['packDraws'], vanilla['packDraws']), (3, 1))
        self.assertEqual(revival['packPool'][0], {'kind': 'ingredients', 'id': 102, 'weight': 50, 'min': 2, 'max': 4})
        discount = next(d for d in self.request('tuning')[1]['definitions'] if d['key'] == 'shop.dailyDiscount')
        self.assertEqual((discount['default'], discount['vanilla']), (40, 25))
        for change, word in (({'prices': dict(revival['prices'], **{'77': 10})}, 'bundle 77'),
                             ({'prices': dict(revival['prices'], **{'1205': 0})}, 'bundle 1205'),
                             ({'packDraws': 0}, 'draws'),
                             ({'packPool': [{'kind': 'swords', 'id': 1, 'weight': 1, 'min': 1, 'max': 1}]}, 'swords 1'),
                             ({'packPool': [{'kind': 'ingredients', 'id': 102, 'weight': 1, 'min': 3, 'max': 2}]}, 'ingredients 102')):
            with self.subTest(word=word):
                status, refused = self.request('rewards', 'PUT', {'revision': page['revision'], 'rewards': dict(revival, **change)})
                self.assertEqual(status, 400)
                self.assertIn(word, refused['error'])
        # A purchase costs what the game was shown when the server started: a new price waits for the next start.
        client, profile = self.profile()
        client.close()
        self.server.stop()
        path = self.directory / 'profiles' / (profile + '.json')
        saved = json.loads(path.read_text()); saved['Player']['Gold'] = 1000; path.write_text(json.dumps(saved))
        self.restart()
        client = self.profile()[0]
        self.assertEqual(client.rpc(75, admin.I(129) + admin.Q(1)), b'\1' + admin.I(129) + admin.I(950))   # Fresh herbs: 50
        page = self.request('rewards')[1]
        status, _ = self.request('rewards', 'PUT', {'revision': page['revision'],
                                                    'rewards': dict(page['rewards'], prices=dict(page['rewards']['prices'], **{'129': 33}))})
        self.assertEqual(status, 200)
        self.assertEqual(client.rpc(75, admin.I(129) + admin.Q(2)), b'\1' + admin.I(129) + admin.I(900))
        client.close()
        self.restart()
        client = self.profile()[0]
        self.assertEqual(client.rpc(75, admin.I(129) + admin.Q(3)), b'\1' + admin.I(129) + admin.I(867))
        client.close()
        # a preset saved before 0.4.0 has no prices or packs: it gets Revival's
        self.server.stop()
        file = self.world / 'presets' / 'custom.json'
        preset = json.loads(file.read_text())
        for key in ('prices', 'packDraws', 'packPool'): del preset['rewards'][key]
        file.write_text(json.dumps(preset))
        self.restart()
        page = self.request('rewards')[1]
        self.assertEqual((page['preset'], page['rewards']['prices'], page['rewards']['packDraws']), ('custom', revival['prices'], 3))

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
        for name, needle in (('', 'view-tuning'), ('app.js', 'renderTuning'), ('', 'view-rewards'), ('app.js', 'renderRewards')):
            req = urllib.request.Request(self.origin + '/' + name, headers={'X-Monster-Admin-Key': admin.SYNTHETIC_KEY})
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertIn(needle, response.read().decode())


if __name__ == '__main__':
    unittest.main()
