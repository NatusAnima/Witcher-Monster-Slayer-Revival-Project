"""Bounded diagnostics with synthetic credentials and disposable loopback services only."""
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import time
import unittest

import test_transport as transport

EVENT = {'schemaVersion': 1, 'event': 'heartbeat', 'uptimeMs': 12000, 'clientBuild': 290013,
         'foreground': True, 'nativeHeartbeatAgeMs': 20, 'gpsSampleAgeMs': 300,
         'gpsAckAgeMs': -1, 'retryState': 'idle', 'sessionGeneration': 0}
FILE_LIMIT = 256 * 1024


class DiagnosticsTests(unittest.TestCase):
    wait_listener = transport.TransportTests.wait_listener
    restart = transport.TransportTests.restart
    request = transport.TransportTests.request
    cli = transport.TransportTests.cli
    approve = transport.TransportTests.approve

    def setUp(self):
        transport.TransportTests.setUp(self)
        self.diagnostics = self.directory / 'diagnostics'
        self.restart(Transport__DiagnosticsDirectory=str(self.diagnostics))

    def send(self, value=EVENT, *, token=transport.TOKEN_A, body=None, headers=None):
        return self.request(token, body=json.dumps(value).encode() if body is None else body,
                            headers={'Content-Type': 'application/json', **(headers or {})},
                            path='/transport/diagnostics')

    def rows(self):
        return [json.loads(line) for path in sorted(self.diagnostics.glob('*.ndjson'))
                for line in path.read_text().splitlines()]

    def fresh_allowance(self):
        self.restart()

    def test_disabled_by_default_and_not_on_other_listeners(self):
        self.restart(Transport__DiagnosticsDirectory='')
        self.assertEqual(self.send()[0], 404)
        self.assertEqual(self.request(path='/transport/diagnostics', port=self.server.http)[0], 404)
        self.assertEqual(self.rows(), [])

    def test_frontdoor_bearer_and_current_approval_are_all_required(self):
        for headers in ({'X-Monster-Transport-Key': None}, {'X-Forwarded-Proto': 'http'},
                        {'Host': 'other.invalid'}, {'Origin': 'https://transport.invalid'}):
            self.assertEqual(self.send(headers=headers)[0], 403)
        for token in (None, '', 'synthetic-invalid'):
            self.assertEqual(self.send(token=token)[0], 401)
        self.assertEqual(self.send()[0], 403)
        self.request()
        self.assertEqual(self.send()[0], 403)
        code, _ = self.approve()
        self.assertEqual(self.send(), (204, None))
        self.cli('revoke', '--code', code)
        self.assertEqual(self.send()[0], 403)
        self.approve(transport.TOKEN_B, ttl=1)
        time.sleep(1.05)
        self.assertEqual(self.send(token=transport.TOKEN_B)[0], 403)
        self.assertEqual(len(self.rows()), 1)

    def test_valid_schema_stores_only_normalized_fields_without_identity_or_secrets(self):
        _, profile_a = self.approve()
        _, profile_b = self.approve(transport.TOKEN_B)
        before = {p.name: p.read_bytes() for p in (self.directory / 'profiles').glob('*') if p.is_file()}
        registry_before = (self.registry / 'registry.json').read_bytes()
        for token in (transport.TOKEN_A, transport.TOKEN_B):
            self.assertEqual(self.send(token=token), (204, None))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {'receivedAt', 'installation', 'diagnostic'})
        self.assertEqual(rows[0]['diagnostic'], EVENT)
        self.assertRegex(rows[0]['installation'], r'^[a-f0-9]{32}$')
        self.assertNotEqual(rows[0]['installation'], rows[1]['installation'])
        text = '\n'.join(p.read_text() for p in self.diagnostics.glob('*.ndjson'))
        for forbidden in (transport.TOKEN_A, transport.TOKEN_B, transport.SYNTHETIC_PROXY_KEY,
                          profile_a, profile_b, hashlib.sha256(bytes(range(32))).hexdigest(), '198.51.100.10'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.directory / 'profiles').glob('*') if p.is_file()})
        self.assertEqual((self.registry / 'registry.json').read_bytes(), registry_before)
        if os.name != 'nt':
            self.assertEqual(self.diagnostics.stat().st_mode & 0o777, 0o700)
            for path in self.diagnostics.iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.request(method='GET', path='/transport/diagnostics')[0], 405)
        self.assertEqual(self.request(path='/transport/diagnostics?event=heartbeat')[0], 403)

    def test_body_and_content_type_limits(self):
        self.approve()
        self.assertEqual(self.send(body=b'')[0], 400)
        self.assertEqual(self.send(headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.send(headers={'Content-Encoding': 'gzip'})[0], 415)
        self.assertEqual(self.send(body=b' ' * 8193)[0], 413)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request('POST', '/transport/diagnostics', body=iter([json.dumps(EVENT).encode()]),
                               headers={**transport.front_headers(transport.TOKEN_A), 'Content-Type': 'application/json'},
                               encode_chunked=True)
            response = connection.getresponse(); response.read()
            self.assertEqual(response.status, 400)
        finally: connection.close()
        self.assertEqual(self.rows(), [])

    def test_unknown_missing_duplicate_nested_and_malformed_fields_are_refused(self):
        self.approve()
        missing = dict(EVENT); del missing['event']
        cases = [json.dumps({**EVENT, 'arbitrary': 'SYNTHETIC_PRIVATE_MARKER'}).encode(), json.dumps(missing).encode(),
                 (json.dumps(EVENT)[:-1] + ',"event":"heartbeat"}').encode(), b'[]',
                 json.dumps({**EVENT, 'event': {'nested': 1}}).encode(), b'{invalid}',
                 json.dumps({**EVENT, 'profileId': 'SYNTHETIC_PROFILE'}).encode(),
                 json.dumps({**EVENT, 'coordinates': [10, 20]}).encode()]
        for index, body in enumerate(cases):
            if index and index % 4 == 0: self.fresh_allowance()
            with self.subTest(index=index): self.assertEqual(self.send(body=body)[0], 400)
        self.assertEqual(self.rows(), [])

    def test_enum_integer_and_age_bounds_are_strict(self):
        self.approve()
        cases = [('event', 'arbitrary-error-text'), ('retryState', 'unexpected'), ('schemaVersion', 2),
                 ('clientBuild', 0), ('clientBuild', 1000000), ('clientBuild', '290013'),
                 ('uptimeMs', -1), ('uptimeMs', 2592000001), ('uptimeMs', 1.5),
                 ('nativeHeartbeatAgeMs', -2), ('gpsSampleAgeMs', 2592000001), ('gpsAckAgeMs', None),
                 ('sessionGeneration', 2147483648), ('foreground', 1), ('event', None), ('schemaVersion', True)]
        for index, (key, value) in enumerate(cases):
            if index and index % 4 == 0: self.fresh_allowance()
            with self.subTest(field=key, value=value): self.assertEqual(self.send({**EVENT, key: value})[0], 400)
        self.assertEqual(self.rows(), [])
        self.fresh_allowance()
        self.assertEqual(self.send({**EVENT, 'uptimeMs': 2592000000, 'nativeHeartbeatAgeMs': -1,
                                   'gpsSampleAgeMs': 2592000000, 'sessionGeneration': 2147483647})[0], 204)

    def test_installation_burst_is_atomic_and_other_installation_retains_allowance(self):
        self.approve(); self.approve(transport.TOKEN_B)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda _: self.send()[0], range(8)))
        self.assertEqual(codes.count(204), 4)
        self.assertEqual(codes.count(429), 4)
        self.assertEqual(self.send(token=transport.TOKEN_B)[0], 204)
        self.assertEqual(len(self.rows()), 5)

    def raw_body(self, token, prefix):
        payload = json.dumps(EVENT).encode()
        sock = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        self.addCleanup(sock.close)
        headers = {**transport.front_headers(token), 'Content-Type': 'application/json',
                   'Content-Length': str(len(payload)), 'Connection': 'close'}
        request = 'POST /transport/diagnostics HTTP/1.1\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in headers.items()) + '\r\n'
        sock.sendall(request.encode() + payload[:prefix])
        return sock, payload[prefix:]

    def test_expiry_or_revocation_during_body_read_prevents_persistence(self):
        code, _ = self.approve()
        sock, remainder = self.raw_body(transport.TOKEN_A, 1)
        time.sleep(.1)
        self.cli('revoke', '--code', code)
        sock.sendall(remainder)
        self.assertIn(b' 403 ', sock.recv(4096).split(b'\r\n', 1)[0])
        self.assertEqual(self.rows(), [])

    def test_four_incomplete_bodies_bound_concurrency_and_release_capacity(self):
        self.approve(); self.approve(transport.TOKEN_B)
        sockets = [self.raw_body(transport.TOKEN_A, 1) for _ in range(4)]
        time.sleep(.15)
        self.assertEqual(self.send(token=transport.TOKEN_B)[0], 429)
        for sock, remainder in sockets:
            sock.sendall(remainder)
            self.assertIn(b' 204 ', sock.recv(4096).split(b'\r\n', 1)[0])
            sock.close()
        self.assertEqual(self.send(token=transport.TOKEN_B)[0], 204)

    @unittest.skipIf(os.name == 'nt', 'Unix file ownership and symlink guards')
    def test_unsafe_storage_is_refused_without_following_or_truncating_files(self):
        self.approve()
        current = self.diagnostics / 'diagnostics-current.ndjson'
        target = self.directory / 'synthetic-unrelated-target'
        current.symlink_to(target)
        self.assertEqual(self.send()[0], 503)
        self.assertFalse(target.exists())
        current.unlink()
        current.write_bytes(b'SYNTHETIC_EXISTING_DATA\n'); current.chmod(0o644)
        self.assertEqual(self.send()[0], 503)
        self.assertEqual(current.read_bytes(), b'SYNTHETIC_EXISTING_DATA\n')
        current.chmod(0o600); current.write_bytes(b'x' * (FILE_LIMIT + 1))
        self.assertEqual(self.send()[0], 503)
        self.assertEqual(current.stat().st_size, FILE_LIMIT + 1)
        current.unlink()
        self.assertEqual(self.send()[0], 204)

    def test_absolute_body_deadline_does_not_extend_on_trickle(self):
        self.approve()
        sock, remainder = self.raw_body(transport.TOKEN_A, 1)
        started = time.monotonic()
        time.sleep(1)
        sock.sendall(remainder[:1])
        status = sock.recv(4096).split(b'\r\n', 1)[0]
        self.assertIn(b' 408 ', status)
        self.assertLess(time.monotonic() - started, 4.5)
        self.assertEqual(self.rows(), [])

    def test_rotation_bounds_both_files_and_keeps_recent_events(self):
        self.approve()
        self.assertEqual(self.send()[0], 204)
        current = self.diagnostics / 'diagnostics-current.ndjson'
        previous = self.diagnostics / 'diagnostics-previous.ndjson'
        self.server.stop()
        line = current.read_bytes()
        current.write_bytes(line * (FILE_LIMIT // len(line)))
        previous.write_bytes(line); previous.chmod(0o600)
        self.restart()
        self.assertEqual(self.send({**EVENT, 'event': 'native-stale'})[0], 204)
        self.assertEqual(len(current.read_text().splitlines()), 1)
        self.assertEqual(json.loads(current.read_text())['diagnostic']['event'], 'native-stale')
        self.assertGreater(previous.stat().st_size, FILE_LIMIT - len(line))
        self.assertLessEqual(sum(p.stat().st_size for p in self.diagnostics.glob('*.ndjson')), 2 * FILE_LIMIT)
        self.assertTrue(all(p.stat().st_size <= FILE_LIMIT for p in self.diagnostics.glob('*.ndjson')))


if __name__ == '__main__':
    unittest.main()
