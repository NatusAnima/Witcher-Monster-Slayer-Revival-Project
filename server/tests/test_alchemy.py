"""Synthetic integration checks for skill-gated alchemy, saved output and native effect rows."""
import gzip
import json
import time
import unittest
import urllib.request

import test_prototype as base

I, Q, Reader = base.I, base.Q, base.Reader
STARTING = [1, 2, 3, 29, 30, 46, 47, 48]
GATED = {50: 2105, 52: 2106, 56: 2107, 61: 2108}


class AlchemyTests(base.PrototypeTests):
    def seed_alchemy(self, skills=None, env=None, name='alchemy-fixture', brewer=None):
        settings = {**self.RECONSTRUCTED, **(env or {})}
        server = self.start(name, settings)
        client = self.client(server)
        client.rpc(63)
        # GetSkills responds before its initial level marker is saved. An acknowledged
        # empty fact write on the same connection establishes a durable fixture before stop.
        self.assertEqual(client.rpc(78, I(0)), b'\1')
        path = self.profile_file(name)
        saved = json.loads(path.read_text())
        server.stop()
        player = saved['Player']
        player['Skills'] = list(STARTING if skills is None else skills)
        player['SkillPoints'] = 100
        player['Gold'] = 1000
        player['Exp'] = 780000
        player['Items'] = {'ingredients': {str(i): 50 for i in range(101, 114)},
                           'potions': {'201': 5, '202': 5, '205': 5}, 'oils': {'301': 5}, 'bombs': {'401': 5}}
        player['OneTimeBundles'] = [95, 96, 97, 98, 99]   # every bag: 1000 slots, so the stock above fits
        if brewer is not None:
            player['Brewers'] = [brewer]
        path.write_text(json.dumps(saved))
        server = self.start(name, settings)
        return server, self.client(server), settings

    def catalogue_alchemy(self, server):
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=3) as response:
            return json.loads(gzip.decompress(response.read()))

    def known(self, client):
        r = Reader(client.rpc(6))
        values = {r.integer(): set(r.ints()) for _ in range(r.integer())}
        self.assertEqual(r.pos, len(r.data))
        return values

    def saved_alchemy(self, name='alchemy-fixture'):
        return json.loads(self.profile_file(name).read_text())['Player']

    def finish_alchemy(self, server, settings, name='alchemy-fixture', remove_skills=False):
        server.stop()
        path = self.profile_file(name)
        saved = json.loads(path.read_text())
        if remove_skills:
            saved['Player']['Skills'] = []
        for brewer in saved['Player']['Brewers']:
            brewer['FinishTime'] = int(time.time()) - 1
        path.write_text(json.dumps(saved))
        server = self.start(name, settings)
        return server, self.client(server)

    @staticmethod
    def loadout(potions):
        return I(0) + I(len(potions)) + b''.join(I(p) for p in potions) + I(-1)

    def test_alchemy_catalogue_has_valid_unlocks_and_capacity(self):
        server, _, _ = self.seed_alchemy()
        data = self.catalogue_alchemy(server)
        recipes = {r['id']: r for r in data['potion_recipes']}
        self.assertEqual(set(recipes), set(range(2101, 2110)))
        self.assertEqual({recipes[r]['output'] for r in GATED.values()}, {204, 206, 207, 208})
        rows = data['skill_to_effect']
        for skill, recipe in GATED.items():
            self.assertIn({'item_id': skill, 'effect_id': 62, 'power': recipe, 'effect_apply_type_id': 18}, rows)
            self.assertTrue(any(r['recipe_id'] == recipe for r in data['potion_recipe_ingredients']))
        for skill in (54, 58):
            self.assertIn({'item_id': skill, 'effect_id': 45, 'power': 1, 'effect_apply_type_id': 18}, rows)
        for row in data['potion_recipe_ingredients']:
            self.assertIn(row['recipe_id'], recipes)
            self.assertGreater(row['amount'], 0)

    def test_alchemy_recipe_knowledge_and_atomic_crafting_gate(self):
        server, c, _ = self.seed_alchemy()
        self.assertEqual(self.known(c)[3], {2101, 2102, 2103, 2104, 2109})
        before = self.saved_alchemy()
        for recipe in GATED.values():
            self.assertEqual(c.rpc(4, Q(1) + I(recipe) + I(3))[:1], b'\0')
        self.assertEqual(c.rpc(4, Q(1) + I(2101) + I(4))[:1], b'\0')
        self.assertEqual(self.saved_alchemy(), before)
        self.assertEqual(c.rpc(64, I(50)), b'\1' + I(50))
        self.assertEqual(self.known(c)[3], {2101, 2102, 2103, 2104, 2105, 2109})
        inventory = self.inventory(c)
        result = c.rpc(4, Q(1) + I(2105) + I(3))
        self.assertEqual(result[:1], b'\1')
        self.assertEqual(c.rpc(4, Q(1) + I(2105) + I(3), repeat=True), result)
        self.assertEqual(c.rpc(4, Q(1) + I(2105) + I(3))[:1], b'\0')
        after = self.inventory(c)
        for item, cost in [(101, 3), (102, 1), (103, 5)]:
            self.assertEqual(after['ingredients'][item], inventory['ingredients'][item] - cost)
        self.assertEqual(after['potions'], inventory['potions'])

    def test_add_station_uses_the_clients_brewer_ids(self):
        # The Alchemy tab's "Add Station" asks the brewers table for ids 2 and 3 (AlchemyBrewingPanel) and buys each
        # through a one-item bundle; an empty list there meant the ids did not match.
        old = {'InstanceId': 7, 'Type': 1202, 'UsesLeft': 20, 'WorkingRecipe': -1, 'FinishTime': 0}
        server, c, _ = self.seed_alchemy(brewer=old)
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=2) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual({r['id']: r['slug'] for r in data['brewers']}, {1: 'brewer_basic', 2: 'brewer_small', 3: 'brewer_big'})
        def stations():
            r = Reader(c.rpc(69)); self.assertEqual(r.byte(), 1)
            return [(r.long(), r.integer(), r.integer(), r.integer(), r.integer())[:2] for _ in range(r.integer())]
        self.assertEqual(stations(), [(1, 1), (7, 2)])       # a station saved as 1202 comes back as the client's 2
        self.assertEqual(c.rpc(75, I(2203) + Q(5))[:1], b'\1')
        self.assertIn(3, [kind for _, kind in stations()])

    def test_alchemy_basic_skill_gate_preserves_preexisting_items_and_work(self):
        # Legacy saved work remains claimable even if the current skill set lacks its prerequisite.
        old = {'InstanceId': 1, 'Type': 1201, 'UsesLeft': -1, 'WorkingRecipe': 2102, 'FinishTime': 1}
        _, c, _ = self.seed_alchemy(skills=[], brewer=old)
        self.assertEqual(self.known(c), {})
        before = self.inventory(c)
        self.assertEqual(c.rpc(68, Q(1)), b'\1' + Q(1) + I(1) + I(3) + I(205))
        self.assertEqual(self.inventory(c)['potions'][205], before['potions'][205] + 1)
        after = self.saved_alchemy()
        for recipe, kind in [(2101, 3), (3101, 4), (4101, 2), (6101, 6)]:
            self.assertEqual(c.rpc(4, Q(1) + I(recipe) + I(kind))[:1], b'\0')
        self.assertEqual(self.saved_alchemy(), after)

    def test_alchemy_slot_capacity_and_duplicate_bypass_all_entrypoints(self):
        _, c, _ = self.seed_alchemy()
        for potions in ([201, 202], [201, 201], [99999]):
            before = self.saved_alchemy()
            self.assertEqual(c.rpc(89, I(301) + I(len(potions)) + b''.join(I(p) for p in potions)), b'\0')
            self.assertEqual(c.rpc(10, self.loadout(potions)), b'\0')
            self.assertEqual(c.rpc(98, self.loadout(potions)), b'\0')
            self.assertEqual(self.saved_alchemy(), before)
        self.assertEqual(c.rpc(64, I(54)), b'\1' + I(54))
        self.assertEqual(c.rpc(10, self.loadout([201, 202])), b'\1')
        self.assertEqual(c.rpc(10, self.loadout([201, 202, 205])), b'\0')
        self.assertEqual(c.rpc(64, I(58)), b'\1' + I(58))
        self.assertEqual(c.rpc(89, I(-1) + I(3) + I(201) + I(202) + I(205)), b'\1')
        before = self.saved_alchemy()
        self.assertEqual(c.rpc(10, self.loadout([201, 202, 205, 203])), b'\0')
        self.assertEqual(c.rpc(10, self.loadout([201, 201])), b'\0')
        self.assertEqual(self.saved_alchemy(), before)
        self.assertEqual(c.rpc(98, self.loadout([201, 202, 205])), b'\1')

    def test_alchemy_capacity_counts_owned_ids_once(self):
        _, c, _ = self.seed_alchemy(skills=STARTING + [54, 54])
        self.assertEqual(c.rpc(10, self.loadout([201, 202, 205])), b'\0')
        self.assertEqual(c.rpc(10, self.loadout([201, 202])), b'\1')

    def test_alchemy_extra_output_saved_at_start_survives_restart_and_retries(self):
        server, c, settings = self.seed_alchemy(skills=STARTING + [63],
                                              env={'Reconstruction__ExtraPotionChancePercent': '100'})
        before = self.inventory(c)['potions'][201]
        self.assertEqual(c.rpc(4, Q(1) + I(2101) + I(3))[:1], b'\1')
        self.assertEqual(self.saved_alchemy()['Brewers'][0]['OutputCount'], 2)
        self.assertEqual(c.rpc(68, Q(1)), b'\0' + Q(1) + I(0))
        # Skill removal and a changed chance cannot reroll the saved craft outcome.
        settings['Reconstruction__ExtraPotionChancePercent'] = '0'
        server, c = self.finish_alchemy(server, settings, remove_skills=True)
        result = b'\1' + Q(1) + I(2) + I(3) + I(201) + I(3) + I(201)
        self.assertEqual(c.rpc(68, Q(1)), result)
        self.assertEqual(c.rpc(68, Q(1), repeat=True), result)
        self.assertEqual(c.rpc(68, Q(1)), b'\0' + Q(1) + I(0))
        self.assertEqual(self.inventory(c)['potions'][201], before + 2)
        server.stop()
        c = self.client(self.start('alchemy-fixture', settings))
        self.assertEqual(c.rpc(68, Q(1)), b'\0' + Q(1) + I(0))
        self.assertEqual(self.inventory(c)['potions'][201], before + 2)

    def test_alchemy_extra_output_excludes_non_potions_and_unowned_skill(self):
        server, c, settings = self.seed_alchemy(skills=STARTING + [63],
                                              env={'Reconstruction__ExtraPotionChancePercent': '100'})
        for recipe, kind in [(3101, 4), (4101, 2), (6101, 6)]:
            self.assertEqual(c.rpc(4, Q(1) + I(recipe) + I(kind))[:1], b'\1')
            self.assertEqual(self.saved_alchemy()['Brewers'][0]['OutputCount'], 1)
            self.assertEqual(c.rpc(45, Q(1)), b'\1')
        server.stop()
        path = self.profile_file('alchemy-fixture'); saved = json.loads(path.read_text())
        saved['Player']['Skills'].remove(63); path.write_text(json.dumps(saved))
        c = self.client(self.start('alchemy-fixture', settings))
        self.assertEqual(c.rpc(4, Q(1) + I(2101) + I(3))[:1], b'\1')
        self.assertEqual(self.saved_alchemy()['Brewers'][0]['OutputCount'], 1)

    def test_alchemy_configured_policy_matches_catalogue_and_crafting_cost(self):
        server, c, _ = self.seed_alchemy(skills=STARTING + [56], env={
            'Reconstruction__SquallElementalRemains': '4', 'Reconstruction__ResolveFloorPercentPerRank': '7',
            'Reconstruction__AttackAdrenalineBonus': '2', 'Reconstruction__EventAdrenalineGain': '2',
            'Reconstruction__InitialAdrenalineGain': '4', 'Reconstruction__FinalBlowSurvivalChancePercent': '20',
            'Reconstruction__InstantSignRecoveryChancePercent': '25', 'Reconstruction__BombAngleReductionDegrees': '10'})
        data = self.catalogue_alchemy(server)
        self.assertIn({'recipe_id': 2107, 'ingredient_id': 108, 'amount': 4}, data['potion_recipe_ingredients'])
        effects = {r['item_id']: r for r in data['skill_to_effect'] if r['item_id'] in {17, 18, 19, 7, 8, 23, 26, 28, 45, 53, 55}}
        for skill, power in [(17, 7), (18, 14), (19, 21), (7, 2), (8, 2), (23, 2), (26, 4), (28, 20), (45, 25), (53, 10), (55, 10)]:
            self.assertEqual(effects[skill]['power'], power, skill)
        self.assertEqual(c.rpc(4, Q(1) + I(2107) + I(3))[:1], b'\1')
        inventory = self.inventory(c)['ingredients']
        self.assertEqual((inventory[108], inventory[101], inventory[103]), (46, 43, 43))

    def test_alchemy_skill_event_rows_match_reviewed_native_dispatch(self):
        server, _, _ = self.seed_alchemy()
        rows = self.catalogue_alchemy(server)['skill_to_effect']
        # Native event9 is shield ending; keep that distinction in the report, not a fictional cast callback.
        expected = {7: (27, 1), 8: (28, 1), 23: (4, 4), 26: (4, 1), 28: (10, 1),
                    41: (4, 11), 42: (4, 9), 43: (4, 8), 44: (4, 7), 45: (14, 1), 62: (4, 10)}
        for skill, pair in expected.items():
            self.assertEqual([(r['effect_id'], r['effect_apply_type_id']) for r in rows if r['item_id'] == skill], [pair])
        self.assertEqual([(r['effect_id'], r['power']) for r in rows if r['item_id'] == 27], [(9, 4)])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(AlchemyTests(name) for name in loader.getTestCaseNames(AlchemyTests)
                              if name.startswith('test_alchemy_'))
