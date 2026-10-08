// GPS collector, ported from the 1.1.116 reconstruction's LAB 25 companion (client/distance_fix/ there; see
// README credits). It captures every Android location fix with its timing and sends bounded batches as RPC 2001
// over the game's own authenticated connection. The server's walking filter decides any credited distance
// (observation or protected policy in the operator panel) and keeps the newest position for placing story goals.
// No socket, file or identity of its own; coordinates are never logged.
'use strict';
import Java from 'frida-java-bridge';

// ── Queue and wire format, unchanged from the LAB companion core ──
class DistanceWire {
  static integer(value, minimum=0) {
    if(!Number.isSafeInteger(value) || value<minimum) throw Error('integer');
    return value;
  }
  static i64(view, offset, value) {
    DistanceWire.integer(value, -Number.MAX_SAFE_INTEGER);
    const high=Math.floor(value/4294967296), low=value-high*4294967296;
    view.setInt32(offset,high,false);view.setUint32(offset+4,low,false);
  }
  static read64(view,offset) {
    const value=view.getInt32(offset,false)*4294967296+view.getUint32(offset+4,false);
    return DistanceWire.integer(value,-Number.MAX_SAFE_INTEGER);
  }
  static hello(elapsed,utc) {
    const bytes=new Uint8Array(24),v=new DataView(bytes.buffer);bytes[0]=1;bytes[1]=1;
    v.setUint32(4,7,false);this.i64(v,8,elapsed);this.i64(v,16,utc);return bytes;
  }
  static batch(epoch,seq,fixes) {
    if(!(epoch instanceof Uint8Array) || epoch.length!==16 || !fixes.length || fixes.length>32) throw Error('batch');
    const b=new Uint8Array(32+fixes.length*40),v=new DataView(b.buffer);b[0]=1;b[1]=2;b.set(epoch,4);
    this.i64(v,20,seq);v.setUint32(28,fixes.length,false);
    fixes.forEach((f,i)=>{const at=32+40*i;
      this.i64(v,at,f.utc);this.i64(v,at+8,f.elapsed);v.setFloat64(at+16,f.lat,false);
      v.setFloat64(at+24,f.lon,false);v.setFloat32(at+32,f.accuracy,false);v.setUint32(at+36,f.flags,false);
    });return b;
  }
  static envelope(id,method,payload) {
    const b=new Uint8Array(18+payload.length),v=new DataView(b.buffer);b[0]=1;b[1]=1;
    this.i64(v,6,id);v.setInt32(14,method,false);b.set(payload,18);return b;
  }
  static response(bytes) {
    if(!(bytes instanceof Uint8Array) || bytes.length<18) return null;
    const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
    if(bytes[0]!==1 || bytes[1]!==2) return null;
    const count=v.getInt32(2,false);if(count<0 || count>4096 || 18+8*count>bytes.length) return null;
    const start=6+8*count,id=this.read64(v,start),method=v.getInt32(start+8,false);
    return {id,method,payload:bytes.slice(start+12)};
  }
  static ack(bytes) {
    if(bytes.length!==48 || bytes[0]!==1 || ![1,2].includes(bytes[1])) throw Error('ack layout');
    const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),status=v.getUint16(2,false);
    const result={op:bytes[1],status,epoch:bytes.slice(4,20),nextSeq:this.read64(v,20),
      total:v.getInt32(28,false),credited:v.getInt32(32,false),mode:v.getUint32(36,false),serverUtc:this.read64(v,40)};
    if(status>7 || result.nextSeq<1 || result.total<0 || result.credited<0 || result.mode>1) throw Error('ack values');
    return result;
  }
  static sameEpoch(a,b) {return a!==null && b!==null && a.length===b.length && a.every((n,i)=>n===b[i]);}
}

