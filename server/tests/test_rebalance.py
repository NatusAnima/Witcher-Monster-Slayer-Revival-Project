"""0.3.0's rebalance and its presets (Revival by default, Vanilla built in): quest and daily rewards, experience, level-ups,
bags, trinket bonuses, summoning scrolls, consumables and the texts the hook gives the game. Synthetic profiles only."""
import gzip
import json
import struct
import time
import unittest
import urllib.request

import test_prototype as base
from test_tasks import TaskTests

I, Q, Reader = base.I, base.Q, base.Reader
SPECIES = {s['monster_id']: s for s in base.WORLD['species']}


def modifiers(data):
    r = Reader(data)
    r.integer()
    return {r.integer(): (r.integer(), r.integer()) for _ in range(r.integer())}   # id: (start, expiry)


class RebalanceTests(TaskTests):
    def edit(self, name, change):
        path = self.profile_file(name)
        profile = json.loads(path.read_text())
        change(profile['Player'])
        path.write_text(json.dumps(profile))

    world = base.PrototypeTests.tuned

    def saved_profile(self, c):
        c.rpc(3); c.rpc(3)      # the first request saves the profile after its answer; the second waits for that

    def static(self, server):
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=2) as response:
            return json.loads(gzip.decompress(response.read()))

    def griffin(self, c):
        return Reader(c.rpc(57, self.completion_body({}, instance=base.GRIFFIN, output='griffin_1'))).end_graph()

    def test_quest_endings_pay_the_presets_table(self):
        server, c = self.reconstructed()
        done = self.griffin(c)
        self.assertEqual((done['exp'], done['gold'], done['potions']), (500, 100, {205: 2}))   # Revival
        self.assertEqual(self.inventory(c)['potions'].get(205), 2)
        self.assertEqual(self.griffin(c)['exp'], 0)                                            # an ending pays once
        server = self.start('test-vanilla', dict(self.RECONSTRUCTED, **self.world('vanilla')))
        done = self.griffin(self.client(server))
        self.assertEqual((done['exp'], done['gold'], done['potions']), (250, 45, {}))            # the wiki's v1.1 amounts

    def test_a_fight_pays_by_rarity_and_after_a_server_restart(self):
        server, c = self.task_server(self.kills(1))
        r = Reader(c.rpc(111, I(16) + I(1) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        monster, instance, _ = group['monsters'][0]
        self.assertEqual(c.rpc(113, Q(instance)), b'\1')
        server.stop()                                            # the encounter outlives a restart
        self.assertEqual(self.saved_fight()['InstanceId'], instance)
        server, c = self.task_server(self.kills(1))
        end = self.combat_end(Reader(c.rpc(114, bytes([1]) + I(13) + I(0) * 13 + bytes([0]))))
        self.assertEqual(end['base'], {1: 100, 2: 250, 3: 600}[SPECIES[monster]['rarity']])
        server.stop()
        self.assertIsNone(self.saved_fight())

    def saved_fight(self):
        return json.loads(self.profile_file('tasks').read_text())['Player'].get('Fight')

    def test_daily_claims_pay_scaled_gold_experience_and_an_item(self):
        server, c = self.task_server(self.kills(1))
        tasks, _, _ = self.daily(c)
        task = next(iter(tasks))
        gold = next(d['gold'] for d in self.kills(1) if d['id'] == task)
        rows = {r['id']: r['reward'] for r in self.static(server)['daily_quests']}
        self.assertEqual(rows[task], 2 * gold)                   # tasks.goldPercent 200 in the panel's row
        self.fight(c)
        before, items = self.player_info(c), self.inventory(c)
        self.assertEqual(self.claim(c, task)[0], 0)
        after, items_after = self.player_info(c), self.inventory(c)
        self.assertEqual((after['gold'] - before['gold'], after['exp'] - before['exp']), (2 * gold, 200))
        count = lambda inv: sum(sum(m.values()) for k, m in inv.items() if k != 'bag')
        self.assertEqual(count(items_after) - count(items), 1)   # one item from the daily pool

    def test_a_lost_level_up_window_comes_again_after_the_next_boot(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Exp=3000, LevelAnnounced=3, LevelShown=2))
        server, c = self.reconstructed()
        c.rpc(115)
        c.rpc(119)
        c.rpc(3)
        c.rpc(3)                # a push follows a reply: the next request reads it
        self.assertEqual([level for method, body in c.pushes if method == 31 for level in [struct.unpack('>i', body[:4])[0]]], [3])
        c.rpc(3)
        self.assertEqual(len([p for p in c.pushes if p[0] == 31]), 1)
        self.assertEqual(server.state()['player'].get('levelShown', 3), 3)

    def test_the_original_level_table_keeps_each_players_level(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Exp=45000 + 4500, LevelAnnounced=10))   # level 10, half way to 11
        server = self.start('test-fresh', dict(self.RECONSTRUCTED, **self.world('revival', **{'xp.vanillaCurve': 1})))
        c = self.client(server)
        c.rpc(115)
        thresholds = {r['id']: r['exp_threshold'] for r in self.static(server)['level_ups']}
        self.assertEqual((thresholds[2], thresholds[10], thresholds[11], thresholds[40]), (1000, 27000, 33000, 3877000))
        self.assertEqual(self.player_info(c)['exp'], 27000 + 2700)                             # still 45 % of the way to 11
        server.stop()
        server = self.start('test-fresh', self.RECONSTRUCTED)                                   # and back
        c = self.client(server)
        c.rpc(115)
        self.assertEqual(self.player_info(c)['exp'], 45000 + 4500)

    def test_bags_count_quest_slots_and_trinkets(self):
        server, c = self.task_server(self.kills(1))
        self.assertEqual(self.inventory(c)['bag'], 400)                                        # Revival's start
        server.stop()
        def change(p):
            p['Story'] = dict(p.get('Story') or {'Active': [], 'Started': [], 'Finished': []}, Outputs=[1179])  # Mushrooming 1st
            p.setdefault('Story', {}).setdefault('Active', []); p['Story'].setdefault('Started', []); p['Story'].setdefault('Finished', [])
            p['Tasks']['Achievements'] = {'20011': 1790000000, '20024': 1790000000, '20001': 1790000000}
        self.edit('tasks', change)
        server, c = self.task_server(self.kills(1))
        self.assertEqual(self.inventory(c)['bag'], 400 + 400 + 200)
        # The trinkets' bonuses: an attack modifier (permanent, not removable), the journal's station.
        live = modifiers(c.rpc(91))
        self.assertEqual(live[921][1], -1)
        c.rpc(92, I(921))
        self.assertIn(921, modifiers(c.rpc(91)))
        r = Reader(c.rpc(69)); r.byte()
        stations = [struct.unpack('>qiiii', r.take(24)) for _ in range(r.integer())]
        self.assertIn((1020024, 1, -1, 0, 0), [(s[0], s[1], s[2], 0, 0) for s in stations])
        rows = [r for r in self.static(server)['player_modifier_to_effect'] if r['item_id'] == 921]
        self.assertEqual([(r['effect_id'], r['power'], r['effect_apply_type_id']) for r in rows], [(30, 20, 22)])
        # Vanilla: no trinket bonuses, the original bag.
        server.stop()
        server, c = self.task_server(self.kills(1), extra=self.world('vanilla'))
        self.assertEqual(self.inventory(c)['bag'], 200)
        self.assertNotIn(921, modifiers(c.rpc(91)))

    def test_summoning_scrolls_follow_their_descriptions(self):
        server, c = self.task_server(self.kills(1))
        server.stop()
        self.edit('tasks', lambda p: p.update(Gold=1000, Items=dict(p['Items'], summoning_scrolls={'6': 1, '4': 1})))
        server, c = self.task_server(self.kills(1))
        r = Reader(c.rpc(111, I(16) + I(6) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual(len(group['monsters']), 5)
        self.assertTrue(all(SPECIES[m[0]]['family'] == 2 for m in group['monsters']))         # 5 random draconids
        # A legendary scroll at level 1 keeps to the level gate: a monster without skulls.
        r = Reader(c.rpc(111, I(16) + I(4) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual([SPECIES[m[0]]['skulls'] for m in group['monsters']], [0])
        self.assertEqual(self.inventory(c)['scrolls'], {})
        # The shop sells them (Alchemy, beside the baits), one at a time.
        bundles = {b['id']: b for b in self.static(server)['shop_bundles']}
        self.assertEqual(bundles[5003]['gold_price'], 150)
        r = Reader(c.rpc(75, I(5003) + Q(42)))
        self.assertEqual(r.byte(), 1)
        self.assertEqual(self.inventory(c)['scrolls'], {3: 1})

    def test_boosters_and_weather_items_are_used_from_the_inventory(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Items=dict(p['Items'], consumables={'1': 1, '3': 1, '4': 1})))
        server, c = self.reconstructed()
        self.assertEqual(self.inventory(c)['consumables'], {1: 1, 3: 1, 4: 1})
        r = Reader(c.rpc(99, I(1)))
        ok, item, expiry = r.byte(), r.integer(), r.integer()
        self.assertEqual((ok, item), (1, 1))
        self.assertAlmostEqual(expiry, time.time() + 1800, delta=120)
        self.assertEqual(self.inventory(c)['consumables'], {3: 1, 4: 1})
        self.assertEqual(c.rpc(99, I(1))[0], 0)                                                # none left
        self.assertEqual(self.griffin(c)['exp'], 1000)                                         # +100 % while it lasts
        where = struct.pack('>ff', 12.3, 45.6)
        self.assertEqual(c.rpc(67, where), I(6))                                               # no weather service: clear
        self.assertEqual(c.rpc(99, I(3))[0], 1)
        self.assertEqual(c.rpc(67, where), I(3))                                               # rain for an hour
        self.assertEqual(c.rpc(99, I(4))[0], 1)
        self.assertEqual(c.rpc(67, where), I(5))                                               # fog replaces it
        live = modifiers(c.rpc(91))
        self.assertIn(914, live)
        self.assertNotIn(913, live)
        consumables = {r['id']: r for r in self.static(server)['consumables']}
        self.assertEqual((consumables[1]['slug'], consumables[1]['duration']), ('xp_booster', 1800))

    def test_the_hook_texts_follow_the_preset(self):
        server, c = self.task_server(self.kills(1))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        silver = texts['replace']['MONSTERS/DESCRIPTIONS/BASILISKWHITE/INFO_2']
        self.assertEqual(silver, '[0{**UI/PANELS/BESTIARY/OCCURANCE**}0]: ' + ''.join(
            f'**MONSTERS/OCCURANCE/{t}**\n' for t in SPECIES[110]['tags']))
        self.assertIn('Bonus: +20% experience and +20% attack against draconids',
                      texts['append']['ACHIEVEMENTS/DESCRIPTIONS/TROPHY_LIZARD_SLAYER'])
        self.assertEqual(texts['replace']['ITEMS/NAMES/CONSUMABLES/INTERACTION_BOOSTER'], 'Rain Charm')
        server.stop()
        server, c = self.task_server(self.kills(1), extra=self.world('vanilla', **{'spawns.wikiOccurrences': 0}))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        self.assertFalse(any(k.startswith('MONSTERS/') for k in texts['replace']))
        self.assertEqual(texts['append'], {})

    def test_bestiary_tiers_follow_the_tuning(self):
        # Each tier's row carries the kills since the previous tier: Revival 3/25/100, Vanilla (before 1.2) 3/50/150.
        for preset, expected in (('revival', {1: 3, 2: 22, 3: 75}), ('vanilla', {1: 3, 2: 47, 3: 100})):
            server = self.start('test-' + preset, dict(self.RECONSTRUCTED, **self.world(preset)))
            rows = self.static(server)['monster_descriptions']
            self.assertEqual({r['level']: r['threshold'] for r in rows if r['monster_id'] == 1}, expected)   # the ghoul
            server.stop()


def load_tests(loader, tests, pattern):
    # Only this module's own tests: the base classes' tests run in their own modules.
    return unittest.TestSuite(RebalanceTests(name) for name in loader.getTestCaseNames(RebalanceTests)
                              if name in RebalanceTests.__dict__)


if __name__ == '__main__':
    unittest.main()
