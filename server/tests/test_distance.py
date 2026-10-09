"""Native metre-delta persistence, replay and task contracts on disposable profiles."""
import concurrent.futures
import json
import struct
import time
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
import test_prototype as base
import test_tasks as taskbase

I = base.I

def movement_hello(elapsed=100000, utc=None):
    return struct.pack('>BBHIqq', 1, 1, 0, 7, elapsed, int(time.time()*1000) if utc is None else utc)

def movement_fix(utc, elapsed, x, *, accuracy=2, flags=1):
    return struct.pack('>qqddfI', utc, elapsed, 0, x/111194.9266, accuracy, flags)

def movement_batch(epoch, first, fixes):
    return struct.pack('>BBH16sqI',1,2,0,epoch,first,len(fixes))+b''.join(fixes)

def movement_ack(payload):
    if len(payload)!=48: raise AssertionError(f'companion ACK length {len(payload)}')
    version,op,status,epoch,nextseq,total,credited,mode,utc=struct.unpack('>BBH16sqiiIq',payload)
    if version!=1 or nextseq<1: raise AssertionError('invalid ACK version/frontier')
    return dict(op=op,status=status,epoch=epoch,next=nextseq,total=total,credited=credited,mode=mode,utc=utc)

class DistanceTests(base.PrototypeTests):
    def distance_server(self):
        server=self.start('distance', {'LocalProfile__NewProfileMode':'reconstructed'})
        return server,self.client(server)

    def test_distance_accumulates_and_retries_survive_restart(self):
        server,c=self.distance_server()
        self.assertEqual(base.decode_batch(c.rpc(115))[27],b'\1'+I(0))
        self.assertEqual(c.rpc(27,I(123)),b'\1'+I(123)); first_id=c.sequence
        self.assertEqual(c.rpc(27,I(123),repeat=True),b'\1'+I(123))
        self.assertEqual(c.rpc(27,I(222)),b'\1'+I(345))
        c.sequence=first_id
        self.assertEqual(c.rpc(27,I(123),repeat=True),b'\1'+I(345))
        self.assertEqual(c.rpc(27,I(456),repeat=True),b'\0'+I(345))
        server.stop();server,c=self.distance_server()
        self.assertEqual(base.decode_batch(c.rpc(115))[27],b'\1'+I(345))
        c.sequence=first_id
        self.assertEqual(c.rpc(27,I(123),repeat=True),b'\1'+I(345))
        self.assertEqual(c.rpc(27,I(1234),repeat=True),b'\0'+I(345))

    def test_distance_invalid_payloads_preserve_total_and_connection(self):
        server,c=self.distance_server();c.rpc(27,I(150))
        for data in [b'',b'\0',I(-1),I(2147483647),I(1)+I(2)]:
            self.assertEqual(c.rpc(27,data),b'\0'+I(150))
            self.assertGreaterEqual(self.player_info(c)['gold'],0)
        self.assertEqual(c.rpc(27,I(0)),b'\1'+I(150))
        self.assertEqual(c.rpc(27,I(200)),b'\1'+I(350))

    def test_distance_concurrent_same_id_is_counted_once(self):
        server,c=self.distance_server();other=self.client(server)
        c.sequence=other.sequence=900000
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            replies=list(pool.map(lambda client:client.rpc(27,I(120)),[c,other]))
        self.assertEqual(replies,[b'\1'+I(120)]*2)
        self.assertEqual(base.decode_batch(c.rpc(115))[27],b'\1'+I(120))

    def test_distance_existing_state_is_preserved_and_failed_save_not_credited(self):
        server,c=self.distance_server();c.rpc(27,I(200));server.stop()
        path=self.profile_file('distance');before=json.loads(path.read_text())
        server,c=self.distance_server()
        pending=path.with_suffix('.json.pending');pending.mkdir()
        try:self.assertEqual(c.rpc(27,I(150)),b'\0'+I(200))
        finally:pending.rmdir()
        failed=c.sequence
        self.assertEqual(json.loads(path.read_text()),before)
        self.assertEqual(c.rpc(27,I(150),repeat=True),b'\1'+I(350))
        after=json.loads(path.read_text());after['Revision']=before['Revision'];after['Player']['Distance']=before['Player']['Distance']
        self.assertEqual(after,before)