class DistanceCoordinator {
  constructor(io) {
    this.io=io;this.serial=0;this.queue=[];this.pending=null;this.epoch=null;this.nextSeq=1;
    this.connected=false;this.paused=false;this.permission=true;this.fixSeen=false;this.resetNext=true;
    this.afterAckElapsed=Infinity;this.lastElapsed=null;this.lastFlush=0;this.negotiateAfter=0;
    this.mode=null;this.counts={captured:0,dropped:0,sent:0,retried:0,acked:0,resets:0};
  }
  note(code) {this.io.note(code);}
  fresh(connected) {
    this.counts.dropped+=this.queue.length;this.queue=[];this.pending=null;this.epoch=null;
    this.nextSeq=1;this.connected=connected;this.fixSeen=false;this.resetNext=true;
    this.lastElapsed=null;this.afterAckElapsed=Infinity;this.negotiateAfter=0;this.mode=null;
    ++this.counts.resets;this.note(connected?'session-ready':'session-ended');
  }
  breakContinuity() {this.resetNext=true;}
  pause(value) {
    this.paused=!!value;this.resetNext=true;
    // Pending immutable data may still be acknowledged, but no segment spans a pause.
    this.counts.dropped+=this.queue.length;this.queue=[];
  }
  setPermission(value) {
    this.permission=!!value;this.resetNext=true;
    if(!this.permission) {this.counts.dropped+=this.queue.length;this.queue=[];this.fixSeen=false;}
  }
  capture(value) {
    const f={...value};++this.counts.captured;
    const valid=Number.isSafeInteger(f.utc) && f.utc>0 && Number.isSafeInteger(f.elapsed) && f.elapsed>=0
      && Number.isFinite(f.lat) && Math.abs(f.lat)<=90 && Number.isFinite(f.lon) && Math.abs(f.lon)<=180
      && Number.isFinite(f.accuracy) && f.accuracy>=0 && Number.isInteger(f.flags) && !(f.flags&~7);
    if(!valid || this.paused || !this.permission) {++this.counts.dropped;this.resetNext=true;return;}
    if((f.flags&1) && f.accuracy>0) this.fixSeen=true;
    if(!this.connected || this.epoch===null || f.elapsed<this.afterAckElapsed) {++this.counts.dropped;return;}
    if(this.lastElapsed!==null && f.elapsed<=this.lastElapsed) {
      ++this.counts.dropped;if(f.elapsed<this.lastElapsed)this.resetNext=true;return;
    }
    this.lastElapsed=f.elapsed;
    if(this.resetNext) {f.flags|=4;this.resetNext=false;}
    this.queue.push(f);
    if(!(f.flags&1) || f.accuracy<=0 || (f.flags&2)) this.resetNext=true;
    this.trim(this.io.clock().elapsed);
  }
  trim(now) {
    let removed=0;
    while(this.queue.length && (this.queue.length>64 || now-this.queue[0].elapsed>60000)) {this.queue.shift();++removed;}
    if(removed) {
      this.counts.dropped+=removed;
      if(this.queue.length)this.queue[0].flags|=4;else this.resetNext=true;
      this.note('queue-trimmed');
    }
  }
  start(op,payload,count=0) {
    // Separate ID namespace and method key; no native request/retry table entry is created.
    const id=-(2400000000+(++this.serial));
    this.pending={id,op,count,firstSeq:this.nextSeq,wire:DistanceWire.envelope(id,2001,payload),
      created:this.io.clock().elapsed,sentAt:-Infinity,queued:false,attempts:0};
  }
  written(id) {if(this.pending && id===this.pending.id)this.pending.queued=false;}
  receive(id,payload) {
    const p=this.pending;if(!p || p.id!==id)return;
    let ack;try {ack=DistanceWire.ack(payload);} catch(_) {this.note('bad-ack');return;}
    if(ack.op!==p.op || (p.op===2 && [0,6].includes(ack.status) && !DistanceWire.sameEpoch(ack.epoch,this.epoch))) {this.note('foreign-ack');return;}
    if(ack.status===6) {this.note('storage-retry');return;}
    if(ack.status!==0) {
      this.pending=null;this.epoch=null;this.queue=[];this.resetNext=true;
      this.negotiateAfter=this.io.clock().elapsed+30000;this.note('refused-'+ack.status);return;
    }
    if((p.op===1 && ack.nextSeq!==1) || (p.op===2 && ack.nextSeq!==p.firstSeq+p.count)) {this.note('bad-sequence-ack');return;}
    this.pending=null;this.mode=ack.mode;this.nextSeq=ack.nextSeq;++this.counts.acked;
    if(p.op===1) {
      this.epoch=ack.epoch;this.afterAckElapsed=this.io.clock().elapsed;
      this.lastElapsed=null;this.queue=[];this.resetNext=true;this.lastFlush=this.afterAckElapsed;
      this.note(ack.mode===1?'protected-ready':'shadow-ready');
    } else this.note('batch-ack');
    this.io.accepted(ack.total,ack.credited,ack.mode);
  }
  tick() {
    const now=this.io.clock();this.trim(now.elapsed);
    if(!this.connected || this.paused || !this.permission || !this.fixSeen)return;
    if(this.pending && now.elapsed-this.pending.created>60000) {
      // An expired uncertain batch cannot bridge into a fresh epoch. The server retains any
      // already committed credit; a distinct HELLO replaces the session epoch and resets its base.
      this.pending=null;this.epoch=null;this.queue=[];this.resetNext=true;
      this.negotiateAfter=now.elapsed+1000;this.note('batch-expired');
    }
    if(!this.pending) {
      if(this.epoch===null && now.elapsed>=this.negotiateAfter)this.start(1,DistanceWire.hello(now.elapsed,now.utc));
      else if(this.epoch!==null && this.queue.length && (this.queue.length>=32 || now.elapsed-this.lastFlush>=10000)) {
        const fixes=this.queue.splice(0,32);this.start(2,DistanceWire.batch(this.epoch,this.nextSeq,fixes),fixes.length);this.lastFlush=now.elapsed;
      }
    }
    const p=this.pending;
    if(p && !p.queued && now.elapsed-p.sentAt>=7000) {
      p.queued=true;
      if(this.io.send(p.wire,p.id)) {if(p.attempts++)++this.counts.retried;++this.counts.sent;p.sentAt=now.elapsed;}
      else p.queued=false;
    }
  }
}

