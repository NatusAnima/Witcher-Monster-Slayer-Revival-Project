"""Native Witcher Aura contracts and persistence; only temporary synthetic players and map geometry."""
import concurrent.futures
import gzip
import json
import time
import unittest
import urllib.request

import test_prototype as base

I, Q, Reader = base.I, base.Q, base.Reader


class AuraTests(base.PrototypeTests):
    CELL = 0x4704440000000000
    PAYLOAD = I(13) + I(29) + I(2000000) + I(1000000)

    @staticmethod
    def geometry(ids, epoch):
        return {i: dict(center=[10.0, 20.0], places=[
            dict(id=f'lab-{int(i):016x}-{epoch}-{n}', lat=10.0001+n/10000,
                 lng=20.0, biomes=[4], kind='path') for n in range(24)]) for i in ids}

    def boot(self, name='aura', overrides=None, mapped=True):
        url, requests = self.playable_service(self.geometry)
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        env.update(overrides or {})
        server = self.start(name, env)
        client = self.client(server)
        if mapped: self.map(client)
        return server, client, env, requests

    def map(self, client):
        return self.locations_by_cell(client.rpc(40, I(1)+Q(self.CELL)))

    def groups(self, data, result=False):
        r = Reader(data)
        if result:
            self.assertEqual(r.byte(), 1)
        groups = []
        for _ in range(r.integer()):
            group = {k:r.integer() for k in ('type', 'item', 'start', 'end', 'lng', 'lat')}
            group['monsters'] = [(r.integer(), r.long(), r.byte()) for _ in range(r.integer())]
            groups.append(group)
        self.assertEqual(r.pos, len(r.data))
        return groups

    def last(self, client):
        r = Reader(client.rpc(117))
        self.assertEqual(r.byte(), 1)
        value = r.integer()
        self.assertEqual(r.pos, len(r.data))
        return value

    def test_aura_bootstrap_includes_zero_timestamp_in_both_profile_modes(self):
        # Original OnGameStarted (0x1A2A8C0) reads method117 from the RPC115 cache;
        # a missing entry invokes the native callback with null, without a network retry.
        legacy_client = self.client()
        reconstructed, client, _, requests = self.boot(name='aura-bootstrap', mapped=False)
        for server, client, count in ((self.server, legacy_client, 21), (reconstructed, client, 22)):
            with self.subTest(parts=count):
                before = server.state()['player']
                response = client.rpc(115)
                batch = base.decode_batch(response)  # Consumes the whole body, including trailing boundaries.
                self.assertIn(117, batch)
                self.assertEqual(Reader(response).integer(), count)
                self.assertEqual(len(batch), count)  # A duplicated method cannot replace another entry.
                self.assertEqual(batch[117], b'\1' + I(0))
                self.assertEqual(batch[117], client.rpc(117))
                after = server.state()['player']
                if before is None:
                    self.assertIsNone(after)
                else:
                    for key in ('aura', 'summons', 'items', 'gold', 'skills', 'skillPoints'):
                        self.assertEqual(after.get(key), before.get(key), key)
                self.assertEqual(112 in batch, count == 22)
        self.assertEqual(requests, [])

    def test_aura_bootstrap_preserves_saved_timestamp_without_summoning(self):
        server, client, env, requests = self.boot(name='aura-bootstrap-saved', mapped=False)
        client.rpc(115)  # Complete normal task/level initialization before seeding the synthetic save.
        server.stop()
        path = self.profile_file('aura-bootstrap-saved')
        saved = json.loads(path.read_text())
        saved['Player']['Aura'] = dict(At=1234567890, RequestId=2468, Longitude=2000000, Latitude=1000000)
        path.write_text(json.dumps(saved))
        server = self.start('aura-bootstrap-saved', env)
        client = self.client(server)
        before, persisted = server.state(), path.read_bytes()
        for _ in range(2):
            response = client.rpc(115)
            batch = base.decode_batch(response)
            self.assertIn(117, batch)
            self.assertEqual(Reader(response).integer(), 22)
            self.assertEqual(len(batch), 22)
            # Factory0x1E79FE4 reads one Result byte and one BIG-endian int32 timestamp.
            self.assertEqual(batch[117], b'\1' + I(1234567890))
            self.assertEqual(batch[117], client.rpc(117))
            self.assertEqual(batch[112], I(0))
        self.assertEqual(server.state(), before)
        self.assertEqual(path.read_bytes(), persisted)
        self.assertEqual(requests, [])  # Neither geometry fetching nor summoning was invoked.

    def test_aura_native_catalogue_powers_and_configuration_bounds(self):
        for overrides, interval in [({},3600),
                ({'Reconstruction__WitcherAuraIntervalSeconds':'900',
                  'Reconstruction__WitcherAuraLifetimeSeconds':'600'},900)]:
            server, client, _, _ = self.boot(name='catalogue-'+str(interval), overrides=overrides)
            with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
                data = json.loads(gzip.decompress(response.read()))
            rows = [r for r in data['skill_to_effect'] if r['item_id'] == 29]
            self.assertEqual(rows, [dict(item_id=29,effect_id=77,power=interval,effect_apply_type_id=18),
                                    dict(item_id=29,effect_id=78,power=1,effect_apply_type_id=18)])
            effects = {r['id']:r for r in data['effects']}
            self.assertEqual([effects[i]['effect_type_id'] for i in (77,78)], [2,2])
            self.assertEqual(self.last(client), 0)
            groups = self.groups(client.rpc(111,self.PAYLOAD),True)
            self.assertEqual(groups[0]['end']-groups[0]['start'], 3600 if interval == 3600 else 600)
            server.stop()
        for bad in [dict(Reconstruction__WitcherAuraIntervalSeconds='299'),
                    dict(Reconstruction__WitcherAuraLifetimeSeconds='86401'),
                    dict(Reconstruction__WitcherAuraIntervalSeconds='300')]:
            with self.assertRaisesRegex(RuntimeError,'WitcherAura'):
                base.Server(self.directory,'bad-aura',bad)

    def test_aura_refuses_missing_or_remote_geometry_and_wrong_skill_without_mutation(self):
        server, client, env, requests = self.boot(mapped=False)
        self.assertEqual(self.last(client), 0)  # The native controller synchronizes first; bootstrap marks the level.
        before = server.state()
        self.assertEqual(client.rpc(111,self.PAYLOAD),b'\0')
        self.assertEqual(requests, [])
        self.assertEqual(server.state()['revision'],before['revision'])
        self.map(client)
        before = server.state()  # Loading the map may persist the tutorial's first story place.
        for payload in [I(13)+I(28)+self.PAYLOAD[8:],
                        I(13)+I(29)+I(0)+I(0),
                        I(13)+I(29)+I(20000000)+I(1000000), I(13)]:
            self.assertEqual(client.rpc(111,payload), b'\0')
        self.assertEqual(client.rpc(117,I(1)),b'\0'+I(0))
        self.assertEqual(self.last(client),0)
        self.assertEqual(server.state()['revision'],before['revision'])
        self.assertEqual(self.groups(client.rpc(112)),[])
        server.stop()
        path = self.profile_file('aura')
        saved = json.loads(path.read_text())
        saved['Player']['Skills'].remove(29)
        path.write_text(json.dumps(saved))
        server = self.start('aura', env); client = self.client(server); self.map(client)
        self.assertEqual(client.rpc(111, self.PAYLOAD), b'\0')
        self.assertEqual(self.last(client), 0)

    def test_aura_success_retries_restart_and_safe_anchor(self):
        server, client, env, requests = self.boot()
        before = server.state()
        response = client.rpc(111,self.PAYLOAD)
        nonce = client.sequence
        group, = self.groups(response, True)
        self.assertEqual((group['type'],group['item'],group['lng'],group['lat']), (13,29,2000000,1000010))
        self.assertEqual(len(group['monsters']),1)
        self.assertEqual(group['end']-group['start'],3600)
        self.assertEqual(client.rpc(111,self.PAYLOAD,repeat=True), response)
        self.assertEqual(client.rpc(111,self.PAYLOAD[:-4]+I(1000001),repeat=True),b'\0')
        self.assertEqual(self.groups(client.rpc(112)),[group])
        self.assertEqual(self.last(client),group['start']+1)
        after = server.state()
        self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual({k:v for k,v in before['player'].items() if k not in ('aura','summons')},
                         {k:v for k,v in after['player'].items() if k not in ('aura','summons')})
        self.assertEqual(len(requests),1)  # Aura consumes already served geometry.
        server.stop()
        restarted = self.start('aura',env)
        client = self.client(restarted)
        client.sequence = nonce
        self.assertEqual(client.rpc(111,self.PAYLOAD,repeat=True),response)
        self.assertEqual(self.groups(client.rpc(112)),[group])
        self.assertEqual(self.last(client),group['start']+1)
        self.assertEqual(client.rpc(111,self.PAYLOAD),b'\0')
        self.assertEqual(restarted.state()['revision'],after['revision'])

    def test_aura_competing_sessions_create_only_one_group(self):
        server, first, _, _ = self.boot()
        second = self.client(server)
        before = server.state()['revision']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda c:c.rpc(111,self.PAYLOAD),(first,second)))
        self.assertEqual(sorted(r[0] for r in results),[0,1])
        self.assertEqual(len(self.groups(first.rpc(112))),1)
        self.assertEqual(server.state()['revision'],before+1)

    def test_aura_expiry_keeps_cooldown_and_future_clock_is_refused(self):
        server, client, env, _ = self.boot()
        group, = self.groups(client.rpc(111,self.PAYLOAD),True)
        server.stop()
        path=self.profile_file('aura')
        saved=json.loads(path.read_text())
        prior_nonce=saved['Player']['Aura']['RequestId']
        now=int(time.time())
        saved['Player']['Summons'][0]['DespawnTime']=now-1
        saved['Player']['Aura']['At']=now+3600
        path.write_text(json.dumps(saved))
        server=self.start('aura',env);client=self.client(server);self.map(client)
        self.assertEqual(client.rpc(111,self.PAYLOAD),b'\0')
        self.assertEqual(self.last(client),now+3600)
        self.assertEqual(self.groups(client.rpc(112)),[])
        server.stop()
        saved=json.loads(path.read_text());saved['Player']['Aura']['At']=now-3602
        path.write_text(json.dumps(saved))
        server=self.start('aura',env);client=self.client(server);self.map(client)
        client.sequence=prior_nonce
        self.assertEqual(client.rpc(111,self.PAYLOAD,repeat=True),b'\0')
        fresh,=self.groups(client.rpc(111,self.PAYLOAD),True)
        self.assertNotEqual(fresh['monsters'][0][1],group['monsters'][0][1])
        self.assertGreater(self.last(client),now-3602)

    def test_aura_failed_disk_write_keeps_memory_and_cooldown_unchanged(self):
        server,client,_,_=self.boot()
        before=server.state()
        pending=self.profile_file('aura').with_suffix('.json.pending');pending.mkdir()
        self.assertEqual(client.rpc(111,self.PAYLOAD),b'\0')
        self.assertEqual(self.last(client),0)
        self.assertEqual(self.groups(client.rpc(112)),[])
        self.assertEqual(server.state()['revision'],before['revision'])
        pending.rmdir()
        self.assertEqual(len(self.groups(client.rpc(111,self.PAYLOAD,repeat=True),True)),1)
        self.assertEqual(server.state()['revision'],before['revision']+1)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(AuraTests(name) for name in loader.getTestCaseNames(AuraTests) if name.startswith('test_aura_'))


if __name__ == '__main__': unittest.main()
