"""Regression checks for semantics recovered from original 1.1.116 ARM64 consumers."""
import gzip
import json
import unittest
import urllib.request
import test_prototype as base
import test_tasks as tasks
I,Q=base.I,base.Q

class AuditContracts(base.PrototypeTests):
    NOW=tasks.TaskTests.NOW
    task_server=tasks.TaskTests.task_server
    daily=tasks.TaskTests.daily
    fight=tasks.TaskTests.fight

    def test_audit_native_action_numbers_and_distance_window_rows(self):
        server,c=self.task_server()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
            data=json.loads(gzip.decompress(response.read()))
        fast=[r['action_type'] for r in data['contract_actions'] if r['contract_id']==12002]
        self.assertEqual(fast,[9])
        contracts={r['id']:r for r in data['contracts']}
        self.assertEqual(contracts[20011]['contract_type_id'],3)
        self.assertEqual(contracts[20011]['value1'],2000000)
        self.assertEqual(contracts[20012]['value2'],3600)
        self.assertNotIn(-1,{r['id'] for r in data['monsters']})
        rarities={r['id']:r['rarity'] for r in data['monsters']}
        self.assertEqual({n:rarities[n] for n in (6,10,27)},{6:1,10:2,27:2})
        # Independently matching pre-1.2 wiki revision554269 and Gamepressure21July2021.
        ingredients=data['oil_recipe_ingredients']
        def recipe(number):
            return {r['ingredient_id']:r['amount'] for r in ingredients if r['recipe_id']==number}
        self.assertEqual(recipe(3103),{112:5,101:3,102:2})
        self.assertEqual(recipe(3108),{104:5,101:3,102:2})

    def test_audit_kill_window_expires_at_boundary_and_completion_latches(self):
        trophy=dict(id=20200,slug='trophy_disturbed_the_water',type=1,target=2,window_seconds=3600)
        server,c=self.task_server(trinkets=[trophy]);self.fight(c)
        self.assertEqual(c.rpc(24),b'\1'+I(0))
        server.stop();server,c=self.task_server(at=self.NOW+3601,fresh_summons=True);self.fight(c)
        self.assertEqual(c.rpc(24),b'\1'+I(0))
        server.stop();server,c=self.task_server(at=self.NOW+3602,fresh_summons=True);self.fight(c)
        self.assertEqual(c.rpc(24),b'\1'+I(2)+I(20200)+I(self.NOW+3602))
        server.stop();server,c=self.task_server(at=self.NOW+7201)
        self.assertEqual(c.rpc(24),b'\1'+I(2)+I(20200)+I(self.NOW+3602))

    def test_audit_kill_at_exact_window_boundary_can_complete_after_zero_progress(self):
        daily=[dict(id=10200+i,slug='kill_4_monsters',type=1,target=2,window_seconds=3600) for i in range(4)]
        server,c=self.task_server(daily=daily);self.daily(c);self.fight(c)
        server.stop();server,c=self.task_server(at=self.NOW+3600,fresh_summons=True)
        # The native timestamp ring still contains the earlier kill; its visible count is now zero.
        for values in self.daily(c)[0].values(): self.assertEqual(sorted(values),[0,self.NOW])
        self.fight(c)
        for values in self.daily(c)[0].values(): self.assertEqual(sorted(values),[self.NOW,self.NOW+3600])
        state=json.loads(self.profile_file('tasks').read_text())
        self.assertTrue(all(e['Progress']==2 for e in state['Player']['Tasks']['Daily']))

    def test_audit_new_window_trinket_does_not_credit_untimed_old_kills(self):
        trophy=dict(id=20200,slug='trophy_disturbed_the_water',type=1,target=2,window_seconds=3600)
        server,c=self.task_server(trinkets=[trophy]);c.rpc(24);server.stop()
        path=self.profile_file('tasks');state=json.loads(path.read_text())
        state['Player']['Kills']={'3':999};state['Player']['Tasks'].pop('TrophyProgress',None)
        path.write_text(json.dumps(state));server,c=self.task_server()
        self.assertEqual(c.rpc(24),b'\1'+I(0));self.fight(c)
        self.assertEqual(c.rpc(24),b'\1'+I(0))

    def test_audit_bestiary_rarity_thresholds_and_preexisting_claims(self):
        server,c=self.reconstructed();c.rpc(3);c.rpc(3);server.stop()
        path=self.profile_file('test-fresh');state=json.loads(path.read_text())
        player=state['Player'];player['Kills']={'2':149,'101':29,'103':5}
        player['KnowledgeClaimed']={'2':2,'101':2,'103':2}
        path.write_text(json.dumps(state));server=self.start('test-fresh',self.RECONSTRUCTED);c=self.client(server)
        for monster in [2,101,103]: self.assertEqual(c.rpc(65,I(monster)),b'\0'+I(-1)+I(0))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
            data=json.loads(gzip.decompress(response.read()))
        for monster,expected in [(2,[3,47,100]),(101,[2,8,20]),(103,[1,1,4])]:
            rows={r['level']:r['threshold'] for r in data['monster_descriptions'] if r['monster_id']==monster}
            self.assertEqual([rows[i] for i in (1,2,3)],expected)
        server.stop();state=json.loads(path.read_text());points=state['Player']['SkillPoints']
        state['Player']['Kills']={'2':150,'101':30,'103':6};path.write_text(json.dumps(state))
        server=self.start('test-fresh',self.RECONSTRUCTED);c=self.client(server)
        for monster in [2,101,103]:
            self.assertEqual(c.rpc(65,I(monster)),b'\1'+I(monster)+I(1))
            self.assertEqual(c.rpc(65,I(monster)),b'\0'+I(-1)+I(0))
        self.assertEqual(json.loads(path.read_text())['Player']['SkillPoints'],points+3)
        # Previously awarded tiers and points survive; changing balance is not a retroactive clawback.
        server.stop();state=json.loads(path.read_text());state['Player']['Kills']['2']=100;path.write_text(json.dumps(state))
        server=self.start('test-fresh',self.RECONSTRUCTED);c=self.client(server)
        self.assertEqual(c.rpc(65,I(2)),b'\0'+I(-1)+I(0))
        saved=json.loads(path.read_text())['Player']
        self.assertEqual(saved['KnowledgeClaimed']['2'],3);self.assertEqual(saved['SkillPoints'],points+3)

    def test_audit_failures_have_complete_correlated_dtos_and_keep_session(self):
        server,c=self.reconstructed();c.rpc(3);c.rpc(3)
        rows=[(4,Q(987654321)+b'x',b'\0'+Q(987654321)+I(0)*3),
              (68,b'x',b'\0'+Q(0)+I(0)),(45,b'x',b'\0'),
              (29,b'x',b'\0'+I(0)),(65,b'x',b'\0'+I(-1)+I(0)),
              (78,I(999),b'\0'),(90,b'x',I(4)+I(1)+I(0)*3),(92,b'x',I(1)+I(0))]
        rows.extend((method,b'x',b'\0'+I(0)*2) for method in (47,48,49,50,51,71,100,109,118))
        for method,payload,expected in rows:
            with self.subTest(method=method):
                self.assertEqual(c.rpc(method,payload),expected)
                self.assertGreaterEqual(self.player_info(c)['gold'],0)
        self.assertEqual(c.rpc(65,I(3)),b'\0'+I(-1)+I(0))
        self.assertEqual(c.rpc(55,I(14)),b'\0'+I(7))

def load_tests(loader,tests,pattern):
    return unittest.TestSuite(AuditContracts(n) for n in loader.getTestCaseNames(AuditContracts)
                              if n.startswith('test_audit_'))