// ── Runtime bridge: the LAB runtime with our addresses and the Android 11 capture path ──
// 1.1.116 libil2cpp.so (sha256 c8a5556b…, pinned by build_client.py), so no per-method byte guards. HandleWrites
// matches the LAB's validated copy (sha256 2a99137f…), which fixes the write probe sites below.
const EXPORTS = {
  domain_get: 0x16d1258, domain_get_assemblies: 0x16d1264, assembly_get_image: 0x16d0c38, image_get_name: 0x16d17fc,
  class_from_name: 0x16d0c64, class_get_methods: 0x16d0c88, method_get_name: 0x16d14c8, method_get_param_count: 0x16d14d8,
  method_get_param: 0x16d14dc, type_get_name: 0x16d1678, free: 0x16d0c10, class_get_field_from_name: 0x16d0c84,
  field_get_offset: 0x16d1398, field_get_value_object: 0x16d13a4, runtime_invoke: 0x16d15c4, object_get_class: 0x16d1558,
  array_new: 0x16d0c20, gchandle_new: 0x16d1428, gchandle_get_target: 0x16d1438, gchandle_free: 0x16d1480,
};
const AT = {
  tick: 0x1b961b0,          // LocationModule.Tick: Unity thread, every frame
  receive: 0x19319e0,       // ClientWorker.HandleReceived
  factory: 0x31860f4,       // SocketMessageFactory.Create(byte, byte[])
  close: 0x3186b20,         // ThreadedClient.Close
  initialize: 0x1930c98,    // ClientWorker.Initialize
  pause: 0x1a3e5a4,         // Game.OnApplicationPause(bool)
  handleWrites: 0x3186820,  // ThreadedClient.HandleWrites
};
const WRITE_SNAPSHOT = AT.handleWrites + 0x38, WRITE_SUCCESS = [AT.handleWrites + 0x60, AT.handleWrites + 0x90];

