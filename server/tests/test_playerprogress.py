"""Read-only player progress acceptance using isolated servers and synthetic saved profiles."""
import json
import unittest
import urllib.error
import urllib.request

import test_admin as admin


def pascal(value):
    if isinstance(value, dict):
        return {''.join(part.title() for part in key.split('_')): pascal(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [pascal(item) for item in value]
    return value


class PlayerProgressTests(unittest.TestCase):
    NOW = 1791000000
    request = admin.AdminTests.request
    restart = admin.AdminTests.restart
    profile = admin.AdminTests.profile
    offline = admin.AdminTests.offline

    def setUp(self):
        admin.AdminTests.setUp(self)
        self.restart(Tasks__FixedUnixTime=str(self.NOW))
        self.daily = json.loads((self.tasks / 'daily.json').read_text())['tasks']
        self.event = json.loads((self.tasks / 'timed.json').read_text())['events'][0]
        self.trinkets = json.loads((self.tasks / 'trinkets.json').read_text())['trinkets']

    @staticmethod
    def entry(definition, progress=0, claimed=False, samples=None):
        return dict(Definition=pascal(definition), Progress=progress, Claimed=claimed, Samples=samples)

    def saved_fixture(self, change, **options):
        client, profile = self.profile('synthetic-progress')
        self.offline(client, profile)
        self.server.stop()
        path = self.directory / 'profiles' / (profile + '.json')
        saved = json.loads(path.read_text())
        saved['Facts']['3'] = 1
        saved['Player']['Tasks'] = dict(
            Day=self.NOW // 86400, Daily=[], Issued=0, Seen=[], Reshuffled=False,
            Stamps=[], LastStamp=-1, HuntClaims=0, Events={}, Achievements={}, Receipts={},
            LastTime=self.NOW, NestsCleared=0, TrophyProgress={})
        change(saved)
        path.write_text(json.dumps(saved))
        self.restart(**options)
        return profile, path

    def read(self, profile):
        status, result = self.request('profiles/' + profile + '/progress')
        self.assertEqual(status, 200, result)
        return result

    @staticmethod
    def rows(section):
        return {row['id']: row for row in section['rows']}

    def test_progress_auth_scope_missing_target_and_no_mutation_method(self):
        _, profile = self.profile()
        path = 'profiles/' + profile + '/progress'
        self.assertEqual(self.request(path, auth=False)[0], 403)
        self.assertEqual(self.request(path, headers={'X-Monster-Admin-Key': 'wrong'})[0], 403)
        self.assertEqual(self.request(path, origin=False)[0], 200)
        self.assertEqual(self.request('profiles/p' + '0' * 31 + '/progress')[0], 404)
        self.assertEqual(self.request('profiles/INVALID/progress')[0], 400)
        request = urllib.request.Request(self.origin + '/api/' + path, method='POST', data=b'{}', headers={
            'X-Monster-Admin-Key': admin.SYNTHETIC_KEY,
            'Origin': self.origin, 'X-Requested-With': 'MonsterSlayerAdmin'})
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(request)
        self.assertEqual(failure.exception.code, 405)
        failure.exception.close()
        request = urllib.request.Request(self.origin + '/api/' + path,
                                         headers={'X-Monster-Admin-Key': admin.SYNTHETIC_KEY})
        with urllib.request.urlopen(request) as response:
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_daily_saved_completion_claim_gate_and_missing_history(self):
        def prepare(saved):
            tasks = saved['Player']['Tasks']
            fast = next(d for d in self.daily if d['id'] == 10006)
            kill = next(d for d in self.daily if d['id'] == 10001)
            tasks.update(Daily=[self.entry(fast, 30), self.entry(kill, 3)], Issued=3, Seen=[10001, 10006, 10002])
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        before_receipts = self.request('receipts')[1]
        for _ in range(2):
            result = self.read(profile)
            rows = self.rows(result['daily'])
            self.assertEqual((rows[10006]['progress'], rows[10006]['target']), (30, 30))
            self.assertEqual(rows[10006]['definition']['fights'], 0)
            self.assertTrue(rows[10006]['completedSaved'])
            self.assertTrue(rows[10006]['pendingClaim'])
            self.assertEqual(rows[10001]['rewardState'], 'incomplete')
            self.assertFalse(result['daily']['historyAvailable'])
            self.assertEqual(set(rows), {10001, 10006})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.request('receipts')[1], before_receipts)

    def test_tracking_gate_blocks_claim_without_erasing_saved_completion(self):
        def prepare(saved):
            saved['Facts']['3'] = 0
            saved['Player']['Tasks']['Daily'] = [self.entry(self.daily[0], self.daily[0]['target'])]
        profile, _ = self.saved_fixture(prepare)
        row = self.read(profile)['daily']['rows'][0]
        self.assertTrue(row['completedSaved'])
        self.assertFalse(row['pendingClaim'])
        self.assertEqual(row['rewardState'], 'blocked-tracking')

    def event_state(self, claimed=False, tasks_claimed=False):
        return dict(Id=self.event['id'], Claimed=claimed,
                    Tasks=[self.entry(d, d['target'], tasks_claimed) for d in self.event['tasks']])

    def test_timed_individual_claims_are_distinct_from_final_reward(self):
        def prepare(saved):
            event = self.event_state()
            event['Tasks'][0]['Claimed'] = True
            saved['Player']['Tasks']['Events'][str(self.event['id'])] = event
        profile, _ = self.saved_fixture(prepare)
        event = self.read(profile)['timed']['rows'][0]
        self.assertEqual(event['window'], 'active')
        self.assertEqual(event['finalRewardState'], 'tasks-unclaimed')
        self.assertFalse(event['pendingClaim'])
        self.assertEqual(event['tasks'][0]['rewardState'], 'claimed')
        self.assertFalse(event['tasks'][0]['pendingClaim'])
        self.assertTrue(all(t['pendingClaim'] for t in event['tasks'][1:]))

    def test_timed_final_reward_requires_claimed_tasks_and_expiry_refuses_it(self):
        def prepare(saved):
            # Final-event claiming does not use the individual-task tutorial gate.
            saved['Facts']['3'] = 0
            saved['Player']['Tasks']['Events'][str(self.event['id'])] = self.event_state(tasks_claimed=True)
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        event = self.read(profile)['timed']['rows'][0]
        self.assertEqual(event['finalRewardState'], 'ready-to-claim')
        self.assertTrue(event['pendingClaim'])
        self.restart(Tasks__FixedUnixTime=str(self.event['end'] + 1))
        event = self.read(profile)['timed']['rows'][0]
        self.assertEqual(event['window'], 'expired')
        self.assertEqual(event['finalRewardState'], 'expired')
        self.assertFalse(event['pendingClaim'])
        self.assertEqual(path.read_bytes(), original)

    def test_absent_task_state_and_event_do_not_become_fabricated_zero_progress(self):
        profile, path = self.saved_fixture(lambda s: s['Player'].update(Tasks=None))
        original = path.read_bytes()
        result = self.read(profile)
        self.assertEqual(result['daily']['availability'], 'not-recorded')
        self.assertEqual(result['daily']['rows'], [])
        self.assertIsNone(result['hunt']['stamps'])
        event = result['timed']['rows'][0]
        self.assertEqual(event['availability'], 'not-recorded')
        self.assertEqual(event['finalRewardState'], 'not-recorded')
        self.assertTrue(all(t['progress'] is None and not t['pendingClaim'] for t in event['tasks']))
        self.assertTrue(result['clock']['requiresGameplayRefresh'])
        self.assertEqual(path.read_bytes(), original)

    def test_clock_floor_expired_hunt_and_incomplete_window_are_read_only(self):
        def prepare(saved):
            state = saved['Player']['Tasks']
            trophy = next(d for d in self.trinkets if d['id'] == 20012)
            state.update(Day=self.NOW // 86400 - 3, LastTime=self.NOW - 7200,
                         Stamps=[self.NOW // 86400 - 4] * 5, LastStamp=self.NOW // 86400 - 4)
            state['TrophyProgress']['20012'] = self.entry(trophy, 2, samples=[self.NOW - 7200] * 2)
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        result = self.read(profile)
        self.assertEqual(result['clock']['reset'], '00:00 UTC')
        self.assertTrue(result['clock']['fixedForTesting'])
        self.assertTrue(result['clock']['requiresGameplayRefresh'])
        self.assertEqual(result['hunt']['rewardState'], 'expired-streak')
        self.assertFalse(result['hunt']['pendingClaim'])
        self.assertEqual(len(result['hunt']['stamps']), 5)
        window = self.rows(result['trinkets'])[20012]
        self.assertEqual(window['progress'], 2)
        self.assertTrue(window['requiresGameplayRefresh'])
        self.restart(Tasks__FixedUnixTime=str(self.NOW - 10800))
        result = self.read(profile)
        self.assertEqual(result['clock']['unixTime'], self.NOW - 7200)
        self.assertEqual(path.read_bytes(), original)

    def test_story_keeps_intro_separate_ignores_obsolete_active_and_unknown_ids_survive(self):
        def prepare(saved):
            saved['QuestStage'] = 'jv_done'
            saved['Player']['CurrentObjective'] = 'synthetic-objective'
            saved['Player']['Story'] = dict(Active=[150], Started=[149, 99999], Finished=[104],
                                          Outputs=[1179], Tracked=149, Reached={'1179': self.NOW}, Clock=900)
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        story = self.read(profile)['story']
        rows = self.rows(story)
        self.assertEqual(story['introductory'], dict(questStage='jv_done', objective='synthetic-objective'))
        self.assertEqual(rows[149]['name'], 'Good Money')
        self.assertEqual(rows[149]['status'], 'started')
        self.assertTrue(rows[149]['tracked'])
        self.assertEqual(rows[104]['status'], 'finished')
        self.assertEqual(rows[150]['status'], 'not-recorded')
        self.assertIsNone(rows[99999]['name'])
        self.assertEqual(rows[99999]['status'], 'started')
        self.assertEqual(story['recordedFinishedCount'], 1)
        self.assertNotIn('percent', json.dumps(story).lower())
        self.assertEqual(path.read_bytes(), original)

    def test_trinkets_derive_correct_species_outputs_distance_and_automatic_unlocks(self):
        def prepare(saved):
            player = saved['Player']
            player['Kills'] = {'31': 1, '1': 300}
            player['Distance'] = dict(Metres=12345, Requests={})
            player['Story'] = dict(Active=[], Started=[], Finished=[], Outputs=[1179])
            player['Tasks']['NestsCleared'] = 51
            player['Tasks']['Achievements'] = {'20001': self.NOW - 10, '29999': self.NOW - 20}
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        result = self.read(profile)
        rows = self.rows(result['trinkets'])
        self.assertEqual(result['trinkets']['unlockedCount'], 2)
        self.assertEqual(rows[20001]['progress'], 0)
        self.assertTrue(rows[20001]['unlocked'])
        self.assertEqual(rows[20002]['progress'], 1)
        self.assertEqual(rows[20002]['rewardState'], 'awaiting-gameplay-refresh')
        self.assertEqual(rows[20003]['progress'], 51)
        self.assertEqual(rows[20004]['progress'], 1)
        self.assertEqual(rows[20005]['progress'], 0)
        self.assertEqual(rows[20011]['progress'], 12345)
        self.assertTrue(rows[29999]['unlocked'])
        self.assertIsNone(rows[29999]['progress'])
        self.assertTrue(all(not row['pendingClaim'] for row in rows.values()))
        self.assertTrue(result['clock']['requiresGameplayRefresh'])
        self.assertEqual(path.read_bytes(), original)

    def test_distance_latched_protection_historical_baseline_and_shadow_are_distinct_and_private(self):
        def prepare(saved):
            player = saved['Player']
            player['Distance'] = dict(Metres=12550, Requests={'123456789123': 7000})
            player['StoryPlaces'] = {'private-place': dict(Id='SYNTHETIC_PRIVATE_PLACE', Lat=42.125, Lng=12.625, Biomes=[1])}
            player['Tasks']['Receipts'] = {'private-nonce': dict(Fingerprint='SYNTHETIC_PRIVATE_FINGERPRINT', Response='AA==')}
            saved['Movement'] = dict(Protected=True, LegacyBaselineMetres=12000, CreditedMetres=550,
                ShadowMillimetres=2500250, RemainderMillimetres=500, ObservedAtMs=self.NOW * 1000,
                Epoch='A' * 32, NextSeq=21, HighWaterUtcMs=self.NOW * 1000,
                ProtectedAcceptedFixes=12, ProtectedRejectedFixes=3, ShadowAcceptedFixes=9, ShadowRejectedFixes=2,
                RejectedReasons={'speed-jump': 3}, Receipts=[dict(FirstSeq=1, Count=1, Digest='B' * 64)],
                RebasedAtMs=(self.NOW - 3600) * 1000)
        profile, path = self.saved_fixture(prepare)
        original = path.read_bytes()
        result = self.read(profile)
        distance = result['distance']
        self.assertEqual((distance['metres'], distance['kilometres']), (12550, 12.55))
        self.assertEqual(distance['legacyBaselineMetres'], 12000)
        self.assertEqual(distance['acceptedMetresSinceProtection'], 550)
        self.assertEqual(distance['shadowAcceptedMetres'], 2500.25)
        self.assertTrue(distance['protectedProfile'])
        self.assertEqual(distance['currentPolicy'], 'shadow')
        self.assertFalse(distance['actualWalkingVerified'])
        self.assertEqual(distance['rejectedReasons'], {'speed-jump': 3})
        self.assertEqual(distance['rebasedAtMs'], (self.NOW - 3600) * 1000)
        payload = json.dumps(result)
        for value in ('SYNTHETIC_PRIVATE_PLACE', 'SYNTHETIC_PRIVATE_FINGERPRINT', '123456789123',
                      'private-nonce', 'A' * 32, 'B' * 64, admin.SYNTHETIC_KEY, str(self.directory)):
            self.assertNotIn(value, payload)
        def keys(value):
            if isinstance(value, dict):
                return set(value).union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value))
            return set()
        self.assertFalse(keys(result) & {'lat', 'lng', 'aura', 'storyPlaces', 'receipts', 'requests', 'epoch', 'transactions'})
        self.assertEqual(path.read_bytes(), original)

    def test_legacy_has_no_fictitious_fifteen_kilometres_and_missing_distance_is_explicit(self):
        profile, path = self.saved_fixture(lambda s: s['Player'].update(Distance=None))
        distance = self.read(profile)['distance']
        self.assertEqual(distance['availability'], 'default-zero')
        self.assertEqual(distance['metres'], 0)
        self.assertIsNone(distance['acceptedMetresSinceProtection'])
        self.server.stop()
        saved = json.loads(path.read_text())
        saved.update(SchemaVersion=1, Player=None, Movement=None, QuestStage=None)
        path.write_text(json.dumps(saved))
        self.restart()
        original = path.read_bytes()
        result = self.read(profile)
        self.assertEqual(result['distance']['availability'], 'legacy-unavailable')
        self.assertIsNone(result['distance']['metres'])
        self.assertIsNone(result['distance']['kilometres'])
        self.assertEqual(result['daily']['availability'], 'legacy-unavailable')
        self.assertEqual(path.read_bytes(), original)

    def test_active_profile_progress_reads_new_saved_revision_without_relogin(self):
        client, profile = self.profile()
        before = self.read(profile)
        response = admin.Reader(client.rpc(27, admin.I(1200)))
        self.assertEqual(response.byte(), 1)
        self.assertEqual(response.integer(), 1200)
        after = self.read(profile)
        self.assertEqual(after['distance']['metres'], 1200)
        self.assertGreater(after['profile']['revision'], before['profile']['revision'])
        self.assertEqual(after['profile']['id'], profile)

    def test_claimed_event_stays_claimed_after_expiry_and_unknown_events_remain_visible(self):
        def prepare(saved):
            saved['Player']['Tasks']['Events'] = {
                str(self.event['id']): self.event_state(claimed=True, tasks_claimed=True),
                '39999': dict(Id=39999, Tasks=[self.entry(self.event['tasks'][0], 4)], Claimed=False)}
        profile, path = self.saved_fixture(prepare, Tasks__FixedUnixTime=str(self.event['end'] + 1))
        original = path.read_bytes()
        events = self.rows(self.read(profile)['timed'])
        self.assertEqual(events[self.event['id']]['finalRewardState'], 'claimed')
        self.assertFalse(events[self.event['id']]['pendingClaim'])
        self.assertEqual(events[39999]['availability'], 'definition-unavailable')
        self.assertEqual(events[39999]['finalRewardState'], 'unavailable')
        self.assertEqual(events[39999]['tasks'][0]['progress'], 4)
        self.assertFalse(events[39999]['tasks'][0]['pendingClaim'])
        self.assertEqual(path.read_bytes(), original)

    def test_disabled_catalogue_retains_saved_progress_but_never_promises_reward(self):
        def prepare(saved):
            saved['Player']['Tasks']['Daily'] = [self.entry(self.daily[0], self.daily[0]['target'])]
        profile, path = self.saved_fixture(prepare)
        self.options.pop('Tasks__Directory')
        self.restart()
        original = path.read_bytes()
        result = self.read(profile)
        self.assertEqual(result['daily']['availability'], 'catalogue-unavailable')
        row = result['daily']['rows'][0]
        self.assertEqual(row['progress'], self.daily[0]['target'])
        self.assertTrue(row['completedSaved'])
        self.assertEqual(row['rewardState'], 'unavailable')
        self.assertFalse(row['pendingClaim'])
        self.assertEqual(result['hunt']['rewardState'], 'unavailable')
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
