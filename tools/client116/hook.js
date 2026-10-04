// Points The Witcher: Monster Slayer 1.1.116 at a self-hosted server. Frida Gadget loads it into the game.
// RVA holds il2cpp exports of the original 1.1.116 libil2cpp.so (sha256 c8a5556b…, checked by
// build_client.py). They are used instead of a by-name lookup, which crashed the Android 17 linker.
'use strict';

const CONFIG = {
  gameHost: '127.0.0.1',  // IPv4 literal of the server, as the phone reaches it
  gamePort: 4253,
  oldHosts: /(^|\.)(thewitchermonsterslayer|spokko)\.com$/,  // the original servers; resolved to gameHost instead
  rewrite: [  // URL prefix -> replacement, applied to every UnityWebRequest
    ['https://gatekeeper.cloud.thewitchermonsterslayer.com', 'http://127.0.0.1:18080'],  // news
    ['https://vectortile.googleapis.com', 'http://127.0.0.1:18082'],                     // OSM map tiles
  ],
};

// Gadget's script mode drops console output, so write to logcat ourselves (tag Frida; restart.py records it).
const androidLog = new NativeFunction(Process.getModuleByName('liblog.so').getExportByName('__android_log_write'),
                                      'int', ['int', 'pointer', 'pointer']);
const logTag = Memory.allocUtf8String('Frida');
const log = (...parts) => androidLog(4, logTag, Memory.allocUtf8String(parts.join(' ')));

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

const RVA = {
  init: 0x16d0afc, domain_get: 0x16d1258, domain_get_assemblies: 0x16d1264, assembly_get_image: 0x16d0c38,
  image_get_name: 0x16d17fc, class_from_name: 0x16d0c64, class_get_method_from_name: 0x16d0c8c,
  string_new: 0x16d15f4, string_chars: 0x16d15f0, string_length: 0x16d15ec, resolve_icall: 0x16d0c08,
  object_get_class: 0x16d1558,
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

let installed = false;
function install(m) {
  if (installed) return;
  installed = true;
  applyNativeFixes(m);
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

  // Game server: every ClientSettings lookup answers with our server, gatekeeper off.
  const setting = (name, value) => {
    let called = false;
    Interceptor.attach(method('Game.dll', 'WitcherWorld.WebstuffClient', 'ClientSettings', name, 0), {
      onLeave(ret) {
        if (!called) log('ClientSettings.' + name, 'called');
        called = true;
        ret.replace(value());
      },
    });
  };
  setting('get_WebstuffServerIp', () => str(CONFIG.gameHost));
  setting('get_WebstuffServerDefaultPort', () => ptr(CONFIG.gamePort));
  setting('get_UseGatekeeper', () => ptr(0));

  // Web requests: every UnityWebRequest URL passes through this native setter. Log each new origin once.
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
  // Addressables: every asset key lookup goes through ResourceLocationMap.Locate(key, type, out locations).
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
  log('hooks installed');
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
