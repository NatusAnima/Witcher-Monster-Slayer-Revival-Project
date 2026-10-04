"""Public transport acceptance with synthetic tokens, loopback sockets and disposable profiles.

The HTTP listener models the trusted TLS front door. These tests do not exercise a public proxy,
certificate, Android client or live registry.
"""
import base64
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import socket
import struct
import subprocess
import tempfile
import time
import unittest

import test_prototype as legacy
from dev import DOTNET, DLL, ROOT, environment

SYNTHETIC_PROXY_KEY = 'SYNTHETIC_TRANSPORT_PROXY_KEY_FOR_DISPOSABLE_TESTS_ONLY'
PUBLIC_HOST = 'transport.invalid'
MAGIC = bytes.fromhex('9043284a')
TOKEN_A = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('=')
TOKEN_B = base64.urlsafe_b64encode(bytes(range(32, 64))).decode().rstrip('=')
TOKEN_C = base64.urlsafe_b64encode(bytes(range(64, 96))).decode().rstrip('=')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def front_headers(token):
    headers = {'Host': PUBLIC_HOST, 'X-Monster-Transport-Key': SYNTHETIC_PROXY_KEY,
               'X-Forwarded-Proto': 'https', 'X-Monster-Client-IP': '198.51.100.10'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    return headers


class UpgradeRefused(Exception):
    def __init__(self, status):
        super().__init__('synthetic WebSocket upgrade refused: ' + str(status))
        self.status = status


class WebSocket:
    """Small stdlib client: masked client frames and complete binary server messages."""
    def __init__(self, port, token, headers=None, path='/transport/game'):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=3)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.closed = False
        self.stream = self.sock.makefile('rb')
        key = base64.b64encode(os.urandom(16)).decode()
        hdr = front_headers(token)
        hdr.update({'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Version': '13',
                    'Sec-WebSocket-Key': key})
        for name, value in (headers or {}).items():
            if value is None:
                hdr.pop(name, None)
            else:
                hdr[name] = value
        request = 'GET ' + path + ' HTTP/1.1\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in hdr.items()) + '\r\n'
        self.sock.sendall(request.encode())
        try:
            first = self.stream.readline(8193)
            if len(first) > 8192:
                raise ValueError('oversize synthetic response line')
            status = int(first.split()[1])
            response = {}
            for _ in range(50):
                line = self.stream.readline(8193)
                if line == b'\r\n': break
                if not line or len(line) > 8192: raise ValueError('invalid synthetic upgrade headers')
                name, value = line.decode('ascii').split(':', 1)
                response[name.lower()] = value.strip()
            else:
                raise ValueError('too many synthetic upgrade headers')
            if status != 101:
                raise UpgradeRefused(status)
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if response.get('sec-websocket-accept') != expected:
                raise ValueError('invalid synthetic upgrade response')
        except Exception:
            self.close()
            raise

    @staticmethod
    def encoded(payload, opcode=2, final=True):
        mask = os.urandom(4)
        size = len(payload)
        head = bytes([(0x80 if final else 0) | opcode])
        if size < 126:
            head += bytes([0x80 | size])
        elif size <= 65535:
            head += b'\xfe' + struct.pack('>H', size)
        else:
            head += b'\xff' + struct.pack('>Q', size)
        return head + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload))

    def send(self, payload, opcode=2, final=True):
        self.sock.sendall(self.encoded(payload, opcode, final))

    def exact(self, size):
        data = self.stream.read(size)
        if len(data) != size:
            raise EOFError('synthetic WebSocket closed')
        return data

    def receive(self):
        message = bytearray()
        initial = None
        while True:
            flags, size = self.exact(2)
            if flags & 0x70 or size & 0x80:
                raise ValueError('unexpected server WebSocket flags')
            final, opcode = bool(flags & 0x80), flags & 15
            size &= 127
            if size == 126: size = struct.unpack('>H', self.exact(2))[0]
            elif size == 127: size = struct.unpack('>Q', self.exact(8))[0]
            if size > 2 * 1024 * 1024:
                raise ValueError('unexpected server WebSocket size')
            payload = self.exact(size)
            if opcode == 8:
                raise EOFError('synthetic WebSocket close frame')
            if opcode == 9:
                self.send(payload, opcode=10)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                if initial is not None:
                    raise ValueError('unexpected nested server message')
                initial = opcode
            elif opcode != 0 or initial is None:
                raise ValueError('unexpected server continuation')
            message.extend(payload)
            if final:
                if initial != 2:
                    raise ValueError('server response must be binary')
                return bytes(message)

    def close(self):
        if not self.closed:
            self.closed = True
            self.stream.close()
            self.sock.close()


