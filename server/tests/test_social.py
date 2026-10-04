"""Original 1.1.116 friend wire layouts and crash-safe social economy, using synthetic local profiles only."""
import concurrent.futures
import hashlib
import json
import unittest
import time
import urllib.error
import urllib.request
from pathlib import Path
import test_prototype as base
I, Q, Reader = base.I, base.Q, base.Reader


class SocialTests(base.PrototypeTests):
    NOW = 1790899200

    def social_server(self, **extra):
        self.social_env = {'LocalProfile__NewProfileMode': 'reconstructed', 'Social__FixedUnixTime': str(self.NOW), **extra}
        server = self.start('social-a', self.social_env)
        a = self.client(server)
        b = self.client(server, identity=base.identity_of('social-b'))
        self.aid, self.bid = self.friends(a)[0], self.friends(b)[0]
        self.assertNotEqual(self.aid, self.bid)
        self.assertTrue(all(100000000000 <= n <= 999999999999 for n in (self.aid, self.bid)))
        return server, a, b

    def friends(self, c):
        r = Reader(c.rpc(102)); own = r.long(); entries = {}
        for _ in range(r.integer()):
            ident = r.long()
            row = dict(status=r.integer(), name=r.string(), gender=r.byte(), head=r.integer(), level=r.integer())
            for prefix in ('sent', 'received'):
                row[prefix] = (r.integer(), r.integer(), r.byte())
            entries[ident] = row
        self.assertEqual(r.integer(), 0)
        self.assertEqual(r.pos, len(r.data))
        return own, entries

    def inventory(self, c):
        r = Reader(c.rpc(5)); maps = [r.facts() for _ in range(9)]
        result = dict(zip(('ingredients', 'bombs', 'potions', 'oils', 'lures', 'senses', 'consumables', 'packs', 'scrolls'), maps))
        result['bag'] = r.integer(); self.assertEqual(r.pos, len(r.data)); return result

    def notices(self, c):
        r = Reader(c.rpc(110)); self.assertEqual(r.byte(), 1)
        notice = [r.longs() for _ in range(3)]
        self.assertEqual((r.integer(), r.pos), (0, len(r.data)))
        return notice

    def pair(self, a, b):
        self.assertEqual(a.rpc(103, Q(self.bid)), b'\1' + Q(self.bid))
        self.assertEqual(b.rpc(104, Q(self.aid)), b'\1' + Q(self.aid))

    def seed_packs(self, server, count=3, full=False):
        # Stop before editing known disposable synthetic profile; never modifies an active store.
        server.stop()
        path = self.directory / 'profiles' / (server.profile_id() + '.json')
        data = json.loads(path.read_text()); data['Player']['Items']['friend_packs'] = {'1': count}
        path.write_text(json.dumps(data))
        if full:
            path = self.directory / 'profiles' / (server.profile_id(base.identity_of('social-b')) + '.json')
            data = json.loads(path.read_text()); data['Player']['Items'] = {'ingredients': {'101': 199}}
            path.write_text(json.dumps(data))
        server = self.start('social-a', self.social_env)
        return server, self.client(server), self.client(server, identity=base.identity_of('social-b'))

    def test_social_invite_accept_reject_delete_and_identity_persistence(self):
        server, a, b = self.social_server()
        second_device = self.client(server, identity=('SYNTHETIC_SOCIAL_OTHER_DEVICE', base.identity_of('social-a')[1]))
        self.assertEqual(self.friends(second_device)[0], self.aid)
        self.assertEqual(a.rpc(103, Q(self.aid)), b'\0' + Q(self.aid))
        self.assertEqual(a.rpc(103, Q(999)), b'\0' + Q(999))
        self.assertEqual(a.rpc(103, Q(self.bid)), b'\1' + Q(self.bid))
        self.assertEqual(self.friends(a)[1][self.bid]['status'], 1)
        self.assertEqual(self.friends(b)[1][self.aid]['status'], 2)
        self.assertEqual(self.notices(b)[0], [self.aid])
        self.assertEqual(a.rpc(104, Q(self.bid)), b'\0' + Q(self.bid))
        self.assertEqual(b.rpc(105, Q(self.aid)), b'\1' + Q(self.aid))
        self.assertEqual(self.friends(a)[1], {})
        self.pair(a, b)
        self.assertEqual(self.notices(a)[1], [self.bid])
        self.assertEqual(self.notices(a)[1], [])
        server.stop(); server = self.start('social-a', self.social_env)
        a, b = self.client(server), self.client(server, identity=base.identity_of('social-b'))
        self.assertEqual(self.friends(a)[0], self.aid)
        self.assertEqual(self.friends(a)[1][self.bid]['status'], 0)
        self.assertEqual(b.rpc(108, Q(self.aid)), b'\1' + Q(self.aid))
        self.assertEqual(self.friends(a)[1], {})

    def test_social_gift_once_replay_restart_and_no_unowned_send(self):
        server, a, b = self.social_server(); self.pair(a, b)
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 0)
        server, a, b = self.seed_packs(server)
        before = self.inventory(b)['ingredients'].get(101, 0)
        send = a.rpc(106, I(1) + Q(self.bid)); nonce = a.sequence
        self.assertEqual(send, b'\1' + I(1) + Q(self.bid))
        self.assertEqual(a.rpc(106, I(2) + Q(self.bid), repeat=True)[0], 0)
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid), repeat=True), send)
        self.assertEqual(self.inventory(a)['packs'], {1: 2})
        self.assertEqual(self.notices(b)[2], [self.aid])
        self.assertEqual(b.rpc(108, Q(self.aid))[0], 0)
        opened = b.rpc(107, Q(self.aid)); open_nonce = b.sequence
        self.assertEqual(opened, b'\1' + Q(self.aid) + I(1) + I(101) + I(5))
        self.assertEqual(b.rpc(107, Q(self.aid), repeat=True), opened)
        self.assertEqual(self.inventory(b)['ingredients'][101], before + 5)
        self.assertEqual(self.notices(b)[2], [])
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 0)
        server.stop(); server = self.start('social-a', self.social_env)
        a, b = self.client(server), self.client(server, identity=base.identity_of('social-b'))
        a.sequence, b.sequence = nonce, open_nonce
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid), repeat=True), send)
        self.assertEqual(b.rpc(107, Q(self.aid), repeat=True), opened)
        self.assertEqual(self.inventory(a)['packs'], {1: 2})
        self.assertEqual(self.inventory(b)['ingredients'][101], before + 5)

    def test_social_concurrent_send_and_open_preserve_economy(self):
        server, a, b = self.social_server(); self.pair(a, b); server, a, b = self.seed_packs(server)
        a2 = self.client(server); b2 = self.client(server, identity=base.identity_of('social-b'))
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda c: c.rpc(106, I(1) + Q(self.bid)), (a, a2)))
        self.assertEqual(sum(r[0] for r in replies), 1)
        before = self.inventory(b)['ingredients'].get(101, 0)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda c: c.rpc(107, Q(self.aid)), (b, b2)))
        self.assertEqual(sum(r[0] for r in replies), 1)
        self.assertEqual(self.inventory(b)['ingredients'][101], before + 5)
        self.assertEqual(self.inventory(a)['packs'], {1: 2})

    def test_social_capacity_refusal_keeps_unopened_gift(self):
        server, a, b = self.social_server(); self.pair(a, b); server, a, b = self.seed_packs(server, full=True)
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 1)
        self.assertEqual(b.rpc(107, Q(self.aid))[0], 0)
        self.assertEqual(self.friends(b)[1][self.aid]['received'][2], 0)
        self.assertEqual(self.inventory(b)['ingredients'], {101: 199})
        self.assertEqual(b.rpc(71, I(101) + I(5))[0], 1)
        self.assertEqual(b.rpc(107, Q(self.aid))[0], 1)
        self.assertEqual(self.inventory(b)['ingredients'], {101: 199})

    def test_social_mutual_invites_limits_and_malformed_stay_connected(self):
        server, a, b = self.social_server(Social__FriendLimit='1')
        third = self.client(server, identity=base.identity_of('social-c')); cid = self.friends(third)[0]
        self.assertEqual(a.rpc(103, Q(self.bid))[0], 1)
        self.assertEqual(b.rpc(103, Q(self.aid))[0], 1)
        self.assertEqual(self.friends(a)[1][self.bid]['status'], 1)
        self.assertEqual(a.rpc(103, Q(cid))[0], 0)
        self.assertEqual(third.rpc(103, Q(self.bid))[0], 0)
        for method in range(103, 109):
            result = a.rpc(method, b'\0')
            self.assertEqual(result[0], 0)
        self.assertEqual(self.friends(a)[0], self.aid)
        self.assertEqual(b.rpc(104, Q(self.aid))[0], 1)
        self.assertEqual(a.rpc(108, Q(self.bid))[0], 1)
        self.assertEqual(a.rpc(103, Q(cid))[0], 1)

    def test_social_recovers_prepared_debit_and_already_applied_grant(self):
        server, a, b = self.social_server(); self.pair(a, b); server, a, b = self.seed_packs(server)
        actor, peer = server.profile_id(), server.profile_id(base.identity_of('social-b'))
        server.stop(); path = self.directory / 'profiles/social.json'; state = json.loads(path.read_text())
        gift = dict(Sender=actor, Receiver=peer, Receipt='synthetic-crash-receipt', Day=self.NOW // 86400,
                    Pack=1, Amount=5, Claimed=False)
        request = I(1) + Q(self.bid)
        state['Pending'] = dict(Actor=actor, Other=peer, Method=106, RequestId=88001,
            Hash=hashlib.sha256(bytes([106]) + request).hexdigest().upper(), Gift=gift)
        path.write_text(json.dumps(state))
        server = self.start('social-a', self.social_env); a, b = self.client(server), self.client(server, identity=base.identity_of('social-b'))
        self.assertEqual(self.friends(b)[1][self.aid]['received'][2], 0)
        self.assertEqual(self.inventory(a)['packs'], {1: 2})
        before = self.inventory(b)['ingredients'].get(101, 0)
        server.stop(); state = json.loads(path.read_text())
        state['Pending'] = dict(Actor=peer, Other=actor, Method=107, RequestId=88002,
            Hash=hashlib.sha256(bytes([107]) + Q(self.aid)).hexdigest().upper(), Gift=gift)
        path.write_text(json.dumps(state))
        profile = self.directory / 'profiles' / (peer + '.json'); data = json.loads(profile.read_text())
        data['Player']['Items'].setdefault('ingredients', {})['101'] = before + 5
        data['Player']['Granted'].append('social:107:synthetic-crash-receipt'); profile.write_text(json.dumps(data))
        server = self.start('social-a', self.social_env); a, b = self.client(server), self.client(server, identity=base.identity_of('social-b'))
        self.assertEqual(self.friends(b)[1][self.aid]['received'][2], 1)
        self.assertEqual(self.inventory(b)['ingredients'][101], before + 5)
        self.assertIsNone(json.loads(path.read_text())['Pending'])

    def test_social_next_day_retains_unopened_gift_and_pack_drop(self):
        server, a, b = self.social_server(Social__GiftIngredientAmount='7')
        self.pair(a, b); server, a, b = self.seed_packs(server, count=4)
        self.assertEqual(a.rpc(106, I(99) + Q(self.bid))[0], 0)
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 1)
        server.stop(); self.social_env['Social__FixedUnixTime'] = str(self.NOW + 86400)
        server = self.start('social-a', self.social_env)
        a, b = self.client(server), self.client(server, identity=base.identity_of('social-b'))
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 0)
        before = self.inventory(b)['ingredients'].get(101, 0)
        self.assertEqual(b.rpc(107, Q(self.aid)), b'\1' + Q(self.aid) + I(1) + I(101) + I(7))
        self.assertEqual(self.inventory(b)['ingredients'][101], before + 7)
        self.assertEqual(a.rpc(106, I(1) + Q(self.bid))[0], 1)
        self.assertEqual(a.rpc(109, I(1) + I(1)), b'\1' + I(1) + I(1))
        self.assertEqual(self.inventory(a)['packs'], {1: 1})
        self.assertEqual(a.rpc(109, I(1) + I(2))[0], 0)
        self.assertEqual(self.inventory(a)['packs'], {1: 1})

    def test_social_admin_recovers_intent_before_revision_guard_and_backup(self):
        import test_admin
        server, a, b = self.social_server(); self.pair(a, b); server, a, b = self.seed_packs(server)
        actor, peer = server.profile_id(), server.profile_id(base.identity_of('social-b'))
        server.stop()
        root = self.directory / 'profiles'; path = root / 'social.json'
        before = json.loads((root / (actor + '.json')).read_text())
        state = json.loads(path.read_text()); gift = dict(Sender=actor, Receiver=peer, Receipt='synthetic-admin-pending',
            Day=self.NOW // 86400, Pack=1, Amount=5, Claimed=False)
        state['Pending'] = dict(Actor=actor, Other=peer, Method=106, RequestId=99001,
            Hash=hashlib.sha256(bytes([106]) + I(1) + Q(self.bid)).hexdigest().upper(), Gift=gift)
        path.write_text(json.dumps(state))
        port = test_admin.free_port(); origin = f'http://127.0.0.1:{port}'
        key = self.directory / 'synthetic-admin.key'; key.write_text(test_admin.SYNTHETIC_KEY); key.chmod(0o600)
        admin = self.directory / 'admin'; world = self.directory / 'world'; world.mkdir()
        (world / 'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":12}')
        env = dict(self.social_env, Admin__Port=str(port), Admin__Origin=origin, Admin__KeyFile=str(key),
            Admin__DataDirectory=str(admin), World__Directory=str(world))
        server = self.start('social-a', env)
        def request(route, body=None):
            headers = {'Content-Type': 'application/json', 'X-Requested-With': 'MonsterSlayerAdmin',
                'X-Monster-Admin-Key': test_admin.SYNTHETIC_KEY, 'Origin': origin}
            req = urllib.request.Request(origin + '/api/' + route,
                data=None if body is None else json.dumps(body).encode(), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                with error: return error.code, json.loads(error.read())
        for _ in range(100):
            try:
                if request('profiles')[0] == 200: break
            except OSError: time.sleep(.02)
        else: self.fail('synthetic admin listener did not become ready')
        identity_before = (root / 'players.json').read_bytes()
        stale = dict(action='reset', revision=before['Revision'], confirm=actor)
        self.assertEqual(request('profiles/' + actor, stale)[0], 409)
        recovered = json.loads((root / (actor + '.json')).read_text())
        self.assertEqual(recovered['Revision'], before['Revision'] + 1)
        self.assertEqual(recovered['Player']['Items']['friend_packs'], {'1': 2})
        self.assertEqual(recovered['Player']['Exp'], before['Player']['Exp'])
        social = json.loads(path.read_text()); self.assertIsNone(social['Pending'])
        self.assertEqual(social['Gifts'][actor + ':' + peer], gift)
        self.assertEqual(list((admin / 'backups').iterdir()), [])
        status, result = request('profiles/' + actor, dict(stale, revision=recovered['Revision']))
        self.assertEqual(status, 200)
        backup = admin / 'backups' / (result['receipt']['id'] + '.profile.json')
        self.assertEqual(json.loads(backup.read_text()), recovered)
        self.assertEqual((root / 'players.json').read_bytes(), identity_before)
        self.assertEqual(json.loads(path.read_text())['Gifts'][actor + ':' + peer], gift)

    def test_social_combat_pack_is_saved_with_fifth_win_and_replay(self):
        server, a, b = self.social_server(); server.stop()
        path = self.directory / 'profiles' / (server.profile_id() + '.json')
        data = json.loads(path.read_text()); data['Player']['Kills'] = {'166': 4}; path.write_text(json.dumps(data))
        server = self.start('social-a', self.social_env); a = self.client(server)
        r = Reader(a.rpc(111, I(16) + I(1) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1); group, = self.summoned_groups(r)
        monster = group['monsters'][0][1]
        self.assertEqual(a.rpc(113, Q(monster)), b'\1')
        body = b'\1' + I(13) + I(0) * 13 + b'\0'
        won = a.rpc(114, body); self.assertEqual(self.combat_end(Reader(won))['pack'], 1)
        self.assertEqual(a.rpc(114, body, repeat=True), won)
        self.assertEqual(self.inventory(a)['packs'], {1: 1})
        server.stop(); server = self.start('social-a', self.social_env); a = self.client(server)
        self.assertEqual(self.inventory(a)['packs'], {1: 1})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(SocialTests(name) for name in loader.getTestCaseNames(SocialTests) if name.startswith('test_social_'))
