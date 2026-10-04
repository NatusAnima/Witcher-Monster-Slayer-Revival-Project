"""Offline repair refusal, recovery and state-preservation checks on disposable data."""
import copy
import fcntl
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = next(p for p in (Path(__file__).resolve().parents[1]/'WitcherRevival.Server/Admin/repair_leshen_trinket.py',
                         Path(__file__).resolve().parent/'repair_leshen_trinket.py') if p.exists())
spec = importlib.util.spec_from_file_location('repair_leshen_trinket', SOURCE)
repair = importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)


class TrinketRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.tasks = self.root/'tasks'; self.profiles = self.root/'profiles'
        self.tasks.mkdir(); self.profiles.mkdir(); self.profile_id = 'p'+'a'*31
        row = dict(id=20002, slug='trophy_in_forest_dark', type=1, target=1, monsters=[166,30], evidence='Client')
        self.catalogue = dict(schema_version=1, trinkets=[row, dict(id=20003, slug='unrelated')])
        self.manifest = dict(trinkets=copy.deepcopy(self.catalogue), daily={'sentinel': 'preserve'}, hunt={}, timed={})
        self.profile = dict(SchemaVersion=2, ProfileId=self.profile_id, Revision=9, Facts={'3':1},
                            Player=dict(Kills={'166':1}, Gold=271, Exp=1250, Items={'oils':{'301':3}}, Skills=[1,2],
                                        Tasks=dict(Achievements={'20002':1790929682, '29999':1790000000},
                                                   Events={'30001':{'Claimed':True}}, Receipts={'synthetic':'retain'})))
        self.paths = {'trinkets':self.tasks/'trinkets.json', 'manifest':self.profiles/'tasks-catalogue.json',
                      'profile':self.profiles/(self.profile_id+'.json')}
        for key,value in [('trinkets',self.catalogue),('manifest',self.manifest),('profile',self.profile)]:
            self.paths[key].write_bytes(repair.encoded(value)); self.paths[key].chmod(0o600)
        for name in ('tasks-catalogue.lock', self.profile_id+'.lock'): (self.profiles/name).touch()
        self.before = {k:p.read_bytes() for k,p in self.paths.items()}
        self.expected = {k:repair.digest(v) for k,v in self.before.items()}
        self.backup = self.root/'backup'

    def run_repair(self, apply=False):
        return repair.repair(self.tasks,self.profiles,self.profile_id,self.backup,self.expected,apply=apply)

    def unchanged(self):
        self.assertEqual({k:p.read_bytes() for k,p in self.paths.items()},self.before)

    def test_preview_then_apply_only_changes_known_award_definition_and_revision(self):
        self.assertEqual(self.run_repair()['status'],'preview'); self.unchanged(); self.assertFalse(self.backup.exists())
        result=self.run_repair(True); self.assertEqual(result['status'],'applied')
        after=json.loads(self.paths['profile'].read_bytes()); expected=copy.deepcopy(self.profile)
        expected['Revision']+=1; del expected['Player']['Tasks']['Achievements']['20002']
        self.assertEqual(after,expected)
        for key in ('trinkets','manifest'):
            before=json.loads(self.before[key]); corrected=copy.deepcopy(before)
            (corrected if key=='trinkets' else corrected['trinkets'])['trinkets'][0]['monsters']=[31]
            self.assertEqual(json.loads(self.paths[key].read_bytes()),corrected)
        for key in self.paths:
            self.assertEqual((self.backup/(key+'.before.json')).read_bytes(),self.before[key])
            self.assertEqual(self.paths[key].stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError): self.run_repair(True)

    def test_both_advisory_locks_refuse_live_repair(self):
        for name in ('tasks-catalogue.lock',self.profile_id+'.lock'):
            with (self.profiles/name).open('r+b') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError,'Stop'):self.run_repair(True)
            self.unchanged(); self.assertFalse(self.backup.exists())

    def test_changed_hash_refuses_before_backup(self):
        self.expected['profile']='0'*64
        with self.assertRaisesRegex(ValueError,'changed'):self.run_repair(True)
        self.unchanged();self.assertFalse(self.backup.exists())

    def test_earned_or_absent_award_and_wrong_catalogue_are_refused(self):
        for species in (31,103):
            candidate=copy.deepcopy(self.profile);candidate['Player']['Kills'][str(species)]=1
            before=dict(self.before,profile=repair.encoded(candidate))
            with self.assertRaisesRegex(ValueError,'potentially earned'):repair.prepare(before,self.profile_id)
        candidate=copy.deepcopy(self.profile);del candidate['Player']['Tasks']['Achievements']['20002']
        with self.assertRaisesRegex(ValueError,'does not have'):repair.prepare(dict(self.before,profile=repair.encoded(candidate)),self.profile_id)
        candidate=copy.deepcopy(self.catalogue);candidate['trinkets'][0]['monsters']=[31]
        with self.assertRaisesRegex(ValueError,'known erroneous'):repair.prepare(dict(self.before,trinkets=repair.encoded(candidate)),self.profile_id)
        self.unchanged()

    def test_interrupted_write_restores_all_three_exact_files(self):
        real=repair.atomic; failed=False
        def once(path,data,mode):
            nonlocal failed
            if path==self.paths['manifest'] and not failed:
                failed=True;raise OSError('synthetic injected failure')
            real(path,data,mode)
        with patch.object(repair,'atomic',side_effect=once),self.assertRaises(OSError):self.run_repair(True)
        self.unchanged();self.assertTrue(failed)
        self.assertEqual(json.loads((self.backup/'receipt.json').read_bytes())['status'],'rolled_back')

    def test_symlink_target_and_backup_inside_profile_store_are_refused(self):
        target=self.root/'external.json';self.paths['profile'].rename(target);self.paths['profile'].symlink_to(target)
        with self.assertRaises(ValueError):self.run_repair(True)
        self.assertEqual(target.read_bytes(),self.before['profile'])
        self.paths['profile'].unlink();target.rename(self.paths['profile']);self.backup=self.profiles/'backup'
        with self.assertRaisesRegex(ValueError,'overlaps'):self.run_repair(True)
        self.unchanged()


if __name__=='__main__':unittest.main()