class GameClient(legacy.Client):
    """Use the existing synthetic legacy RPC encoder/reader through a WebSocket."""
    def __init__(self, ws, identity=(b'SYNTHETIC_OLD_DEVICE', b'SYNTHETIC_OLD_ACCOUNT'), auth=True):
        self.ws, self.sock = ws, ws.sock
        self.sequence = random.getrandbits(40) << 8
        self.pushes = []
        if auth:
            self.send(3, legacy.auth_body(*identity))
            if self.receive() != (3, legacy.I(1) + b'\0'):
                raise ValueError('synthetic legacy authentication failed')

    def send(self, channel, payload):
        self.ws.send(MAGIC + bytes([channel]) + legacy.I(len(payload)) + payload)

    def receive(self):
        data = self.ws.receive()
        if len(data) < 5:
            raise ValueError('truncated backend frame')
        channel, size = struct.unpack('>Bi', data[:5])
        if size != len(data) - 5:
            raise ValueError('backend WebSocket message is not one complete frame')
        return channel, data[5:]

    def close(self):
        self.ws.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='twms-transport-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.port = free_port()
        self.registry = self.directory / 'transport-registry'
        self.key = self.directory / 'synthetic-proxy.key'
        self.key.write_text(SYNTHETIC_PROXY_KEY)
        self.key.chmod(0o600)
        self.options = {'Transport__Port': str(self.port), 'Transport__RegistryDirectory': str(self.registry),
                        'Transport__ProxyKeyFile': str(self.key), 'Transport__PublicHost': PUBLIC_HOST,
                        'LocalProfile__NewProfileMode': 'reconstructed'}
        self.server = legacy.Server(self.directory, 'synthetic-transport', self.options)
        self.addCleanup(self.server.stop)
        self.wait_listener()
        self.cli('open', '--ttl-seconds', '600', '--slots', '16')

    def wait_listener(self):
        for _ in range(100):
            try:
                if self.request(method='GET')[0] == 405: return
            except OSError:
                pass
            time.sleep(.02)
        self.fail('synthetic transport listener did not become ready')

    def restart(self, **options):
        self.server.stop()
        self.options.update(options)
        self.server = legacy.Server(self.directory, 'synthetic-transport', self.options)
        self.addCleanup(self.server.stop)
        self.wait_listener()

    def request(self, token=TOKEN_A, method='POST', body=b'', headers=None, path='/transport/enroll', port=None):
        hdr = front_headers(token)
        for name, value in (headers or {}).items():
            if value is None: hdr.pop(name, None)
            else: hdr[name] = value
        connection = http.client.HTTPConnection('127.0.0.1', self.port if port is None else port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=hdr)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            connection.close()

    def ws(self, token=TOKEN_A, **kwargs):
        ws = WebSocket(self.port, token, **kwargs)
        self.addCleanup(ws.close)
        return ws

    def game(self, token=TOKEN_A, **kwargs):
        return GameClient(self.ws(token), **kwargs)

    def cli(self, action, *arguments, success=True):
        result = subprocess.run([str(DOTNET), str(DLL), '--transport-admin', action,
                                 '--registry', str(self.registry), '--profiles', str(self.directory / 'profiles'),
                                 *arguments], cwd=ROOT, env=environment(), capture_output=True, text=True, timeout=10)
        if success is None:
            return result.returncode, json.loads(result.stdout)
        self.assertEqual(result.returncode == 0, success, 'synthetic transport CLI outcome')
        if success:
            return json.loads(result.stdout)
        return result

    def existing_profile(self, name, fact_value):
        identity = (name + '-device', name + '-account')
        client = legacy.Client(self.server, identity=identity)
        self.addCleanup(client.close)
        self.assertEqual(client.rpc(78, legacy.I(2) + legacy.I(70001) + legacy.I(fact_value)), b'\1')
        profile = self.server.profile_id(identity)
        client.close()
        return profile

    def approve(self, token=TOKEN_A, profile=None, ttl=None):
        status, enrollment = self.request(token)
        self.assertEqual(status, 200)
        self.assertEqual(enrollment['status'], 'pending')
        args = ['--code', enrollment['code']]
        args += ['--profile', profile] if profile else ['--new-profile']
        if ttl is not None: args += ['--ttl-seconds', str(ttl)]
        result = self.cli('approve', *args)
        self.assertEqual(result['status'], 'approved')
        return enrollment['code'], result['profile']

    def assert_refused(self, token, status=403, **kwargs):
        with self.assertRaises(UpgradeRefused) as refused:
            self.ws(token, **kwargs)
        self.assertEqual(refused.exception.status, status)

    def assert_closed(self, ws, timeout=4):
        ws.sock.settimeout(timeout)
        try:
            while True: ws.receive()
        except (EOFError, ConnectionResetError):
            return
        except socket.timeout:
            self.fail('synthetic rejected session remained open')

    def test_frontdoor_and_enrollment_requirements(self):
        for headers in ({'X-Monster-Transport-Key': None}, {'X-Monster-Transport-Key': 'synthetic-wrong'},
                        {'X-Forwarded-Proto': None}, {'X-Forwarded-Proto': 'http'},
                        {'Host': 'other.invalid'}, {'Origin': 'https://' + PUBLIC_HOST},
                        {'X-Monster-Client-IP': None}, {'X-Monster-Client-IP': 'not-an-address'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)
        for token in (None, '', 'short', TOKEN_A + '=', 'A' * 44, '+' * 43, 'A' * 42 + 'B'):
            with self.subTest(token=token):
                self.assertEqual(self.request(token)[0], 401)
        self.assertEqual(self.request(method='GET')[0], 405)
        self.assertEqual(self.request(body=b'not-empty')[0], 400)
        self.assertEqual(self.request(path='/transport/enroll?token=synthetic')[0], 403)
        self.assertEqual(self.request(port=self.server.http)[0], 404)

    def test_enrollment_stable_code_hash_only_and_no_implicit_profile(self):
        before = sorted(p.name for p in (self.directory / 'profiles').glob('p*.json'))
        status, first = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(first['status'], 'pending')
        self.assertRegex(first['code'], r'^[A-F0-9]{4}-[A-F0-9]{4}$')
        self.assertEqual(self.request(), (200, first))
        self.assertEqual(sorted(p.name for p in (self.directory / 'profiles').glob('p*.json')), before)
        self.assert_refused(TOKEN_A)
        self.assert_refused(TOKEN_B)
        self.assert_refused(None, status=401)
        stored = b'\n'.join(p.read_bytes() for p in self.registry.rglob('*') if p.is_file())
        self.assertIn(hashlib.sha256(bytes(range(32))).hexdigest().encode(), stored.lower())
        self.assertNotIn(TOKEN_A.encode(), stored)
        self.assertNotIn(bytes(range(32)), stored)
        self.server.log.flush()
        self.assertNotIn(TOKEN_A, self.server.logpath.read_text())
        self.assertNotIn(SYNTHETIC_PROXY_KEY, self.server.logpath.read_text())

    def test_two_approved_tokens_keep_distinct_fixed_profiles_across_legacy_auth(self):
        first = self.existing_profile('synthetic-first', 11)
        second = self.existing_profile('synthetic-second', 22)
        code_a, _ = self.approve(TOKEN_A, first)
        self.approve(TOKEN_B, second)
        index = (self.directory / 'profiles/players.json').read_bytes()
        one, two = self.game(TOKEN_A), self.game(TOKEN_B)
        self.assertEqual(legacy.Reader(one.rpc(59)).facts()[70001], 11)
        self.assertEqual(legacy.Reader(two.rpc(59)).facts()[70001], 22)
        for client in (one, two):
            client.send(3, legacy.auth_body(b'synthetic-second-device', b'synthetic-second-account'))
            self.assertEqual(client.receive(), (3, legacy.I(1) + b'\0'))
        self.assertEqual(legacy.Reader(one.rpc(59)).facts()[70001], 11)
        self.assertEqual(legacy.Reader(two.rpc(59)).facts()[70001], 22)
        self.assertEqual((self.directory / 'profiles/players.json').read_bytes(), index)
        self.cli('approve', '--code', code_a, '--profile', second, success=False)
        self.assertEqual(self.request(TOKEN_A)[1]['status'], 'approved')
        one.close(); two.close(); self.restart()
        self.assertEqual(legacy.Reader(self.game(TOKEN_A).rpc(59)).facts()[70001], 11)
        self.assertEqual(legacy.Reader(self.game(TOKEN_B).rpc(59)).facts()[70001], 22)
        self.assertEqual((self.directory / 'profiles/players.json').read_bytes(), index)

    def test_new_profile_approval_has_no_legacy_identity_binding(self):
        index_path = self.directory / 'profiles/players.json'
        before = index_path.read_bytes() if index_path.exists() else None
        _, profile = self.approve()
        client = self.game()
        self.assertEqual(client.rpc(78, legacy.I(2) + legacy.I(70002) + legacy.I(9)), b'\1')
        saved = json.loads((self.directory / 'profiles' / (profile + '.json')).read_text())
        self.assertEqual(saved['Facts']['70002'], 9)
        self.assertEqual(index_path.read_bytes() if index_path.exists() else None, before)

    def test_revocation_closes_active_session_and_survives_restart(self):
        code, _ = self.approve()
        client = self.game()
        self.assertIsInstance(legacy.Reader(client.rpc(59)).facts(), dict)
        self.assertEqual(self.cli('revoke', '--code', code)['status'], 'revoked')
        self.assert_closed(client.ws)
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)
        self.cli('approve', '--code', code, '--new-profile', success=False)
        self.restart()
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)

    def test_per_principal_session_limit_releases_capacity(self):
        self.approve()
        first, second = self.game(), self.game()
        self.assert_refused(TOKEN_A, status=429)
        first.close()
        deadline = time.monotonic() + 3
        while True:
            try:
                replacement = self.game()
                break
            except UpgradeRefused as error:
                if error.status != 429 or time.monotonic() >= deadline: raise
                time.sleep(.05)
        self.assertIsInstance(legacy.Reader(replacement.rpc(59)).facts(), dict)
        self.assertIsInstance(legacy.Reader(second.rpc(59)).facts(), dict)

    def test_invalid_messages_close_before_any_legacy_identity_resolution(self):
        self.approve()
        index_path = self.directory / 'profiles/players.json'
        before = index_path.read_bytes() if index_path.exists() else None
        auth = legacy.auth_body(b'SYNTHETIC_REJECTED_DEVICE', b'SYNTHETIC_REJECTED_ACCOUNT')
        good = MAGIC + b'\3' + legacy.I(len(auth)) + auth
        cases = [('text', b'not binary', 1), ('magic', b'BAD!' + good[4:], 2),
                 ('short', good[:8], 2), ('negative_length', good[:5] + legacy.I(-1), 2),
                 ('length', good[:5] + legacy.I(len(auth) + 1) + auth, 2),
                 ('two_frames', good + good, 2), ('oversize', b'x' * 65537, 2)]
        for name, payload, opcode in cases:
            with self.subTest(case=name):
                ws = self.ws()
                ws.send(payload, opcode=opcode)
                self.assert_closed(ws)
                ws.close()
                self.assertEqual(index_path.read_bytes() if index_path.exists() else None, before)

    def test_burst_frame_limit_closes_session(self):
        self.approve()
        ws = self.ws()
        body = legacy.auth_body(b'SYNTHETIC_BURST_DEVICE', b'SYNTHETIC_BURST_ACCOUNT')
        frame = MAGIC + b'\3' + legacy.I(len(body)) + body
        ws.sock.sendall(b''.join(WebSocket.encoded(frame) for _ in range(280)))
        self.assert_closed(ws)

    def test_fragmented_binary_message_reassembles_one_legacy_frame(self):
        self.approve()
        ws = self.ws()
        body = legacy.auth_body(b'SYNTHETIC_FRAGMENT_DEVICE', b'SYNTHETIC_FRAGMENT_ACCOUNT')
        frame = MAGIC + b'\3' + legacy.I(len(body)) + body
        ws.send(frame[:7], final=False)
        ws.send(frame[7:18], opcode=0, final=False)
        ws.send(frame[18:], opcode=0)
        client = GameClient(ws, auth=False)
        self.assertEqual(client.receive(), (3, legacy.I(1) + b'\0'))
        self.assertIsInstance(legacy.Reader(client.rpc(59)).facts(), dict)
        # The bound is on the assembled message, not independently on each fragment.
        ws.send(b'x' * 32768, final=False)
        ws.send(b'x' * 32769, opcode=0)
        self.assert_closed(ws)

    def test_first_message_and_partial_message_deadlines_close_stalled_sessions(self):
        self.approve()
        self.restart(Transport__FirstFrameSeconds='1', Transport__FragmentSeconds='1')
        idle = self.ws()
        self.assert_closed(idle, timeout=3)
        idle.close()
        client = self.game()
        body = b'\1\1' + legacy.I(0) + legacy.Q(client.sequence + 1) + legacy.I(59)
        frame = MAGIC + b'\1' + legacy.I(len(body)) + body
        client.ws.send(frame[:12], final=False)
        self.assert_closed(client.ws, timeout=3)

    def test_first_fragment_does_not_extend_the_authentication_deadline(self):
        self.approve()
        self.restart(Transport__FirstFrameSeconds='1', Transport__FragmentSeconds='3')
        ws = self.ws()
        body = legacy.auth_body(b'SYNTHETIC_SLOW_DEVICE', b'SYNTHETIC_SLOW_ACCOUNT')
        frame = MAGIC + b'\3' + legacy.I(len(body)) + body
        ws.send(frame[:12], final=False)
        # A fragment must not replace the one-second first-message budget with three seconds.
        self.assert_closed(ws, timeout=2)

    def test_short_approval_expiry_revokes_active_and_future_sessions(self):
        self.approve(ttl=2)
        client = self.game()
        self.assertIsInstance(legacy.Reader(client.rpc(59)).facts(), dict)
        self.assert_closed(client.ws, timeout=4)
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)

    def test_expired_pending_invitation_refreshes_without_resetting_live_polls(self):
        self.restart(Transport__PendingSeconds='2')
        _, first = self.request()
        self.assertEqual(first['status'], 'pending')
        registry = self.registry / 'registry.json'
        before = registry.read_bytes()
        self.assertEqual(self.request(), (200, first))
        self.assertEqual(registry.read_bytes(), before)
        time.sleep(2.05)
        _, refreshed = self.request()
        self.assertEqual(refreshed['status'], 'pending')
        self.assertNotEqual(refreshed['code'], first['code'])
        self.cli('approve', '--code', first['code'], '--new-profile', success=False)
        rows = json.loads(registry.read_text())['entries']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], refreshed['code'])
        self.assert_refused(TOKEN_A)

    def test_renewal_preserves_profile_and_cannot_revive_explicit_revocation(self):
        profile = self.existing_profile('synthetic-renewal', 31)
        code, _ = self.approve(profile=profile, ttl=1)
        time.sleep(1.05)
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)
        renewed = self.cli('renew', '--code', code, '--ttl-seconds', '60')
        self.assertEqual((renewed['status'], renewed['profile'], renewed['code']), ('approved', profile, code))
        self.assertEqual(legacy.Reader(self.game().rpc(59)).facts()[70001], 31)
        before = json.loads((self.registry / 'registry.json').read_text())['entries'][0]
        self.cli('renew', '--code', code, '--ttl-seconds', '120')
        after = json.loads((self.registry / 'registry.json').read_text())['entries'][0]
        self.assertGreater(after['expiresAt'], before['expiresAt'])
        self.assertEqual({k: v for k, v in before.items() if k != 'expiresAt'},
                         {k: v for k, v in after.items() if k != 'expiresAt'})
        self.cli('renew', '--code', code, '--profile', profile, success=False)
        self.cli('revoke', '--code', code)
        self.cli('renew', '--code', code, '--ttl-seconds', '60', success=False)
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)

    def test_public_static_data_url_is_scoped_to_authenticated_transport(self):
        self.approve()
        remote = self.game()
        remote.send(4, legacy.I(2))
        channel, payload = remote.receive()
        self.assertEqual(channel, 4)
        reader = legacy.Reader(payload)
        self.assertEqual(reader.integer(), 2)
        self.assertEqual(reader.string(), 'https://' + PUBLIC_HOST + '/staticdata')
        self.assertEqual(reader.pos, len(payload))
        local = legacy.Client(self.server)
        self.addCleanup(local.close)
        local.send(4, legacy.I(2))
        channel, payload = local.receive()
        self.assertEqual(channel, 4)
        reader = legacy.Reader(payload)
        self.assertEqual(reader.integer(), 2)
        self.assertNotEqual(reader.string(), 'https://' + PUBLIC_HOST + '/staticdata')

    def test_concurrent_approval_and_revocation_preserve_one_immutable_binding(self):
        first = self.existing_profile('synthetic-race-first', 41)
        second = self.existing_profile('synthetic-race-second', 42)
        _, pending = self.request()
        code = pending['code']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda profile: self.cli('approve', '--code', code,
                                                              '--profile', profile, success=None), (first, second)))
        self.assertEqual(sorted(status for status, _ in outcomes), [0, 2])
        winner = next(value['profile'] for status, value in outcomes if status == 0)
        row, = json.loads((self.registry / 'registry.json').read_text())['entries']
        self.assertEqual((row['status'], row['profile']), ('approved', winner))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            renew = pool.submit(self.cli, 'renew', '--code', code, '--ttl-seconds', '60', success=None)
            revoke = pool.submit(self.cli, 'revoke', '--code', code, success=None)
            self.assertIn(renew.result()[0], (0, 2))
            self.assertEqual(revoke.result()[0], 0)
        row, = json.loads((self.registry / 'registry.json').read_text())['entries']
        self.assertEqual((row['status'], row['profile']), ('revoked', winner))
        self.assertEqual(self.request()[1]['status'], 'revoked')
        self.assert_refused(TOKEN_A)

    def test_non_ascii_proxy_key_and_cross_origin_static_url_fail_startup(self):
        self.server.stop()
        non_ascii = self.directory / 'synthetic-non-ascii.key'
        non_ascii.write_text('SYNTHETIC_INVALID_PROXY_KEY_' + '\u00e9' * 16)
        non_ascii.chmod(0o600)
        cases = [{'Transport__ProxyKeyFile': str(non_ascii)},
                 {'Transport__StaticDataUrl': 'http://' + PUBLIC_HOST + '/staticdata'},
                 {'Transport__StaticDataUrl': 'https://other.invalid/staticdata'},
                 {'Transport__StaticDataUrl': 'https://' + PUBLIC_HOST + '/other'}]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                http, tcp = legacy.available_ports()
                env = environment(); env.update(self.options); env.update(overrides)
                result = subprocess.run([str(DOTNET), str(DLL), '--Http:Port', str(http),
                    '--GameServer:Port', str(tcp), '--LocalProfile:DataDirectory', str(self.directory / 'profiles')],
                    cwd=ROOT, env=env, capture_output=True, timeout=5)
                output = result.stdout + result.stderr
                expected = (b'Invalid transport proxy key format.' if 'Transport__ProxyKeyFile' in overrides
                            else b'Transport static data must use its configured HTTPS host.')
                self.assertIn(expected, output)
                self.assertNotIn(b'Approved transport listener ready', output)
                self.assertNotIn(non_ascii.read_bytes(), output)

    def test_enrollment_defaults_closed_and_existing_polls_survive_closed_window(self):
        self.registry = self.directory / 'fresh-closed-registry'
        self.restart(Transport__RegistryDirectory=str(self.registry))
        self.assertEqual(self.request(), (200, {'status': 'closed', 'code': ''}))
        self.assertEqual(self.cli('list')['entries'], [])
        self.cli('open', '--ttl-seconds', '2', '--slots', '2')
        _, pending = self.request()
        registry = self.registry / 'registry.json'
        saved = registry.read_bytes()
        self.assertEqual(self.request(), (200, pending))
        self.assertEqual(registry.read_bytes(), saved)
        time.sleep(2.05)
        self.assertEqual(self.request(), (200, pending))
        self.assertEqual(self.request(TOKEN_B), (200, {'status': 'closed', 'code': ''}))
        self.assertEqual(registry.read_bytes(), saved)
        self.cli('approve', '--code', pending['code'], '--new-profile')
        saved = registry.read_bytes()
        self.assertEqual(self.request()[1]['status'], 'approved')
        self.assertEqual(registry.read_bytes(), saved)
        self.restart()
        self.assertEqual(self.request(TOKEN_B), (200, {'status': 'closed', 'code': ''}))
        self.assertEqual(self.request()[1]['status'], 'approved')

    def test_enrollment_window_slot_quota_is_not_consumed_by_existing_polls(self):
        self.cli('open', '--ttl-seconds', '600', '--slots', '2')
        _, first = self.request()
        registry = self.registry / 'registry.json'
        before = registry.read_bytes()
        for _ in range(8): self.assertEqual(self.request(), (200, first))
        self.assertEqual(registry.read_bytes(), before)
        self.assertEqual(json.loads(before)['enrollmentRemaining'], 1)
        self.assertEqual(self.request(TOKEN_B)[1]['status'], 'pending')
        exhausted = registry.read_bytes()
        self.assertEqual(json.loads(exhausted)['enrollmentRemaining'], 0)
        self.assertEqual(self.request(TOKEN_C), (200, {'status': 'closed', 'code': ''}))
        self.assertEqual(registry.read_bytes(), exhausted)
        for ttl, slots in (('0', '1'), ('601', '1'), ('10', '0'), ('10', '17')):
            self.cli('open', '--ttl-seconds', ttl, '--slots', slots, success=False)
        self.assertEqual(registry.read_bytes(), exhausted)

    def test_pending_source_quota_uses_private_ipv4_and_ipv6_prefix_hashes(self):
        def token(number):
            return base64.urlsafe_b64encode(bytes([number]) * 32).decode().rstrip('=')
        ipv4 = ['198.51.100.10', '198.51.100.11']
        ipv6 = ['2001:db8:1234:5678::1', '2001:db8:1234:5678::abcd', '2001:db8:1234:5679::1']
        for number in range(100, 104):
            self.assertEqual(self.request(token(number))[1]['status'], 'pending')
        self.assertEqual(self.request(token(104))[0], 429)
        self.assertEqual(self.request(token(100))[1]['status'], 'pending')
        self.assertEqual(self.request(token(104), headers={'X-Monster-Client-IP': ipv4[1]})[1]['status'], 'pending')
        for number in range(105, 109):
            self.assertEqual(self.request(token(number), headers={'X-Monster-Client-IP': ipv6[0]})[1]['status'], 'pending')
        self.assertEqual(self.request(token(109), headers={'X-Monster-Client-IP': ipv6[1]})[0], 429)
        self.assertEqual(self.request(token(109), headers={'X-Monster-Client-IP': ipv6[2]})[1]['status'], 'pending')
        stored = (self.registry / 'registry.json').read_text()
        for address in ipv4 + ipv6: self.assertNotIn(address, stored)
        for row in json.loads(stored)['entries']:
            self.assertRegex(row['sourceHash'], r'^[a-f0-9]{64}$')
        listing = json.dumps(self.cli('list')).lower()
        self.assertNotIn('sourcehash', listing)
        self.assertNotIn('tokenhash', listing)

    def test_expired_pending_cannot_reopen_its_window_or_revoked_invitation(self):
        self.restart(Transport__PendingSeconds='2')
        _, pending = self.request()
        self.cli('close')
        time.sleep(2.05)
        self.assertEqual(self.request(), (200, {'status': 'closed', 'code': ''}))
        self.cli('approve', '--code', pending['code'], '--new-profile', success=False)
        self.cli('open', '--ttl-seconds', '600', '--slots', '2')
        _, refreshed = self.request()
        self.assertEqual(refreshed['status'], 'pending')
        self.cli('revoke', '--code', refreshed['code'])
        saved = (self.registry / 'registry.json').read_bytes()
        self.assertEqual(self.request(), (200, {'status': 'revoked', 'code': refreshed['code']}))
        self.assertEqual((self.registry / 'registry.json').read_bytes(), saved)