class DistanceTaskTests(base.PrototypeTests):
    NOW=taskbase.TaskTests.NOW
    task_server=taskbase.TaskTests.task_server
    daily=taskbase.TaskTests.daily
    claim=taskbase.TaskTests.claim

    def test_distance_claim_is_paid_ahead_of_the_reports_unless_protected(self):
        # The client counts a walk done as it happens but reports it in steps of 100 m, so its claim can come while the server is behind.
        definitions=[dict(id=10100+i,slug='on_the_path',type=3,target=300,gold=50) for i in range(4)]
        server,c=self.task_server(daily=definitions)
        first,second=list(self.daily(c)[0])[:2]
        c.rpc(27,I(120))
        wallet=self.player_info(c)['gold']
        self.assertEqual(self.claim(c,first),(0,first,wallet+50,1))
        self.assertNotIn(first,self.daily(c)[0])
        # a protected profile counts only the server's own fixes
        world=self.directory/'world';world.mkdir()
        (world/'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":12}')
        (world/'distance-policy.json').write_text('{"mode":"protected"}')
        server.stop();server,c=self.task_server(daily=definitions,extra={'World__Directory':str(world)})
        self.assertEqual(movement_ack(c.rpc(2001,movement_hello()))['mode'],1)
        self.assertEqual(self.claim(c,second),(1,second,wallet+50,1))
        self.assertEqual(self.player_info(c)['gold'],wallet+50)

    def test_distance_daily_is_since_issue_and_lifetime_trinket_uses_total(self):
        definitions=[dict(id=10100+i,slug='on_the_path',type=3,target=300,gold=50) for i in range(4)]
        trophies=[dict(id=20100,slug='trophy_from_vizima_to_beauclair',type=3,target=2000000)]
        server,c=self.task_server(daily=definitions,trinkets=trophies)
        c.rpc(27,I(100));original=self.daily(c)[0]
        self.assertTrue(all(v==[0] for v in original.values()))
        c.rpc(27,I(120));nonce=c.sequence
        self.assertTrue(all(v==[120] for v in self.daily(c)[0].values()))
        c.sequence=nonce;c.rpc(27,I(120),repeat=True)
        self.assertTrue(all(v==[120] for v in self.daily(c)[0].values()))
        c.rpc(27,I(250));self.assertTrue(all(v==[300] for v in self.daily(c)[0].values()))
        c.rpc(27,I(2000000-470))
        self.assertEqual(c.rpc(24),b'\1'+I(2)+I(20100)+I(self.NOW))
        server.stop();server,c=self.task_server()
        self.assertEqual(base.decode_batch(c.rpc(115))[27],b'\1'+I(2000000))

    def test_distance_protected_credit_drives_tasks_and_award_without_legacy_delta(self):
        world=self.directory/'world';world.mkdir()
        (world/'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":12}')
        (world/'distance-policy.json').write_text('{"mode":"protected"}')
        definitions=[dict(id=10100+i,slug='on_the_path',type=3,target=10,gold=50) for i in range(4)]
        trophies=[dict(id=20100,slug='trophy_from_vizima_to_beauclair',type=3,target=10)]
        server,c=self.task_server(daily=definitions,trinkets=trophies,extra={'World__Directory':str(world)})
        self.assertTrue(all(v==[0] for v in self.daily(c)[0].values()))
        hello=movement_hello();ack=movement_ack(c.rpc(2001,hello));utc=struct.unpack('>q',hello[-8:])[0]
        (world/'distance-policy.json').write_text('{"mode":"shadow"}');time.sleep(1.05)
        shadow=base.Client(server,identity=('SYNTHETIC_SHADOW_DEVICE','SYNTHETIC_SHADOW_ACCOUNT'));self.addCleanup(shadow.close)
        shadow_hello=movement_hello();shadow_ack=movement_ack(shadow.rpc(2001,shadow_hello));shadow_utc=struct.unpack('>q',shadow_hello[-8:])[0]
        self.assertEqual(shadow_ack['mode'],0)
        # Real server receipt/monotonic bounds remain active. A 25s capture window fits only
        # after 10s of real time plus the explicit 15s future tolerance; no test clock bypass.
        time.sleep(10.2)
        fixes=[movement_fix(utc+s*1000,100000+s*1000,x,flags=5 if s==0 else 1)
               for s,x in [(0,0),(5,7.5),(10,15),(20,30),(25,37.5)]]
        batch=movement_batch(ack['epoch'],1,fixes)
        result=movement_ack(c.rpc(2001,batch))
        self.assertEqual((result['status'],result['credited'],result['total']),(0,15,15))
        self.assertTrue(all(v==[10] for v in self.daily(c)[0].values()))
        self.assertEqual(c.rpc(24),b'\1'+I(2)+I(20100)+I(self.NOW))
        self.assertEqual(c.pushes.count((25,I(20100))),1)
        replay=movement_ack(c.rpc(2001,batch))
        self.assertEqual((replay['total'],replay['credited']),(15,0))
        self.assertEqual(c.rpc(27,I(100)),b'\0'+I(15))
        self.assertEqual(c.rpc(27,I(0)),b'\1'+I(15))
        self.assertEqual(c.pushes.count((25,I(20100))),1)
        shadow_fixes=[movement_fix(shadow_utc+s*1000,100000+s*1000,x,flags=5 if s==0 else 1)
                      for s,x in [(0,0),(5,7.5),(10,15),(20,30),(25,37.5)]]
        simulated=movement_ack(shadow.rpc(2001,movement_batch(shadow_ack['epoch'],1,shadow_fixes)))
        self.assertEqual((simulated['status'],simulated['total'],simulated['credited']),(0,0,0))
        shadow_path=self.directory/'profiles'/(server.profile_id(('SYNTHETIC_SHADOW_DEVICE','SYNTHETIC_SHADOW_ACCOUNT'))+'.json')
        shadow_ledger=json.loads(shadow_path.read_text())['Movement']
        self.assertEqual((shadow_ledger['ShadowMillimetres'],shadow_ledger['CreditedMetres'],shadow_ledger['ShadowAcceptedFixes']),(15000,0,1))
        ledger=json.loads(self.profile_file('tasks').read_text())['Movement']
        self.assertEqual(ledger['CreditedMetres'],15)
        self.assertEqual(ledger['ShadowMillimetres'],0)


