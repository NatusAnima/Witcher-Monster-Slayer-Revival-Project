"""Operator API acceptance against isolated processes, disposable files and synthetic identities."""
import copy
import concurrent.futures
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import http.server
import importlib.util
import json
import shutil
import socket
import struct
import subprocess
import sys
import threading
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import test_prototype as base
from test_prototype import Server, Client, ROOT, I, Q, Reader

SYNTHETIC_KEY = 'SYNTHETIC_ADMIN_PROXY_KEY_FOR_DISPOSABLE_TESTS_ONLY'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.port = free_port()
        self.origin = f'http://127.0.0.1:{self.port}'
        self.key = self.directory / 'synthetic-proxy.key'
        self.key.write_text(SYNTHETIC_KEY)
        self.key.chmod(0o600)
        self.news = self.directory / 'news'
        self.tasks = self.directory / 'tasks'
        self.world = self.directory / 'world'
        self.world.mkdir()
        (self.world / 'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":12}')
        for name, destination in [('news', self.news), ('tasks', self.tasks)]:
            source = ROOT / 'WitcherRevival.Server' / name
            if not source.exists(): source = Path(__file__).parent / name
            shutil.copytree(source, destination)
        self.admin = self.directory / 'admin'
        self.options = {
            'Admin__Port': str(self.port), 'Admin__Origin': self.origin,
            'Admin__KeyFile': str(self.key), 'Admin__DataDirectory': str(self.admin),
            'News__Directory': str(self.news), 'Tasks__Directory': str(self.tasks),
            'World__Directory': str(self.world), 'LocalProfile__NewProfileMode': 'reconstructed'}
        self.server = Server(self.directory, 'synthetic-admin', self.options)
        self.addCleanup(self.server.stop)
        for _ in range(100):
            try:
                if self.request('overview')[0] == 200: break
            except OSError: time.sleep(.02)
        else: self.fail('admin listener did not become ready')

    def restart(self, **options):
        self.server.stop()
        self.options.update(options)
        self.server = Server(self.directory, 'synthetic-admin', self.options)
        self.addCleanup(self.server.stop)
        for _ in range(100):
            try:
                if self.request('overview')[0] == 200: return
            except OSError: time.sleep(.02)
        self.fail('restarted admin listener did not become ready')

    def request(self, path, method='GET', body=None, auth=True, origin=True, headers=None):
        hdr = {'Content-Type': 'application/json', 'X-Requested-With': 'MonsterSlayerAdmin'}
        if auth: hdr['X-Monster-Admin-Key'] = SYNTHETIC_KEY
        if origin: hdr['Origin'] = self.origin
        hdr.update(headers or {})
        raw = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.origin + '/api/' + path, data=raw, headers=hdr, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def profile(self, name='synthetic-admin'):
        identity = (name + '-device', name + '-account')
        client = Client(self.server, identity=identity)
        self.addCleanup(client.close)
        client.rpc(63)
        # Establish the saved fixture before inspecting it through the operator API.
        self.assertEqual(client.rpc(78, I(0)), b'\1')
        profile = self.server.profile_id(identity)
        self.assertTrue((self.server.directory / 'profiles' / (profile + '.json')).is_file())
        return client, profile

    def offline(self, client, profile):
        client.close()
        for _ in range(100):
            record = next(p for p in self.request('profiles')[1] if p['id'] == profile)
            if record['activeSessions'] == 0: return record
            time.sleep(.01)
        self.fail('synthetic client did not disconnect')

    def test_admin_auth_origin_and_port_separation(self):
        self.assertEqual(self.request('overview', auth=False)[0], 403)
        self.assertEqual(self.request('overview', headers={'X-Monster-Admin-Key': 'wrong'})[0], 403)
        self.assertEqual(self.request('world', 'PUT', {}, origin=False)[0], 403)
        self.assertEqual(self.request('world', 'PUT', {}, headers={'Origin': 'https://invalid.example'})[0], 403)
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.server.get('/api/overview')
        self.assertEqual(rejected.exception.code, 404)
        rejected.exception.close()
        d = self.request('overview')[1]
        self.assertEqual(d['utcReset'], '00:00 UTC')
        self.assertEqual(d['density'], 12)
        request = urllib.request.Request(self.origin+'/', headers={'X-Monster-Admin-Key': SYNTHETIC_KEY})
        with urllib.request.urlopen(request) as response:
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertNotIn(SYNTHETIC_KEY, response.read().decode())

    def test_extended_operator_reads_stay_authenticated_and_do_not_claim_dependency_health(self):
        for endpoint in ('map', 'weather', 'catalogue', 'system', 'server/status', 'news', 'profiles/p'+'0'*31):
            self.assertEqual(self.request(endpoint, auth=False)[0], 403, endpoint)
        self.assertEqual(self.request('weather', 'PUT', {}, origin=False)[0], 403)
        status, system = self.request('system')
        self.assertEqual(status, 200)
        self.assertEqual(system['scope'], 'current-backend-process')
        self.assertGreater(system['memoryBytes'], 0)
        self.assertTrue(any(f['status'] == 'not-probed' for f in system['features']))
        self.assertNotIn(str(self.directory), json.dumps(system))
        self.assertNotIn(SYNTHETIC_KEY, json.dumps(system))

    def test_server_metrics_first_sample_cache_and_process_host_contract(self):
        status, first = self.request('server/status')
        self.assertEqual(status, 200)
        self.assertEqual(first['status'], 'responding')
        self.assertEqual(first['readiness'], {'adminApi': 'responding', 'gameAndDependencies': 'not-probed'})
        self.assertEqual(first['sampleIntervalSeconds'], 2)
        self.assertEqual(first['sampleMode'], 'on-demand-cached')
        sampled = datetime.fromisoformat(first['sampledAt'].replace('Z', '+00:00'))
        self.assertEqual(sampled.utcoffset(), timedelta(0))
        self.assertLess(abs((datetime.now(timezone.utc)-sampled).total_seconds()), 10)
        process = first['process']
        self.assertTrue(process['available'])
        self.assertGreater(process['residentMemoryBytes'], 0)
        self.assertGreaterEqual(process['uptimeSeconds'], 0)
        self.assertGreaterEqual(process['totalCpuSeconds'], 0)
        self.assertEqual(process['cpu']['normalization'], 'one-logical-cpu')
        self.assertEqual(process['cpu']['status'], 'warming-up')
        self.assertFalse(process['cpu']['available'])
        self.assertIsNone(process['cpu']['percent'])
        self.assertIsNone(process['cpu']['windowSeconds'])
        host = first['host']
        self.assertEqual(host['scope'], 'procfs-host-not-cgroup')
        if sys.platform.startswith('linux'):
            self.assertTrue(host['available'])
            self.assertGreaterEqual(host['logicalCpuCount'], 1)
            self.assertEqual(host['cpu']['status'], 'warming-up')
            self.assertEqual(host['cpu']['normalization'], 'all-host-logical-cpus')
            self.assertIsNone(host['cpu']['percent'])
            self.assertGreaterEqual(host['uptimeSeconds'], process['uptimeSeconds'])
            memory = host['memory']
            self.assertTrue(memory['available'])
            self.assertGreater(memory['totalBytes'], 0)
            self.assertEqual(memory['usedBytes'], memory['totalBytes']-memory['availableBytes'])
            self.assertAlmostEqual(memory['usedPercent'], memory['usedBytes']/memory['totalBytes']*100)
            for key in ('one', 'five', 'fifteen'):
                self.assertGreaterEqual(host['load'][key], 0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            reads = list(pool.map(lambda _: self.request('server/status'), range(16)))
        self.assertTrue(all(code == 200 and value == first for code, value in reads))

    def test_server_metrics_delta_window_refresh_and_restart_reset(self):
        first = self.request('server/status')[1]
        time.sleep(2.1)
        second = self.request('server/status')[1]
        self.assertNotEqual(second['sampledAt'], first['sampledAt'])
        process = second['process']
        cpu = process['cpu']
        self.assertEqual(cpu['status'], 'available')
        self.assertTrue(cpu['available'])
        self.assertGreaterEqual(cpu['windowSeconds'], 2)
        self.assertAlmostEqual(cpu['percent'],
            (process['totalCpuSeconds']-first['process']['totalCpuSeconds'])/cpu['windowSeconds']*100)
        self.assertGreaterEqual(process['uptimeSeconds'], first['process']['uptimeSeconds'])
        if sys.platform.startswith('linux'):
            host_cpu = second['host']['cpu']
            self.assertIn(host_cpu['status'], ('available', 'counter-reset'))
            if host_cpu['available']:
                self.assertGreaterEqual(host_cpu['percent'], 0)
                self.assertLessEqual(host_cpu['percent'], 100)
                self.assertEqual(host_cpu['windowSeconds'], cpu['windowSeconds'])
        self.restart()
        fresh = self.request('server/status')[1]
        self.assertEqual(fresh['process']['cpu']['status'], 'warming-up')
        self.assertIsNone(fresh['process']['cpu']['percent'])

    def test_server_metrics_reads_are_private_read_only_and_isolated_from_game_port(self):
        client, profile = self.profile('synthetic-metrics')
        self.offline(client, profile)
        def saved_bytes():
            return {str(p.relative_to(self.directory)): p.read_bytes()
                    for folder in (self.directory/'profiles', self.admin, self.world)
                    for p in folder.rglob('*') if p.is_file()}
        before = saved_bytes()
        first = self.request('server/status')[1]
        payload = json.dumps(first)
        for forbidden in (SYNTHETIC_KEY, str(self.directory), profile, 'synthetic-metrics', socket.gethostname()):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(self.request('server/status', auth=False)[0], 403)
        with self.assertRaises(urllib.error.HTTPError) as absent:
            self.server.get('/api/server/status')
        self.assertEqual(absent.exception.code, 404)
        absent.exception.close()
        for method in ('POST', 'PUT', 'DELETE'):
            request = urllib.request.Request(self.origin+'/api/server/status', data=b'{}', method=method,
                headers={'X-Monster-Admin-Key': SYNTHETIC_KEY, 'Origin': self.origin,
                         'X-Requested-With': 'MonsterSlayerAdmin', 'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(refused.exception.code, 405)
            refused.exception.close()
        self.assertEqual(saved_bytes(), before)
        self.assertEqual(self.request('receipts')[1], [])

    def test_embedded_operator_languages_are_complete_and_authenticated(self):
        languages = ('pl', 'en', 'es', 'fr', 'de', 'uk', 'hu', 'cs', 'sl', 'sk')
        reference = None
        for asset in ['i18n.js', *('lang-' + code + '.json' for code in languages)]:
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(self.origin + '/' + asset, timeout=3)
            self.assertEqual(rejected.exception.code, 403, asset)
            rejected.exception.close()
            request = urllib.request.Request(self.origin + '/' + asset,
                headers={'X-Monster-Admin-Key': SYNTHETIC_KEY})
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertIn('no-store', response.headers['Cache-Control'])
                data = response.read().decode()
                self.assertNotIn(SYNTHETIC_KEY, data)
                if asset.endswith('.json'):
                    self.assertEqual(response.headers.get_content_type(), 'application/json')
                    pack = json.loads(data)
                    self.assertIsInstance(pack, dict)
                    self.assertGreater(len(pack), 600)
                    if reference is None:
                        reference = set(pack)
                        self.assertTrue(all(k == v for k, v in pack.items()))
                    self.assertEqual(set(pack), reference, asset)
                    self.assertTrue(all(isinstance(v, str) and v.strip() for v in pack.values()), asset)
        request = urllib.request.Request(self.origin + '/lang-unsupported.json',
            headers={'X-Monster-Admin-Key': SYNTHETIC_KEY})
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(rejected.exception.code, 404)
        rejected.exception.close()

    def test_world_balance_metadata_reports_scheduled_generation_transition(self):
        at = 4_102_444_800
        self.restart(World__SpawnBalanceFromUnixSeconds=str(at))
        status, data = self.request('world')
        self.assertEqual(status, 200)
        balance = data['spawnBalance']
        self.assertEqual([balance[k] for k in ('common', 'rare', 'legendary')], [88, 18, 3])
        self.assertEqual(balance['fromUnixSeconds'], at)
        self.assertEqual(balance['allNewByUnixSeconds'], at + 1800)
        self.assertEqual(balance['scope'], 'ordinary-shared-world')
        self.assertEqual(balance['speciesWeights'], 'equal-base-with-environmental-boosts')
        self.assertEqual(data['saved']['document'], {'schemaVersion': 1, 'monsterSlotsPerCell': 12})
        # Density writes cannot change the generation boundary or hidden balance fields.
        document = dict(data['saved']['document'], fromUnixSeconds=0)
        status, _ = self.request('world', 'PUT', {'revision': data['saved']['revision'], 'document': document})
        self.assertEqual(status, 400)

    def test_spawn_balance_write_backup_restore_and_restart(self):
        status, original = self.request('world/balance')
        self.assertEqual(status, 200)
        default = {'common': 88, 'rare': 18, 'legendary': 3, 'speciesWeights': {}}
        self.assertEqual(original['saved'], {'revision': 'missing', 'document': default})
        self.assertEqual(original['effective'], default)
        self.assertEqual(original['defaults'], default)
        self.assertEqual(len(original['species']), 139)
        self.assertEqual(original['scope'], 'ordinary-shared-world')
        species = [s['monsterId'] for s in original['species']]
        desired = {'common': 100, 'rare': 7, 'legendary': 1,
                   'speciesWeights': {str(species[0]): 0, str(species[1]): 20, str(species[2]): 1}}
        canonical = copy.deepcopy(desired); del canonical['speciesWeights'][str(species[2])]
        before = int(time.time())
        status, write = self.request('world/balance', 'PUT', {'revision': 'missing', 'document': desired})
        self.assertEqual(status, 200)
        self.assertEqual(write['receipt']['action'], 'spawn-balance')
        self.assertEqual(write['receipt']['outcome'], 'applied')
        saved = self.request('world/balance')[1]
        self.assertEqual(saved['saved']['document'], canonical)
        self.assertGreaterEqual(saved['fromUnixSeconds'], before+1)
        self.assertEqual(saved['allNewByUnixSeconds'], saved['fromUnixSeconds']+1800)
        path = self.world/'spawn-balance.json'
        persisted = json.loads(path.read_text())
        self.assertEqual(persisted['versions'][0], {'fromUnixSeconds': 0, 'rules': default})
        self.assertEqual(persisted['versions'][-1]['rules'], canonical)
        self.assertEqual(write['revision'], hashlib.sha256(path.read_bytes()).hexdigest())
        metadata = self.request('world')[1]['spawnBalance']
        self.assertEqual((metadata['common'], metadata['rare'], metadata['legendary']), (100, 7, 1))
        self.assertEqual(metadata['fromUnixSeconds'], saved['fromUnixSeconds'])
        self.assertEqual(metadata['speciesWeights'], 'operator-multipliers-with-environmental-boosts')
        backup = self.request('receipts/'+write['receipt']['id']+'/backup')[1]
        self.assertEqual(backup['previous']['document'], default)
        self.assertNotIn('versions', backup['previous']['document'])
        unchanged = path.read_bytes()
        self.restart()
        self.assertEqual(path.read_bytes(), unchanged)
        self.assertEqual(self.request('world/balance')[1]['saved'], saved['saved'])
        time.sleep(max(0, saved['fromUnixSeconds']-time.time())+.02)
        self.assertEqual(self.request('world/balance')[1]['effective'], canonical)
        restore = {'revision': saved['saved']['revision'], 'document': backup['previous']['document']}
        status, restored = self.request('world/balance', 'PUT', restore)
        self.assertEqual(status, 200)
        self.assertEqual(self.request('world/balance')[1]['saved']['document'], default)
        timeline = json.loads(path.read_text())['versions']
        self.assertEqual(timeline[:-1], persisted['versions'])
        prior = self.request('receipts/'+restored['receipt']['id']+'/backup')[1]['previous']['document']
        self.assertEqual(prior, canonical)
        self.assertEqual(self.request('world/balance', 'PUT', restore)[0], 409)

    def test_spawn_balance_refuses_invalid_shapes_unknown_species_and_concurrent_writes(self):
        original = self.request('world/balance')[1]
        base_document = original['saved']['document']
        all_disabled = {str(s['monsterId']): 0 for s in original['species']}
        invalid = [{}, dict(base_document, common=-1), dict(base_document, common=10001),
                   dict(base_document, common=0, rare=0, legendary=0), dict(base_document, common=1.5),
                   dict(base_document, speciesWeights=None), dict(base_document, speciesWeights={'999999': 2}),
                   dict(base_document, speciesWeights={'31': -1}), dict(base_document, speciesWeights={'31': 1001}),
                   dict(base_document, speciesWeights={'31': 1.5}), dict(base_document, speciesWeights={'031': 1}),
                   dict(base_document, speciesWeights=all_disabled), dict(base_document, fromUnixSeconds=0)]
        for document in invalid:
            self.assertEqual(self.request('world/balance', 'PUT', {'revision': 'missing', 'document': document})[0], 400, document)
        duplicate = b'{"revision":"missing","document":{"common":88,"rare":18,"legendary":3,"speciesWeights":{"31":0,"31":2}}}'
        self.assertEqual(self.request('world/balance', 'PUT', duplicate)[0], 400)
        self.assertEqual(self.request('world/balance', auth=False)[0], 403)
        self.assertEqual(self.request('world/balance', 'PUT', original['saved'], origin=False)[0], 403)
        self.assertFalse((self.world/'spawn-balance.json').exists())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.request('world/balance', 'PUT', original['saved']), range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        self.assertEqual(len(self.request('receipts')[1]), 1)
        self.assertEqual(self.request('world/balance')[1]['saved']['document'], base_document)

    def test_spawn_balance_respects_pinned_future_activation(self):
        activation = 4_102_444_800
        self.restart(World__SpawnBalanceFromUnixSeconds=str(activation))
        original = self.request('world/balance')[1]
        changed = copy.deepcopy(original['saved']); changed['document']['common'] = 40
        self.assertEqual(self.request('world/balance', 'PUT', changed)[0], 200)
        saved = self.request('world/balance')[1]
        self.assertEqual(saved['fromUnixSeconds'], activation)
        self.assertEqual(saved['effective'], original['effective'])
        self.assertEqual(saved['saved']['document']['common'], 40)
        self.restart()
        self.assertEqual(self.request('world/balance')[1], saved)

    def test_spawn_balance_keeps_served_encounters_across_edit_and_restart(self):
        cells = [0x4704440000000000 + (k << 40) for k in range(3)]
        def response(ids, epoch):
            return {i: dict(center=[10.0, 20.0], places=[dict(id=f'lab-{int(i):016x}-{epoch}-{n}',
                lat=10.0+n/1000, lng=20.0, biomes=[1], kind='path') for n in range(24)]) for i in ids}
        url, _ = base.PrototypeTests.playable_service(self, response)
        self.restart(Playable__Url=url)
        client, _ = self.profile('synthetic-balance-map')
        query = I(3)+b''.join(Q(c) for c in cells)
        before = base.PrototypeTests.locations_by_cell(client.rpc(40, query))['monsters']
        saved = self.request('world/balance')[1]['saved']
        saved['document'] = dict(saved['document'], common=1, rare=0, legendary=0,
            speciesWeights={str(m['monster']): 0 for m in before})
        self.assertEqual(self.request('world/balance', 'PUT', saved)[0], 200)
        for restarted in (False, True):
            if restarted:
                self.restart(); client, _ = self.profile('synthetic-balance-map')
            after = base.PrototypeTests.locations_by_cell(client.rpc(40, query))['monsters']
            for monster in before:
                if monster['spawn_ms']/1000+monster['ttl'] > time.time()+1:
                    self.assertIn(monster, after)

    def test_catalogue_matches_active_compressed_client_data(self):
        status, data = self.request('catalogue')
        self.assertEqual(status, 200)
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata') as response:
            wire = response.read()
        self.assertEqual(data['revision'], hashlib.sha256(wire).hexdigest())
        tables = json.loads(gzip.decompress(wire))
        self.assertEqual({t['name']: t['rows'] for t in data['tables']}, tables)
        self.assertTrue(all(t['count'] == len(t['rows']) for t in data['tables']))
        self.assertEqual(len(data['bestiary']), 139)
        self.assertTrue(data['readOnly'])
        self.assertEqual(data['source'], 'active-static-catalogue')

    def test_profile_details_and_social_counts_are_read_only_without_private_bindings(self):
        client, profile = self.profile('synthetic-detail')
        path = self.directory/'profiles'/(profile+'.json')
        before = path.read_bytes()
        status, detail = self.request('profiles/'+profile)
        self.assertEqual(status, 200)
        self.assertEqual(detail['summary']['id'], profile)
        self.assertIn('inventory', detail)
        self.assertEqual(detail['social']['registered'], False)
        self.assertEqual(detail['social']['friends'], 0)
        self.assertFalse((self.directory/'profiles'/'social.json').exists())
        self.assertEqual(path.read_bytes(), before)
        encoded = json.dumps(detail).lower()
        for private in ('synthetic-detail-device', 'synthetic-detail-account', 'requestid', 'longitude', 'latitude', 'storyplaces'):
            self.assertNotIn(private, encoded)
        own = Reader(client.rpc(102)).long()
        other, other_profile = self.profile('synthetic-social-other')
        other_id = Reader(other.rpc(102)).long()
        self.assertEqual(client.rpc(103, Q(other_id)), b'\1'+Q(other_id))
        social_path = self.directory/'profiles'/'social.json'
        social_before = social_path.read_bytes()
        sent = self.request('profiles/'+profile)[1]['social']
        received = self.request('profiles/'+other_profile)[1]['social']
        self.assertEqual((sent['invitationsSent'], received['invitationsReceived']), (1, 1))
        self.assertEqual(social_path.read_bytes(), social_before)
        self.assertEqual(other.rpc(104, Q(own)), b'\1'+Q(own))
        self.assertEqual(self.request('profiles/'+profile)[1]['social']['friends'], 1)
        self.assertNotIn(str(own), json.dumps(self.request('profiles/'+profile)[1]['social']))
        self.assertEqual(self.request('profiles/p'+'0'*31)[0], 404)

    def test_profile_label_saves_online_restores_and_survives_restart_without_game_changes(self):
        client, profile = self.profile('synthetic-label')
        route = 'profiles/'+profile+'/label'
        initial = self.request(route)[1]
        self.assertEqual(initial, {'revision': 'missing', 'document': {'label': ''}})
        def game_files():
            return {p.name: p.read_bytes() for p in (self.directory/'profiles').iterdir() if p.is_file()}
        before = game_files()
        status, saved = self.request(route, 'PUT', {'revision': initial['revision'], 'document': {'label': '  Telefon próbny  '}})
        self.assertEqual(status, 200)
        self.assertEqual((saved['receipt']['action'], saved['receipt']['target'], saved['receipt']['outcome']),
                         ('profile-label', profile, 'applied'))
        current = self.request(route)[1]
        self.assertEqual(current['document'], {'label': 'Telefon próbny'})
        summary = self.request('profiles/'+profile)[1]['summary']
        self.assertEqual(summary['label'], 'Telefon próbny')
        self.assertEqual(summary['activeSessions'], 1)
        self.assertEqual((summary['identityKind'], summary['deviceCount']), ('account', 1))
        self.assertEqual(next(p for p in self.request('profiles')[1] if p['id'] == profile)['label'], 'Telefon próbny')
        backup = self.request('receipts/'+saved['receipt']['id']+'/backup')[1]
        self.assertEqual(backup['previous']['document'], {'label': ''})
        path = self.admin/'profile-labels'/(profile+'.json')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(game_files(), before)
        client.close()
        self.restart()
        self.assertEqual(self.request(route)[1], current)
        self.assertEqual(self.request(route, 'PUT', {'revision': current['revision'],
                         'document': backup['previous']['document']})[0], 200)
        self.assertEqual(self.request('profiles/'+profile)[1]['summary']['label'], '')
        self.assertEqual(game_files(), before)

    def test_profile_labels_refuse_invalid_unauthorized_and_stale_writes(self):
        _, profile = self.profile('synthetic-label-guards')
        route = 'profiles/'+profile+'/label'
        initial = self.request(route)[1]
        self.assertEqual(self.request(route, auth=False)[0], 403)
        for document in ({}, {'label': None}, {'label': 4}, {'label': 'a'*65},
                         {'label': 'a\nb'}, {'label': 'a\0b'}, {'label': 'a', 'profile': profile}):
            self.assertEqual(self.request(route, 'PUT', {'revision': 'missing', 'document': document})[0], 400)
        duplicate = b'{"revision":"missing","document":{"label":"one","label":"two"}}'
        self.assertEqual(self.request(route, 'PUT', duplicate)[0], 400)
        self.assertEqual(self.request(route, 'PUT', initial, origin=False)[0], 403)
        self.assertEqual(self.request(route, 'PUT', initial, auth=False)[0], 403)
        self.assertEqual(self.request('profiles/p'+'0'*31+'/label')[0], 404)
        self.assertEqual(self.request('profiles/invalid!/label', 'PUT', initial)[0], 400)
        self.assertEqual(list((self.admin/'profile-labels').iterdir()), [])
        self.assertEqual(self.request('receipts')[1], [])
        first = self.request(route, 'PUT', {'revision': 'missing', 'document': {'label': 'x'*64}})
        self.assertEqual(first[0], 200)
        self.assertEqual(self.request(route, 'PUT', initial)[0], 409)
        self.assertEqual(self.request(route)[1]['document'], {'label': 'x'*64})

    def test_profile_label_concurrency_is_scoped_to_operator_metadata(self):
        _, profile = self.profile('synthetic-label-race')
        _, other = self.profile('synthetic-label-other')
        route = 'profiles/'+profile+'/label'
        paths = list((self.directory/'profiles').iterdir())
        before = {p.name: p.read_bytes() for p in paths if p.is_file()}
        def save(label):
            return self.request(route, 'PUT', {'revision': 'missing', 'document': {'label': label}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['first', 'second']))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        self.assertIn(self.request(route)[1]['document']['label'], ['first', 'second'])
        self.assertEqual(self.request('profiles/'+other+'/label')[1], {'revision': 'missing', 'document': {'label': ''}})
        self.assertEqual(len(self.request('receipts')[1]), 1)
        self.assertEqual({p.name: p.read_bytes() for p in paths if p.is_file()}, before)

    def test_profile_identity_summary_follows_guest_account_rules_without_exposing_keys(self):
        def enter(device, account):
            client = Client(self.server, identity=(device, account))
            self.addCleanup(client.close)
            self.assertEqual(client.rpc(78, I(0)), b'\1')
            return self.server.profile_id((device, account))
        def summary(profile): return self.request('profiles/'+profile)[1]['summary']
        first = enter('synthetic-identity-first', '')
        second = enter('synthetic-identity-second', '')
        self.assertNotEqual(first, second)
        self.assertEqual((summary(first)['identityKind'], summary(first)['deviceCount']), ('guest', 1))
        account = enter('synthetic-identity-first', 'synthetic-shared-account')
        self.assertEqual(account, first)
        self.assertEqual(enter('synthetic-identity-second', 'synthetic-shared-account'), first)
        self.assertEqual((summary(first)['identityKind'], summary(first)['deviceCount']), ('account', 2))
        self.assertEqual((summary(second)['identityKind'], summary(second)['deviceCount']), ('guest', 1))
        fresh = enter('synthetic-identity-first', '')
        self.assertNotEqual(first, fresh)
        self.assertEqual((summary(fresh)['identityKind'], summary(fresh)['deviceCount']), ('guest', 1))
        index_path = self.directory/'profiles'/'players.json'
        before = index_path.read_bytes()
        public = json.dumps(self.request('profiles')[1])
        private = json.loads(before)
        for value in (*private['Devices'], *private['Accounts'], 'synthetic-identity-first',
                      'synthetic-identity-second', 'synthetic-shared-account'):
            self.assertNotIn(value, public)
        self.assertEqual(index_path.read_bytes(), before)

    def test_weather_override_expires_without_mislabeling_last_answer_and_can_be_reverted(self):
        client, _ = self.profile('synthetic-weather')
        point = struct.pack('>ff', 10.1, 20.2)
        initial = self.request('weather')[1]
        self.assertEqual(initial['saved']['revision'], 'missing')
        self.assertIsNone(initial['effective']['lastAnswered'])
        expires = datetime.now(timezone.utc) + timedelta(seconds=4)
        write = {'revision': 'missing', 'document': {'schemaVersion': 1, 'mode': 'manual', 'code': 3, 'expiresAt': expires.isoformat()}}
        status, receipt = self.request('weather', 'PUT', write)
        self.assertEqual(status, 200)
        self.assertEqual(receipt['receipt']['target'], 'global-weather')
        time.sleep(1.05)
        self.assertEqual(client.rpc(67, point), I(3))
        observed = self.request('weather')[1]['effective']['lastAnswered']
        self.assertEqual((observed['code'], observed['source'], observed['valueStatus']), (3, 'manual', 'override'))
        self.assertEqual(self.request('weather', 'PUT', write)[0], 409)
        time.sleep(max(0, (expires-datetime.now(timezone.utc)).total_seconds()) + .06)
        expired = self.request('weather')[1]
        self.assertEqual(expired['saved']['document']['mode'], 'manual')
        self.assertEqual(expired['effective']['mode'], 'automatic')
        self.assertFalse(expired['effective']['overrideActive'])
        self.assertEqual(expired['effective']['lastAnswered'], observed)
        self.assertEqual(expired['effective']['valueStatus'], 'fallback')
        self.assertEqual(client.rpc(67, point), I(6))
        fallback = self.request('weather')[1]['effective']['lastAnswered']
        self.assertEqual((fallback['code'], fallback['source']), (6, 'clear-fallback'))
        automatic = dict(expired['saved'], document={'schemaVersion': 1, 'mode': 'automatic', 'code': None, 'expiresAt': None})
        status, result = self.request('weather', 'PUT', automatic)
        self.assertEqual(status, 200)
        backup = self.request('receipts/'+result['receipt']['id']+'/backup')[1]
        restored_document = backup['previous']['document']
        self.assertEqual((restored_document['mode'], restored_document['code']), ('manual', 3))
        self.assertEqual(datetime.fromisoformat(restored_document['expiresAt']), expires)

    def test_weather_observation_provenance_follows_its_cell_and_automatic_is_not_a_new_measurement(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                failed = 'latitude=20.1' in self.path
                body = json.dumps({'current': {'weather_code': 61}}).encode()
                self.send_response(503 if failed else 200)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        fake = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.server_close); self.addCleanup(fake.shutdown)
        self.restart(Weather__Url=f'http://127.0.0.1:{fake.server_port}/weather')
        self.assertIsNone(self.request('weather')[1]['effective']['code'])
        self.assertEqual(requests, [])
        client, _ = self.profile('synthetic-provider')
        good = struct.pack('>ff', 10.1, 30.0); failed = struct.pack('>ff', 20.1, 30.0)
        self.assertEqual(client.rpc(67, good), I(3))
        first = self.request('weather')[1]['effective']['lastAnswered']
        self.assertEqual(first['valueStatus'], 'observed')
        self.assertIsNotNone(first['dataAt'])
        self.assertEqual(client.rpc(67, failed), I(6))
        fallback = self.request('weather')[1]['effective']['lastAnswered']
        self.assertEqual((fallback['source'], fallback['valueStatus'], fallback['dataAt']), ('clear-fallback', 'fallback', None))
        self.assertEqual(client.rpc(67, good), I(3))
        status = self.request('weather')[1]['effective']
        self.assertEqual(status['lastFetchOutcome'], 'failed-clear-fallback')
        self.assertEqual(status['lastAnswered']['valueStatus'], 'cached')
        self.assertEqual(status['lastAnswered']['dataAt'], first['dataAt'])
        write = self.request('weather')[1]['saved']
        write['document'] = {'schemaVersion': 1, 'mode': 'manual', 'code': 4,
            'expiresAt': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        self.assertEqual(self.request('weather', 'PUT', write)[0], 200)
        time.sleep(1.05)
        self.assertEqual(client.rpc(67, good), I(4))
        prior = self.request('weather')[1]['effective']['lastAnswered']
        write = self.request('weather')[1]['saved']
        write['document'] = {'schemaVersion': 1, 'mode': 'automatic', 'code': None, 'expiresAt': None}
        self.assertEqual(self.request('weather', 'PUT', write)[0], 200)
        time.sleep(1.05)
        automatic = self.request('weather')[1]['effective']
        self.assertEqual(automatic['mode'], 'automatic')
        self.assertIsNone(automatic['code'])
        self.assertEqual(automatic['lastAnswered'], prior)
        self.assertEqual(len(requests), 2)
        self.assertEqual(client.rpc(67, good), I(3))
        self.assertEqual(self.request('weather')[1]['effective']['lastAnswered']['source'], 'open-meteo-cache')

    def test_weather_rejects_unbounded_invalid_and_stale_mutations(self):
        base = {'schemaVersion': 1, 'mode': 'manual', 'code': 4, 'expiresAt': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        invalid = [dict(base, code=8), dict(base, expiresAt=None), dict(base, mode='automatic'),
                   dict(base, expiresAt=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()),
                   dict(base, expiresAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()), dict(base, extra=True)]
        for document in invalid:
            self.assertEqual(self.request('weather', 'PUT', {'revision': 'missing', 'document': document})[0], 400)
        self.assertFalse((self.world/'weather.json').exists())
        good = {'revision': 'missing', 'document': base}
        self.assertEqual(self.request('weather', 'PUT', good)[0], 200)
        self.restart()
        self.assertEqual(self.request('weather')[1]['effective']['mode'], 'manual')
        before = (self.world/'weather.json').read_bytes()
        self.assertEqual(self.request('weather', 'PUT', dict(good, revision='wrong'))[0], 409)
        self.assertEqual((self.world/'weather.json').read_bytes(), before)

    def test_map_observes_sent_cells_without_fetching_or_changing_profiles(self):
        cells = [0x4704440000000000 + (k << 40) for k in range(3)]
        def response(ids, epoch):
            return {i: dict(center=[10.0, 20.0], places=[dict(id=f'lab-{int(i):016x}-{epoch}-{n}',
                lat=10.0+n/1000, lng=20.0, biomes=[10], kind='path') for n in range(24)]) for i in ids}
        url, requests = base.PrototypeTests.playable_service(self, response)
        self.restart(Playable__Url=url)
        client, profile = self.profile('synthetic-map')
        self.assertEqual(self.request('map')[0], 400)
        self.assertEqual(self.request('map?profile=p'+'0'*31)[0], 404)
        self.assertEqual(self.request('map?profile='+profile)[1]['status'], 'empty')
        self.assertEqual(requests, [])
        wire = base.PrototypeTests.locations_by_cell(client.rpc(40, I(3)+b''.join(Q(c) for c in cells)))
        client.rpc(78, I(0))  # Ensure the completed map observation precedes these read-only checks.
        path = self.directory/'profiles'/(profile+'.json')
        before = path.read_bytes(); request_count = len(requests)
        status, view = self.request('map?profile='+profile)
        self.assertEqual(status, 200)
        self.assertEqual(view['status'], 'ready')
        self.assertEqual(view['scope'], 'last-client-map-response')
        self.assertEqual({c['id'] for c in view['cells']}, {str(c) for c in cells})
        self.assertEqual(view['counts']['monsters'], len(wire['monsters']))
        self.assertEqual({p['id'] for p in view['points'] if p['kind']=='monster'}, {str(m['instance']) for m in wire['monsters']})
        self.assertFalse(view['truncated'])
        self.assertEqual(view, self.request('map?profile='+profile)[1] | {'ageSeconds': view['ageSeconds']})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(requests), request_count)
        client.rpc(40, I(0)); client.rpc(78, I(0))
        self.assertEqual(self.request('map?profile='+profile)[1]['observedAt'], view['observedAt'])
        # A global override must not redraw the generations that have already been used.
        write = self.request('weather')[1]['saved']
        write['document'] = {'schemaVersion': 1, 'mode': 'manual', 'code': 5,
            'expiresAt': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        self.assertEqual(self.request('weather', 'PUT', write)[0], 200)
        time.sleep(1.05)
        after = base.PrototypeTests.locations_by_cell(client.rpc(40, I(3)+b''.join(Q(c) for c in cells)))
        for monster in wire['monsters']:
            if monster['spawn_ms']/1000+monster['ttl'] > time.time()+1:
                self.assertIn(monster, after['monsters'])
        self.restart()
        self.assertEqual(self.request('map?profile='+profile)[1]['status'], 'empty')

    def test_news_language_creation_and_backup_preview_require_normal_write_revision(self):
        index = self.request('news')[1]
        self.assertIn('pl', index['languages'])
        pending = self.request('news/cs')[1]
        self.assertEqual(pending['revision'], 'missing')
        self.assertEqual(self.request('news/cs', 'PUT', pending)[0], 200)
        self.assertIn('cs', self.request('news')[1]['languages'])
        prior = self.request('news/pl')[1]
        changed = copy.deepcopy(prior); changed['document']['news_list'][0]['title'] = 'Synthetic replacement'
        result = self.request('news/pl', 'PUT', changed)[1]
        status, backup = self.request('receipts/'+result['receipt']['id']+'/backup')
        self.assertEqual(status, 200)
        self.assertEqual(backup['previous']['document'], prior['document'])
        self.assertEqual(self.request('news/pl')[1]['document']['news_list'][0]['title'], 'Synthetic replacement')
        self.assertEqual(self.request('receipts/not-a-receipt/backup')[0], 400)

    def test_news_validation_identifies_entry_and_field_without_mutating_feed(self):
        original = self.request('news/pl')[1]
        before = (self.news / 'pl.json').read_bytes()
        document = copy.deepcopy(original)
        entry = copy.deepcopy(document['document']['news_list'][0])
        entry.update(id=entry['id'], title='   ', content='\t', date='31/02/2026',
                     group_id='bad;group', image_url='folder/private-picture.png')
        document['document']['news_list'].append(entry)
        document['document']['featured'] = 2147483647
        status, result = self.request('news/pl', 'PUT', document)
        self.assertEqual(status, 400)
        self.assertEqual(result['error'], 'news_validation')
        index = len(document['document']['news_list']) - 1
        fields = {item['field']: item['code'] for item in result['fields']}
        for field, code in [('id', 'unique_positive_id'), ('title', 'required_text'),
                            ('content', 'required_text'), ('date', 'calendar_date'),
                            ('group_id', 'group_format'), ('image_url', 'image_format')]:
            self.assertEqual(fields[f'news_list[{index}].{field}'], code)
        self.assertEqual(fields['featured'], 'featured_missing')
        self.assertNotIn('private-picture', json.dumps(result))
        self.assertEqual((self.news / 'pl.json').read_bytes(), before)
        self.assertFalse(list((self.admin / 'receipts').glob('*.json')))

    def test_news_schema_and_missing_cover_have_actionable_errors(self):
        original = self.request('news/pl')[1]
        for field, value, code in [('title', None, 'text_required'), ('id', 1.5, 'integer_required')]:
            document = copy.deepcopy(original)
            document['document']['news_list'][0][field] = value
            status, result = self.request('news/pl', 'PUT', document)
            self.assertEqual(status, 400)
            self.assertIn({'field': f'news_list[0].{field}', 'code': code}, result['fields'])
        document = copy.deepcopy(original)
        document['document']['news_list'][0]['image_url'] = 'not-uploaded.png'
        status, result = self.request('news/pl', 'PUT', document)
        self.assertEqual(status, 400)
        self.assertIn({'field': 'news_list[0].image_url', 'code': 'image_missing'}, result['fields'])
        del document['document']['news_list'][0]['content']
        status, result = self.request('news/pl', 'PUT', document)
        self.assertEqual(status, 400)
        self.assertIn({'field': 'news_list[0].content', 'code': 'text_required'}, result['fields'])
        document = copy.deepcopy(original)
        document['document']['news_list'][0]['image_url'] = ''
        self.assertEqual(self.request('news/pl', 'PUT', document)[0], 200)

    def test_news_size_limit_applies_to_canonical_saved_feed(self):
        document = {'revision': 'missing', 'document': {'featured': 1, 'news_list': [{
            'id': 1, 'group_id': 'news-1', 'title': 'Synthetic', 'short_description': '',
            'date': '04/10/2026', 'image_url': '', 'content': ''}]}}
        encode = lambda: json.dumps(document, separators=(',', ':')).encode()
        document['document']['news_list'][0]['content'] = 'a' * (1024 * 1024 - len(encode()) - 1)
        self.assertEqual(len(encode()), 1024 * 1024 - 1)
        status, result = self.request('news/xx', 'PUT', encode())
        self.assertEqual(status, 400)
        self.assertEqual(result, {'error': 'news_validation', 'fields': [{'field': 'document', 'code': 'feed_size'}]})
        self.assertFalse((self.news / 'xx.json').exists())
        document['document']['news_list'][0]['content'] += 'a' * 100
        self.assertEqual(self.request('news/xx', 'PUT', encode())[1]['fields'][0]['code'], 'feed_size')

    def test_news_validated_write_backup_receipt_and_stale_retry(self):
        document = self.request('news/pl')[1]
        before = (self.news/'pl.json').read_bytes()
        document['document']['news_list'][0]['title'] = 'Synthetic operator update'
        status, result = self.request('news/pl', 'PUT', document)
        self.assertEqual(status, 200)
        self.assertEqual(result['receipt']['outcome'], 'applied')
        self.assertEqual((self.admin/'backups'/(result['receipt']['id']+'.bin')).read_bytes(), before)
        self.assertEqual(self.server.get('/news/pl')['news_list'][0]['title'], 'Synthetic operator update')
        self.assertEqual(self.request('news/pl', 'PUT', document)[0], 409)
        document = self.request('news/pl')[1]
        document['document']['news_list'][0]['date'] = '31/02/2026'
        self.assertEqual(self.request('news/pl', 'PUT', document)[0], 400)
        self.assertEqual(self.server.get('/news/pl')['news_list'][0]['title'], 'Synthetic operator update')
        receipt = self.request('receipts')[1][0]
        self.assertNotIn('Synthetic operator update', json.dumps(receipt))

    def test_news_images_require_safe_names_dimensions_and_version(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/news/images/default.png') as r:
            png = r.read()
        status, result = self.request('images/synthetic.png', 'PUT', png, headers={'If-Match':'missing'})
        self.assertEqual(status, 200)
        self.assertEqual(self.request('images')[1], ['synthetic.png'])
        self.assertEqual(self.request('images/synthetic.png', 'PUT', png, headers={'If-Match':'missing'})[0], 409)
        self.assertEqual(self.request('images/invalid.png', 'PUT', b'not an image', headers={'If-Match':'missing'})[0], 400)
        self.assertFalse((self.news/'images'/'invalid.png').exists())

    def test_world_hot_reload_validation_and_compare_exchange(self):
        document = self.request('world')[1]['saved']
        document['document']['monsterSlotsPerCell'] = 18
        self.assertEqual(self.request('world', 'PUT', document)[0], 200)
        time.sleep(1.05)
        self.assertEqual(self.request('world')[1]['effective']['monsterSlotsPerCell'], 18)
        self.assertEqual(self.request('world', 'PUT', document)[0], 409)
        document = self.request('world')[1]['saved']
        document['document']['monsterSlotsPerCell'] = 19
        self.assertEqual(self.request('world', 'PUT', document)[0], 400)
        self.assertEqual(self.request('world')[1]['effective']['monsterSlotsPerCell'], 18)

    def test_task_rotation_live_rejects_static_mutation_and_stages_append(self):
        document = self.request('tasks')[1]
        daily = document['daily']
        daily['document']['tasks'][0]['weight'] = 5
        self.assertEqual(self.request('tasks/daily', 'PUT', daily)[0], 200)
        time.sleep(1.05)
        data = self.request('tasks')[1]
        self.assertEqual(data['daily']['document']['tasks'][0]['weight'], 5)
        invalid = copy.deepcopy(data['daily'])
        invalid['document']['tasks'][0]['target'] += 1
        self.assertEqual(self.request('tasks/daily', 'PUT', invalid)[0], 409)
        invalid = copy.deepcopy(data['daily'])
        for task in invalid['document']['tasks']: task['weight'] = 0
        self.assertEqual(self.request('tasks/daily', 'PUT', invalid)[0], 400)
        candidate = data['catalogue']
        entry = copy.deepcopy(candidate['document']['daily']['tasks'][0])
        entry.update(id=19001, slug='synthetic_new_task')
        candidate['document']['daily']['tasks'].append(entry)
        status, result = self.request('tasks/staged', 'PUT', candidate)
        self.assertEqual(status, 200)
        self.assertEqual(result['receipt']['outcome'], 'staged')
        self.assertNotIn(19001, [t['id'] for t in json.loads((self.tasks/'daily.json').read_text())['tasks']])

    def test_staged_catalogue_applier_refuses_live_game_then_applies_offline(self):
        document = self.request('tasks')[1]['catalogue']
        added = copy.deepcopy(document['document']['daily']['tasks'][0])
        added.update(id=19002, slug='synthetic_maintenance_task')
        document['document']['daily']['tasks'].append(added)
        status, result = self.request('tasks/staged', 'PUT', document)
        self.assertEqual(status, 200)
        operation = result['receipt']['id']
        source = ROOT/'WitcherRevival.Server'/'Admin'/'apply_staged_tasks.py'
        if not source.exists(): source = Path(__file__).with_name('apply_staged_tasks.py')
        spec = importlib.util.spec_from_file_location('apply_staged_tasks', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        before = (self.tasks/'daily.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Stop the task-enabled game'):
            module.apply(self.admin, self.tasks, self.directory/'profiles', operation)
        self.assertEqual((self.tasks/'daily.json').read_bytes(), before)
        self.server.stop()
        applied = module.apply(self.admin, self.tasks, self.directory/'profiles', operation)
        self.assertEqual(applied['status'], 'applied')
        self.assertIn(19002, [t['id'] for t in json.loads((self.tasks/'daily.json').read_text())['tasks']])
        self.assertEqual((self.admin/'backups'/(operation+'-tasks')/'daily.json').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'not an unapplied'):
            module.apply(self.admin, self.tasks, self.directory/'profiles', operation)

    def test_profile_reset_requires_offline_confirmation_and_revision_preserves_identity(self):
        client, profile = self.profile()
        records = self.request('profiles')[1]
        record = next(p for p in records if p['id']==profile)
        identity_before = (self.directory/'profiles'/'players.json').read_bytes()
        key_before = hashlib.sha256((self.directory/'profiles'/'identity.key').read_bytes()).hexdigest()
        body = {'action':'reset', 'revision':record['revision'], 'confirm':profile}
        self.assertEqual(self.request('profiles/'+profile, 'POST', body)[0], 409)
        record = self.offline(client, profile)
        body['revision'] = record['revision']
        self.assertEqual(self.request('profiles/'+profile, 'POST', dict(body, confirm='different'))[0], 400)
        self.assertEqual(self.request('profiles/'+profile, 'POST', dict(body, revision=-1))[0], 409)
        status, result = self.request('profiles/'+profile, 'POST', body)
        self.assertEqual(status, 200)
        self.assertEqual(result['profile']['revision'], record['revision']+1)
        self.assertEqual((self.directory/'profiles'/'players.json').read_bytes(), identity_before)
        self.assertEqual(hashlib.sha256((self.directory/'profiles'/'identity.key').read_bytes()).hexdigest(),key_before)
        backup = self.admin/'backups'/(result['receipt']['id']+'.profile.json')
        self.assertEqual(json.loads(backup.read_text())['ProfileId'], profile)
        self.assertEqual(self.request('profiles/'+profile, 'POST', body)[0], 409)

    def test_profile_backup_restore_is_bound_to_target_and_current_revision(self):
        client, profile = self.profile('synthetic-recovery')
        other_client, other = self.profile('synthetic-other')
        record = self.offline(client, profile)
        other_record = self.offline(other_client, other)
        status, changed = self.request('profiles/'+profile, 'POST',
            {'action':'clock','revision':record['revision'],'confirm':profile,'seconds':3600})
        self.assertEqual(status,200)
        body={'action':'restore','revision':changed['profile']['revision'],'confirm':profile,'backup':changed['receipt']['id']}
        self.assertEqual(self.request('profiles/'+other,'POST',dict(body,confirm=other,revision=other_record['revision']))[0],409)
        self.assertEqual(self.request('profiles/'+profile,'POST',dict(body,revision=-1))[0],409)
        status,restored=self.request('profiles/'+profile,'POST',body)
        self.assertEqual(status,200)
        self.assertEqual(restored['profile']['storyClockSeconds'],0)
        self.assertEqual(restored['profile']['revision'],changed['profile']['revision']+1)
        saved=json.loads((self.admin/'backups'/(restored['receipt']['id']+'.profile.json')).read_text())
        self.assertEqual(saved['Player']['Story']['Clock'],3600)

    def test_profile_copy_keeps_source_and_bindings_and_refuses_connected_source(self):
        client, target = self.profile('synthetic-target')
        source_client, source = self.profile('synthetic-source')
        target_record = self.offline(client, target)
        source_record = next(p for p in self.request('profiles')[1] if p['id']==source)
        body={'action':'copy','revision':target_record['revision'],'confirm':target,'source':source,'sourceRevision':source_record['revision']}
        self.assertEqual(self.request('profiles/'+target,'POST',body)[0],409)
        source_record=self.offline(source_client,source)
        status,result=self.request('profiles/'+source,'POST',{'action':'clock','revision':source_record['revision'],'confirm':source,'seconds':3600})
        self.assertEqual(status,200)
        body['sourceRevision']=result['profile']['revision']
        source_before=(self.directory/'profiles'/(source+'.json')).read_bytes()
        index_before=(self.directory/'profiles'/'players.json').read_bytes()
        status,result=self.request('profiles/'+target,'POST',body)
        self.assertEqual(status,200)
        self.assertEqual(result['profile']['storyClockSeconds'],3600)
        self.assertEqual((self.directory/'profiles'/(source+'.json')).read_bytes(),source_before)
        self.assertEqual((self.directory/'profiles'/'players.json').read_bytes(),index_before)
        source_state=json.loads(source_before);target_state=json.loads((self.directory/'profiles'/(target+'.json')).read_bytes())
        self.assertEqual(source_state['Player'],target_state['Player'])
        self.assertNotEqual(source_state['ProfileId'],target_state['ProfileId'])


    def test_distance_policy_receipt_guard_activation_and_read_only_profile_scope(self):
        from test_distance import movement_hello, movement_ack, movement_batch, movement_fix
        client,profile=self.profile(); other,other_id=self.profile('synthetic-gps-other')
        path='profiles/'+profile+'/distance'
        untouched=(self.directory/'profiles'/(profile+'.json')).read_bytes()
        state=self.request(path)[1]
        self.assertEqual((state['profileId'],state['mode'],state['quality']['status']),(profile,'legacy','not-observed'))
        self.assertIsNone(state['lastFix']);self.assertFalse(state['coverage']['positionAvailable'])
        self.assertEqual(self.request(path,auth=False)[0],403)
        self.assertEqual(self.request('profiles/unknown/distance')[0],404)
        self.assertEqual((self.directory/'profiles'/(profile+'.json')).read_bytes(),untouched)
        default=self.request('distance-policy')[1]
        self.assertEqual(default['document'],{'mode':'shadow'})
        self.assertEqual(default['appliesOn'],'new-hello')
        self.assertTrue(default['protectedProfilesRemainProtected'])
        hello=movement_hello();first=movement_ack(client.rpc(2001,hello));hello_id=client.sequence
        self.assertEqual(self.request(path)[1]['mode'],'shadow')
        for bad in [{'mode':'legacy'},{'mode':'protected','extra':1},{'mode':None},{}]:
            self.assertEqual(self.request('distance-policy','PUT',{'revision':'missing','document':bad})[0],400)
        write={'revision':default['revision'],'document':{'mode':'protected'}}
        status,saved=self.request('distance-policy','PUT',write);self.assertEqual(status,200)
        self.assertEqual(saved['receipt']['action'],'distance-policy')
        self.assertEqual(self.request('distance-policy','PUT',write)[0],409)
        prior=self.request('receipts/'+saved['receipt']['id']+'/backup')[1]
        self.assertEqual(prior['previous']['document'],{'mode':'shadow'})
        client.sequence=hello_id
        self.assertEqual(movement_ack(client.rpc(2001,hello,repeat=True))['mode'],0)
        fresh=movement_hello();current=movement_ack(client.rpc(2001,fresh))
        self.assertEqual(current['mode'],1)
        utc=struct.unpack('>q',fresh[-8:])[0]
        batch=movement_batch(current['epoch'],1,[movement_fix(utc,100000,0,flags=5)])
        self.assertEqual(movement_ack(client.rpc(2001,batch))['status'],0)
        untouched=(self.directory/'profiles'/(profile+'.json')).read_bytes()
        view=self.request(path)[1]
        self.assertEqual(view['mode'],'protected');self.assertEqual(view['quality']['status'],'acquiring')
        self.assertEqual(view['lastFix']['lat'],0);self.assertEqual(view['lastFix']['lng'],0)
        self.assertIsNone(self.request('profiles/'+other_id+'/distance')[1]['lastFix'])
        self.assertEqual((self.directory/'profiles'/(profile+'.json')).read_bytes(),untouched)
        reset={'revision':saved['revision'],'document':prior['previous']['document']}
        self.assertEqual(self.request('distance-policy','PUT',reset)[0],200)
        self.assertEqual(movement_ack(client.rpc(2001,movement_hello()))['mode'],1)
        self.assertEqual(client.rpc(27,I(999)),b'\0'+I(0))
        self.restart()
        retained=self.request(path)[1]
        self.assertEqual(retained['mode'],'protected');self.assertIsNone(retained['lastFix'])
        self.assertFalse(retained['capability']['sessionActive'])
        self.assertEqual(self.request('distance-policy')[1]['document'],{'mode':'shadow'})

    def test_distance_protection_survives_progress_reset_restore_and_copy_with_rebase(self):
        from test_distance import movement_hello, movement_ack, movement_batch, movement_fix
        client,target=self.profile();source_client,source=self.profile('synthetic-gps-source')
        client.rpc(27,I(123));source_client.rpc(27,I(456))
        self.assertEqual(self.request('distance-policy','PUT',{'revision':'missing','document':{'mode':'protected'}})[0],200)
        hello=movement_hello();ack=movement_ack(client.rpc(2001,hello));utc=struct.unpack('>q',hello[-8:])[0]
        oldbatch=movement_batch(ack['epoch'],1,[movement_fix(utc,100000,0,flags=5)])
        client.rpc(2001,oldbatch)
        target_record=self.offline(client,target);source_record=self.offline(source_client,source)
        code,reset=self.request('profiles/'+target,'POST',{'action':'reset','revision':target_record['revision'],'confirm':target})
        self.assertEqual(code,200)
        status=self.request('profiles/'+target+'/distance')[1]
        self.assertEqual((status['mode'],status['totals']['metres'],status['totals']['legacyBaselineMetres'],status['totals']['acceptedMetresSinceProtection']),('protected',0,0,0))
        self.assertIsNotNone(status['totals']['rebasedAt'])
        code,restored=self.request('profiles/'+target,'POST',{'action':'restore','revision':reset['profile']['revision'],'confirm':target,'backup':reset['receipt']['id']})
        self.assertEqual(code,200)
        status=self.request('profiles/'+target+'/distance')[1]
        self.assertEqual((status['totals']['metres'],status['totals']['legacyBaselineMetres']),(123,123))
        code,copied=self.request('profiles/'+target,'POST',{'action':'copy','revision':restored['profile']['revision'],'confirm':target,'source':source,'sourceRevision':source_record['revision']})
        self.assertEqual(code,200)
        status=self.request('profiles/'+target+'/distance')[1]
        self.assertEqual((status['mode'],status['totals']['metres'],status['totals']['legacyBaselineMetres']),('protected',456,456))
        self.assertEqual(self.request('profiles/'+source+'/distance')[1]['mode'],'legacy')
        connection=Client(self.server,identity=('synthetic-admin-device','synthetic-admin-account'));self.addCleanup(connection.close)
        self.assertEqual(connection.rpc(27,I(500)),b'\0'+I(456))
        self.assertEqual(movement_ack(connection.rpc(2001,oldbatch))['status'],2)
        hello=movement_hello();new=movement_ack(connection.rpc(2001,hello));utc=struct.unpack('>q',hello[-8:])[0]
        first=movement_ack(connection.rpc(2001,movement_batch(new['epoch'],1,[movement_fix(utc,100000,10000,flags=5)])))
        self.assertEqual((first['status'],first['total'],first['credited']),(0,456,0))


class ServerMetricsParserTests(unittest.TestCase):
    def test_synthetic_sources_deltas_missing_data_counter_resets_and_concurrent_cache(self):
        # The packaged runtime has no SDK/source. Its real HTTP metrics tests above still run.
        # Local builds additionally exercise the exact production parser with synthetic procfs data.
        source = ROOT/'WitcherRevival.Server/Admin/ServerMetrics.cs'
        if not source.is_file() or not (base.DOTNET.parent/'sdk').is_dir():
            self.skipTest('source-level metrics fixture requires the local SDK; HTTP tests cover the packaged runtime')
        program = r'''
using WitcherRevival.Server.Admin;
using M = WitcherRevival.Server.Admin.ServerMetrics;
class Clock : TimeProvider {
    public long Ticks;
    public DateTimeOffset Utc = DateTimeOffset.Parse("2026-10-02T10:00:00+02:00");
    public override long TimestampFrequency => 1000;
    public override long GetTimestamp() => Ticks;
    public override DateTimeOffset GetUtcNow() => Utc;
    public void Advance() { Ticks += 2000; Utc += TimeSpan.FromSeconds(2); }
}
class Program {
    static int checks;
    static void Check(bool condition) { checks++; if (!condition) throw new Exception("fixture assertion " + checks); }
    static void Near(double? value, double expected) => Check(value is not null && Math.Abs(value.Value-expected)<0.00001);
    static string Stat(string times) => "cpu " + times + "\ncpu0 0 0 0 0\ncpu1 0 0 0 0\nintr 9999\n";
    static void Main() {
        var memory = M.ParseMemory("MemTotal: 1000 kB\nMemFree: 50 kB\nMemAvailable: 600 kB\n");
        Check(memory.Available); Check(memory.TotalBytes==1024000); Check(memory.AvailableBytes==614400);
        Check(memory.UsedBytes==409600); Near(memory.UsedPercent, 40);
        Near(M.ParseMemory("MemTotal: 1000 kB\nMemAvailable: 0 kB").UsedPercent, 100);
        foreach (var value in new string?[] { null, "", "MemTotal: 1000 kB", "MemTotal: 0 kB\nMemAvailable: 0 kB",
            "MemTotal: 1 kB\nMemAvailable: 2 kB", "MemTotal: 1 kB\nMemAvailable: -1 kB",
            "MemTotal: 9223372036854775807 kB\nMemAvailable: 0 kB", "MemTotal: 10 MB\nMemAvailable: 1 kB",
            "MemTotal: 10 kB\nMemTotal: 10 kB\nMemAvailable: 1 kB" }) {
            var bad = M.ParseMemory(value); Check(!bad.Available && bad.TotalBytes is null && bad.UsedPercent is null);
        }
        var load = M.ParseLoad("1.25 2.50 30.75 1/999 99999\n");
        Check(load.Available); Near(load.One,1.25); Near(load.Five,2.5); Near(load.Fifteen,30.75);
        foreach (var value in new string?[] { null, "", "1 2", "NaN 1 2", "1 Infinity 2", "-1 2 3", "1,25 2 3" })
            Check(!M.ParseLoad(value).Available && M.ParseLoad(value).One is null);
        Near(M.ParseUptime("1234.50 6789.0"),1234.5);
        Check(M.ParseUptime("NaN 0") is null); Check(M.ParseUptime("-1 0") is null);
        Check(M.ParseCpu(null) is null); Check(M.ParseCpu("cpu 1 -2 3 4") is null);
        Check(M.ParseCpu("cpu 1 2 3") is null); Check(M.ParseCpu("cpu 18446744073709551616 2 3 4") is null);
        Check(M.ParseCpu("cpu 1 2 3 4\ncpu 1 2 3 4") is null);
        Check(M.ParseCpu(Stat("1 2 3 4")+"cpu1 0 0 0 0") is null);
        Check(M.ParseCpu("cpu 1 2 3 4")?.Count is null);
        Check(M.ParseCpu(Stat("1 2 3 4"))?.Count==2);
        var clock = new Clock(); int reads = 0;
        var rawProcess = new M.ProcessCounters(30, 123456, 10);
        var proc = new Dictionary<string,string?> {
            ["stat"] = Stat("100 20 30 400 40 5 5 0 50 10"),
            ["meminfo"] = "MemTotal: 1000 kB\nMemAvailable: 600 kB",
            ["loadavg"] = "1.25 2.50 30.75 1/999 99999",
            ["uptime"] = "1234.5 6789.0" };
        var sampler = new M(clock, () => { Interlocked.Increment(ref reads); return rawProcess; }, name => proc[name], true);
        var first = sampler.Read();
        Check(first.SampledAt.Offset==TimeSpan.Zero); Check(first.Process.Cpu.Status=="warming-up");
        Check(first.Host.Cpu.Status=="warming-up"); Check(first.Process.Cpu.Percent is null);
        Check(first.Host.Cpu.WindowSeconds is null); Check(first.Host.Status=="available");
        Parallel.For(0, 100, _ => { if (!ReferenceEquals(first,sampler.Read())) throw new Exception("cache changed"); });
        Check(reads==1); clock.Ticks=1999; Check(ReferenceEquals(first,sampler.Read())); Check(reads==1);
        clock.Ticks=2000; clock.Utc-=TimeSpan.FromHours(1); // Wall-clock correction cannot change CPU's monotonic interval.
        rawProcess = rawProcess with { CpuSeconds=15 };
        proc["stat"] = Stat("160 20 50 500 60 5 5 0 70 10");
        var second=sampler.Read(); Check(reads==2); Near(second.Process.Cpu.Percent,250);
        Near(second.Process.Cpu.WindowSeconds,2); Near(second.Host.Cpu.Percent,40);
        Near(second.Host.Cpu.WindowSeconds,2); Check(second.Host.Cpu.LogicalCpuCount==2);
        Check(second.Process.Cpu.Normalization=="one-logical-cpu");
        Check(second.Host.Cpu.Normalization=="all-host-logical-cpus");
        // A decreasing iowait counter invalidates the entire host interval without breaking process metrics.
        clock.Advance(); proc["stat"] = Stat("170 20 60 510 59 5 5 0 70 10");
        var reset=sampler.Read(); Check(reset.Host.Cpu.Status=="counter-reset"); Check(reset.Host.Cpu.Percent is null);
        Check(reset.Process.Cpu.Available); Near(reset.Process.Cpu.Percent,0);
        clock.Advance(); rawProcess=rawProcess with { CpuSeconds=2 }; proc["stat"]=Stat("180 20 70 520 60 5 5 0 70 10");
        Check(sampler.Read().Process.Cpu.Status=="counter-reset");
        clock.Advance(); rawProcess=rawProcess with { CpuSeconds=3 }; proc["loadavg"]=null;
        var partial=sampler.Read(); Check(partial.Host.Status=="partial"); Check(partial.Host.Memory.Available);
        Check(!partial.Host.Load.Available && partial.Host.Load.One is null); Near(partial.Process.Cpu.Percent,50);
        Check(!partial.Host.Cpu.Available); // No aggregate counter movement: not a measured zero percent.
        clock.Advance(); foreach(var name in proc.Keys.ToArray()) proc[name]=null;
        var missing=sampler.Read(); Check(!missing.Host.Available); Check(missing.Host.Status=="unavailable");
        Check(missing.Host.UptimeSeconds is null); Check(missing.Host.LogicalCpuCount is null); Check(missing.Process.Available);
        clock.Advance(); proc["stat"]=Stat("190 20 80 530 60 5 5 0 70 10");
        Check(sampler.Read().Host.Cpu.Status=="warming-up"); // Never bridge a missing source interval.
        clock.Advance(); proc["stat"] += "cpu2 0 0 0 0\n";
        Check(sampler.Read().Host.Cpu.Status=="counter-reset"); // CPU hotplug changes the observed capacity.
        clock.Advance(); rawProcess=new(null,null,null);
        var absent=sampler.Read(); Check(!absent.Process.Available); Check(absent.Process.Status=="unavailable");
        Check(absent.Process.ResidentMemoryBytes is null); Check(absent.Process.Cpu.Status=="unavailable");
        var unsupported=new M(clock,()=>new(3,100,1),_=>throw new Exception("must not read procfs"),false).Read();
        Check(unsupported.Host.Status=="unsupported"); Check(!unsupported.Host.Available);
        Check(unsupported.Host.Cpu.Status=="unsupported"); Check(unsupported.Host.Memory.TotalBytes is null);
        Check(unsupported.Process.Available); Check(unsupported.Readiness.GameAndDependencies=="not-probed");
        Console.WriteLine("METRICS_FIXTURE_PASS " + checks);
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='synthetic-metrics-probe-') as folder:
            directory = Path(folder)
            shutil.copyfile(source, directory/'ServerMetrics.cs')
            (directory/'Program.cs').write_text(program)
            (directory/'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            (directory/'MetricsProbe.csproj').write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
                '<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
                '<Nullable>enable</Nullable></PropertyGroup></Project>')
            result = subprocess.run([str(base.DOTNET), 'build', 'MetricsProbe.csproj', '-c', 'Release',
                '-p:NuGetAudit=false', '-p:UseSharedCompilation=false', '--nologo'], cwd=directory,
                env=base.environment(), capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            probe = subprocess.run([str(base.DOTNET), str(directory/'bin/Release/net10.0/MetricsProbe.dll')],
                cwd=directory, env=base.environment(), capture_output=True, text=True, timeout=15)
            self.assertEqual(probe.returncode, 0, probe.stdout+probe.stderr)
            self.assertIn('METRICS_FIXTURE_PASS', probe.stdout)


if __name__ == '__main__': unittest.main()
