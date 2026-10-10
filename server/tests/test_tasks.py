"""Task RPC, persistence and rotation checks using isolated synthetic profiles and a fixed task clock."""
import concurrent.futures
import gzip
import json
import shutil
import time
import unittest
import urllib.request
from pathlib import Path

import test_prototype as base

I, Q, Reader = base.I, base.Q, base.Reader


class TaskTests(base.PrototypeTests):
    NOW = 1790812800  # Synthetic midnight, UTC; the task clock is independent of story/world clocks.

    def task_server(self, daily=None, timed=None, trinkets=None, at=None, name='tasks', fresh_summons=False, extra=None):
        root = self.directory / 'tasks'
        if not root.exists():
            source = next(p for p in (base.ROOT / 'WitcherRevival.Server/tasks', base.ROOT / 'app/tasks') if p.exists())
            shutil.copytree(source, root)
        for filename, content in [('daily', daily), ('timed', timed), ('trinkets', trinkets)]:
            if content is not None:
                (root / (filename + '.json')).write_text(json.dumps({'schema_version': 1,
                    {'daily': 'tasks', 'timed': 'events', 'trinkets': 'trinkets'}[filename]: content}))
        if fresh_summons:
            path = self.profile_file(name)
            data = json.loads(path.read_text()); data['Player']['Summons'] = []; path.write_text(json.dumps(data))
        server = self.start(name, {'LocalProfile__NewProfileMode': 'reconstructed',
            'Tasks__Directory': str(root), 'Tasks__FixedUnixTime': str(self.NOW if at is None else at), **(extra or {})})
        client = self.client(server)
        client.rpc(78, I(1)+I(3)+I(1))  # Synthetic completed-tutorial fact, required by native tracking.
        return server, client

    @staticmethod
    def kills(count=4):
        return [dict(id=10000+i, slug='kill_4_monsters', type=1, target=count, gold=10+i) for i in range(1, 5)]

    def daily(self, client):
        r = Reader(client.rpc(20)); self.assertEqual(r.byte(), 1); r.integer()
        add, reroll = r.integer(), r.integer()
        entries = {r.integer(): r.ints() for _ in range(r.integer())}
        self.assertEqual(r.pos, len(r.data))
        return entries, add, reroll

    def fight(self, c, *, win=True, details=None):
        r = Reader(c.rpc(111, I(16)+I(1)+I(1000000)+I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        monster = next(row[1] for row in group['monsters'] if row[2])
        self.assertEqual(c.rpc(113, Q(monster)), b'\1')
        details = details or [0]*13
        response = c.rpc(114, bytes([win])+I(len(details))+b''.join(I(v) for v in details)+b'\0')
        return response

    def claim(self, c, task):
        r = Reader(c.rpc(81, I(task)))
        result = tuple(r.integer() for _ in range(4)); self.assertEqual(r.pos, len(r.data)); return result

    def test_tasks_daily_claims_are_atomic_replayed_and_persistent(self):
        server, c = self.task_server(self.kills(1))
        tasks, can_add, can_reroll = self.daily(c)
        self.assertEqual((len(tasks), can_add, can_reroll), (3, 0, 1))
        self.assertTrue(all(v == [0] for v in tasks.values()))
        task = next(iter(tasks))
        self.assertNotEqual(self.claim(c, task)[0], 0)
        self.fight(c)
        progress, _, _ = self.daily(c)
        self.assertTrue(all(v == [self.NOW] for v in progress.values()))
        other = self.client(server)
        c.sequence, other.sequence = 90000, 91000
        before = self.player_info(c)['gold']
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda client: self.claim(client, task), [c, other]))
        self.assertEqual(sum(r[0] == 0 for r in results), 1)
        expected = before + next(d['gold'] for d in self.kills(1) if d['id'] == task)
        self.assertEqual(self.player_info(c)['gold'], expected)
        self.assertNotEqual(self.claim(c, task)[0], 0)
        remaining = self.daily(c)[0]
        removed = next(iter(remaining))
        self.assertEqual(c.rpc(23, I(removed)), b'\1'+I(removed))
        r = Reader(c.rpc(21)); self.assertEqual(r.byte(), 1); self.assertEqual(len(r.ints()), 1)
        retained = self.daily(c)[0]
        server.stop()
        server, c = self.task_server()
        self.assertEqual(self.daily(c)[0], retained)
        self.assertEqual(self.player_info(c)['gold'], expected)

    def test_tasks_midnight_keeps_unfinished_and_resets_one_reroll(self):
        server, c = self.task_server(self.kills())
        original = self.daily(c)[0]
        old = next(iter(original)); r = Reader(c.rpc(22, I(old)))
        self.assertEqual(r.byte(), 1); replacement = r.integer()
        self.assertNotIn(replacement, original)
        self.assertEqual(c.rpc(22, I(replacement))[0], 0)
        retained = self.daily(c)[0]
        server.stop(); server, c = self.task_server(at=self.NOW+86400)
        self.assertEqual(self.daily(c)[0], retained)
        self.assertEqual(self.daily(c)[2], 1)
        self.assertEqual(c.rpc(22, I(replacement))[0], 1)

    def test_tasks_hunt_five_days_claim_once_and_missed_day_reset(self):
        server, c = self.task_server(self.kills())
        for day in range(5):
            if day:
                server.stop(); server, c = self.task_server(at=self.NOW+86400*day, fresh_summons=True)
                c.sequence = 10000*(day+1)
            c.rpc(115)
            self.fight(c)
            self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [self.NOW//86400+i for i in range(day+1)])
            self.fight(c)
            self.assertEqual(len(Reader(c.rpc(94)).weekly()['stamps']), day+1)
            self.assertFalse(any(m == 96 for m, _ in c.pushes))
        reply = c.rpc(95)
        self.assertEqual(reply, b'\1'+I(10001)+I(10001))
        self.assertEqual(c.rpc(95, repeat=True), reply)
        self.assertEqual(c.rpc(95), bytes(9))
        self.assertEqual(self.inventory(c)['scrolls'], {2: 1})
        self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [])
        used = c.rpc(111, I(16)+I(2)+I(1000000)+I(1000000))
        r = Reader(used); self.assertEqual(r.byte(), 1)
        owned_group, = self.summoned_groups(r)
        self.assertEqual(len(owned_group['monsters']), 5)
        self.assertEqual(c.rpc(111, I(16)+I(2)+I(1000000)+I(1000000), repeat=True), used)
        self.assertEqual(c.rpc(111, I(16)+I(2)+I(1000000)+I(1000000)), b'\0'+I(0))
        self.assertEqual(self.inventory(c)['scrolls'], {})
        modifier, = [m for m in server.state()['player']['modifiers'] if m['id'] == 13]
        self.assertEqual((modifier['start'], modifier['expire']), (owned_group['start'], owned_group['start']+500))
        server.stop(); server, c = self.task_server(at=self.NOW+86400*5, fresh_summons=True)
        c.sequence = 200000; self.fight(c)
        self.assertEqual(len(Reader(c.rpc(94)).weekly()['stamps']), 1)
        server.stop(); server, c = self.task_server(at=self.NOW+86400*7)
        self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [])
        self.assertEqual(self.inventory(c)['scrolls'], {})

    def test_tasks_timed_claims_and_expiry_clear_native_event_body(self):
        event = dict(id=24001, name='ARACHAS_WEEK_1', start=self.NOW, end=self.NOW+86400,
                     gold=70, tasks=[dict(id=12001, slug='kill_4_monsters', type=1, target=1, gold=13,
                     rewards=[dict(type=3, item=205, amount=1)])], rewards=[dict(type=1, item=101, amount=2)])
        server, c = self.task_server(self.kills(), timed=[event])
        batch = base.decode_batch(c.rpc(115))
        r = Reader(batch[122]); self.assertEqual((r.byte(), r.integer(), r.integer()), (1, 0, 24001))
        self.assertEqual((r.integer(), r.integer(), r.ints(), r.ints(), r.integer()), (1, 12001, [0], [], 0))
        self.assertEqual(self.claim(c, 12001)[3], 2)
        self.assertEqual(c.rpc(123), b'\0')
        before = self.player_info(c)['gold']; self.fight(c)
        self.assertEqual(self.claim(c, 12001), (0, 12001, before+13, 2))
        self.assertNotEqual(self.claim(c, 12001)[0], 0)
        r = Reader(c.rpc(123)); self.assertEqual((r.byte(), r.integer(), r.integer(), r.integer()), (1, 0, 24001, 70))
        self.assertEqual((r.integer(), r.integer(), r.integer(), r.integer()), (1, 1, 101, 2))
        self.assertEqual(self.player_info(c)['gold'], before+83)
        self.assertEqual(c.rpc(123), b'\0')
        self.assertEqual(self.inventory(c)['potions'], {205: 1})
        server.stop(); server, c = self.task_server(at=self.NOW+86401)
        c.sequence = 300000
        self.assertEqual(c.rpc(125), b'\1')
        self.assertEqual(c.rpc(122), b'\1'+I(0)+I(-1)+I(0)+I(0)+I(0))
        self.assertEqual(self.claim(c, 12001)[3], 2)
        self.assertEqual(c.rpc(123), b'\0')

    def test_tasks_action_windows_include_losses_and_zero_action_fights(self):
        daily = self.kills()
        daily[0] = dict(id=10001, slug='on_your_guard', type=11, target=10, fights=2, actions=[2], gold=10)
        daily = daily[:3]
        server, c = self.task_server(daily)
        self.daily(c)
        self.assertEqual(self.daily(c)[0][10001], [0, 0])
        details = [0]*13; details[2] = 6
        self.fight(c, win=False, details=details)
        self.assertEqual(self.daily(c)[0][10001], [0, 6])
        self.fight(c, win=False)
        self.assertEqual(self.daily(c)[0][10001], [6, 0])
        self.fight(c, win=False)
        self.assertEqual(self.daily(c)[0][10001], [0, 0])
        self.assertNotEqual(self.claim(c, 10001)[0], 0)
        self.fight(c, win=False, details=details); self.fight(c, win=False, details=details)
        self.fight(c, win=False)  # Completion stays latched even when a subsequent window would be smaller.
        self.assertEqual(self.claim(c, 10001)[0], 0)
        self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [])

    def test_tasks_timed_sync_keeps_claimed_and_progress_lists_disjoint(self):
        event = dict(id=24001, name='ARACHAS_WEEK_1', start=self.NOW, end=self.NOW+86400,
                     gold=70, rewards=[], tasks=[
                         dict(id=12001, slug='kill_4_monsters', type=1, target=1, gold=13),
                         dict(id=12002, slug='kill_4_monsters', type=1, target=2, gold=17)])
        server, c = self.task_server(self.kills(), timed=[event])
        c.rpc(115); self.fight(c)
        before = self.player_info(c)['gold']
        self.assertEqual(self.claim(c, 12001), (0, 12001, before+13, 2))

        def check(body, pending, claimed, final=False):
            r = Reader(body)
            self.assertEqual((r.byte(), r.integer(), r.integer()), (1, 0, event['id']))
            progress = [(r.integer(), r.ints()) for _ in range(r.integer())]
            received = r.ints()
            self.assertEqual((r.integer(), r.pos), (int(final), len(r.data)))
            self.assertEqual(dict(progress), pending)
            self.assertEqual(received, claimed)
            # Native 0x18288BC creates separate progress objects for both lists, without deduplication.
            rendered_ids = [task for task, _ in progress]+received
            self.assertEqual(sorted(rendered_ids), [12001, 12002])

        check(c.rpc(122), {12002: [self.NOW, 0]}, [12001])
        server.stop(); server, c = self.task_server(at=self.NOW+1)
        c.sequence = 400000
        check(base.decode_batch(c.rpc(115))[122], {12002: [self.NOW, 0]}, [12001])
        self.assertNotEqual(self.claim(c, 12001)[0], 0)
        self.assertEqual(self.player_info(c)['gold'], before+13)
        self.fight(c)
        self.assertEqual(self.claim(c, 12002), (0, 12002, before+30, 2))
        check(c.rpc(122), {}, [12001, 12002])
        self.assertEqual(c.rpc(123), b'\1'+I(0)+I(event['id'])+I(70)+I(0))
        check(c.rpc(122), {}, [12001, 12002], final=True)
        self.assertEqual(self.player_info(c)['gold'], before+100)

    def test_tasks_crafting_preparation_and_trinkets_follow_saved_actions(self):
        daily = [dict(id=10001, slug='brewing', type=6, target=1, item_type=3, gold=5),
                 dict(id=10002, slug='witcher_the_professional', type=10, target=1, item_type=4, gold=5),
                 dict(id=10003, slug='kill_4_monsters', type=1, target=4, gold=5)]
        trophy = dict(id=20001, slug='trophy_in_forest_dark', type=1, target=1, monsters=[1])
        server, c = self.task_server(daily, trinkets=[trophy])
        c.rpc(115); server.stop()
        # Synthetic crafting fixture: a completed known recipe and one owned preparation item.
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Brewers'] = [dict(InstanceId=1, Type=1201, UsesLeft=-1, WorkingRecipe=2102, FinishTime=1)]
        data['Player']['Items']['oils'] = {'301': 1}
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        self.assertEqual(c.rpc(68, Q(1))[0], 1)
        self.assertEqual(self.daily(c)[0][10001], [1])
        self.assertEqual(c.rpc(68, Q(1))[0], 0)
        self.assertEqual(c.rpc(89, I(301)+I(0)), b'\1')
        self.assertEqual(c.rpc(89, I(301)+I(0)), b'\0')
        self.assertEqual(self.daily(c)[0][10002], [1])
        self.fight(c)
        response = Reader(c.rpc(24)); self.assertEqual(response.byte(), 1)
        self.assertEqual(response.ints(), [20001, self.NOW])
        self.assertEqual([body for method, body in c.pushes if method == 25], [I(20001)])
        self.fight(c); c.rpc(3)
        self.assertEqual(len([1 for method, _ in c.pushes if method == 25]), 1)
        other = self.client(server, identity=('ANOTHER_SYNTHETIC_DEVICE', ''))
        self.assertEqual(other.rpc(24), b'\1'+I(0))
        server.stop(); server, c = self.task_server()
        self.assertEqual(c.rpc(24), b'\1'+I(2)+I(20001)+I(self.NOW))

    def test_tasks_first_leshen_trinket_rejects_hounds_and_accepts_leshen(self):
        # Exercise the shipped definition, not a synthetic substitute for its species list.
        server, c = self.task_server()
        c.rpc(115); server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Kills'] = {'166': 1, '30': 2, '188': 1}
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        vintage = I(20025)+I(self.NOW)   # The Best Vintage, every player's from the start
        self.assertEqual(c.rpc(24), b'\1'+I(2)+vintage)
        c.rpc(115)
        self.assertFalse(any(method == 25 for method, _ in c.pushes))
        server.stop()
        data = json.loads(path.read_text()); data['Player']['Kills']['31'] = 1
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        self.assertEqual(c.rpc(24), b'\1'+I(4)+I(20002)+I(self.NOW)+vintage)
        server.stop(); server, c = self.task_server()
        self.assertEqual(c.rpc(24), b'\1'+I(4)+I(20002)+I(self.NOW)+vintage)

    def test_tasks_season1_trinkets_follow_endings_and_catch_up(self):
        def achievements(c):
            r = Reader(c.rpc(24)); self.assertEqual(r.byte(), 1); values = r.ints()
            return set(values[::2])
        server, c = self.task_server()
        self.assertEqual(achievements(c), {20025})   # The Best Vintage: every player, from the start
        server.stop()
        # A profile that played Good Money, Pride and "A Joint Venture" before these trinkets existed catches up.
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['QuestStage'] = 'jv_done'
        data['Player']['Granted'].append('joint_venture')
        data['Player']['Story'] = {'Active': [], 'Started': [], 'Finished': [149, 150], 'Outputs': [1015, 1078],
                                   'Tracked': None, 'Reached': {}, 'Clock': 0}
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        self.assertEqual(achievements(c), {20025, 20014, 20015, 20016})
        server.stop()
        # Each branch of an ending has its own trinket; the season journal waits for all twelve quests.
        data = json.loads(path.read_text())
        data['Player']['Story']['Finished'] = [104, 147, 148, 149, 150, 152, 153, 154, 158, 159, 160, 161]
        data['Player']['Story']['Outputs'] += [1043, 1039, 1116, 1275, 1176]   # curse broken, Lothar killed, Dehael died
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        self.assertEqual(achievements(c), {20025, 20014, 20015, 20016, 20018, 20020, 20021, 20023, 20024})

    def test_tasks_offline_leshen_repair_survives_refresh_without_reaward(self):
        from test_trinket_repair import repair
        import copy
        source = next(p for p in (base.ROOT/'WitcherRevival.Server/tasks/trinkets.json',
                                  base.ROOT/'app/tasks/trinkets.json') if p.exists())
        old = json.loads(source.read_text())['trinkets']
        next(d for d in old if d['id'] == 20002)['monsters'] = [166, 30]
        server, c = self.task_server(trinkets=old)
        c.rpc(115); server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Kills'] = {'166': 1}; path.write_text(json.dumps(data))
        server, c = self.task_server()
        vintage = I(20025)+I(self.NOW)   # The Best Vintage, every player's from the start
        self.assertEqual(c.rpc(24), b'\1'+I(4)+I(20002)+I(self.NOW)+vintage)
        paths = {'trinkets': self.directory/'tasks/trinkets.json',
                 'manifest': self.directory/'profiles/tasks-catalogue.json', 'profile': path}
        expected = {k:repair.digest(p.read_bytes()) for k,p in paths.items()}
        with self.assertRaisesRegex(ValueError, 'Stop'):
            repair.repair(self.directory/'tasks', self.directory/'profiles', path.stem,
                          self.directory/'repair-backup', expected, apply=True)
        server.stop(); before = json.loads(path.read_text())
        expected = {k:repair.digest(p.read_bytes()) for k,p in paths.items()}
        result = repair.repair(self.directory/'tasks', self.directory/'profiles', path.stem,
                              self.directory/'repair-backup', expected, apply=True)
        self.assertEqual(result['status'], 'applied')
        wanted = copy.deepcopy(before); wanted['Revision'] += 1
        del wanted['Player']['Tasks']['Achievements']['20002']
        self.assertEqual(json.loads(path.read_text()), wanted)
        server, c = self.task_server()
        self.assertEqual(c.rpc(24), b'\1'+I(2)+vintage); c.rpc(115)
        self.assertEqual(c.rpc(24), b'\1'+I(2)+vintage)
        self.assertFalse(any(method == 25 for method, _ in c.pushes))

    def test_tasks_bad_reload_keeps_catalogue_and_malformed_rpcs_keep_session(self):
        server, c = self.task_server(self.kills())
        original = self.daily(c)
        path = self.directory/'tasks'/'daily.json'
        path.write_text('{')
        time.sleep(1.05)
        self.assertEqual(self.daily(c), original)
        data = {'schema_version': 1, 'tasks': self.kills()}
        data['tasks'][0]['target'] = 99
        path.write_text(json.dumps(data)); time.sleep(1.05)
        self.assertEqual(self.daily(c), original)
        for method, length in [(21, 5), (22, 5), (23, 5), (81, 16), (86, 5), (95, 9), (123, 1), (125, 1)]:
            self.assertEqual(len(c.rpc(method, b'x')), length)
            self.assertEqual(len(self.daily(c)[0]), 3)

    def test_tasks_static_transports_agree_and_every_reference_resolves(self):
        server, c = self.task_server()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
            data = json.loads(gzip.decompress(response.read()))
        preloader = self.client(server, auth=False); preloader.send(4, I(1)+I(0))
        channel, payload = preloader.receive(); r = Reader(payload)
        self.assertEqual((channel, r.integer()), (4, 1))
        self.assertEqual(json.loads(gzip.decompress(r.take(r.integer()))), data)
        contracts = {row['id'] for row in data['contracts']}
        self.assertTrue(all(row['contract_id'] in contracts for row in data['daily_quests']+data['achievements']))
        self.assertEqual(len([d for d in data['daily_quests'] if d['daily_quest_type_id'] == 1]), 42)
        self.assertEqual(len([d for d in data['daily_quests'] if d['daily_quest_type_id'] == 2]), 3)
        self.assertEqual(len(data['achievements']), 25)
        self.assertEqual(len(contracts), 70)
        combat = [row for row in data['contracts'] if row['contract_type_id'] == 11]
        self.assertTrue(combat)
        # Native map/nest progress skips its sword filter only for -1. Zero means steel,
        # which hid silver-sword progress despite the saved cumulative count increasing.
        self.assertTrue(all(row['value4'] == -1 for row in combat))
        self.assertEqual(next(row for row in combat if row['id'] == 12002)['value1'], 0)
        self.assertIn(20, base.decode_batch(c.rpc(115)))
        self.assertEqual(data['summoning_scrolls'], [dict(id=2, slug='summoning_scroll_basic', priority=0, duration=500)])
        modifier_ids = {m['id'] for m in data['player_modifiers']}
        self.assertTrue(all(row['player_modifier_id'] in modifier_ids for row in data['summoning_scrolls_player_modifiers']))

    def test_tasks_invalid_initial_data_fails_before_player_storage(self):
        self.task_server()
        path = self.directory/'tasks'/'daily.json'
        doc = json.loads(path.read_text()); doc['tasks'][0]['monsters'] = [2147483647]
        path.write_text(json.dumps(doc))
        root = self.directory/'invalid-start'; root.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'task condition'):
            base.Server(root, 'invalid-tasks', {'Tasks__Directory': str(path.parent)})
        self.assertFalse((root/'profiles').exists())

    def test_tasks_supplied_timed_event_reward_chain_restart_and_expiry(self):
        source = next(p for p in (base.ROOT/'WitcherRevival.Server/tasks', base.ROOT/'app/tasks') if p.exists())
        event, = json.loads((source/'timed.json').read_text())['events']
        now = event['start']+1
        server, c = self.task_server(at=now)
        batch = base.decode_batch(c.rpc(115)); r = Reader(batch[122])
        self.assertEqual((r.byte(), r.integer(), r.integer()), (1, 0, event['id']))
        tasks = {r.integer(): r.ints() for _ in range(r.integer())}
        self.assertEqual(tasks, {12001: [0]*4, 12002: [0], 12003: [0]})
        self.assertEqual((r.ints(), r.integer(), r.pos), ([], 0, len(r.data)))
        self.assertEqual(c.rpc(123), b'\0')
        before = self.player_info(c)['gold']; server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Items']['oils'] = {'301': 1}
        path.write_text(json.dumps(data))
        server, c = self.task_server(at=now)
        self.assertEqual(c.rpc(89, I(301)+I(0)), b'\1')
        details = [0]*13; details[8] = 9
        for _ in range(3): self.fight(c, details=details)
        def fast_progress():
            r = Reader(c.rpc(122)); self.assertEqual((r.byte(), r.integer(), r.integer()), (1, 0, event['id']))
            return {r.integer(): r.ints() for _ in range(r.integer())}[12002]
        self.assertEqual(fast_progress(), [27])
        # The tutorial fixture supplies only three monsters; replace that synthetic group after restart.
        server.stop(); server, c = self.task_server(at=now, fresh_summons=True)
        self.assertEqual(fast_progress(), [27])
        details[8] = 3
        self.fight(c, details=details)
        self.assertEqual(fast_progress(), [30])
        for task in (12001, 12002): self.assertEqual(self.claim(c, task)[0], 0)
        self.assertEqual(c.rpc(123), b'\0')  # Every complete subtask reward must first be claimed.
        self.assertEqual(self.claim(c, 12003), (0, 12003, before+100, 2))
        self.assertEqual(self.inventory(c)['potions'].get(205), 1)
        expected = b'\1'+I(0)+I(event['id'])+I(250)+I(1)+I(16)+I(2)+I(1)
        self.assertEqual(c.rpc(123), expected)
        self.assertEqual(c.rpc(123, repeat=True), expected)
        self.assertEqual(c.rpc(123), b'\0')
        self.assertEqual(self.player_info(c)['gold'], before+350)
        self.assertEqual(self.inventory(c)['scrolls'], {2: 1})
        server.stop(); server, c = self.task_server(at=now)
        self.assertEqual(c.rpc(123), b'\0')
        self.assertEqual(self.inventory(c)['scrolls'], {2: 1})
        self.assertEqual(self.player_info(c)['gold'], before+350)
        server.stop(); server, c = self.task_server(at=event['end']+1)
        self.assertEqual(c.rpc(122), b'\1'+I(0)+I(-1)+I(0)+I(0)+I(0))
        self.assertEqual(c.rpc(123), b'\0')
        self.assertEqual(self.inventory(c)['scrolls'], {2: 1})

    def test_tasks_herbs_and_nest_actions_use_only_accepted_transactions(self):
        cell = 0x4704440000000000
        url, _ = self.playable_service(lambda ids, epoch: {i: {'center': [10.0, 20.0], 'places': [
            {'id': f'task-{int(i):016x}-{epoch}-{n}', 'lat': 10.0+n/1000, 'lng': 20.0, 'biomes': [1], 'kind': 'path'}
            for n in range(8)]} for i in ids})
        daily = [dict(id=10001, slug='herbalism', type=12, target=4, items=[101, 102], gold=5),
                 dict(id=10002, slug='on_your_guard', type=11, target=8, fights=2, actions=[2], gold=5),
                 dict(id=10003, slug='kill_4_monsters', type=1, target=4, gold=5)]
        trophy = dict(id=20001, slug='trophy_legendary_monster_slayer', type=2, target=1, min_level=10)
        server, c = self.task_server(daily, trinkets=[trophy], extra={'Playable__Url': url})
        c.rpc(115); server.stop()
        path = self.profile_file('tasks'); profile = json.loads(path.read_text())
        profile['Player']['Exp'] = 45000; profile['Player']['LevelAnnounced'] = 10
        path.write_text(json.dumps(profile))
        server, c = self.task_server(extra={'Playable__Url': url})
        world = self.locations_by_cell(c.rpc(40, I(1)+Q(cell)))
        herb = world['herbs'][0]['instance']
        r = Reader(c.rpc(19, Q(herb))); self.assertEqual(r.byte(), 1); loot = r.ints()
        amount = sum(1 for i in loot if i in (101, 102))
        self.assertEqual(self.daily(c)[0][10001], [min(4, amount)])
        self.assertEqual(c.rpc(19, Q(herb))[0], 0)
        self.assertEqual(self.daily(c)[0][10001], [min(4, amount)])
        nest = world['nests'][0]['instance']
        details = ([0, 0, 4], [0, 0, 4], [])
        c.rpc(53, self.nest_combat(False, nest, details=details))
        self.assertEqual(self.daily(c)[0][10002], [0, 0])
        c.rpc(52, Q(nest)); c.rpc(53, self.nest_combat(False, nest, details=details))
        self.assertEqual(self.daily(c)[0][10002], [4, 4])
        self.assertEqual(self.claim(c, 10002)[0], 0)
        self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [])
        c.rpc(52, Q(nest)); c.rpc(53, self.nest_combat(True, nest))
        self.assertEqual(len(Reader(c.rpc(94)).weekly()['stamps']), 1)
        self.assertEqual(c.rpc(24), b'\1'+I(2)+I(20001)+I(self.NOW))

    def test_tasks_restart_rejects_changed_catalogue_without_touching_profile(self):
        server, c = self.task_server(self.kills())
        self.daily(c); server.stop()
        saved = self.profile_file('tasks').read_bytes()
        manifest = (self.directory/'profiles'/'tasks-catalogue.json').read_bytes()
        path = self.directory/'tasks'/'daily.json'
        data = json.loads(path.read_text()); data['tasks'][0]['gold'] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, 'persisted IDs'):
            self.task_server()
        self.assertEqual(self.profile_file('tasks').read_bytes(), saved)
        self.assertEqual((self.directory/'profiles'/'tasks-catalogue.json').read_bytes(), manifest)
        # New IDs are permitted at the next coordinated restart, while old definitions remain stable.
        data['tasks'][0]['gold'] -= 1
        data['tasks'].append(dict(id=10005, slug='kill_4_monsters', type=1, target=4, gold=20))
        path.write_text(json.dumps(data)); server, c = self.task_server()
        self.assertEqual(len(self.daily(c)[0]), 3)

    def test_tasks_tutorial_gate_and_absolute_level_contract(self):
        daily = self.kills()[:3]
        daily[0] = dict(id=10001, slug='kill_4_monsters', type=7, target=1, gold=5)
        server, c = self.task_server(daily)
        self.assertEqual(self.daily(c)[0][10001], [1])
        c.rpc(78, I(1)+I(3)+I(0))
        self.assertNotEqual(self.claim(c, 10001)[0], 0)
        c.rpc(78, I(1)+I(3)+I(1))
        self.assertEqual(self.claim(c, 10001)[0], 0)
        c.rpc(78, I(1)+I(3)+I(0))
        self.fight(c)
        self.assertTrue(all(v == [0]*4 for v in self.daily(c)[0].values()))
        self.assertEqual(Reader(c.rpc(94)).weekly()['stamps'], [])

    def test_tasks_skills_quests_and_story_outputs_count_as_they_happen(self):
        # Types 8 (skills learned), 9 (quests finished) and 13 (story outputs reached, here a trinket).
        daily = self.kills()[:3]
        daily[0] = dict(id=10001, slug='kill_4_monsters', type=8, target=1, gold=5)
        daily[1] = dict(id=10002, slug='kill_4_monsters', type=9, target=1, quests=[149], gold=5)
        server, c = self.task_server(daily, trinkets=[dict(id=20001, slug='trophy_in_forest_dark', type=13, target=1, outputs=[1001])])
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
            skills = {row['slug']: row['id'] for row in reversed(json.loads(gzip.decompress(response.read()))['skills'])}
        self.daily(c)                                                                     # issued as the game asks at boot
        for output in ('griffin_1', 'wraith_won', 'gargoyle'):                            # 1100 XP: level 2's skill points
            c.rpc(57, self.completion_body({}, instance=self.TUT_EXAM, output=output))
        self.assertEqual(c.rpc(64, I(skills['muscle_memory']))[0], 1)
        self.assertEqual(self.daily(c)[0][10001], [1])
        server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['QuestStage'], data['Facts'] = 'jv_done', {'100': 4}                       # "A Joint Venture" done
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        for key, output, facts, _ in base.SEASON1['walks']['149']:                       # Good Money, as the game plays it
            node = next(n for n in base.SEASON1['nodes'] if n['key'] == key)
            c.rpc(57, self.completion_body({int(k): v for k, v in facts.items()}, instance=node['instance'], output=output))
        self.assertEqual(self.daily(c)[0][10002], [1])
        self.assertEqual(c.rpc(24), b'\1'+I(2)+I(20001)+I(self.NOW))

    def test_tasks_every_kill_and_story_target_can_be_met(self):
        # A kill task's monsters spawn in the world or fall in a story fight; a story trinket's outputs exist.
        folder = next(p for p in (base.ROOT / 'WitcherRevival.Server/tasks', base.ROOT / 'app/tasks') if p.exists())
        load = lambda name, key: json.loads((folder / f'{name}.json').read_text())[key]
        tasks = load('daily', 'tasks') + load('trinkets', 'trinkets') + [t for e in load('timed', 'events') for t in e['tasks']]
        met = {s['monster_id'] for s in base.WORLD['species']} | {int(k) for o in base.SEASON1['outputs'] for k in o['kills']}
        outputs = {o['id'] for o in base.SEASON1['outputs']}
        for task in tasks:
            with self.subTest(task=task['id']):
                self.assertLessEqual(set(task.get('monsters') or []), met)
                self.assertLessEqual(set(task.get('outputs') or []), outputs)

    def test_tasks_bombs_count_owned_consumption_once(self):
        daily = self.kills()[:3]
        daily[0] = dict(id=10001, slug='kill_4_monsters', type=4, target=3, items=[401], gold=5)
        server, c = self.task_server(daily)
        self.daily(c); server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Items']['bombs'] = {'401': 2}
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        reply = c.rpc(39, I(401)); self.assertEqual(reply, b'\1'+I(1))
        self.assertEqual(c.rpc(39, I(401), repeat=True), reply)
        self.assertEqual(self.daily(c)[0][10001], [1])
        c.rpc(39, I(401)); c.rpc(39, I(401))  # The graph's free tutorial bomb earns no owned-item progress.
        self.assertEqual(self.daily(c)[0][10001], [2])
        self.assertNotEqual(self.claim(c, 10001)[0], 0)

    def test_tasks_disable_preserves_rewards_and_hides_missing_static_references(self):
        server, c = self.task_server(self.kills(1), trinkets=[
            dict(id=20001, slug='trophy_in_forest_dark', type=1, target=1, monsters=[1])])
        self.daily(c); self.fight(c); server.stop()
        path = self.profile_file('tasks'); data = json.loads(path.read_text())
        data['Player']['Items']['summoning_scrolls'] = {'2': 2}
        path.write_text(json.dumps(data))
        server, c = self.task_server()
        self.assertEqual(c.rpc(111, I(16)+I(2)+I(1000000)+I(1000000))[0], 1)
        server.stop(); before = json.loads(path.read_text())['Player']
        server = self.start('tasks', {'LocalProfile__NewProfileMode': 'reconstructed'})
        c = self.client(server); batch = base.decode_batch(c.rpc(115))
        self.assertEqual(batch[24], b'\1'+I(0))
        groups = self.summoned_groups(Reader(c.rpc(112)))
        self.assertTrue(all(g['item'] != 2 for g in groups))
        self.assertEqual(self.inventory(c)['scrolls'], {})
        self.assertEqual(c.rpc(111, I(16)+I(2)+I(1000000)+I(1000000)), b'\0'+I(0))
        server.stop(); after = json.loads(path.read_text())['Player']
        for field in ('Tasks', 'Items', 'Gold', 'Modifiers', 'Summons'):
            self.assertEqual(after[field], before[field])
        server, c = self.task_server()
        self.assertEqual(self.inventory(c)['scrolls'], {2: 1})
        self.assertEqual(c.rpc(24), b'\1'+I(2)+I(20001)+I(self.NOW))


def load_tests(loader, tests, pattern):
    # Reuse the existing protocol helpers without running its inherited regression suite twice.
    return unittest.TestSuite(TaskTests(name) for name in loader.getTestCaseNames(TaskTests) if name.startswith('test_tasks_'))