class MovementTests(base.PrototypeTests):
    def movement_server(self, mode='protected'):
        world = self.directory / 'world'
        world.mkdir(exist_ok=True)
        (world/'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":12}')
        (world/'distance-policy.json').write_text(json.dumps({'mode': mode}))
        server = self.start('movement', {'LocalProfile__NewProfileMode': 'reconstructed', 'World__Directory': str(world)})
        return server, self.client(server)

    def test_distance_companion_lease_shape_replay_failure_and_restart(self):
        server, c = self.movement_server()
        self.assertEqual(c.rpc(27, I(200)), b'\1'+I(200))
        hello = movement_hello(); ack = movement_ack(c.rpc(2001, hello)); hello_id = c.sequence
        self.assertEqual((ack['status'], ack['mode'], ack['total'], ack['next']), (0, 1, 200, 1))
        self.assertEqual(movement_ack(c.rpc(2001, hello, repeat=True))['epoch'], ack['epoch'])
        self.assertEqual(c.rpc(27, I(400)), b'\0'+I(200))
        self.assertEqual(c.rpc(27, I(0)), b'\1'+I(200))
        other = self.client(server)
        self.assertEqual(movement_ack(other.rpc(2001, movement_hello()))['status'], 4)
        now = struct.unpack('>q', hello[-8:])[0]
        fix = movement_fix(now, 100000, 0, flags=5)
        batch = movement_batch(ack['epoch'], 1, [fix])
        path = self.profile_file('movement'); before = path.read_bytes()
        pending = path.with_suffix('.json.pending'); pending.mkdir()
        try: self.assertEqual(movement_ack(c.rpc(2001, batch))['status'], 6)
        finally: pending.rmdir()
        self.assertEqual(path.read_bytes(), before)
        processed = movement_ack(c.rpc(2001, batch, repeat=True))
        self.assertEqual((processed['status'], processed['next'], processed['credited']), (0, 2, 0))
        before = path.read_bytes()
        self.assertEqual(movement_ack(c.rpc(2001, batch))['status'], 0)
        self.assertEqual(path.read_bytes(), before)
        wrong = movement_batch(ack['epoch'], 1, [movement_fix(now, 100000, 50)])
        self.assertEqual(movement_ack(c.rpc(2001, wrong))['status'], 3)
        self.assertEqual(movement_ack(c.rpc(2001, movement_batch(ack['epoch'], 3, [fix])))['status'], 3)
        for seq in range(2,67):
            next_batch=movement_batch(ack['epoch'],seq,[movement_fix(now+seq,100000+seq,0)])
            self.assertEqual(movement_ack(c.rpc(2001,next_batch))['status'],0)
        compacted=json.loads(path.read_text())['Movement']
        self.assertEqual((len(compacted['Receipts']),compacted['NextSeq']),(64,67))
        # Even an evicted receipt remains behind the durable sequence frontier.
        self.assertEqual(movement_ack(c.rpc(2001,batch))['status'],3)
        for malformed in [b'', b'\1\1\0\0', hello+b'\0', b'\2'+hello[1:],
                          batch+b'\0', movement_batch(ack['epoch'], 2, [movement_fix(now,100000,0,flags=8)])]:
            self.assertEqual(movement_ack(c.rpc(2001, malformed))['status'], 1)
        fresh = movement_ack(c.rpc(2001, movement_hello()))
        self.assertNotEqual(fresh['epoch'], ack['epoch'])
        self.assertEqual(movement_ack(c.rpc(2001, batch))['status'], 2)
        c.sequence = hello_id
        self.assertEqual(movement_ack(c.rpc(2001, hello, repeat=True))['status'], 3)
        server.stop(); server, c = self.movement_server('shadow')
        self.assertEqual(c.rpc(27, I(400)), b'\0'+I(200))
        after = movement_ack(c.rpc(2001, movement_hello()))
        self.assertEqual(after['mode'], 1)
        self.assertEqual(movement_ack(c.rpc(2001, batch))['status'], 2)
        ledger = json.loads(path.read_text())['Movement']
        self.assertTrue(ledger['Protected'])
        self.assertEqual(ledger['LegacyBaselineMetres'], 200)
        self.assertFalse(any(key.lower() in json.dumps(ledger).lower() for key in ['latitude', 'longitude', 'accuracy']))

    def test_distance_companion_shadow_and_profiles_are_isolated(self):
        server, c = self.movement_server('shadow')
        hello = movement_hello(); ack = movement_ack(c.rpc(2001, hello))
        self.assertEqual(ack['mode'], 0)
        other = base.Client(server, identity=('SYNTHETIC_OTHER_GPS_DEVICE', 'SYNTHETIC_OTHER_GPS_ACCOUNT'))
        self.addCleanup(other.close)
        other_ack = movement_ack(other.rpc(2001, movement_hello()))
        now = struct.unpack('>q', hello[-8:])[0]
        self.assertEqual(movement_ack(other.rpc(2001, movement_batch(ack['epoch'], 1, [movement_fix(now,100000,0)])))['status'], 2)
        self.assertNotEqual(ack['epoch'], other_ack['epoch'])
        self.assertEqual(c.rpc(27, I(123)), b'\1'+I(123))
        self.assertEqual(base.decode_batch(other.rpc(115))[27], b'\1'+I(0))

    def test_distance_companion_concurrent_hello_has_one_owner(self):
        server, c = self.movement_server(); other = self.client(server)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda client: movement_ack(client.rpc(2001, movement_hello())), [c,other]))
        self.assertEqual(sorted(a['status'] for a in replies), [0,4])
        self.assertTrue(json.loads(self.profile_file('movement').read_text())['Movement']['Protected'])


