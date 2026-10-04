"""Skill catalogue and purchase regressions; every saved player is a temporary synthetic fixture."""
import gzip
import json
import unittest
import urllib.request

import test_prototype as base

I, Reader = base.I, base.Reader

# Identity snapshot before the rank repair. These IDs are already stored in player profiles.
LEGACY_CHAINS = {
    'fast_attack': [1], 'strong_attack': [2], 'parry': [3],
    'muscle_memory': [4, 9, 10, 11, 12], 'strength_training': [5, 13, 14, 15, 16],
    'hit_deflection': [6], 'precise_blows': [7], 'crushing_blows': [8], 'resolve': [17, 18, 19],
    'fleet_footed': [20], 'anatomical_knowledge': [21], 'lightning_reflexes': [22],
    'cold_blood': [23], 'counterattack': [24], 'crippling_strike': [25], 'razor_focus': [26],
    'battle_trance': [27], 'undying': [28], 'witcher_aura': [29], 'igni_sign': [30],
    'pyromaniac': [31, 32, 33, 34, 35], 'focus': [36], 'aard_sign': [37], 'quen_sign': [38],
    'shock_wave': [39], 'quen_discharge': [40], 'adrenaline_burst': [41], 'quen_intensity': [42],
    'igni_intensity': [43], 'aard_intensity': [44], 'gorged_on_power': [45], 'oil_preparation': [46],
    'brewing': [47], 'bomb_creation': [48], 'enhanced_oils': [49], 'tawny_owl': [50],
    'fixative': [51], 'cat': [52], 'steady_aim': [53], 'acquired_tolerance': [54],
    'advanced_steady_aim': [55], 'squall': [56], 'protective_coating': [57], 'fast_metabolism': [58],
    'pyrotechnics': [59], 'superior_oils': [60], 'wolverine': [61], 'advanced_pyrotechnics': [62],
    'elixir_master': [63],
}
FIVE_RANKS = {'muscle_memory', 'strength_training', 'fleet_footed', 'anatomical_knowledge',
              'battle_trance', 'pyromaniac', 'focus', 'shock_wave', 'quen_discharge', 'fixative',
              'protective_coating', 'pyrotechnics'}
SIGN_REQUIREMENTS = {31: 30, 39: 37, 40: 38, 42: 38, 43: 30, 44: 37}


