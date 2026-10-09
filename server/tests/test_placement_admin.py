"""Placement control API, using a disposable server, sidecar, profile and OSM geometry."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

import test_admin as admin
from test_prototype import I, Q, ROOT


class PlacementAdminTests(unittest.TestCase):
    setUp = admin.AdminTests.setUp
    restart = admin.AdminTests.restart
    request = admin.AdminTests.request
    profile = admin.AdminTests.profile

    def sidecar(self):
        folder=ROOT/'connection/map-road-fixture-01'
        if not folder.is_dir(): folder=Path(__file__).parent/'map-road-fixture-01'
        if not folder.is_dir(): self.fail('Packaged placement fixture modules are missing')
        sys.path.insert(0,str(folder))
        import playable_locations as pl
        import s2cells
        self.cell=s2cells.cell_of(10,20,pl.CELL_LEVEL)
        projection=pl.Projection(*s2cells.center(self.cell))
        ring=[projection.latlng(x,y) for x,y in [(-200,-200),(200,-200),(200,200),(-200,200)]]
        class Index:
            meta={'source_timestamp':'2026-01-01T00:00:00Z'}
            def covers(self,*args):return True
            def document(self,*args,clip=None):return {'elements':[dict(type='area',id=1,kind='forest',rings=[ring])]}
        service=pl.PlayableLocations(Index(),self.world/'placement-policy.json')
        listener=ThreadingHTTPServer(('127.0.0.1',0),pl.make_handler(service))
        thread=threading.Thread(target=listener.serve_forever,daemon=True);thread.start()
        self.addCleanup(listener.server_close);self.addCleanup(listener.shutdown)
        self.restart(Playable__Url=f'http://127.0.0.1:{listener.server_port}')
        return service,projection

    def test_policy_preview_save_receipt_conflict_backup_and_old_day_replay(self):
        service,projection=self.sidecar()
        client,profile=self.profile('synthetic-placement')
        client.rpc(40,I(1)+Q(self.cell));client.rpc(78,I(0))
        before=(self.directory/'profiles'/(profile+'.json')).read_bytes()
        today=int(time.time()//86400)
        old=service.payload([self.cell],today)
        status,context=self.request('map/context?profile='+profile)
        self.assertEqual(status,200)
        self.assertTrue(context['features']);self.assertEqual(context['cells'][0]['id'],str(self.cell))
        self.assertFalse(context['preview'])
        initial=self.request('placement-policy')[1]
        self.assertEqual(initial['revision'],'missing');self.assertTrue(initial['enabled'])
        desired=copy.deepcopy(initial['document']);desired['maxPoints']=8
        lat,lng=projection.latlng(100,100)
        desired['preferred']=[dict(id='synthetic-preferred',lat=lat,lng=lng)]
        write=dict(revision=initial['revision'],document=desired)
        status,preview=self.request('placement-policy/preview?profile='+profile,'POST',write)
        self.assertEqual(status,200);self.assertTrue(preview['preview'])
        self.assertEqual(preview['epoch'],today+1)
        self.assertLessEqual(preview['cells'][0]['selected'],8)
        self.assertFalse((self.world/'placement-policy.json').exists())
        status,saved=self.request('placement-policy','PUT',write)
        self.assertEqual(status,200);self.assertEqual(saved['receipt']['outcome'],'applied')
        current=self.request('placement-policy')[1]
        self.assertEqual(current['revision'],saved['revision'])
        self.assertEqual(current['effective']['maxPoints'],24)
        self.assertEqual(current['scheduledEpoch'],today+1)
        self.assertEqual(self.request('placement-policy','PUT',write)[0],409)
        self.assertEqual(service.payload([self.cell],today),old)
        self.assertEqual((self.directory/'profiles'/(profile+'.json')).read_bytes(),before)
        status,backup=self.request('receipts/'+saved['receipt']['id']+'/backup')
        self.assertEqual(status,200);self.assertEqual(backup['previous']['document'],initial['document'])
        status,_=self.request('placement-policy','PUT',dict(revision=current['revision'],document=backup['previous']['document']))
        self.assertEqual(status,200)
        schedule=json.loads((self.world/'placement-policy.json').read_text())
        self.assertEqual(len(schedule['versions']),1)  # replace tomorrow, never append ambiguous dates
        self.assertEqual(service.payload([self.cell],today),old)

    def test_authorization_limits_unsafe_points_and_unavailable_service(self):
        self.assertEqual(self.request('placement-policy',auth=False)[0],403)
        self.assertEqual(self.request('placement-policy')[0],503)
        service,projection=self.sidecar()
        initial=self.request('placement-policy')[1]
        self.assertEqual(self.request('placement-policy','PUT',initial,origin=False)[0],403)
        for update in [dict(maxPoints=1000),dict(spacingMeters=1),
                       dict(preferred=[dict(id='unsafe',lat=10.5,lng=20.5)])]:
            value=copy.deepcopy(initial['document']);value.update(update)
            self.assertEqual(self.request('placement-policy','PUT',dict(revision='missing',document=value))[0],400)
        self.assertFalse((self.world/'placement-policy.json').exists())
        client,profile=self.profile('synthetic-empty-area')
        self.assertEqual(self.request('map/context?profile='+profile)[0],409)
        self.assertEqual(self.request('map/context?profile=p'+'0'*31)[0],404)

    def test_schedule_byte_budget_refuses_before_receipt_or_file_change(self):
        service,projection=self.sidecar()
        initial=self.request('placement-policy')[1]
        lat,lng=projection.latlng(100,100)
        desired=copy.deepcopy(initial['document'])
        desired['preferred']=[dict(id=('p'*44)+str(i),lat=lat,lng=lng) for i in range(64)]
        desired['exclusions']=[dict(id=('e'*44)+str(i),lat=11,lng=21,radiusMeters=10) for i in range(32)]
        versions=[]
        while True:
            next_versions=versions+[dict(fromEpoch=len(versions)+1,policy=desired)]
            raw=json.dumps(dict(schemaVersion=1,versions=next_versions),indent=2).encode()
            if len(raw)>1024*1024: break
            versions=next_versions
        self.assertLess(len(versions),128)
        path=self.world/'placement-policy.json'
        before=json.dumps(dict(schemaVersion=1,versions=versions),indent=2).encode();path.write_bytes(before)
        current=self.request('placement-policy')[1]
        self.assertEqual(current['status'],'ready')
        receipts=self.request('receipts')[1]
        self.assertEqual(self.request('placement-policy','PUT',dict(revision=current['revision'],document=desired))[0],409)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.request('receipts')[1],receipts)
        self.assertEqual(self.request('placement-policy')[1]['status'],'ready')

    def test_bad_schedule_blocks_writes_and_reports_retained_good_policy(self):
        service,_=self.sidecar()
        initial=self.request('placement-policy')[1]
        write=dict(revision='missing',document=initial['document'])
        self.assertEqual(self.request('placement-policy','PUT',write)[0],200)
        current=self.request('placement-policy')[1]
        path=self.world/'placement-policy.json';good=path.read_bytes();path.write_text('{broken')
        bad=self.request('placement-policy')[1]
        self.assertEqual(bad['status'],'invalid-retaining-last-good')
        self.assertEqual(bad['revision'],current['revision'])
        self.assertEqual(self.request('placement-policy','PUT',dict(revision=current['revision'],document=current['document']))[0],409)
        self.assertEqual(path.read_text(),'{broken')
        path.write_bytes(good)
        self.assertEqual(self.request('placement-policy')[1]['status'],'ready')

if __name__=='__main__':unittest.main()