class MovementCoreTests(unittest.TestCase):
    def test_distance_segment_walk_noise_jump_gap_clock_and_batched_partition(self):
        source = base.ROOT/'WitcherRevival.Server/Net/DistanceIntegrity.cs'
        if not source.is_file() or not (base.DOTNET.parent/'sdk').is_dir():
            self.skipTest('source-level segment fixture requires the local SDK; TCP tests cover the packaged runtime')
        program = r'''
using D = WitcherRevival.Server.Net.DistanceIntegrity;
static class Probe {
 const long Utc = 1791028800000;
 static D.Fix F(int sec,double x=0,double y=0,float accuracy=2,uint flags=1) => new(Utc+sec*1000L, sec*1000L, y/111194.9266,x/111194.9266,accuracy,flags);
 static void Check(bool yes,string why) { if(!yes) throw new Exception(why); }
 static (double Credit,D.Track Track,List<string> Reasons) Run(IEnumerable<D.Fix> fixes) {
   var track=new D.Track();double credit=0;var reasons=new List<string>();
   foreach(var f in fixes) { var r=D.Evaluate(track,f,Utc+120000);track=r.Track;credit+=r.Metres;reasons.Add(r.Reason); }
   return(credit,track,reasons);
 }
 static void Main() {
   var walk=Enumerable.Range(0,17).Select(i=>F(i*5,i*7.5)).ToArray();
   var walking=Run(walk);Check(walking.Credit>=89 && walking.Credit<=106,"walking must credit measured segments, excluding acquisition and pending tail");
   var state=new D.Track();double split=0;
   foreach(var batch in walk.Chunk(3)) foreach(var f in batch) { var r=D.Evaluate(state,f,Utc+120000);state=r.Track;split+=r.Metres; }
   Check(split==walking.Credit,"batch partition must not alter result");
   var noise=Run(Enumerable.Range(0,25).Select(i=>F(i*5,Math.Sin(i)*2,Math.Cos(i)*2,5)));
   Check(noise.Credit==0,"bounded stationary GPS drift must earn zero");
   var jump=Run(new[]{F(0),F(5),F(10),F(15,1000),F(20),F(25),F(30),F(35)});
   Check(jump.Credit==0 && jump.Reasons.Count(r=>r=="speed-jump")==2,"teleport out and back must not count either leg");
   var smallReturn=Run(new[]{F(0),F(5),F(10),F(20,20),F(25)});
   Check(smallReturn.Credit==0 && smallReturn.Reasons.Contains("return-jump"),"unconfirmed moderate out/back spike must not count");
   var resumed=Run(new[]{F(0),F(5),F(10),F(15,1000),F(20,1000),F(25,1000),F(35,1015),F(40,1022.5)});
   Check(resumed.Credit>14 && resumed.Credit<16,"walking resumes from new post-teleport baseline");
   var gap=Run(new[]{F(0),F(5),F(10),F(20,15),F(60,60),F(65,60),F(70,60)});
   Check(gap.Credit==0 && gap.Reasons.Contains("long-gap"),"long gap drops pending segment");
   var reset=Run(new[]{F(0),F(5),F(10),F(20,15),F(25,1000,flags:5)});
   Check(reset.Credit==0,"reset cannot settle previous pending segment");
   var ready=Run(new[]{F(0),F(5),F(10)}).Track;
   foreach(var item in new[]{(F(15) with{Lat=double.NaN},"invalid-fix"),(F(15,accuracy:99),"inaccurate"),
     (F(15,flags:0),"missing-accuracy"),(F(15,flags:3),"mock-location"),(F(10),"non-monotonic"),
     (F(15) with{CapturedUtcMs=Utc+25000},"clock-discontinuity"),(F(-1),"invalid-fix"),
     (F(140),"future-fix")}) {var r=D.Evaluate(ready,item.Item1,Utc+120000);Check(r.Metres==0 && r.Reason==item.Item2,item.Item2);}
   Check(D.Evaluate(ready,F(15),Utc+140000).Reason=="stale-fix","capture age uses server UTC");
   var driving=Run(Enumerable.Range(0,13).Select(i=>F(i*5,i*30,accuracy:5)));
   Check(driving.Credit==0,"sustained vehicle speed must not earn walking distance");
   var clockRecovery=Run(new[]{F(0),F(5),F(10),F(15) with{CapturedUtcMs=Utc+25000},
     F(20) with{CapturedUtcMs=Utc+30000},F(25) with{CapturedUtcMs=Utc+35000},
     F(35,15) with{CapturedUtcMs=Utc+45000},F(40,22.5) with{CapturedUtcMs=Utc+50000}});
   Check(clockRecovery.Credit>14 && clockRecovery.Credit<16,"bounded clock discontinuity reacquires a fresh baseline");
   var stationary=new D.Track();
   for(int sec=0;sec<=240;sec+=5) {var f=F(sec);var r=D.Evaluate(stationary,f,f.CapturedUtcMs);Check(r.Metres==0,"long stationary zero");stationary=r.Track;}
   Check(stationary.Anchor is not null && stationary.Last!.ElapsedMs-stationary.Anchor.ElapsedMs<=120000,"stationary anchor retention bound");
   long tick=0;var lease=new D.SessionLease(()=>tick);var old=Guid.NewGuid();var replacement=Guid.NewGuid();
   Check(lease.CanAcquire(old),"first authenticated session may acquire");lease.Acquire(old);
   tick=89999;Check(lease.IsCurrent(old) && !lease.CanAcquire(replacement),"live owner retains lease through deadline");
   tick=90000;Check(!lease.IsCurrent(old) && lease.CanAcquire(replacement),"silent owner expires without TCP close");
   Check(!lease.Renew(old),"expired old batch cannot renew");lease.Acquire(replacement);
   Check(!lease.IsCurrent(old) && !lease.Renew(old),"stale owner cannot send after takeover");
   Check(!lease.Release(old) && lease.IsCurrent(replacement),"late old socket close cannot revoke replacement");
   tick=179999;Check(lease.Renew(replacement),"valid traffic renews lease");tick=180000;
   Check(lease.IsCurrent(replacement),"renewal extends the activity deadline");
   Check(lease.Release(replacement) && lease.CanAcquire(old),"explicit disconnect releases current owner");
   Console.WriteLine("DISTANCE_CORE_PASS");
 }
}
'''
        with tempfile.TemporaryDirectory(prefix='synthetic-distance-core-') as folder:
            directory=Path(folder);shutil.copyfile(source,directory/'DistanceIntegrity.cs')
            (directory/'Program.cs').write_text(program)
            (directory/'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            (directory/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
            built=subprocess.run([str(base.DOTNET),'build','Probe.csproj','-c','Release','-p:NuGetAudit=false','-p:UseSharedCompilation=false','--nologo'],cwd=directory,env=base.environment(),capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(base.DOTNET),str(directory/'bin/Release/net10.0/Probe.dll')],cwd=directory,env=base.environment(),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('DISTANCE_CORE_PASS',result.stdout)

def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (DistanceTests, DistanceTaskTests, MovementTests, MovementCoreTests)
                              for name in loader.getTestCaseNames(cls) if name.startswith('test_distance_'))

if __name__=='__main__':unittest.main()