export function startGps(image, log) {
  const zero=ptr(0),keep=[];
  let n=null,ready=false,failed=false,javaReady=false,coordinator=null;
  let workerHandle=0,workerKey='',unityThread=null,clock={elapsed:0,utc:0};
  let lastTick=-1,lastPermission=-1,lastStats=-1,permissions=true,lastCaptured=-1,lastCode='';
  const queued=new Map(); // At most one telemetry message held in the native queue.
  function note(code) {
    // Codes and bounded counters only; never exception text, epochs, payloads or fixes.
    if(code===lastCode)return;lastCode=code;log('gps',code);
  }
  function raw(p,len) {return new Uint8Array(p.readByteArray(len));}
  const fn=(name,result,args)=>new NativeFunction(image.base.add(EXPORTS[name]),result,args);
  n={domain:fn('domain_get','pointer',[]),assemblies:fn('domain_get_assemblies','pointer',['pointer','pointer']),
    assemblyImage:fn('assembly_get_image','pointer',['pointer']),imageName:fn('image_get_name','pointer',['pointer']),
    klass:fn('class_from_name','pointer',['pointer','pointer','pointer']),methods:fn('class_get_methods','pointer',['pointer','pointer']),
    methodName:fn('method_get_name','pointer',['pointer']),paramCount:fn('method_get_param_count','uint',['pointer']),
    param:fn('method_get_param','pointer',['pointer','uint']),typeName:fn('type_get_name','pointer',['pointer']),
    free:fn('free','void',['pointer']),field:fn('class_get_field_from_name','pointer',['pointer','pointer']),
    fieldOffset:fn('field_get_offset','int',['pointer']),getRef:fn('field_get_value_object','pointer',['pointer','pointer']),
    invoke:fn('runtime_invoke','pointer',['pointer','pointer','pointer','pointer']),
    objectClass:fn('object_get_class','pointer',['pointer']),arrayNew:fn('array_new','pointer',['pointer','ulong']),
    root:fn('gchandle_new','uint',['pointer','bool']),target:fn('gchandle_get_target','pointer',['uint']),
    unroot:fn('gchandle_free','void',['uint'])};
  function root(p) {if(p.isNull())throw Error('null root');const h=n.root(p,0);if(!h)throw Error('root');return h;}
  function cstr(s) {return Memory.allocUtf8String(s);}
  function invoke(m,o,values) {
    const args=values.length?Memory.alloc(values.length*8):zero;
    values.forEach((p,i)=>args.add(8*i).writePointer(p));
    const ex=Memory.alloc(8);ex.writePointer(zero);const result=n.invoke(m,o,args,ex);
    if(!ex.readPointer().isNull())throw Error('managed invocation');return result;
  }
  function method(k,name,types) {
    const it=Memory.alloc(8);it.writePointer(zero);
    for(;;) {const m=n.methods(k,it);if(m.isNull())break;
      if(n.methodName(m).readCString()!==name || n.paramCount(m)!==types.length)continue;
      const actual=types.map((_,i)=>{const p=n.typeName(n.param(m,i));try{return p.readCString();}finally{n.free(p);}});
      if(actual.every((t,i)=>t===types[i]))return m;
    }throw Error('method signature');
  }
  function field(k,name,offset) {const f=n.field(k,cstr(name));if(f.isNull() || n.fieldOffset(f)!==offset)throw Error('field layout');return f;}
  function writtenRequestId(message,consumed=true) {
    // Serialize consumes the original ByteBuffer. Inspect only its retained envelope,
    // without resetting the native read position or reading the GPS payload.
    if(message.add(0x10).readU8()!==1)return null;
    const size=message.add(0x20).readS32(),buffer=message.add(0x18).readPointer();
    if(size<18 || size>32768 || buffer.isNull())return null;
    const array=buffer.add(0x10).readPointer();
    const read=buffer.add(0x1c).readS32();
    if(array.isNull() || (read!==size && (consumed || read!==0)) || buffer.add(0x20).readS32()!==size
      || Number(array.add(0x18).readU64())<size)return null;
    const bytes=raw(array.add(0x20),18),view=new DataView(bytes.buffer);
    if(bytes[0]!==1 || bytes[1]!==1 || view.getInt32(2,false)!==0 || view.getInt32(14,false)!==2001)return null;
    return DistanceWire.read64(view,6);
  }
  function installWriteObservers(threadedClass,messageClass) {
    const listeners=[];
    let replay=null; // At most one tuple of primitive values; no unrooted managed reference.
    function tracked(client,consumed) {
      if(!queued.size || client.isNull() || !n.objectClass(client).equals(threadedClass))return null;
      const message=client.add(0x60).readPointer();
      if(message.isNull())return null;
      const key=message.toString(),id=queued.get(key);
      if(id===undefined || !n.objectClass(message).equals(messageClass) || writtenRequestId(message,consumed)!==id)return null;
      return {clientKey:client.toString(),thread:Process.getCurrentThreadId(),key,id};
    }
    function complete(item) {
      if(item!==null && queued.get(item.key)===item.id) {
        queued.delete(item.key);if(coordinator)coordinator.written(item.id);
      }
    }
    try {
      // Function-form instruction probes: an object {onEnter} also installs a
      // return listener in QJS. Each site permits a full 16-byte ARM64 redirect
      // without overwriting a branch target inside it. Do not hook +0x5c: the
      // ordinary no-replay path jumps to +0x60, inside that redirect.
      listeners.push(Interceptor.attach(image.base.add(WRITE_SNAPSHOT),function() {
        replay=null;
        try {replay=tracked(this.context.x19,false);}catch(_) {note('write-success-guard');}
      }));
      listeners.push(Interceptor.attach(image.base.add(WRITE_SUCCESS[0]),function() {
        const item=replay;replay=null;
        try {
          if(item===null || item.thread!==Process.getCurrentThreadId())return;
          const client=this.context.x19;
          if(client.isNull() || client.toString()!==item.clientKey || !n.objectClass(client).equals(threadedClass))return;
          // The native old-message path has cleared +0x60. Read no message
          // memory here: its primitive identity was checked before Write.
          if(!client.add(0x60).readPointer().isNull())return;
          complete(item);
        } catch(_) {note('write-success-guard');}
      }));
      listeners.push(Interceptor.attach(image.base.add(WRITE_SUCCESS[1]),function() {
        try {complete(tracked(this.context.x19,true));}catch(_) {note('write-success-guard');}
      }));
      return listeners;
    } catch(error) {for(const listener of listeners)listener.detach();throw error;}
  }
  let runtimeSend=()=>false;
  function buildRuntime() {
    const count=Memory.alloc(8);count.writeU64(0);const list=n.assemblies(n.domain(),count),size=Number(count.readU64()),images={};
    if(size<1 || size>512)throw Error('image count');
    for(let i=0;i<size;i++){const im=n.assemblyImage(list.add(8*i).readPointer());images[n.imageName(im).readCString()]=im;}
    function klass(im,ns,name){if(!images[im])throw Error('image');const k=n.klass(images[im],cstr(ns),cstr(name));if(k.isNull())throw Error('class');return k;}
    const wk=klass('Game.dll','WitcherWorld.WebstuffClient','ClientWorker');
    const mk=klass('Game.dll','WitcherWorld.WebstuffClient.Core.Socket','Message');
    const bk=klass('Game.dll','WitcherWorld.WebstuffClient','ByteBuffer');
    const fk=klass('Game.dll','WitcherWorld.WebstuffClient.Network','SocketMessageFactory');
    const tk=klass('Game.dll','WitcherWorld.WebstuffClient.Network','ThreadedClient');
    const byte=klass('mscorlib.dll','System','Byte');
    const wf=field(wk,'_factory',0x30),wq=field(wk,'_outgoingSocketMessages',0x58);
    field(mk,'Type',0x10);field(mk,'Data',0x18);field(mk,'Size',0x20);
    field(bk,'_buffer',0x10);field(bk,'_capacity',0x18);field(bk,'_readPosition',0x1c);field(bk,'_writePosition',0x20);
    field(tk,'_currentWriteMessage',0x60);
    const handleWrites=method(tk,'HandleWrites',[]);
    if(!handleWrites.readPointer().equals(image.base.add(AT.handleWrites)))throw Error('write success method');
    const create=method(fk,'Create',['System.Byte','System.Byte[]']);
    if(!create.readPointer().equals(image.base.add(AT.factory)))throw Error('factory code');
    const receiveAddress=image.base.add(AT.receive),original=new NativeFunction(receiveAddress,'void',['pointer','pointer','pointer']);
    function rememberWorker(w) {
      if(w.toString()===workerKey)return;
      if(!n.objectClass(w).equals(wk))throw Error('worker class');
      const h=root(w);if(workerHandle)n.unroot(workerHandle);workerHandle=h;workerKey=w.toString();queued.clear();
      if(coordinator)coordinator.fresh(false);
    }
    function messagePayload(message) {
      if(message.isNull() || message.add(0x10).readU8()!==1)return null;
      const size=message.add(0x20).readS32();if(size<18 || size>32768)return null;
      const buffer=message.add(0x18).readPointer();if(buffer.isNull())return null;
      const arr=buffer.add(0x10).readPointer(),start=buffer.add(0x1c).readS32(),end=buffer.add(0x20).readS32();
      if(arr.isNull() || start<0 || end<start || end-start!==size || end>Number(arr.add(0x18).readU64()))return null;
      return raw(arr.add(0x20+start),size);
    }
    function requestId(message) {
      const bytes=messagePayload(message);if(bytes===null || bytes[0]!==1 || bytes[1]!==1)return null;
      const v=new DataView(bytes.buffer),count=v.getInt32(2,false);
      if(count!==0 || v.getInt32(14,false)!==2001)return null;
      return DistanceWire.read64(v,6);
    }
    const replacement=new NativeCallback((worker,message,mi)=>{
      let consumed=false;
      try {
        rememberWorker(worker);
        const type=message.isNull()?-1:message.add(0x10).readU8();
        if(type===3) { // Exact original authentication-success payload; no identifier is read.
          const b=message.add(0x18).readPointer();
          if(!b.isNull()) {
            const a=b.add(0x10).readPointer(),start=b.add(0x1c).readS32(),end=b.add(0x20).readS32();
            if(!a.isNull() && start>=0 && end-start===5 && end<=Number(a.add(0x18).readU64())) {
              const p=raw(a.add(0x20+start),5);
              if(p[0]===0 && p[1]===0 && p[2]===0 && p[3]===1 && p[4]===0 && coordinator)coordinator.fresh(true);
            }
          }
        } else if(type===1) {
          const b=messagePayload(message);
          if(b!==null) {
            // Read method before 64-bit request ID: ordinary native IDs may exceed JS's safe integer range.
            const v=new DataView(b.buffer),ackCount=v.getInt32(2,false),at=6+8*ackCount;
            if(b[0]===1 && b[1]===2 && ackCount>=0 && ackCount<=4096 && at+12<=b.length) {
              if(v.getInt32(at+8,false)===2001) {
                consumed=true;
                const response=DistanceWire.response(b);
                if(coordinator && response)coordinator.receive(response.id,response.payload);
              } else if(coordinator && !coordinator.connected)coordinator.fresh(true);
            }
          }
        }
      } catch(_) {note('receive-guard');}
      if(!consumed)original(worker,message,mi);
    },'void',['pointer','pointer','pointer']);
    const listeners=installWriteObservers(tk,mk);
    listeners.push(Interceptor.attach(image.base.add(AT.close),{onEnter(){if(coordinator)coordinator.fresh(false);}}));
    listeners.push(Interceptor.attach(image.base.add(AT.initialize),{onEnter(){queued.clear();if(coordinator)coordinator.fresh(false);}}));
    listeners.push(Interceptor.attach(image.base.add(AT.pause),{onEnter(args){if(coordinator)coordinator.pause(args[1].toInt32()!==0);}}));
    function send(bytes,id) {
      if(!ready || !workerHandle || queued.size || Process.getCurrentThreadId()!==unityThread)return false;
      const w=n.target(workerHandle);if(w.isNull())return false;
      const queue=n.getRef(wq,w),factory=n.getRef(wf,w);if(queue.isNull() || factory.isNull())return false;
      const qk=n.objectClass(queue),enqueue=method(qk,'Enqueue',['WitcherWorld.WebstuffClient.Core.Socket.Message']);
      const countMethod=method(qk,'get_Count',[]),box=invoke(countMethod,queue,[]);
      if(box.isNull() || box.add(0x10).readS32()>32)return false;
      const array=n.arrayNew(byte,bytes.length),ah=root(array);let mh=0;
      try {
        array.add(0x20).writeByteArray(bytes);
        const channel=Memory.alloc(1);channel.writeU8(1);
        const message=invoke(create,factory,[channel,array]);mh=root(message);
        if(requestId(message)!==id)throw Error('serialized message');
        const key=message.toString();queued.set(key,id);
        try {invoke(enqueue,queue,[message]);}catch(e){queued.delete(key);throw e;}
        return true;
      } finally {if(mh)n.unroot(mh);n.unroot(ah);}
    }
    runtimeSend=send;
    Interceptor.replace(receiveAddress,replacement);Interceptor.flush();keep.push(replacement,...listeners);
    ready=true;note('native-ready');
  }
  function installCapture() {
    const app=Java.use('android.app.ActivityThread').currentApplication();
    const sdk=Java.use('android.os.Build$VERSION').SDK_INT.value;
    // The clock is read natively: SystemClock.elapsedRealtime() is CLOCK_BOOTTIME and currentTimeMillis() is the
    // wall clock, so the 250 ms timer below needs no Java call (each one attached this thread to the VM).
    const clockGettime=new NativeFunction(Process.getModuleByName('libc.so').getExportByName('clock_gettime'),'int',['int','pointer']);
    const timespec=Memory.alloc(16);
    function updateClock() {
      clockGettime(7,timespec); // CLOCK_BOOTTIME
      clock={elapsed:timespec.readS64().toNumber()*1000+Math.floor(timespec.add(8).readS64().toNumber()/1000000),utc:Date.now()};
    }
    updateClock();
    coordinator=new DistanceCoordinator({clock:()=>clock,note,send:(b,id)=>runtimeSend(b,id),accepted:()=>{}});
    const location=Java.use('android.location.Location');
    function capture(fix) {
      // Unity's path interleaves gps, network and passive fixes; an older one would only force a new baseline.
      const elapsed=Math.floor(Number(fix.getElapsedRealtimeNanos().toString())/1000000);
      if(elapsed<=lastCaptured)return;
      lastCaptured=elapsed;
      const has=fix.hasAccuracy();
      coordinator.capture({utc:Number(fix.getTime().toString()),elapsed,
        lat:Number(fix.getLatitude()),lon:Number(fix.getLongitude()),
        accuracy:has?Number(fix.getAccuracy()):0,flags:(has?1:0)|(fix.isFromMockProvider()?2:0)});
    }
    // Android 12+: no Java method of the game is replaced. On Android 16 (Samsung, ART cecb684d…) every method
    // replacement by the Java bridge broke ART: replacing ReflectionHelper.a crashed the GC
    // (CodeInfo::DecodeGcMasksOnly), and replacing the fused callback CustomUnityActivity$3.onLocationResult
    // crashed the first delivery from Google Play services (Class::GetDescriptor in InitializeClass). The game
    // keeps location running, so the newest fix Android holds is read from LocationManager instead, twice a
    // second, with plain calls from this thread.
    let pollFix=null;
    if(sdk>30) {
      const manager=Java.cast(app.getSystemService('location'),Java.use('android.location.LocationManager'));
      const providers=['fused','gps','network'];
      let lastPoll=-1;
      pollFix=()=>{
        if(clock.elapsed-lastPoll<500)return;
        lastPoll=clock.elapsed;
        let newest=null,newestAt=-1;
        for(const provider of providers) {
          let fix=null;
          try {fix=manager.getLastKnownLocation(provider);} catch(_) {continue;} // provider missing on this phone
          if(fix===null)continue;
          const at=Number(fix.getElapsedRealtimeNanos().toString());
          if(at>newestAt) {newest=fix;newestAt=at;}
        }
        if(newest!==null)capture(newest);
      };
    }
    // Android 11 and older: Unity listens to LocationManager through a Java proxy; every proxy call passes here.
    if(sdk<=30) {
      const proxy=Java.use('com.unity3d.player.ReflectionHelper').a.overload('long','java.lang.String','[Ljava.lang.Object;');
      proxy.implementation=function(handle,name,args) {
        if(name==='onLocationChanged') {
          try {
            updateClock();
            const fix=args!==null && args.length===1 ? args[0] : null;
            if(fix!==null && location.class.isInstance(fix)) {
              if(permissions)capture(Java.cast(fix,location));else coordinator.breakContinuity();
            }
          } catch(_) {coordinator.breakContinuity();note('capture-failed');}
        }
        return proxy.call(this,handle,name,args);
      };
      keep.push(proxy);
    }
    setInterval(()=>{
      try {updateClock();}catch(_){note('clock-unavailable');if(coordinator)coordinator.breakContinuity();return;}
      if(clock.elapsed-lastPermission>=2000) {
        lastPermission=clock.elapsed;
        try {Java.performNow(()=>{
          const current=app.checkSelfPermission('android.permission.ACCESS_FINE_LOCATION')===0;
          if(permissions!==current) {permissions=current;coordinator.setPermission(current);note(current?'permission-restored':'permission-missing');}
        });}catch(_){note('permission-unavailable');coordinator.breakContinuity();}
      }
      if(pollFix!==null && permissions) {
        try {Java.performNow(pollFix);}catch(_){note('capture-failed');coordinator.breakContinuity();}
      }
      if(clock.elapsed-lastStats>=60000) {
        lastStats=clock.elapsed;const c=coordinator.counts;
        log('gps counts captured='+c.captured+' dropped='+c.dropped+' sent='+c.sent+' ack='+c.acked+' resets='+c.resets);
      }
    },250);
    javaReady=true;note('capture-ready');
  }

  keep.push(Interceptor.attach(image.base.add(AT.tick),{onEnter(){
    if(failed)return;
    const thread=Process.getCurrentThreadId();if(unityThread===null)unityThread=thread;if(thread!==unityThread)return;
    try {
      if(!ready)buildRuntime();
      if(coordinator && javaReady && clock.elapsed!==lastTick) {lastTick=clock.elapsed;coordinator.tick();}
    }catch(_){if(!ready)failed=true;note('tick-guard');}
  }}));
  // Java.perform waits for the app's class loader; a failure leaves the game's own location handling alone.
  Java.perform(()=>{try {installCapture();} catch(e) {failed=true;note('capture-unavailable');log('gps', e.message);}});
}
