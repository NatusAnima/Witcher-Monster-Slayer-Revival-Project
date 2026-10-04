"""Tester-management acceptance using disposable registries and synthetic installations.

Reuses the operator HTTP and transport WebSocket fixtures. No real credentials,
devices, proxy, player saves, or production listeners are involved.
"""
import concurrent.futures
import hashlib
import http.client
import json
import time
import unittest
import urllib.error

import test_admin as admin
import test_prototype as legacy
import test_transport as transport


class AdminTransportTests(unittest.TestCase):
    request = admin.AdminTests.request
    restart = admin.AdminTests.restart
    existing_profile = transport.TransportTests.existing_profile
    assert_closed = transport.TransportTests.assert_closed

    def setUp(self):
        admin.AdminTests.setUp(self)
        self.disabled_snapshot = self.request('transport')
        self.transport_port = admin.free_port()
        self.registry = self.directory / 'transport-registry'
        key = self.directory / 'synthetic-transport-proxy.key'
        key.write_text(transport.SYNTHETIC_PROXY_KEY)
        key.chmod(0o600)
        self.restart(Transport__Port=str(self.transport_port),
                     Transport__RegistryDirectory=str(self.registry),
                     Transport__ProxyKeyFile=str(key),
                     Transport__PublicHost=transport.PUBLIC_HOST)
        for _ in range(100):
            try:
                if self.enroll(method='GET')[0] == 405:
                    break
            except OSError:
                pass
            time.sleep(.02)
        else:
            self.fail('synthetic transport listener did not become ready')

    def enroll(self, token=transport.TOKEN_A, method='POST'):
        connection = http.client.HTTPConnection('127.0.0.1', self.transport_port, timeout=3)
        try:
            connection.request(method, '/transport/enroll', body=b'',
                               headers=transport.front_headers(token))
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    def state(self):
        status, data = self.request('transport')
        self.assertEqual(status, 200)
        self.assertTrue(data['available'])
        return data['state']

    def row(self, code, state=None):
        return next(e for e in (self.state() if state is None else state)['entries'] if e['code'] == code)

    def change(self, action, code=None, expected=200, **fields):
        body = {'revision': self.state()['revision'], 'action': action,
                'confirm': code if code is not None else 'enrollment'}
        if code is not None:
            body['code'] = code
        body.update(fields)
        status, data = self.request('transport', 'POST', body)
        self.assertEqual(status, expected, (action, data))
        if status == 200:
            self.assertEqual(data['receipt']['action'], 'transport-' + action)
            self.assertEqual(data['receipt']['outcome'], 'applied')
            self.assertEqual(data['revision'], data['state']['revision'])
            self.assertEqual(data['revision'], self.state()['revision'])
        return data

    def open_enrollment(self, seconds=600, slots=16):
        return self.change('open', seconds=seconds, slots=slots)

    def pending(self, token=transport.TOKEN_A):
        status, result = self.enroll(token)
        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'pending')
        return result['code']

    def approve(self, token=transport.TOKEN_A, profile=None, seconds=3600):
        code = self.pending(token)
        binding = {'newProfile': True} if profile is None else {'profile': profile}
        data = self.change('approve', code, seconds=seconds, **binding)
        return code, self.row(code, data['state'])['profile']

    def game(self, token=transport.TOKEN_A):
        ws = transport.WebSocket(self.transport_port, token)
        self.addCleanup(ws.close)
        return transport.GameClient(ws)

    def assert_upgrade_refused(self, token=transport.TOKEN_A):
        with self.assertRaises(transport.UpgradeRefused) as refused:
            self.game(token)
        self.assertEqual(refused.exception.status, 403)

    def saved_profiles(self):
        return {p.name: p.read_bytes() for p in (self.directory / 'profiles').glob('*') if p.is_file()}

    def wait_status(self, code, expected):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            row = self.row(code)
            if row['status'] == expected:
                return row
            time.sleep(.03)
        self.fail('synthetic installation did not reach ' + expected)

    def test_authorization_origin_and_unconfigured_state(self):
        self.assertEqual(self.disabled_snapshot, (200, {'available': False}))
        before = self.state()
        body = {'revision': before['revision'], 'action': 'open', 'confirm': 'enrollment',
                'seconds': 30, 'slots': 1}
        for method in ('GET', 'POST'):
            self.assertEqual(self.request('transport', method, body if method == 'POST' else None,
                                          auth=False)[0], 403)
        self.assertEqual(self.request('transport', headers={'X-Monster-Admin-Key': 'synthetic-wrong'})[0], 403)
        for options in ({'origin': False}, {'headers': {'Origin': 'https://other.invalid'}},
                        {'headers': {'X-Requested-With': ''}}):
            self.assertEqual(self.request('transport', 'POST', body, **options)[0], 403)
        self.assertEqual(self.state()['revision'], before['revision'])
        self.assertEqual(self.request('receipts')[1], [])
        with self.assertRaises(urllib.error.HTTPError) as absent:
            self.server.get('/api/transport')
        self.assertEqual(absent.exception.code, 404)
        absent.exception.close()
        self.restart(Transport__Port='0')
        self.assertEqual(self.request('transport'), (200, {'available': False}))
        self.assertEqual(self.request('transport', 'POST', body)[0], 409)

    def test_window_quota_close_preserves_existing_requests_and_access(self):
        initial = self.state()
        self.assertFalse(initial['enrollmentOpen'])
        self.assertEqual(initial['entries'], [])
        self.assertEqual(self.enroll()[1], {'status': 'closed', 'code': ''})
        self.open_enrollment(slots=2)
        first = self.pending()
        second = self.pending(transport.TOKEN_B)
        full = self.state()
        self.assertFalse(full['enrollmentOpen'])
        self.assertEqual(full['enrollmentRemaining'], 0)
        self.assertEqual(self.enroll(transport.TOKEN_C)[1], {'status': 'closed', 'code': ''})
        self.assertEqual(self.pending(), first)
        self.assertEqual(self.state()['revision'], full['revision'])
        self.change('approve', first, newProfile=True, seconds=3600)
        self.change('close')
        closed = self.state()
        self.assertEqual((closed['enrollmentOpen'], closed['enrollmentUntil'], closed['enrollmentRemaining']),
                         (False, 0, 0))
        self.assertEqual(self.row(first)['status'], 'approved')
        self.assertEqual(self.row(second)['status'], 'pending')
        self.assertEqual(self.pending(transport.TOKEN_B), second)
        self.assertIsInstance(legacy.Reader(self.game().rpc(59)).facts(), dict)

    def test_snapshot_and_receipts_expose_only_safe_fields(self):
        profile = self.existing_profile('synthetic-projection', 11)
        saves = self.saved_profiles()
        self.open_enrollment()
        code, _ = self.approve(profile=profile)
        registry_bytes = (self.registry / 'registry.json').read_bytes()
        status, snapshot = self.request('transport')
        self.assertEqual(status, 200)
        self.assertEqual(set(snapshot), {'available', 'state', 'profiles', 'limits'})
        self.assertEqual(snapshot['limits'], {'enrollmentSeconds': 600, 'enrollmentSlots': 16,
                                            'accessSeconds': 31536000})
        row = self.row(code, snapshot['state'])
        self.assertEqual(set(row), {'code', 'status', 'profile', 'createdAt', 'pendingUntil', 'expiresAt'})
        self.assertLess(abs(snapshot['state']['observedAt'] - time.time()), 3)
        self.assertTrue(any(p['id'] == profile for p in snapshot['profiles']))
        payload = json.dumps([snapshot, self.request('receipts')[1]])
        for value in (transport.TOKEN_A, transport.SYNTHETIC_PROXY_KEY, admin.SYNTHETIC_KEY,
                      str(self.directory), 'tokenHash', 'sourceHash',
                      hashlib.sha256(bytes(range(32))).hexdigest()):
            self.assertNotIn(value, payload)
        self.assertEqual((self.registry / 'registry.json').read_bytes(), registry_bytes)
        self.assertEqual(self.saved_profiles(), saves)
        receipt = self.request('receipts')[1][0]
        self.assertEqual(receipt['target'], code)
        after = json.loads(receipt['after'])
        self.assertEqual(after['installation']['profile'], profile)

    def test_exact_code_confirmation_and_validation_preserve_state(self):
        self.open_enrollment()
        code = self.pending()
        saved = (self.registry / 'registry.json').read_bytes()
        for fields in ({'confirm': code + ' '}, {'confirm': ''}, {'profile': None, 'newProfile': False},
                       {'profile': 'p' + '0' * 31, 'newProfile': True}, {'seconds': 0},
                       {'seconds': 31536001}, {'slots': 1}, {'unrecognized': True}):
            with self.subTest(fields=fields):
                body = {'revision': self.state()['revision'], 'action': 'approve', 'code': code,
                        'confirm': code, 'newProfile': True, 'seconds': 60}
                body.update(fields)
                self.assertEqual(self.request('transport', 'POST', body)[0], 400)
                self.assertEqual((self.registry / 'registry.json').read_bytes(), saved)
        for fields in ({'seconds': 601, 'slots': 1}, {'seconds': 1, 'slots': 17},
                       {'seconds': 0, 'slots': 1}, {'seconds': 1, 'slots': 0},
                       {'seconds': 1, 'slots': 1, 'confirm': code}):
            self.change('open', expected=400, **fields)
            self.assertEqual((self.registry / 'registry.json').read_bytes(), saved)
        self.change('approve', code, newProfile=True, seconds=60)
        self.change('approve', code, expected=409, newProfile=True, seconds=60)

    def test_stale_and_duplicate_requests_are_rejected_without_retargeting(self):
        self.open_enrollment()
        code = self.pending()
        revision = self.state()['revision']
        body = {'revision': revision, 'action': 'approve', 'code': code, 'confirm': code,
                'newProfile': True, 'seconds': 3600}
        first_status, first = self.request('transport', 'POST', body)
        self.assertEqual(first_status, 200)
        saved = (self.registry / 'registry.json').read_bytes()
        self.assertEqual(self.request('transport', 'POST', body)[0], 409)
        for wrong in (None, revision, first['revision'] + 1):
            self.change('revoke', code, expected=409, revision=wrong)
            self.assertEqual((self.registry / 'registry.json').read_bytes(), saved)
        self.assertEqual(len(self.state()['entries']), 1)
        self.assertEqual(self.row(code)['profile'], self.row(code, first['state'])['profile'])
        outcomes = [r['outcome'] for r in self.request('receipts')[1] if r['action'] == 'transport-approve']
        self.assertCountEqual(outcomes, ['applied', 'refused'])

    def test_concurrent_approval_has_one_winner(self):
        first = self.existing_profile('synthetic-cas-first', 21)
        second = self.existing_profile('synthetic-cas-second', 22)
        saves = self.saved_profiles()
        self.open_enrollment()
        code = self.pending()
        revision = self.state()['revision']
        def approve(profile):
            return self.request('transport', 'POST', {'revision': revision, 'action': 'approve',
                                'code': code, 'confirm': code, 'profile': profile, 'seconds': 3600})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, (first, second)))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        winner = self.row(code, next(body['state'] for status, body in results if status == 200))['profile']
        self.assertEqual(self.row(code)['profile'], winner)
        self.assertEqual(self.saved_profiles(), saves)

    def test_new_approvals_reserve_separate_profiles_without_copying_progress(self):
        existing = self.existing_profile('synthetic-kept-save', 31)
        saves = self.saved_profiles()
        self.open_enrollment()
        code_a, profile_a = self.approve()
        code_b, profile_b = self.approve(transport.TOKEN_B)
        self.assertEqual(len({existing, profile_a, profile_b}), 3)
        self.assertEqual(self.saved_profiles(), saves)
        self.assertNotIn(profile_a + '.json', saves)
        self.assertNotIn(profile_b + '.json', saves)
        first, second = self.game(), self.game(transport.TOKEN_B)
        self.assertEqual(first.rpc(78, legacy.I(2) + legacy.I(70002) + legacy.I(71)), b'\1')
        self.assertNotIn(70002, legacy.Reader(second.rpc(59)).facts())
        self.assertEqual(json.loads((self.directory / 'profiles' / (profile_a + '.json')).read_text())['Facts']['70002'], 71)
        self.assertEqual((self.directory / 'profiles' / (existing + '.json')).read_bytes(), saves[existing + '.json'])
        self.assertEqual((self.directory / 'profiles/players.json').read_bytes(), saves['players.json'])
        self.assertEqual(self.row(code_a)['profile'], profile_a)
        self.assertEqual(self.row(code_b)['profile'], profile_b)

    def test_time_setting_starts_now_and_expiry_is_distinct_from_revocation(self):
        self.open_enrollment()
        code, profile = self.approve(seconds=3600)
        original = self.row(code)['expiresAt']
        before = int(time.time())
        self.change('renew', code, seconds=60)
        shortened = self.row(code)
        self.assertLess(shortened['expiresAt'], original)
        self.assertGreaterEqual(shortened['expiresAt'], before + 60)
        self.assertLessEqual(shortened['expiresAt'], int(time.time()) + 60)
        self.assertEqual(shortened['profile'], profile)
        self.change('renew', code, seconds=1)
        expired = self.wait_status(code, 'expired')
        self.assertEqual(expired['profile'], profile)
        self.assert_upgrade_refused()
        self.change('renew', code, seconds=3600)
        self.assertEqual(self.row(code)['status'], 'approved')
        client = self.game()
        self.change('revoke', code)
        self.assert_closed(client.ws)
        self.assertEqual(self.row(code)['status'], 'revoked')
        self.change('renew', code, expected=409, seconds=3600)
        self.change('rebind', code, expected=409, newProfile=True)
        self.assert_upgrade_refused()
        self.restart()
        self.assertEqual(self.row(code)['status'], 'revoked')

    def test_expired_pending_request_cannot_be_approved_or_renewed(self):
        self.restart(Transport__PendingSeconds='1')
        self.open_enrollment()
        code = self.pending()
        self.wait_status(code, 'request-expired')
        self.change('approve', code, expected=409, newProfile=True, seconds=3600)
        self.change('renew', code, expected=409, seconds=3600)
        self.change('rebind', code, expected=409, newProfile=True)
        replacement = self.pending()
        self.assertNotEqual(replacement, code)
        self.change('approve', code, expected=409, newProfile=True, seconds=3600)
        self.assertEqual([r['code'] for r in self.state()['entries']], [replacement])

    def test_rebind_preserves_saves_deadline_and_other_installation_sessions(self):
        first = self.existing_profile('synthetic-rebind-first', 41)
        second = self.existing_profile('synthetic-rebind-second', 42)
        saves = self.saved_profiles()
        self.open_enrollment()
        code, _ = self.approve(profile=first)
        other_code, _ = self.approve(transport.TOKEN_B, profile=first)
        old, other = self.game(), self.game(transport.TOKEN_B)
        self.assertEqual(legacy.Reader(old.rpc(59)).facts()[70001], 41)
        deadline = self.row(code)['expiresAt']
        self.change('rebind', code, profile=second)
        self.assert_closed(old.ws)
        self.assertEqual(legacy.Reader(other.rpc(59)).facts()[70001], 41)
        self.assertEqual(legacy.Reader(self.game().rpc(59)).facts()[70001], 42)
        self.assertEqual((self.row(code)['profile'], self.row(code)['expiresAt']), (second, deadline))
        self.assertEqual(self.row(other_code)['profile'], first)
        self.assertEqual(self.saved_profiles(), saves)
        self.change('rebind', code, expected=409, profile=second)

    def test_fast_rebind_a_b_a_still_closes_original_session(self):
        first = self.existing_profile('synthetic-roundtrip-first', 51)
        second = self.existing_profile('synthetic-roundtrip-second', 52)
        saves = self.saved_profiles()
        self.open_enrollment()
        code, _ = self.approve(profile=first)
        started = time.monotonic()
        old = self.game()
        self.change('rebind', code, profile=second)
        self.change('rebind', code, profile=first)
        elapsed = time.monotonic() - started
        # Both commits occur before the monitor's one-second scheduled revisit.
        self.assertLess(elapsed, .8, 'fixture too slow to establish the A→B→A monitoring regression')
        self.assertEqual(self.row(code)['profile'], first)
        self.assert_closed(old.ws)
        self.assertEqual(legacy.Reader(self.game().rpc(59)).facts()[70001], 51)
        self.assertEqual(self.saved_profiles(), saves)

    def test_rebind_of_expired_access_does_not_renew_it(self):
        first = self.existing_profile('synthetic-expired-first', 61)
        second = self.existing_profile('synthetic-expired-second', 62)
        saves = self.saved_profiles()
        self.open_enrollment()
        code, _ = self.approve(profile=first, seconds=1)
        original = self.wait_status(code, 'expired')
        self.change('rebind', code, profile=second)
        changed = self.row(code)
        self.assertEqual((changed['status'], changed['profile'], changed['expiresAt']),
                         ('expired', second, original['expiresAt']))
        self.assert_upgrade_refused()
        self.assertEqual(self.saved_profiles(), saves)
        self.change('renew', code, seconds=3600)
        self.assertEqual(legacy.Reader(self.game().rpc(59)).facts()[70001], 62)

    def test_legacy_registry_without_binding_revision_remains_readable_and_unchanged(self):
        first = self.existing_profile('synthetic-legacy-first', 81)
        second = self.existing_profile('synthetic-legacy-second', 82)
        saves = self.saved_profiles()
        self.open_enrollment()
        code, _ = self.approve(profile=first)
        path = self.registry / 'registry.json'
        self.server.stop()
        document = json.loads(path.read_text())
        # Explicit pre-management schema: no generation field, even if a later
        # serializer changes its default-value policy.
        for entry in document['entries']:
            entry.pop('bindingRevision', None)
        old_bytes = (json.dumps(document, indent=2) + '\n').encode()
        path.write_bytes(old_bytes)
        path.chmod(0o600)
        self.restart()
        self.assertEqual(self.row(code)['status'], 'approved')
        client = self.game()
        self.assertEqual(legacy.Reader(client.rpc(59)).facts()[70001], 81)
        client.close()
        self.assertEqual(path.read_bytes(), old_bytes)
        self.change('renew', code, seconds=3600)
        self.assertNotIn('bindingRevision', json.loads(path.read_text())['entries'][0])
        self.change('rebind', code, profile=second)
        self.assertEqual(json.loads(path.read_text())['entries'][0]['bindingRevision'], 1)
        self.restart()
        self.assertEqual(legacy.Reader(self.game().rpc(59)).facts()[70001], 82)
        self.assertEqual(self.saved_profiles(), saves)


if __name__ == '__main__':
    unittest.main()
