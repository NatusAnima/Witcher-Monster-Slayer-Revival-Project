"""World density, shared geometry cache and UTC reset regressions with synthetic inputs only."""
import concurrent.futures
from datetime import datetime, timezone
import json
import time
import unittest
from zoneinfo import ZoneInfo

import test_prototype as base
from test_tasks import TaskTests

I, Q, Reader = base.I, base.Q, base.Reader


class WorldPolicyTests(base.PrototypeTests):
    CELLS = [0x4704440000000000 + (k << 40) for k in range(3)]

    @staticmethod
    def response(ids, epoch):
        return {i: dict(center=[10.0, 20.0], places=[
            dict(id=f'lab-{int(i):016x}-{epoch}-{n}', lat=10.0+n/1000,
                 lng=20.0, biomes=[10], kind='path') for n in range(24)]) for i in ids}

    def policy(self, value):
        root = self.directory / 'world'
        root.mkdir(exist_ok=True)
        pending = root / 'world.pending'
        pending.write_text(json.dumps(value))
        pending.replace(root / 'world.json')
        return root

    def map(self, client):
        return self.locations_by_cell(client.rpc(40, I(len(self.CELLS))+b''.join(Q(i) for i in self.CELLS)))

    def test_world_density_hot_reload_preserves_existing_instances_and_placements(self):
        root = self.policy(dict(schemaVersion=1, monsterSlotsPerCell=6))
        url, _ = self.playable_service(self.response)
        server = self.start('density', dict(self.RECONSTRUCTED, Playable__Url=url, World__Directory=str(root)))
        client = self.client(server)
        before = self.map(client)
        self.policy(dict(schemaVersion=1, monsterSlotsPerCell=12))
        time.sleep(1.05)
        after = self.map(client)
        self.assertEqual((after['herbs'], after['nests'], after['cells']),
                         (before['herbs'], before['nests'], before['cells']))
        self.assertEqual(len(after['monsters']), 36)  # Twelve shared encounters per populated cell, at any XP.
        for old in before['monsters']:
            if old['spawn_ms']//1000 + old['ttl'] > time.time()+1:
                self.assertIn(old, after['monsters'])
        places = [m['place'] for m in after['monsters']]
        self.assertEqual(len(places), len(set(places)))
        self.assertFalse(set(places) & {m['place'] for m in after['herbs']+after['nests']})
        self.assertTrue(all(m['ttl'] == 1800 for m in after['monsters']))
        self.assertEqual(after, self.map(client))
        self.policy(dict(schemaVersion=1, monsterSlotsPerCell=18))
        time.sleep(1.05)
        maximum = self.map(client)
        self.assertEqual(len(maximum['monsters']), 54)
        self.assertEqual((maximum['herbs'], maximum['nests'], maximum['cells']),
                         (after['herbs'], after['nests'], after['cells']))
        for old in after['monsters']:
            if old['spawn_ms']//1000 + old['ttl'] > time.time()+1:
                self.assertIn(old, maximum['monsters'])

    def test_world_rejects_invalid_initial_policy_and_retains_last_valid_reload(self):
        root = self.policy(dict(schemaVersion=1, monsterSlotsPerCell=19))
        with self.assertRaisesRegex(RuntimeError, 'World policy'):
            base.Server(self.directory, 'invalid-world', dict(World__Directory=str(root)))
        self.policy(dict(schemaVersion=1, monsterSlotsPerCell=12))
        url, _ = self.playable_service(self.response)
        client = self.client(self.start('valid-world', dict(self.RECONSTRUCTED,
                    Playable__Url=url, World__Directory=str(root))))
        before = self.map(client)
        for invalid in [dict(schemaVersion=2, monsterSlotsPerCell=6),
                        dict(schemaVersion=1, monsterSlotsPerCell=5),
                        dict(schemaVersion=1, monsterSlotsPerCell=6, extra=True),
                        dict(schemaVersion=1)]:
            self.policy(invalid); time.sleep(1.05)
            after = self.map(client)
            self.assertEqual(len(after['monsters']), 36)
            self.assertEqual(after['cells'], before['cells'])
        self.assertIn('World policy reload refused', self.servers[-1].logpath.read_text())

    def test_world_balance_rejects_invalid_history_and_retains_last_valid_reload(self):
        root = self.policy(dict(schemaVersion=1, monsterSlotsPerCell=12))
        path = root/'spawn-balance.json'
        rules = dict(common=1, rare=0, legendary=0, speciesWeights={})
        valid = dict(schemaVersion=1, versions=[dict(fromUnixSeconds=0, rules=rules)])
        invalid = dict(valid, schemaVersion=2)
        path.write_text(json.dumps(invalid))
        with self.assertRaisesRegex(RuntimeError, 'Invalid spawn balance history'):
            base.Server(self.directory, 'invalid-balance-history', dict(World__Directory=str(root)))
        path.write_text(json.dumps(valid))
        url, _ = self.playable_service(self.response)
        server = self.start('valid-balance-history', dict(self.RECONSTRUCTED,
            Playable__Url=url, World__Directory=str(root)))
        client = self.client(server)
        before = self.map(client)
        rarities = {s['monster_id']: s['rarity'] for s in base.WORLD['species']}
        self.assertTrue(before['monsters'])
        self.assertTrue(all(rarities[m['monster']] == 1 for m in before['monsters']))
        pending = root/'spawn-balance.pending'; pending.write_text(json.dumps(invalid)); pending.replace(path)
        time.sleep(1.05)
        after = self.map(client)
        self.assertTrue(all(rarities[m['monster']] == 1 for m in after['monsters']))
        for monster in before['monsters']:
            if monster['spawn_ms']/1000+monster['ttl'] > time.time()+1:
                self.assertIn(monster, after['monsters'])
        self.assertIn('Spawn balance reload refused', server.logpath.read_text())

    def test_world_levels_share_instances_and_personal_kills_survive_reconnect_and_restart(self):
        url, _ = self.playable_service(self.response)
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('level-shared-world', env)
        identities = [server.identity] + [(f'SYNTHETIC_WORLD_LEVEL_{level}', '') for level in (3, 6, 10)]
        for identity in identities:
            self.client(server, identity=identity).rpc(78, I(1)+I(10145)+I(1))
        server.stop()
        for identity, level, exp in zip(identities, (1, 3, 6, 10), (0, 3000, 15000, 45000)):
            path = self.directory / 'profiles' / (server.profile_id(identity)+'.json')
            profile = json.loads(path.read_text())
            profile['Player']['Exp'], profile['Player']['LevelAnnounced'] = exp, level
            path.write_text(json.dumps(profile))
        server = self.start('level-shared-world', env)
        clients = [self.client(server, identity=identity) for identity in identities]
        worlds = [self.map(client) for client in clients]
        self.assertEqual(len(worlds[0]['monsters']), 54)  # Default18; sparse geometry is tested separately.
        self.assertTrue(all(world == worlds[0] for world in worlds[1:]))
        skulls = {s['monster_id']: s['skulls'] for s in base.WORLD['species']}
        self.assertTrue(any(skulls[m['monster']] > 0 for m in worlds[0]['monsters']))

        # Select a comfortably live instance so reconnect/startup cannot straddle its expiration.
        target = max(worlds[0]['monsters'], key=lambda m: m['spawn_ms']//1000+m['ttl'])
        self.assertEqual(clients[0].rpc(41, Q(target['instance'])), b'\1')
        self.assertGreater(self.combat_end(Reader(clients[0].rpc(8, b'\1'+I(13)+I(0)*13+b'\0')))['base'], 0)
        earned_exp = self.player_info(clients[0])['exp']
        clients[0].close()
        resumed = self.client(server, identity=identities[0])
        self.assertNotIn(target, self.map(resumed)['monsters'])
        self.assertEqual(resumed.rpc(41, Q(target['instance'])), b'\0')
        self.assertIn(target, self.map(clients[-1])['monsters'])
        late = self.client(server, identity=('SYNTHETIC_WORLD_LATE_LOGIN', ''))
        self.assertIn(target, self.map(late)['monsters'])

        server.stop()
        server = self.start('level-shared-world', env)
        resumed = self.client(server, identity=identities[0])
        other = self.client(server, identity=identities[-1])
        self.assertNotIn(target, self.map(resumed)['monsters'])
        self.assertIn(target, self.map(other)['monsters'])
        self.assertEqual(resumed.rpc(41, Q(target['instance'])), b'\0')
        self.assertEqual(self.player_info(resumed)['exp'], earned_exp)

    def test_world_geometry_requests_coalesce_across_players_and_separate_epochs(self):
        def respond(ids, epoch):
            time.sleep(.12)
            return self.response(ids, epoch)
        url, requests = self.playable_service(respond)
        server = self.start('shared-world', dict(self.RECONSTRUCTED, Playable__Url=url))
        clients = [self.client(server, identity=(f'SYNTHETIC_CACHE_{i}', '')) for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            maps = list(executor.map(self.map, clients))
        self.assertEqual(len(requests), 1)
        self.assertTrue(all(world == maps[0] for world in maps))
        for client in clients: self.map(client)
        self.assertEqual(len(requests), 1)
        # Still-loaded prior-day place IDs must use their original geometry epoch.
        old = f'lab-{self.CELLS[0]:016x}-{int(time.time())//86400-1}-0'
        clients[0].rpc(87, I(1)+base.S(old))
        self.assertEqual(len(requests), 2)

    def test_world_rarity_weights_apply_to_category_not_species_count_or_beginner_slots(self):
        rarity = {s['monster_id']: s['rarity'] for s in base.WORLD['species']}
        for biome in (1, 7, 5):
            def respond(ids, epoch):
                result = self.response(ids, epoch)
                for cell in result.values():
                    for place in cell['places']: place['biomes'] = [biome]
                return result
            url, _ = self.playable_service(respond)
            c = self.client(self.start('rarity-' + str(biome), dict(self.RECONSTRUCTED, Playable__Url=url)))
            counts = dict.fromkeys((1, 2, 3), 0)
            for batch in range(5):
                ids = [0x4704440000000000 + ((batch*64+k) << 34) for k in range(64)]
                response = self.locations_by_cell(c.rpc(40, I(64)+b''.join(Q(i) for i in ids)))
                self.assertEqual(len(response['monsters']), 64*18)
                for monster in response['monsters']: counts[rarity[monster['monster']]] += 1
            total = sum(counts.values())
            for kind, weight in ((1, 88), (2, 18), (3, 3)):
                # Six binomial standard deviations plus a small finite-fixture allowance.
                expected = weight / 109
                margin = 6*(expected*(1-expected)/total)**.5 + .003
                self.assertAlmostEqual(counts[kind]/total, expected, delta=margin,
                                       msg=f'biome={biome} rarity={kind} counts={counts}')

    def test_world_balance_activation_is_fixed_across_restart_and_legacy_stays_available(self):
        url, _ = self.playable_service(self.response)
        env = dict(self.RECONSTRUCTED, Playable__Url=url,
                   World__SpawnBalanceFromUnixSeconds=str(4_102_444_800))
        s = self.start('balance-scheduled', env)
        before = self.map(self.client(s))
        s.stop()
        after = self.map(self.client(self.start('balance-scheduled', env)))
        for monster in before['monsters']:
            if monster['spawn_ms']//1000 + monster['ttl'] > time.time()+1:
                self.assertIn(monster, after['monsters'])
        # Reject configuration errors at startup; a request must not discover them later.
        with self.assertRaisesRegex(RuntimeError, 'World spawn balance'):
            base.Server(self.directory, 'negative-balance', dict(World__SpawnBalanceFromUnixSeconds='-1'))


class UtcResetTests(TaskTests):
    def test_world_daily_stamp_boundary_is_utc_through_warsaw_dst_changes(self):
        # UTC midnight is 01:00 or 02:00 locally, not regional midnight or a fixed Polish hour.
        for day, hour in [('2026-03-29', 1), ('2026-03-30', 2), ('2026-10-25', 2), ('2026-10-26', 1)]:
            at = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            self.assertEqual(at.astimezone(ZoneInfo('Europe/Warsaw')).hour, hour)
            stamp = int(at.timestamp())
            name = 'utc-' + day
            server, client = self.task_server(at=stamp-1, name=name)
            self.fight(client)
            self.assertEqual(Reader(client.rpc(94)).weekly()['stamps'], [stamp//86400-1])
            server.stop()
            server, client = self.task_server(at=stamp, name=name, fresh_summons=True)
            # The boundary grants eligibility, and a qualifying win grants the next stamp.
            self.assertEqual(Reader(client.rpc(94)).weekly()['stamps'], [stamp//86400-1])
            self.fight(client)
            self.assertEqual(Reader(client.rpc(94)).weekly()['stamps'], [stamp//86400-1, stamp//86400])
            server.stop()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(loader.loadTestsFromName(name, cls)
        for cls in (WorldPolicyTests, UtcResetTests)
        for name in loader.getTestCaseNames(cls) if name.startswith('test_world_'))
