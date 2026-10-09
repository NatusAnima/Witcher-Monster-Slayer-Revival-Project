"""Synthetic geometry only: policy history, safe controls, diagnostics and nemeton boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import playable_locations as pl
import placement_policy as policy
import s2cells
import test_playable_locations as fixtures


class PlacementPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'placement-policy.json'
        self.fixture = fixtures.CandidateTests(); self.fixture.setUp()
        self.cell, self.proj = self.fixture.cell, self.fixture.proj
        self.doc = {'elements': [self.fixture.area('forest', -200, -200, 200, 200)]}
        owner = self
        class Index:
            meta = {'source_timestamp': '2026-01-01T00:00:00Z'}
            def covers(self, *args): return True
            def document(self, *args, clip=None): return owner.doc
        self.index = Index()
        self.service = pl.PlayableLocations(self.index, self.path)

    def save(self, desired, epoch=20730):
        self.path.write_text(json.dumps({'schemaVersion': 1, 'versions': [{'fromEpoch': epoch, 'policy': desired}]}))
        self.service.policy.refresh()

    def test_legacy_geometry_matches_pre_policy_golden_and_is_retained_across_days(self):
        f = self.fixture
        self.doc['elements'] += [f.way('footway', [(-180,0),(180,0)]),
            f.way('residential', [(-300,-100),(300,-100)]), f.area('building',30,20,70,60)]
        old = self.service.cell(self.cell, 20729)
        self.assertEqual(hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest(),
            # was 1752b331... until woods were limited to half a cell and the ids took PLACEMENT_VERSION 4 (2026-10-07), then
            # e92e9ce4... until the place mix replaced that limit, places lined the streets and the ids took
            # PLACEMENT_VERSION 5 (2026-10-09): deliberate changes of the default draw; days drawn under a scheduled policy
            # keep their own rule
            'af79fd23bdd20e318654d4289beaf2ff6e48aa8e478b9fdf48e9cdd4140d5e77')
        self.save(dict(policy.DEFAULT, maxPoints=8, spacingMeters=100))
        self.assertEqual(self.service.cell(self.cell,20729),old)
        self.assertEqual(pl.PlayableLocations(self.index,self.path).cell(self.cell,20729),old)
        future=self.service.cell(self.cell,20730)
        self.assertLessEqual(len(future),8)
        self.assertNotEqual(future,old)
        self.assertTrue(all(pl._distance_m(a,b)>99 for i,a in enumerate(future) for b in future[i+1:]))
        from unittest.mock import patch
        with patch.object(pl.time,'time',return_value=20729*86400):
            self.assertEqual(self.service.cell(self.cell,0),pl.PlayableLocations(self.index).cell(self.cell,0))

    def test_exclusion_and_preferred_points_obey_geometry_and_sampling(self):
        lat,lng=self.proj.latlng(100,100)
        exlat,exlng=self.proj.latlng(-90,-90)
        desired=dict(policy.DEFAULT, preferred=[dict(id='p1',lat=lat,lng=lng)],
            exclusions=[dict(id='area1',lat=exlat,lng=exlng,radiusMeters=80)])
        self.assertEqual(self.service.validate(desired),desired)
        self.save(desired)
        future=self.service.cell(self.cell,20730)
        self.assertEqual(future[0]['kind'],'preferred')
        self.assertTrue(all(pl._distance_m(p,{'lat':exlat,'lng':exlng})>79 for p in future))
        for xy, extra in [((0,0),[self.fixture.way('residential',[(-250,0),(250,0)])]),
                          ((0,0),[self.fixture.area('building',-20,-20,20,20)]),
                          ((0,0),[self.fixture.area('water',-20,-20,20,20)]),
                          ((-90,-90),[]), ((210,210),[])]:
            with self.subTest(xy=xy,extra=extra):
                base=copy.deepcopy(self.doc)
                self.doc['elements']+=extra
                bad=copy.deepcopy(desired);bad['preferred'][0].update(zip(('lat','lng'),self.proj.latlng(*xy)))
                with self.assertRaises(ValueError): self.service.validate(bad)
                self.doc=base

    def test_epoch_zero_validates_current_quest_ground_but_future_policy_waits(self):
        from unittest.mock import patch
        now=20729
        original=self.service.cell(self.cell,now)
        zero=self.service.cell(self.cell,0)
        lat,lng=self.proj.latlng(0,0)
        desired=dict(policy.DEFAULT,exclusions=[dict(id='exclude-all',lat=lat,lng=lng,radiusMeters=1000)])
        self.save(desired,now+1)
        with patch.object(pl.time,'time',return_value=now*86400):
            self.assertEqual(self.service.cell(self.cell,0),zero)
        with patch.object(pl.time,'time',return_value=(now+1)*86400):
            self.assertEqual(self.service.cell(self.cell,0),[])
            self.assertEqual(self.service.cell(self.cell,now),original)

    def test_preferred_point_cannot_offset_into_unmapped_verge(self):
        self.doc={'elements':[self.fixture.way('path',[(-100,0),(100,0)])]}
        lat,lng=self.proj.latlng(0,8)
        with self.assertRaises(ValueError):
            self.service.validate(dict(policy.DEFAULT,preferred=[dict(id='verge',lat=lat,lng=lng)]))
        lat,lng=self.proj.latlng(0,0)
        self.assertTrue(self.service.validate(dict(policy.DEFAULT,preferred=[dict(id='path',lat=lat,lng=lng)])))

    def test_strict_bounds_and_history_prevent_unbounded_or_ambiguous_policy(self):
        for key,value in [('maxPoints',65),('maxPoints',True),('spacingMeters',34),('spacingMeters',float('nan')),
                          ('preferred',[dict(id='p',lat=90,lng=0)]),
                          ('exclusions',[dict(id='e',lat=10,lng=20,radiusMeters=1001)])]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError): policy.policy(dict(policy.DEFAULT,**{key:value}))
        with self.assertRaises(ValueError):policy.policy(dict(policy.DEFAULT,unknown=1))
        for versions in [[{'fromEpoch':1,'policy':policy.DEFAULT}]*2,
                         [{'fromEpoch':i+1,'policy':policy.DEFAULT} for i in range(129)]]:
            with self.assertRaises(ValueError):policy.schedule({'schemaVersion':1,'versions':versions})

    def test_invalid_schedule_retains_last_good_and_recovers_without_rewriting_history(self):
        self.save(dict(policy.DEFAULT,maxPoints=8))
        original=self.service.cell(self.cell,20730)
        revision=self.service.policy.revision
        good=self.path.read_text();self.path.write_text('{broken')
        self.service.policy.refresh()
        self.assertEqual(self.service.policy.status()['status'],'invalid-retaining-last-good')
        self.assertEqual(self.service.policy.revision,revision)
        self.assertEqual(self.service.cell(self.cell,20730),original)
        with self.assertRaises(ValueError):pl.PlayableLocations(self.index,self.path)
        self.path.write_text(good)
        self.assertEqual(self.service.policy.status()['status'],'ready')
        self.path.unlink()
        self.assertEqual(self.service.policy.status()['status'],'invalid-retaining-last-good')

    def test_context_reports_coverage_rejections_and_bounded_geometry(self):
        self.doc['elements'] += [self.fixture.way('residential',[(-300,0),(300,0)]),
                                self.fixture.area('building',-60,-60,60,60)]
        d=self.service.admin_map([self.cell],20729)
        c=d['cells'][0]
        self.assertGreater(c['rejected']['road'],0)
        self.assertGreater(c['rejected']['building'],0)
        self.assertEqual(c['safe'],c['selected']+c['spacingRejected']+c['capacityRejected'])
        self.assertEqual(d['source'],'local-osm-index')
        self.index.covers=lambda *args:False
        d=self.service.admin_map([self.cell],20729)
        self.assertFalse(d['cells'][0]['covered']);self.assertEqual(d['cells'][0]['selected'],0)
        self.index.covers=lambda *args:True
        self.doc={'elements':[self.fixture.way('residential',[(i,0) for i in range(25000)])]}
        d=self.service.admin_map([self.cell],20729)
        self.assertTrue(d['truncated']);self.assertEqual(d['features'],[])

    def test_curated_points_cannot_bypass_nemeton_separation_at_cell_boundary(self):
        face,i,j,level=s2cells.to_face_ij(self.cell);shift=s2cells.MAX_LEVEL-level
        other=s2cells.from_face_ij(face,(i+1)<<shift,j<<shift,level)
        corners=s2cells.corners(self.cell)
        lat,lng=((a+b)/2 for a,b in zip(corners[1],corners[2]))
        anchor=pl.Projection(lat,lng);preferred=[];elements=[]
        for cell in (self.cell,other):
            x,y=anchor.xy(*s2cells.center(cell));scale=2/(x*x+y*y)**.5
            a,b=anchor.latlng(x*scale,y*scale)
            preferred.append(dict(id=str(cell),lat=a,lng=b))
            elements.append(dict(type='way',tags={'highway':'path'},geometry=[{'lat':a,'lon':b},{'lat':a+.000001,'lon':b}]))
        self.doc={'elements':elements};self.save(dict(policy.DEFAULT,preferred=preferred))
        self.assertLess(pl._distance_m(*preferred),5)
        for epoch in range(20730,20740):
            together=self.service.payload([self.cell,other],epoch)
            self.assertTrue(all(len(v['places'])==1 for v in together.values()))
            self.assertEqual(sum(v['nest_place_id'] is not None for v in together.values()),1)
            self.assertEqual(together,{**self.service.payload([other],epoch),**self.service.payload([self.cell],epoch)})

if __name__=='__main__':unittest.main()
