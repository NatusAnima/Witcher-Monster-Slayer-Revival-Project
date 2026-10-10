"""The Players tab's debug tools: off unless enabled, saved with receipts and backups, pushed to a running game, never
counted by tasks, and the debug modifiers out of gameplay's reach."""
import gzip
import json
import math
import struct
import time
import unittest
import urllib.request

import test_admin as admin
import test_prototype as base
from test_prototype import I, Q, Reader

CELLS = [0x4704440000000000 + (k << 40) for k in range(9)]


class DebugTests(unittest.TestCase):
    setUp = admin.AdminTests.setUp
    restart = admin.AdminTests.restart
    request = admin.AdminTests.request
    profile = admin.AdminTests.profile
    offline = admin.AdminTests.offline
    playable_service = base.PrototypeTests.playable_service

    def debug(self, profile, **body):
        return self.request(f'profiles/{profile}/debug', 'POST', body)

    def saved(self, profile):
        return json.loads((self.server.directory / 'profiles' / (profile + '.json')).read_text())

    def booted(self, name='synthetic-admin'):
        client, profile = self.profile(name)
        client.rpc(115)                       # the boot batch, then the post-sync gate: pushes may follow
        self.assertEqual(client.rpc(119), b'\1' + I(0))
        return client, profile

    @staticmethod
    def pushed(client, method):
        """The payloads of [method] pushed since the last call: queued pushes follow the next reply, so they arrive
        ahead of the one after it."""
        client.rpc(61)
        client.rpc(61)
        found = [payload for called, payload in client.pushes if called == method]
        client.pushes.clear()
        return found

    def test_off_unless_enabled(self):
        _, profile = self.profile()
        self.assertEqual(self.debug(profile, action='gold', value=5)[0], 404)
        self.assertFalse(self.request(f'profiles/{profile}')[1]['debugTools'])
        self.restart(Admin__DebugTools='true')
        self.assertEqual(self.debug(profile, action='nonsense')[0], 400)
        self.assertEqual(self.debug(profile, action='gold', value=-1)[0], 400)
        self.assertEqual(self.debug('p0123456789abcdef0123456789abcde', action='gold', value=5)[0], 404)

    def test_values_reach_a_running_game_and_tasks_do_not_count_them(self):
        self.restart(Admin__DebugTools='true')
        client, profile = self.booted()
        tasks = self.saved(profile)['Player']['Tasks']
        status, result = self.debug(profile, action='gold', value=4321)
        self.assertEqual((status, result['receipt']['outcome'], result['outcome']['live']), (200, 'applied', True))
        info, = self.pushed(client, 3)
        r = Reader(info); r.byte(); r.string()
        self.assertEqual(r.integer(), 4321)                                  # the game's wallet, without a restart
        points = self.saved(profile)['Player']['SkillPoints']
        self.assertEqual(self.debug(profile, action='level', value=10)[0], 200)
        player = self.saved(profile)['Player']
        self.assertEqual((player['Exp'], player['SkillPoints'], player['LevelAnnounced']), (45000, points + 45, 10))
        self.assertEqual(player['Tasks'], tasks)                             # no task or trinket saw these changes
        self.assertTrue(self.pushed(client, 63))
        self.assertTrue(self.request('profiles')[1][0]['debug'])
        # a boot reads everything afresh, so it drops what was still queued
        self.assertEqual(self.debug(profile, action='skillPoints', value=7)[0], 200)
        client.rpc(115)
        self.assertEqual(self.pushed(client, 63), [])

    def test_items_stations_and_gear_come_and_go(self):
        self.restart(Admin__DebugTools='true')
        client, profile = self.booted()
        def inventory():
            r = Reader(client.rpc(5)); return [r.facts() for _ in range(9)]
        before = inventory()[2].get(205, 0)
        self.assertEqual(self.debug(profile, action='item', kind='potions', item=205, amount=3)[0], 200)
        self.assertEqual(self.debug(profile, action='item', kind='potions', item=205, amount=-2)[0], 200)
        self.assertEqual(inventory()[2].get(205, 0), before + 1)
        status, refused = self.debug(profile, action='item', kind='potions', item=99999, amount=1)
        self.assertEqual((status, refused['error']), (400, 'Unknown item.'))
        self.assertEqual(self.debug(profile, action='item', kind='swords', item=14, amount=1)[0], 200)
        self.assertIn(14, self.saved(profile)['Player']['Equipment']['Swords'])
        self.assertEqual(self.debug(profile, action='item', kind='swords', item=14, amount=-1)[0], 200)
        self.assertNotIn(14, self.saved(profile)['Player']['Equipment']['Swords'])
        self.assertEqual(self.debug(profile, action='item', kind='swords', item=7, amount=-1)[0], 409)   # the starting sword stays
        self.assertEqual(self.debug(profile, action='item', kind='brewers', item=3, amount=2)[0], 200)
        self.assertEqual([b['Type'] for b in self.saved(profile)['Player']['Brewers']].count(3), 2)
        self.assertEqual(self.debug(profile, action='item', kind='brewers', item=1, amount=1)[0], 400)    # the basic one is unique
        self.assertTrue(self.pushed(client, 69))

    def test_invincibility_and_one_hit_kills_are_debug_modifiers_only(self):
        self.restart(Admin__DebugTools='true')
        client, profile = self.booted()
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=3) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual({(r['item_id'], r['effect_id'], r['power'], r['effect_apply_type_id'])
                          for r in data['player_modifier_to_effect']}, {(901, 40, 100000, 1), (902, 41, 100000, 1)})
        self.assertLessEqual({901, 902}, {r['id'] for r in data['player_modifiers']})
        self.assertEqual(client.rpc(90, I(901) + I(0))[4:8], I(1))           # gameplay cannot add them
        self.assertEqual(self.debug(profile, action='invincible', on=True)[0], 200)
        self.assertEqual(self.debug(profile, action='oneHit', on=True)[0], 200)
        def held():
            r = Reader(client.rpc(91)); r.integer()
            return {r.integer(): (r.integer(), r.integer())[1] for _ in range(r.integer())}
        self.assertEqual(held(), {901: -1, 902: -1})                          # -1: never expires, shown without a timer
        self.assertEqual(self.debug(profile, action='invincible', on=False)[0], 200)
        self.assertEqual(set(held()), {902})
        self.assertEqual(self.request(f'profiles/{profile}')[1]['modifiers'], [902])

    def test_quests_come_next_to_the_player(self):
        origin = (10.0, 20.0)
        places = [{'id': f'lab-test-{m}', 'lat': origin[0] + m / 110540.0, 'lng': origin[1], 'biomes': [4], 'kind': 'path'}
                  for m in (100, 400, 800)]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        self.restart(Admin__DebugTools='true', Playable__Url=url)
        client, profile = self.booted()
        # the tutorial's quests stay beside the player
        self.assertEqual(self.debug(profile, action='questsHere')[0], 409)
        client.rpc(57, base.PrototypeTests.completion_body({3: 1}, instance=base.PrototypeTests.TUT_EXAM, output='exam_end'))
        client.rpc(57, base.PrototypeTests.completion_body())                  # Thorstein: the dead horse, 600-1000 m away
        self.assertEqual(self.debug(profile, action='questsHere')[0], 409)   # no map loaded yet
        client.rpc(88, I(9) + b''.join(Q(cell) for cell in CELLS))
        status, result = self.debug(profile, action='questsHere')
        self.assertEqual(status, 200)
        self.assertRegex(result['outcome']['effect'],
                         r"^Moved 1 quest place\(s\) within (99|100) m of the map's centre\. Restart the game to see them\.$")
        quest = Reader(client.rpc(60)).quest()
        horse, = quest['nodes']
        place, = [loc for loc in quest['locations'] if loc[0] == horse['place']]
        self.assertTrue(horse['place'].startswith('lab-story-dead_horse-'))
        self.assertAlmostEqual(struct.unpack('>ff', place[1])[0], places[0]['lat'], places=4)
        # Without GPS from the hook, the game's own position in its weather request counts.
        client.rpc(67, struct.pack('>ff', places[2]['lat'], places[2]['lng']))
        status, result = self.debug(profile, action='questsHere')
        self.assertRegex(result['outcome']['effect'], r"^Moved 1 quest place\(s\) within [01] m of you\.")
        horse, = (quest := Reader(client.rpc(60)).quest())['nodes']
        place, = [loc for loc in quest['locations'] if loc[0] == horse['place']]
        self.assertAlmostEqual(struct.unpack('>ff', place[1])[0], places[2]['lat'], places=4)

    def test_the_quest_runner_plays_every_quest_in_order_from_a_new_profile(self):
        # From the tutorial to the last season 1 quest, each next step is shown to the player (offered, on the map or in the
        # journal) before the runner completes it, and every step moves its quest on.
        origin, cos = (10.0, 20.0), math.cos(math.radians(10.0))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + math.sin(k * math.pi / 4) * r / 110540.0,
                   'lng': origin[1] + math.cos(k * math.pi / 4) * r / (111320.0 * cos), 'biomes': [4], 'kind': 'path'}
                  for r in (100, 150, 200, 250, 300, 400, 500, 600, 700) for k in range(8)]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        self.restart(Admin__DebugTools='true', Playable__Url=url)
        client, profile = self.booted()
        client.rpc(88, I(9) + b''.join(Q(cell) for cell in CELLS))
        steps = 0
        while todo := [q for q in self.request(f'profiles/{profile}')[1]['quests'] if q['next']]:
            quest = todo[0]
            self.assertNotIn('not shown yet', quest['next'], quest['name'])
            status, result = self.debug(profile, action='questStep', value=quest['id'])
            self.assertEqual(status, 200, result)
            self.assertNotIn('did not move on', result['outcome']['effect'])
            steps += 1
            self.assertLess(steps, 200)
        quests = self.request(f'profiles/{profile}')[1]['quests']
        self.assertEqual((len(quests), {q['state'] for q in quests}), (15, {'done'}))
        gear = self.saved(profile)['Player']['Equipment']
        self.assertTrue(8 in gear['Armors'] and 17 in gear['Swords'])     # Hermit's Armor and Dawnbringer
        self.assertEqual(self.debug(profile, action='questStep', value=149)[0], 409)

    def test_time_for_quests_rides_on_the_weather(self):
        # The hook takes 16 × (1 + mask) off the weather code and answers the quests' full moon, dawn, dusk and day checks.
        self.restart(Admin__DebugTools='true')
        client, profile = self.booted()
        weather = lambda: Reader(client.rpc(67, struct.pack('>ff', 10.0, 20.0))).integer()
        clear = weather()
        self.assertLess(clear, 16)
        status, result = self.debug(profile, action='sky', value=1)      # full moon, night
        self.assertEqual(status, 200)
        self.assertTrue(result['outcome']['effect'].startswith('Quests see a full moon '))
        self.assertEqual((weather(), self.request(f'profiles/{profile}')[1]['sky']), (clear + 16 * 2, 1))
        self.assertEqual(self.debug(profile, action='sky', value=16)[0], 400)
        self.assertTrue(self.debug(profile, action='sky', value=-1)[1]['outcome']['effect'].startswith("Quests see the phone's own sky"))
        self.assertEqual(weather(), clear)

    def test_history_restores_a_debug_change(self):
        self.restart(Admin__DebugTools='true')
        client, profile = self.profile()
        gold = self.saved(profile)['Player']['Gold']
        status, result = self.debug(profile, action='gold', value=999)
        self.assertEqual(status, 200)
        backup = result['receipt']['id']
        self.assertEqual(json.loads((self.directory / 'admin' / 'backups' / (backup + '.profile.json')).read_text())['Player']['Gold'], gold)
        record = self.offline(client, profile)
        status, _ = self.request(f'profiles/{profile}', 'POST',
                                 {'revision': record['revision'], 'action': 'restore', 'confirm': profile, 'backup': backup})
        self.assertEqual(status, 200)
        self.assertEqual(self.saved(profile)['Player']['Gold'], gold)


if __name__ == '__main__':
    unittest.main()
