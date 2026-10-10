// Points The Witcher: Monster Slayer 1.1.116 at a self-hosted server. Frida Gadget loads it into the game.
// RVA holds il2cpp exports of the original 1.1.116 libil2cpp.so (sha256 c8a5556b…, checked by
// build_client.py). They are used instead of a by-name lookup, which crashed the Android 17 linker.
// It imports the GPS collector and Frida's Java bridge, so restart.py bundles it before pushing it.
'use strict';
import Java from 'frida-java-bridge';
import { startGps } from './gps.js';

const CONFIG = {
  gameHost: '127.0.0.1',  // IPv4 literal of the server, as the phone reaches it
  gamePort: 4253,
  oldHosts: /(^|\.)(thewitchermonsterslayer|spokko)\.com$/,  // the original servers; resolved to gameHost instead
  rewrite: [  // URL prefix -> replacement, applied to every UnityWebRequest
    ['https://gatekeeper.cloud.thewitchermonsterslayer.com', 'http://127.0.0.1:18080'],  // news
    ['https://vectortile.googleapis.com', 'http://127.0.0.1:18082'],                     // OSM map tiles
  ],
  // What's new reads its feed through System.Net (GatekeeperNewsLoader.Fetch), from the build's own environment
  // (gatekeeper.test.dev.spokko.com on 1.1.116); that HTTPS request is refused at connect(), so send it to the server.
  news: [/^https:\/\/gatekeeper\.[^/]+\/news\//, 'http://127.0.0.1:18080/news/'],
  logPort: 18094,  // the companion app's log sink (ServerService.LOG_PORT)
  crashMarker: '/sdcard/Android/data/com.spokko.witchermonsterslayer/files/crash-test',  // test only, see startDiagnostics
};
const LIBIL2CPP_SHA256 = 'c8a5556b1d37e86bb9427ce5b3d70389ac9b39fd9abcb81f31651d904c5b4aa3';  // what build_client.py verified

// Gadget's script mode drops console output, so write to logcat ourselves (tag Frida; restart.py records it) and
// to the companion app's log sink, so a bug report holds the game's side of a crash.
const androidLog = new NativeFunction(Process.getModuleByName('liblog.so').getExportByName('__android_log_write'),
                                      'int', ['int', 'pointer', 'pointer']);
const logTag = Memory.allocUtf8String('Frida');
const log = (...parts) => {
  const text = parts.join(' ');
  androidLog(4, logTag, Memory.allocUtf8String(text));
  sinkWrite(text);
};

// Native redirect: the game reads its server from ClientSettings without always calling the getters,
// so also resolve the original hosts to our server, then map their ports at connect().
// Port 80 (the game protocol) goes to gamePort; 443 (HTTPS via System.Net) is refused at once
// instead of hanging, since our server speaks plain HTTP.
const libc = Process.getModuleByName('libc.so');
const serverHost = Memory.allocUtf8String(CONFIG.gameHost);
const resolved = new Set();
Interceptor.attach(libc.getExportByName('getaddrinfo'), {
  onEnter(args) {
    const host = args[0].isNull() ? null : args[0].readCString();
    if (host && !resolved.has(host)) {
      resolved.add(host);
      log('dns', host, CONFIG.oldHosts.test(host) ? '-> ' + CONFIG.gameHost : '(unchanged)');
    }
    if (host && CONFIG.oldHosts.test(host)) args[0] = serverHost;
  },
});
const serverIp = CONFIG.gameHost.split('.').map(Number);
Interceptor.attach(libc.getExportByName('connect'), {
  onEnter(args) {
    const sa = args[1];
    const family = sa.readU16();
    // AF_INET: address at +4; AF_INET6: only v4-mapped addresses (::ffff:a.b.c.d), IPv4 part at +20
    const at = family === 2 ? 4 : family === 10 && sa.add(18).readU16() === 0xffff ? 20 : -1;
    if (at < 0 || !serverIp.every((b, i) => sa.add(at + i).readU8() === b)) return;
    const port = (sa.add(2).readU8() << 8) | sa.add(3).readU8();
    const to = port === 80 ? CONFIG.gamePort : port === 443 ? 1 : port;
    sa.add(2).writeU8(to >> 8);
    sa.add(3).writeU8(to & 0xff);
  },
});

// The log sink: lines go to the companion app over a loopback socket. Best effort and never blocking the game: the socket
// is non-blocking, sends use MSG_DONTWAIT|MSG_NOSIGNAL, a missing listener or a full buffer only loses lines, and nothing
// here runs at script load (the first line connects, at most every 5 s).
const cSocket = new NativeFunction(libc.getExportByName('socket'), 'int', ['int', 'int', 'int']);
const cConnect = new SystemFunction(libc.getExportByName('connect'), 'int', ['int', 'pointer', 'int']);
const cSend = new NativeFunction(libc.getExportByName('send'), 'int', ['int', 'pointer', 'int', 'int']);
const cClose = new NativeFunction(libc.getExportByName('close'), 'int', ['int']);
const EINPROGRESS = 115;
let sinkFd = -1;
let sinkTried = 0;
let sinkOpened = 0;
const sinkBacklog = [];

function openSink() {
  const fd = cSocket(2, 1 | 0x800, 0);  // AF_INET, SOCK_STREAM | SOCK_NONBLOCK
  if (fd < 0) return -1;
  const sa = Memory.alloc(16);
  sa.writeByteArray(new Array(16).fill(0));
  sa.writeU16(2);
  sa.add(2).writeU8(CONFIG.logPort >> 8);
  sa.add(3).writeU8(CONFIG.logPort & 0xff);
  serverIp.forEach((b, i) => sa.add(4 + i).writeU8(b));
  const rc = cConnect(fd, sa, 16);
  if (rc.value !== 0 && rc.errno !== EINPROGRESS) { cClose(fd); return -1; }
  return fd;
}

function sinkSend(line) {
  return cSend(sinkFd, Memory.allocUtf8String(line), line.length, 0x4040) === line.length;
}

function sinkWrite(text) {
  try {
    // ASCII only, so a line's length is its byte count
    sinkBacklog.push(new Date().toISOString() + ' pid=' + Process.id + ' ' + String(text).replace(/[^\x20-\x7e]/g, '?').slice(0, 2000) + '\n');
    if (sinkBacklog.length > 200) sinkBacklog.shift();
    if (sinkFd < 0) {
      if (Date.now() - sinkTried < 5000) return;
      sinkTried = Date.now();
      sinkFd = openSink();
      sinkOpened = Date.now();
      if (sinkFd < 0) return;
    }
    while (sinkBacklog.length) {
      if (!sinkSend(sinkBacklog[0])) {
        // still connecting, a full buffer, or the app is gone: after a second the connection is dropped and rebuilt later
        if (Date.now() - sinkOpened > 1000) {
          cClose(sinkFd);
          sinkFd = -1;
        }
        return;
      }
      sinkBacklog.shift();
    }
  } catch (e) {
    // a log line must never break the game
  }
}

const RVA = {
  init: 0x16d0afc, domain_get: 0x16d1258, domain_get_assemblies: 0x16d1264, assembly_get_image: 0x16d0c38,
  image_get_name: 0x16d17fc, class_from_name: 0x16d0c64, class_get_method_from_name: 0x16d0c8c,
  string_new: 0x16d15f4, string_chars: 0x16d15f0, string_length: 0x16d15ec, resolve_icall: 0x16d0c08,
  object_get_class: 0x16d1558,
  create_http: 0x20a4a28,  // System.Net.WebRequest.CreateHttp(string); the overload with Uri has the same name and arity
  weather_response: 0x247a5f4,  // GetWeatherResponse.Factory.Deserialize: the reply with the weather code (+0x10)
  astro_condition: 0x17e1fac,   // AstroConditionNode.HasDesiredValue: the quests' full moon, sunrise, sunset and day checks
  enviro_next_port: 0x17f2604,  // LoadEnviroNode.GetNextOutputPort: its "NextNode" port, which the graph follows
  investigation_next_port: 0x17f175c,  // InvestigationNode.GetNextOutputPort: its "FollowingNode" port
  node_output_port: 0x3201c20,  // XNode.Node.GetOutputPort(string)
  node_input_port: 0x3201c44,   // XNode.Node.GetInputPort(string)
  port_connections: 0x3206610,  // XNode.NodePort.get_ConnectionCount
  port_add: 0x32077fc,          // XNode.NodePort.AddConnections(NodePort): copies the other port's connections onto this one
  port_clear: 0x3201b98,        // XNode.NodePort.ClearConnections
  port_connect: 0x3204ab4,      // XNode.NodePort.Connect(NodePort)
  object_name: 0x290ef4c,       // UnityEngine.Object.get_name
};

// Asset paths the client asks for that 1.1.116 ships elsewhere. The reward popup is only under
// ui/windows/events/; without the fix it never loads and the dimmed map stays locked.
const ASSET_KEY_FIXES = [
  ['/ui/windows/marketing/prefabs/reward_item_window.prefab', '/ui/windows/events/prefabs/reward_item_window.prefab'],
];

// Native code fixes, ported from the 1.1.116 reconstruction's LAB builds (see README credits):
// [name, rva, original hex, patched hex].
// Each is applied only over its exact original bytes; branches inside are relative to the same address.
const NATIVE_FIXES = [
  // LAB 18 coin preview: each gold reward preview gets its own item as sprite owner. Without it, opening
  // contracts/events throws "PlayerInventory ... still didn't release previous resource" and hangs.
  ['coin preview', 0x1A0D084,
    '140a00b4e20300aae00314aae10316aae3031faab36b0194530900b4285c01f0085144f9e10300aae00313aa020140f9a6431d94' +
    'e85a019008e544f9f30300aa080140f9e00308aa39f5f497e10313aae2031faaf40300aabd0afd97',
    'f70300aae85a019008e544f9000140f947f5f497f40300aac07640f9200900b4e10314aae20317aae3031faaad6b0194930800b4' +
    '285c01f0085144f9e10300aae00313aa020140f9a0431d94e10300aae00314aae2031faabd0afd97'],
];
const hex = buf => Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');

function applyNativeFixes(m) {
  for (const [name, rva, before, after] of NATIVE_FIXES) {
    const at = m.base.add(rva);
    const size = before.length / 2;
    const current = hex(at.readByteArray(size));
    if (current === after) continue;  // already applied (hook reloaded into a running game)
    if (current !== before) { log('native fix skipped, unexpected bytes:', name); continue; }
    Memory.patchCode(at, size, code => code.writeByteArray(after.match(/../g).map(h => parseInt(h, 16))));
    log('native fix applied:', name);
  }
}

// One install stage. A throw inside one used to end the whole install silently (Gadget's script mode shows no errors), leaving
// the game half hooked; now each stage reports whether it worked and the others still run.
function stage(name, work) {
  try {
    work();
    log('stage ok:', name);
    return true;
  } catch (e) {
    log('stage FAILED:', name, '-', e.message);
    return false;
  }
}

let installed = false;
function install(m) {
  if (installed) return;
  installed = true;
  log('frida', Frida.version, Script.runtime, 'libil2cpp', m.path, 'base', m.base, 'size', m.size, 'built for sha256', LIBIL2CPP_SHA256);
  stage('native fixes', () => applyNativeFixes(m));
  // Time for quests (the dashboard's debug tools): the server adds 16 × (1 + mask) to the weather code, one mask bit per
  // AstroConditionNode.condition (+0x44: full moon 0, sunrise 1, sunset 2, day 3). The game gets the plain code back, and
  // its quests see that sky until a plain code comes; without one they see the phone's own.
  stage('quest sky', () => {
    let sky = -1;
    Interceptor.attach(m.base.add(RVA.weather_response), {
      onLeave(reply) {
        if (reply.isNull()) return;
        const code = reply.add(0x10).readS32();
        const mask = code >= 16 ? (code >> 4) - 1 : -1;
        if (mask !== sky) log('quest sky', mask < 0 ? 'as on the phone' : 'mask ' + mask);
        sky = mask;
        if (mask >= 0) reply.add(0x10).writeS32(code & 15);
      },
    });
    Interceptor.attach(m.base.add(RVA.astro_condition), {
      onEnter(args) { this.node = args[0]; },
      onLeave(result) { if (sky >= 0) result.replace(ptr((sky >> this.node.add(0x44).readS32()) & 1)); },
    });
  });

  let il2cpp = null;
  stage('il2cpp images', () => {
    const fn = (name, ret, args) => new NativeFunction(m.base.add(RVA[name]), ret, args);
    const domainGet = fn('domain_get', 'pointer', []);
    const assemblies = fn('domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
    const assemblyImage = fn('assembly_get_image', 'pointer', ['pointer']);
    const imageName = fn('image_get_name', 'pointer', ['pointer']);
    const classFromName = fn('class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
    const methodFromName = fn('class_get_method_from_name', 'pointer', ['pointer', 'pointer', 'int']);
    const stringNew = fn('string_new', 'pointer', ['pointer']);
    const stringChars = fn('string_chars', 'pointer', ['pointer']);
    const stringLength = fn('string_length', 'int', ['pointer']);
    const resolveIcall = fn('resolve_icall', 'pointer', ['pointer']);
    const objectClass = fn('object_get_class', 'pointer', ['pointer']);

    const images = {};
    const count = Memory.alloc(8);
    const list = assemblies(domainGet(), count);
    for (let i = 0; i < Number(count.readU64()); i++) {
      const image = assemblyImage(list.add(i * 8).readPointer());
      images[imageName(image).readCString()] = image;
    }
    const method = (assembly, ns, cls, name, argc) => {
      const klass = classFromName(images[assembly], Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
      if (klass.isNull()) throw new Error(`class ${ns}.${cls} not found`);
      const info = methodFromName(klass, Memory.allocUtf8String(name), argc);
      if (info.isNull()) throw new Error(`${cls}.${name} not found`);
      return info.readPointer();  // MethodInfo.methodPointer
    };
    const str = s => stringNew(Memory.allocUtf8String(s));
    const read = s => (s.isNull() ? null : stringChars(s).readUtf16String(stringLength(s)));
    il2cpp = { images, classFromName, resolveIcall, objectClass, method, str, read };
  });
  if (il2cpp) {
    const { images, classFromName, resolveIcall, objectClass, method, str, read } = il2cpp;

    // Game server: every ClientSettings lookup answers with our server, gatekeeper off.
    const setting = (name, value) => stage('ClientSettings.' + name, () => {
      let called = false;
      Interceptor.attach(method('Game.dll', 'WitcherWorld.WebstuffClient', 'ClientSettings', name, 0), {
        onLeave(ret) {
          if (!called) log('ClientSettings.' + name, 'called');
          called = true;
          ret.replace(value());
        },
      });
    });
    setting('get_WebstuffServerIp', () => str(CONFIG.gameHost));
    setting('get_WebstuffServerDefaultPort', () => ptr(CONFIG.gamePort));
    setting('get_UseGatekeeper', () => ptr(0));

    // Web requests: every UnityWebRequest URL passes through this native setter. Log each new origin once.
    stage('web requests', () => {
      const seen = new Set();
      Interceptor.attach(resolveIcall(Memory.allocUtf8String('UnityEngine.Networking.UnityWebRequest::SetUrl')), {
        onEnter(args) {
          const url = read(args[1]);
          if (!url) return;
          const rule = CONFIG.rewrite.find(([from]) => url.startsWith(from));
          if (rule) args[1] = str(rule[1] + url.slice(rule[0].length));
          const origin = url.split('/').slice(0, 3).join('/');
          if (!seen.has(origin)) {
            seen.add(origin);
            log('url', url.split('?')[0], rule ? '-> ' + rule[1] : '(unchanged)');
          }
        },
      });
    });
    stage('news requests', () => {
      Interceptor.attach(m.base.add(RVA.create_http), {
        onEnter(args) {
          const url = read(args[0]);
          if (!url || !CONFIG.news[0].test(url)) return;
          args[0] = str(url.replace(CONFIG.news[0], CONFIG.news[1]));
          log('news', url, '->', CONFIG.news[1]);
        },
      });
    });
    // Graph wiring fixed in 1.2: Will o' the Wisp's stump and catch graphs (the only ones in 1.1.116) hang their next step on
    // LoadEnviroNode's "ResultNode" port instead of "NextNode", so the graph stops on the loaded background (logcat: "Load
    // Enviro ... doesn't have following node connected", a black screen). Before the game reads the node's next port, any
    // ResultNode connections move onto NextNode, as in 1.2's graphs; nodes without them are untouched.
    stage('graph wiring', () => {
      const fn = (rva, ret, args) => new NativeFunction(m.base.add(rva), ret, args);
      const outputPort = fn(RVA.node_output_port, 'pointer', ['pointer', 'pointer', 'pointer']);
      const connections = fn(RVA.port_connections, 'int', ['pointer', 'pointer']);
      const addConnections = fn(RVA.port_add, 'void', ['pointer', 'pointer', 'pointer']);
      const clearConnections = fn(RVA.port_clear, 'void', ['pointer', 'pointer']);
      Interceptor.attach(m.base.add(RVA.enviro_next_port), {
        onEnter(args) {
          const result = outputPort(args[0], str('ResultNode'), NULL);   // strings made per call: nothing keeps them alive
          if (result.isNull() || connections(result, NULL) === 0) return;
          const next = outputPort(args[0], str('NextNode'), NULL);
          if (next.isNull()) return;
          addConnections(next, result, NULL);
          clearConnections(result, NULL);
          log('graph wiring fixed: LoadEnviroNode ResultNode -> NextNode');
        },
      });
      // The treasure graph's investigation (the chest) is followed by its expiring effect alone: the "Fadeoutblacktransition"
      // runner that sends the quest end "treasure" has nothing leading in, so the game runs the effect, finds no next step
      // and the chest stays open (logcat: "Investigation ... in s01hq04_treasure graph doesn't have following node
      // connected"). As in the catch graph, a runner of that name with nothing leading in is connected after the
      // investigation; it is the only one in the story graphs.
      const inputPort = fn(RVA.node_input_port, 'pointer', ['pointer', 'pointer', 'pointer']);
      const connect = fn(RVA.port_connect, 'void', ['pointer', 'pointer', 'pointer']);
      const objectName = fn(RVA.object_name, 'pointer', ['pointer', 'pointer']);
      Interceptor.attach(m.base.add(RVA.investigation_next_port), {
        onEnter(args) {
          const graph = args[0].add(0x20).readPointer();          // Node.graph
          const nodes = graph.isNull() ? NULL : graph.add(0x18).readPointer();   // NodeGraph.nodes, a List<Node>
          if (nodes.isNull()) return;
          const items = nodes.add(0x10).readPointer();
          for (let i = 0; i < nodes.add(0x18).readS32(); i++) {
            const node = items.add(0x20 + i * 8).readPointer();
            if (node.isNull() || !(read(objectName(node, NULL)) || '').startsWith('Fadeoutblacktransition')) continue;
            const preceding = inputPort(node, str('PrecedingNode'), NULL);
            if (preceding.isNull() || connections(preceding, NULL) !== 0) continue;
            connect(outputPort(args[0], str('FollowingNode'), NULL), preceding, NULL);
            log('graph wiring fixed: Investigation FollowingNode -> Fadeoutblacktransition');
          }
        },
      });
    });
    // Addressables: every asset key lookup goes through ResourceLocationMap.Locate(key, type, out locations).
    stage('addressables', () => {
      const stringClass = classFromName(images['mscorlib.dll'], Memory.allocUtf8String('System'), Memory.allocUtf8String('String'));
      Interceptor.attach(method('Unity.Addressables.dll', 'UnityEngine.AddressableAssets.ResourceLocators',
                                'ResourceLocationMap', 'Locate', 3), {
        onEnter(args) {
          if (args[1].isNull() || !objectClass(args[1]).equals(stringClass)) return;
          const key = read(args[1]);
          const fix = ASSET_KEY_FIXES.find(([from]) => key.endsWith(from));
          if (!fix) return;
          args[1] = str(key.slice(0, -fix[0].length) + fix[1]);
          log('asset key fixed', fix[0], '->', fix[1]);
        },
      });
    });
  }
  log('hooks installed');
  stage('gps', () => startGps(m, log));
  stage('diagnostics', startDiagnostics);
}

// Diagnostics for bug reports. Nothing here runs on a hot or a crashing path: a heartbeat every 10 s (a missing one is the
// crash signal in the companion's game log) and, once, a look at how the previous run ended.
function startDiagnostics() {
  const started = Date.now();
  const rssMb = () => {
    try {
      const m = /VmRSS:\s+(\d+) kB/.exec(File.readAllText('/proc/self/status'));
      return m ? Math.round(m[1] / 1024) : -1;
    } catch (e) {
      return -1;
    }
  };
  setInterval(() => sinkWrite('heartbeat rss=' + rssMb() + 'MB up=' + Math.round((Date.now() - started) / 1000) + 's'), 10000);

  // How the previous run ended, read late so the game's start is not slowed: Android's record of it (a low-memory kill, a
  // native crash, a swipe from Recents) and our own uid's last log lines, including a native crash's backtrace from the
  // crash buffer. The companion keeps them in game.log.
  setTimeout(() => {
    const failed = e => sinkWrite('previous run: not readable: ' + e.message);
    try {
      Java.perform(() => {
        try {
          const manager = Java.cast(Java.use('android.app.ActivityThread').currentApplication().getSystemService('activity'),
                                    Java.use('android.app.ActivityManager'));
          const exits = manager.getHistoricalProcessExitReasons(null, 0, 5);
          const ExitInfo = Java.use('android.app.ApplicationExitInfo');
          for (let i = 0; i < exits.size(); i++) {
            const e = Java.cast(exits.get(i), ExitInfo);
            sinkWrite('previous exit ' + i + ': time=' + e.getTimestamp() + ' reason=' + e.getReason() + ' status=' + e.getStatus() +
                      ' importance=' + e.getImportance() + ' pss=' + e.getPss() + 'kB rss=' + e.getRss() + 'kB description=' + e.getDescription());
          }
          for (const [label, args] of [['logcat crash', ['-d', '-b', 'crash']], ['logcat errors', ['-d', '*:E', '-t', '300']]]) {
            const process = Java.use('java.lang.Runtime').getRuntime().exec(Java.array('java.lang.String', ['logcat'].concat(args)));
            const reader = Java.use('java.io.BufferedReader').$new(Java.use('java.io.InputStreamReader').$new(process.getInputStream()));
            let total = 0;
            for (let line = reader.readLine(); line !== null && total < 65536; line = reader.readLine()) {
              total += String(line).length;
              sinkWrite(label + ': ' + String(line).slice(0, 400));
            }
            reader.close();
            process.destroy();
          }
        } catch (e) {
          failed(e);
        }
      });
    } catch (e) {
      failed(e);
    }
  }, 20000);

  // Test aid, inert unless the marker file exists (adb can push it): abort the process so the capture above can be tried on a
  // phone, where "am kill" cannot cause a native crash.
  const access = new NativeFunction(libc.getExportByName('access'), 'int', ['pointer', 'int']);
  if (access(Memory.allocUtf8String(CONFIG.crashMarker), 0) === 0) {
    sinkWrite('crash test marker found: aborting in 20 s');
    const abort = new NativeFunction(libc.getExportByName('abort'), 'void', []);
    setTimeout(() => abort(), 20000);
  }
}

const loaded = Process.findModuleByName('libil2cpp.so');
if (loaded) {
  install(loaded);  // the hook file was reloaded into a running game
} else {
  Process.attachModuleObserver({
    onAdded(m) {
      if (m.name === 'libil2cpp.so') Interceptor.attach(m.base.add(RVA.init), { onLeave() { install(m); } });
    },
  });
}