class SkillTests(base.PrototypeTests):
    def catalogue(self, server=None):
        with urllib.request.urlopen(f'http://127.0.0.1:{(server or self.server).http}/staticdata', timeout=3) as response:
            return json.loads(gzip.decompress(response.read()))

    def seed(self, skills, points=100, exp=780000):
        # Create via the real serializer, then edit only this stopped temporary synthetic player.
        server = self.start('skill-fixture', self.RECONSTRUCTED)
        client = self.client(server)
        client.rpc(63)
        # GetSkills can respond before the new profile exists on disk; wait for an
        # acknowledged empty fact write rather than racing shutdown against that save.
        self.assertEqual(client.rpc(78, I(0)), b'\1')
        path = self.profile_file('skill-fixture')
        saved = json.loads(path.read_text())
        server.stop()
        saved['Player']['Skills'] = skills
        saved['Player']['SkillPoints'] = points
        saved['Player']['Exp'] = exp
        path.write_text(json.dumps(saved))
        server = self.start('skill-fixture', self.RECONSTRUCTED)
        return server, self.client(server), saved

    def skill_state(self, client):
        r = Reader(client.rpc(63))
        state = r.ints(), r.integer()
        self.assertEqual(r.pos, len(r.data))
        return state

    def test_skills_identity_rank_chains_and_prerequisites(self):
        data = self.catalogue()
        skills = {row['id']: row for row in data['skills']}
        self.assertEqual(len(data['skills']), 101)
        self.assertEqual(set(skills), set(range(1, 102)))
        self.assertEqual({s['slug'] for s in skills.values()}, set(LEGACY_CHAINS))
        for slug, ids in LEGACY_CHAINS.items():
            for old_id in ids:
                self.assertEqual(skills[old_id]['slug'], slug)
            chain = [s for s in skills.values() if s['slug'] == slug]
            count = 5 if slug in FIVE_RANKS else 3 if slug == 'resolve' else 2 if slug in {'lightning_reflexes', 'counterattack'} else 1
            self.assertEqual(len(chain), count, slug)
            roots = [s for s in chain if 'parent_id' not in s]
            self.assertEqual([r['id'] for r in roots], [ids[0]], slug)
            ordered = roots[:]
            while len(ordered) < count:
                children = [s for s in chain if s.get('parent_id') == ordered[-1]['id']]
                self.assertEqual(len(children), 1, slug)
                ordered.append(children[0])
            self.assertEqual([s['id'] for s in ordered[:len(ids)]], ids)
            if count == 5:
                self.assertEqual([s['cost'] for s in ordered], [1, 3, 5, 9, 15], slug)
        self.assertEqual([skills[i]['cost'] for i in [17, 18, 19]], [1, 5, 15])
        self.assertEqual(skills[55]['required_level'], 20)
        requirements = {(r['skill_id'], r['required_skill_id']) for r in data['skill_requirements']}
        self.assertLessEqual(set(SIGN_REQUIREMENTS.items()), requirements)
        for row in skills.values():
            if 'parent_id' in row:
                self.assertEqual(skills[row['parent_id']]['slug'], row['slug'])
                self.assertIn((row['id'], row['parent_id']), requirements)
        for child in SIGN_REQUIREMENTS:
            self.assertNotIn('parent_id', skills[child])

    def test_skills_full_rank_attack_effects_and_transport_match(self):
        data = self.catalogue()
        c = self.client(auth=False)
        c.send(4, I(1) + I(0)); channel, payload = c.receive(); r = Reader(payload)
        self.assertEqual((channel, r.integer()), (4, 1))
        tcp = json.loads(gzip.decompress(r.take(r.integer())))
        self.assertEqual(tcp, data)
        self.assertEqual(r.pos, len(payload))
        rows = data['skill_to_effect']
        definitions = {r['id']: r['effect_type_id'] for r in data['effects']}
        for slug, effect in [('muscle_memory', 1), ('strength_training', 2)]:
            for skill, power in zip(LEGACY_CHAINS[slug], [4, 8, 12, 16, 20]):
                actual = [(r['effect_id'], r['power'], r['effect_apply_type_id']) for r in rows if r['item_id'] == skill]
                self.assertEqual(actual, [(effect, power, 1)])
                self.assertEqual(definitions[effect], 1)
        # Unlocks belong to signs, not their new independent upgrade chains.
        for skill, effect in [(30, 43), (37, 42), (38, 44)]:
            self.assertIn({'item_id': skill, 'effect_id': effect, 'power': 1, 'effect_apply_type_id': 18}, rows)

    def test_skills_trigger_units_and_unresolved_effects(self):
        data = self.catalogue()
        rows = data['skill_to_effect']
        effects = {r['id']: r for r in data['effects']}
        self.assertEqual(len(effects), len(data['effects']))
        self.assertEqual(len(rows), len({(r['item_id'], r['effect_id']) for r in rows}))
        for row in rows:
            self.assertIn(row['effect_id'], effects)
        # Native event contracts: counterattack on deflect, delay in milliseconds on perfect finisher.
        self.assertIn({'item_id': 24, 'effect_id': 5, 'power': 5, 'effect_apply_type_id': 5}, rows)
        self.assertIn({'item_id': 73, 'effect_id': 5, 'power': 10, 'effect_apply_type_id': 5}, rows)
        self.assertIn({'item_id': 25, 'effect_id': 8, 'power': 1000, 'effect_apply_type_id': 15}, rows)
        skills = {r['id']: r for r in data['skills']}
        for slug in FIVE_RANKS:
            with self.subTest(slug=slug):
                ranked = [s for s in skills.values() if s['slug'] == slug]
                self.assertTrue(all(any(r['item_id'] == s['id'] and effects[r['effect_id']]['effect_type_id'] == 1
                                        for r in rows) for s in ranked))
        # Resolve uses an explicitly authored minimum floor, not an unsafe loss modifier stacked with armor.
        for skill, power in [(17, 10), (18, 20), (19, 30)]:
            self.assertEqual([r for r in rows if r['item_id'] == skill],
                             [{'item_id': skill, 'effect_id': 59, 'power': power, 'effect_apply_type_id': 1}])

    def test_skills_level_gate_and_cross_prerequisite_on_later_rank(self):
        server, c, _ = self.seed([1, 2, 3, 31], points=20, exp=105000)  # Synthetic level 15, missing Igni.
        before = self.skill_state(c)
        self.assertEqual(c.rpc(64, I(55)), b'\0' + I(55))  # Advanced Steady Aim is level 20.
        self.assertEqual(c.rpc(64, I(32)), b'\0' + I(32))  # Parent row does not waive the separate sign.
        self.assertEqual(c.rpc(64, I(99999)), b'\0' + I(99999))
        self.assertEqual(self.skill_state(c), before)

    def test_skills_old_purchases_and_points_survive_bootstrap(self):
        server, c, before = self.seed(list(range(1, 64)), points=7)
        batch = base.decode_batch(c.rpc(115)); r = Reader(batch[63])
        self.assertEqual((r.ints(), r.integer()), (list(range(1, 64)), 7))
        self.assertEqual(r.pos, len(r.data))
        self.assertEqual(c.rpc(64, I(12)), b'\0' + I(12))
        self.assertEqual(self.skill_state(c), (list(range(1, 64)), 7))
        server.stop()
        after = json.loads(self.profile_file('skill-fixture').read_text())
        self.assertEqual(after['Player'], before['Player'])
        restarted = self.start('skill-fixture', self.RECONSTRUCTED)
        self.assertEqual(self.skill_state(self.client(restarted)), (list(range(1, 64)), 7))

    def test_skills_purchase_separately_checks_sign_and_rank(self):
        server, c, _ = self.seed([1, 2, 3, 30], points=100)
        before = self.skill_state(c)
        self.assertEqual(c.rpc(64, I(39)), b'\0' + I(39))  # Shock Wave still needs Aard.
        self.assertEqual(c.rpc(64, I(40)), b'\0' + I(40))  # Quen Discharge still needs Quen.
        self.assertEqual(c.rpc(64, I(32)), b'\0' + I(32))  # Igni alone is not Pyromaniac rank one.
        self.assertEqual(self.skill_state(c), before)
        self.assertEqual(c.rpc(64, I(37)), b'\1' + I(37))
        self.assertEqual(c.rpc(64, I(39)), b'\1' + I(39))
        self.assertEqual(c.rpc(64, I(31)), b'\1' + I(31))
        self.assertEqual(c.rpc(64, I(32)), b'\1' + I(32))
        self.assertEqual(self.skill_state(c), ([1, 2, 3, 30, 37, 39, 31, 32], 90))
        self.assertEqual(c.rpc(64, I(43)), b'\1' + I(43))  # Separate intensity keeps Igni owned.
        self.assertIn(30, self.skill_state(c)[0])

    def test_skills_appended_rank_cost_refusal_replay_and_restart(self):
        server, c, _ = self.seed([1, 2, 3, 20], points=3)
        data = self.catalogue(server)
        rank2 = next(s for s in data['skills'] if s.get('parent_id') == 20)
        rank3 = next(s for s in data['skills'] if s.get('parent_id') == rank2['id'])
        self.assertGreater(rank2['id'], 63)
        before = self.skill_state(c)
        self.assertEqual(c.rpc(64, I(rank3['id'])), b'\0' + I(rank3['id']))
        self.assertEqual(self.skill_state(c), before)
        response = c.rpc(64, I(rank2['id']))
        self.assertEqual(response, b'\1' + I(rank2['id']))
        self.assertEqual(c.rpc(64, I(rank2['id']), repeat=True), response)
        expected = ([1, 2, 3, 20, rank2['id']], 0)
        self.assertEqual(self.skill_state(c), expected)
        self.assertEqual(c.rpc(64, I(rank2['id'])), b'\0' + I(rank2['id']))
        self.assertEqual(c.rpc(64, I(rank3['id'])), b'\0' + I(rank3['id']))
        server.stop()
        restarted = self.start('skill-fixture', self.RECONSTRUCTED)
        self.assertEqual(self.skill_state(self.client(restarted)), expected)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(SkillTests(name) for name in loader.getTestCaseNames(SkillTests)
                              if name.startswith('test_skills_'))
