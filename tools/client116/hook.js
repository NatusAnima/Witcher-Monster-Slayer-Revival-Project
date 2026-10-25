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
  httpPort: 18080,  // the server's HTTP port (ServerService.HTTP_PORT)
  tilePort: 18082,  // the tile service (ServerService.TILE_PORT)
  oldHosts: /(^|\.)(thewitchermonsterslayer|spokko)\.com$/,  // the original servers; resolved to gameHost instead
  // The hosts of the game's connection test and of its NTP clock (see the "offline play" stage), resolved to gameHost
  // too, so that no lookup waits for a network that is not there.
  offlineHosts: /^((google|facebook)\.com|time\.(google|windows|apple)\.com|[0-9]\.pool\.ntp\.org)$/,
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
    const ours = host !== null && (CONFIG.oldHosts.test(host) || CONFIG.offlineHosts.test(host));
    if (host && !resolved.has(host)) {
      resolved.add(host);
      log('dns', host, ours ? '-> ' + CONFIG.gameHost : '(unchanged)');
    }
    if (ours) args[0] = serverHost;
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
  object_get_class: 0x16d1558, object_new: 0x16d1564, runtime_invoke: 0x16d15c4,
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
  internet_reachability: 0x271e790,  // UnityEngine.Application.get_internetReachability: NotReachable 0, carrier 1, LAN 2
  connection_test_from_host: 0x1a412b4,  // ConnectionTest.FromHost(string, int): the TCP tests of ConnectionTester.RunTest
  time_sync_run: 0x189d3c0,     // TimeSyncTask.Run: one NTP request, its milliseconds since 1900 (0 when none answered)
  login_window_show: 0x17ae78c,      // LoginWindowAdapter.Show(bool gameStarted): the sign-in window
  settings_login_info: 0x1819b48,    // SettingsWindow.UpdateLoginInfo: shows the settings' sign-in part by the login state
  game_object_set_active: 0x23fdd80,  // UnityEngine.GameObject.SetActive(bool)
  component_game_object: 0x272a59c,   // UnityEngine.Component.get_gameObject
  // I2.Loc.LocalizationManager.GetTranslation(Term, FixForRTL, maxLineLengthForRTL, ignoreRTLnumbers, applyParameters,
  // localParametersRoot, overrideLanguage): every game text goes through it (ScriptLocalization, Localize,
  // DataManager.Translate); a missing term returns null.
  get_translation: 0x1c933d8,
  modifiers_gui_update: 0x1822ca8,  // PlayerModifiersGUI.UpdatePlayerModifiersGUI: the map's effects panel (_modifiersSettings +0x20)
  modifier_slot_init: 0x18224b8,    // PlayerModifierGUISlot.Initialize(preset, modifier, effectName): one effect's icon and frame
  item_management_load: 0x17d31e0,  // ItemManagementWindow.LoadData(data): the inventory's count-and-Remove window (data.Item +0x10)
  component_transform: 0x272a55c,   // UnityEngine.Component.get_transform
  game_object_transform: 0x23fdc20,  // UnityEngine.GameObject.get_transform
  transform_parent: 0x31c9a8c,      // UnityEngine.Transform.get_parent
  transform_find: 0x31cb12c,        // UnityEngine.Transform.Find(string): a child by name
  transform_sibling_index: 0x31cb094,  // UnityEngine.Transform.GetSiblingIndex
  transform_child_count: 0x31caf44, // UnityEngine.Transform.get_childCount
  transform_get_child: 0x31cb5e8,   // UnityEngine.Transform.GetChild(int)
  game_object_component_by_name: 0x23fd290,  // UnityEngine.GameObject.GetComponent(string)
  tmp_get_text: 0x19b97bc,          // TMPro.TMP_Text.get_text
  tmp_set_text: 0x19b97c4,          // TMPro.TMP_Text.set_text
  current_language_code: 0x1c8eb68,  // I2.Loc.LocalizationManager.get_CurrentLanguageCode (static): "en", "pl", "pt-BR"…
  alchemy_slot_click: 0x18c99e0,    // AlchemyItemSlot.OnClick: an inventory slot tapped (its item +0x80) opens the info window
  alchemy_slot_management: 0x18c9f18,  // AlchemyItemSlot.OnManagementPressed: the slot's count window (ItemManagementWindow)
  inventory_item_load: 0x17d14b8,   // InventoryItemWindow.LoadData(data): an item's info window (data.Item +0x10)
  inventory_item_friends: 0x17d2a0c,  // InventoryItemWindow.OpenFriendsPanel: a pack's one button, Send
  drop_pack_reply: 0x247f888,       // DropFriendPackResponse.Factory.Deserialize(TypeMessage): reads [byte][int][int] of the reply
  drop_items_response: 0x1876f78,   // ItemManagementWindow.OnDropItemsResponse<object>(response, storage): the count window's answer
  inventory_get_item: 0x1a0cc10,    // PlayerInventory.GetItem(itemTypeId, id, amount): an item to show, nothing added
  item_claim_data: 0x18cfddc,       // ItemClaimWindowData..ctor(Item, int quantity, bool bigOpenSfx): Items +0x10 (List<Pair<Item,int>>)
  show_window: 0x1817864,           // ShowWindow..ctor(IWindowContent, bool hideCurrentWindow): the window manager's signal
  safe_fire: 0x198dd1c,             // SignalBusExtensions.SafeFire(SignalBus, object signal, object identifier)
  open_pack_reply: 0x1e79ed0,       // OpenPackResponse.Factory.Deserialize(TypeMessage): [byte][long][int][int][int] of the reply
  open_pack_response: 0x1978ec0,    // FriendsModule.OnOpenPackResponse: a gift's item added and shown in the game's pack window
  item_claim_load: 0x18da558,       // ItemClaimWindow.LoadData(data): the claim window got its items
  sword_damage: 0x1938fa8,          // SwordModule.CalculateSwordDamage(hitType, stats): a Damage (+0x14 AdditiveBonus, +0x18 Value)
  collecting_distance: 0x1909214,   // CollectingQuestPoi.OnUpdate: cmp w8, #200, the metres walked before a find shows
  collecting_created: 0x19090ec,    // CollectingQuestPoi.OnCreated: a collecting find on the map (its instance +0x180)
  collecting_walked: 0x190944c,     // CollectingQuestPoi.OnDistanceWalkedSignal: the instance's metres (+0x80) grow by 100
  quest_poi_instantiate: 0x1909f58,  // QuestPoiInstance.ShouldBeInstantiated(position, time): Activated +0x58, IsQuestGiver
                                     // +0x59, DisplayMode +0x60
  tracked_quest: 0x19a5aa8,         // StoryModule.SetTrackedQuest(int questId, bool manualToggle)
  fact_requirement: 0x1962d3c,      // FactRequirementNode.HasDesiredValue: Node.graph +0x20, FactRequirement +0x48 (Value
                                    // +0x10, Operator +0x14: Equal 0 … LowerThan 4, FactId +0x18)
};
const callbacks = [];  // NativeCallbacks given to Interceptor.replace, kept from the garbage collector

// Asset paths the client asks for that 1.1.116 ships elsewhere. The reward popup is only under
// ui/windows/events/; without the fix it never loads and the dimmed map stays locked.
const ASSET_KEY_FIXES = [
  ['/ui/windows/marketing/prefabs/reward_item_window.prefab', '/ui/windows/events/prefabs/reward_item_window.prefab'],
];

// Native code fixes, ported from the 1.1.116 reconstruction's LAB builds (see README credits):
// [name, rva, original hex, patched hex].
// Each is applied only over its exact original bytes; branches inside are relative to the same address.
const NATIVE_FIXES = [
  // The shop sells bags only while the inventory holds fewer than 1000 items (PlayerInventory.CanExpandInventory:
  // cmp w8, #1000); the server's largest bag is a dashboard setting (Tuning inventory.maxSize), so the client's limit
  // becomes 4095 and the server decides.
  ['bag limit', 0x1A0E060, '1fa10f71', '1ffd3f71'],
  // No "buy more orens" offer: when the wallet cannot pay, the shop's purchase window and the fight's quick buy open
  // GoldOfferWindow with the shop's packs of orens (bought for real money in the original); with no pack in the shop it
  // throws and leaves the shop dimmed (Economy.cs). Their not-enough branch returns instead (each method's own epilogue).
  ['no gold offer: shop', 0x181A2DC, '086c01d0730e40f9b41640b908a945f9', 'fd7b42a9f44f41a9f657c3a8c0035fd6'],
  ['no gold offer: quick buy', 0x1814864, '486c0190730e40f908a945f9000140f9', 'fd7b42a9f44f41a9f50743f8c0035fd6'],
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

// A hook the game calls every frame, in C (a CModule exporting onEnter/onLeave, which calls into JS only when there is
// work): a JS callback per call costs a few microseconds each, many times a frame. Without CModule (a Gadget build without
// its C compiler) the same hook runs in JS, as before.
function fastHook(name, target, source, symbols, js) {
  try {
    const module = new CModule(source, symbols);
    callbacks.push(module);
    Interceptor.attach(target, module);
    log('fast hook:', name);
  } catch (e) {
    log('fast hook in JS:', name, '-', e.message);
    Interceptor.attach(target, js);
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
    il2cpp = { images, classFromName, methodFromName, resolveIcall, objectClass, method, str, read };
  });
  if (il2cpp) {
    const { images, classFromName, methodFromName, resolveIcall, objectClass, method, str, read } = il2cpp;

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
    // Offline play. Before the game starts, PreGameConditionsModule.CheckNetworkAvailability (0x199F464) wants Android to
    // report a network, then a TCP connection to a known host (ConnectionTester.KNOWN_HOSTS: google.com and facebook.com,
    // port 80); and SyncedTime lets the player in only after an NTP answer (HandleTimeSyncRequests 0x19B0D40). Without the
    // internet neither comes and the game never starts. The server is on this phone: the phone counts as on a local
    // network, the connection tests reach the server, and the game's clock is the phone's, which the server keeps too.
    stage('offline play', () => {
      const said = new Set();
      const once = (...parts) => {
        if (said.has(parts[0])) return;
        said.add(parts[0]);
        log('offline play:', ...parts);
      };
      // ConnectionHandler.Tick asks every frame
      const noNetwork = new NativeCallback(() => once('no network on the phone', '-> local network'), 'void', []);
      callbacks.push(noNetwork);
      fastHook('reachability', m.base.add(RVA.internet_reachability), `
        #include <gum/guminterceptor.h>
        extern void no_network (void);
        static int said;
        void onLeave (GumInvocationContext * ic) {
          if (gum_invocation_context_get_return_value (ic) != 0) return;
          gum_invocation_context_replace_return_value (ic, (void *) 2);
          if (!said) { said = 1; no_network (); }
        }`, { no_network: noNetwork }, {
        onLeave(ret) {
          if (ret.toInt32() !== 0) return;
          once('no network on the phone', '-> local network');
          ret.replace(ptr(2));
        },
      });
      Interceptor.attach(m.base.add(RVA.connection_test_from_host), {
        onEnter(args) {
          const host = read(args[0]);
          if (host === CONFIG.gameHost) return;
          once('connection test ' + host, '-> the server');
          args[0] = str(CONFIG.gameHost);
          args[1] = ptr(CONFIG.httpPort);
        },
      });
      // Run answers NTP milliseconds, counted from 1900: HandleTimeSyncRequests adds -2208988800000 (x28, 0x19B0DD4) before
      // FromUnixTimeMilliseconds. A plain Unix time put the game's clock in 1956, before every monster's window.
      const clock = new NativeCallback(() => {
        once('clock', 'the phone\'s, not NTP');
        return int64(Date.now() + 2208988800000);
      }, 'int64', ['pointer', 'pointer']);
      callbacks.push(clock);
      Interceptor.replace(m.base.add(RVA.time_sync_run), clock);
    });
    // No Google sign-in once the game runs: it only linked accounts of the original servers. LoginWindowAdapter.Show opens the
    // sign-in window, in the game (gameStarted) after a failed silent sign-in or from the settings; the settings show their
    // account section by the login state (UpdateLoginInfo, also when the window opens): the heading "--- ACCOUNT ---" and the
    // "Login" block (its title, the user id, the sign-in buttons in _loginParent +0xF0, the logout button). All of it goes;
    // _signInText +0x138 too. The window before the game starts is left as it is.
    stage('no sign-in window', () => {
      const show = m.base.add(RVA.login_window_show);
      const original = new NativeFunction(show, 'void', ['pointer', 'bool', 'pointer']);
      const skip = new NativeCallback((adapter, gameStarted, info) => {
        if (!gameStarted) return original(adapter, gameStarted, info);
        log('sign-in window not shown');
      }, 'void', ['pointer', 'bool', 'pointer']);
      callbacks.push(skip);
      Interceptor.replace(show, skip);
      const setActive = new NativeFunction(m.base.add(RVA.game_object_set_active), 'void', ['pointer', 'bool', 'pointer']);
      const gameObjectOf = new NativeFunction(m.base.add(RVA.component_game_object), 'pointer', ['pointer', 'pointer']);
      const transformOf = new NativeFunction(m.base.add(RVA.game_object_transform), 'pointer', ['pointer', 'pointer']);
      const parentOf = new NativeFunction(m.base.add(RVA.transform_parent), 'pointer', ['pointer', 'pointer']);
      const childNamed = new NativeFunction(m.base.add(RVA.transform_find), 'pointer', ['pointer', 'pointer', 'pointer']);
      const siblingIndex = new NativeFunction(m.base.add(RVA.transform_sibling_index), 'int', ['pointer', 'pointer']);
      const childAt = new NativeFunction(m.base.add(RVA.transform_get_child), 'pointer', ['pointer', 'int', 'pointer']);
      const objectName = new NativeFunction(m.base.add(RVA.object_name), 'pointer', ['pointer', 'pointer']);
      let said = false;
      Interceptor.attach(m.base.add(RVA.settings_login_info), {
        onEnter(args) { this.window = args[0]; },
        onLeave() {
          const hidden = [];
          const hide = (gameObject) => {
            if (gameObject.isNull()) return;
            setActive(gameObject, 0, NULL);   // a 'bool' argument takes a number: false threw "expected an integer"
            hidden.push(read(objectName(gameObject, NULL)));
          };
          const part = this.window.add(0xf0).readPointer();   // _loginParent
          if (!part.isNull()) {
            hide(part);
            const login = parentOf(transformOf(part, NULL), NULL);                 // "Login"
            if (!login.isNull()) {
              hide(gameObjectOf(login, NULL));
              const content = parentOf(login, NULL);
              let heading = content.isNull() ? NULL : childNamed(content, str('--- ACCOUNT ---'), NULL);
              const at = siblingIndex(login, NULL);   // else the section's heading, which comes just before it
              if (heading.isNull() && !content.isNull() && at > 0) heading = childAt(content, at - 1, NULL);
              if (!heading.isNull()) hide(gameObjectOf(heading, NULL));
            }
          }
          const text = this.window.add(0x138).readPointer();  // _signInText
          if (!text.isNull()) hide(gameObjectOf(text, NULL));
          if (!said) log('settings: hidden', hidden.join(', ') || 'nothing');
          said = true;
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
    // The dashboard's settings for the game (Tuning, sent with the texts); each one off keeps the original game.
    stage('game settings', () => {
      const objectName = new NativeFunction(m.base.add(RVA.object_name), 'pointer', ['pointer', 'pointer']);
      // combat.oilsMultiply. CalculateSwordDamage builds a Damage whose Value is the sword's base damage and whose
      // AdditiveBonus sums the hit type's, the attack's and the oil's bonus (SwordModifiers +0x108: OilModifier +0x58, its value
      // +0x10, 0.33 for the basic oil, more with the oil skills); weaknesses and potions are added to that sum, so the oil gave
      // its share of the base only. On, the oil leaves the sum and multiplies the blow.
      whenSettings(() => {
        if (!SETTINGS['combat.oilsMultiply']) return;
        let said = false;
        Interceptor.attach(m.base.add(RVA.sword_damage), {
          onEnter(args) { this.sword = args[0]; },
          onLeave(damage) {
            if (damage.isNull()) return;
            const modifiers = this.sword.add(0x108).readPointer();
            const oil = modifiers.isNull() ? NULL : modifiers.add(0x58).readPointer();
            const bonus = oil.isNull() ? 0 : oil.add(0x10).readFloat();
            if (bonus === 0) return;
            damage.add(0x18).writeFloat(damage.add(0x18).readFloat() * (1 + bonus));
            damage.add(0x14).writeFloat(damage.add(0x14).readFloat() - bonus);
            if (!said) log('oils: the oil multiplies the blow by', (1 + bonus).toFixed(2));
            said = true;
          },
        });
        log('oils: multiply');
      });
      // quests.collectingDistance: the metres CollectingQuestPoi.OnUpdate waits for (cmp w8, #200; the game counts 100 m steps).
      whenSettings(() => {
        const metres = SETTINGS['quests.collectingDistance'];
        if (!metres || metres === 200) return;
        const at = m.base.add(RVA.collecting_distance);
        if (hex(at.readByteArray(4)) !== '1f210371') return void log('collecting: unexpected code, the distance stays 200 m');
        Memory.patchCode(at, 4, code => code.writeU32((0x7100011f | (metres << 10)) >>> 0));   // cmp w8, #metres
        log('collecting: a find after', metres, 'm');
      });
      // quests.collectingUntracked: QuestPoiInstance.ShouldBeInstantiated shows a quest node only once SetActiveQuestNodes has
      // activated it (+0x58), which it does for the tracked quest's nodes alone, so tracking another quest hid the mushrooms
      // and stopped the candles. A collecting find or a timed node (Collecting 7, Auto 5) of a started quest shows anyway.
      whenSettings(() => {
        if (!SETTINGS['quests.collectingUntracked']) return;
        Interceptor.attach(m.base.add(RVA.quest_poi_instantiate), {
          onEnter(args) { this.poi = args[0]; },
          onLeave(shown) {
            if (shown.toInt32() !== 0) return;
            const display = this.poi.add(0x60).readS32();
            if ((display === 5 || display === 7) && this.poi.add(0x58).readU8() === 0 && this.poi.add(0x59).readU8() === 0)
              shown.replace(ptr(1));
          },
        });
        log('collecting: finds show without tracking their quest');
      });
      // quests.intruderAllEndings: the Intruder's ending graph gives full_reward and bonus_reward only for fact 33 = 0, and the
      // sorcerer's dialogue always sets 1 (2 once his 24 hours are waited out). Its two "33 = 0" requirements read "33 < 2".
      whenSettings(() => {
        if (!SETTINGS['quests.intruderAllEndings']) return;
        const seen = new Set();
        Interceptor.attach(m.base.add(RVA.fact_requirement), {
          onEnter(args) {
            const requirement = args[0].add(0x48).readPointer();
            if (requirement.isNull() || requirement.add(0x18).readS32() !== 33 || requirement.add(0x14).readS32() !== 0 ||
                requirement.add(0x10).readS32() !== 0) return;
            const graph = args[0].add(0x20).readPointer();
            const name = graph.isNull() ? null : read(objectName(graph, NULL));
            if (!(name || '').startsWith('s01mq06_vogt_02')) {   // a copy of the graph is named "…(Clone)"
              if (!seen.has(name)) log('intruder: f33 = 0 asked in', name, '(kept)');
              seen.add(name);
              return;
            }
            requirement.add(0x14).writeS32(4);   // LowerThan
            requirement.add(0x10).writeS32(2);
            log('intruder: the ending reads f33 < 2');
          },
        });
      });
      // Diagnostics for the collecting quests (rare events): a find on the map, the walking it counts, the tracked quest.
      Interceptor.attach(m.base.add(RVA.collecting_created), { onEnter() { log('collecting: a find is on the map'); } });
      Interceptor.attach(m.base.add(RVA.collecting_walked), {
        onEnter(args) { this.poi = args[0]; },
        onLeave() {
          const instance = this.poi.add(0x180).readPointer();
          if (!instance.isNull()) log('collecting: walked', instance.add(0x80).readS32(), 'm');
        },
      });
      Interceptor.attach(m.base.add(RVA.tracked_quest), {
        onEnter(args) { log('tracked quest', args[1].toInt32(), (args[2].toInt32() & 1) ? '(by the player)' : '(by the story)'); },
      });
    });
    // Addressables: every asset key lookup goes through ResourceLocationMap.Locate(key, type, out locations).
    // Every asset load (hundreds when a fight starts) asks: in C only a key with the fix's ending reaches JS.
    stage('addressables', () => {
      const stringClass = classFromName(images['mscorlib.dll'], Memory.allocUtf8String('System'), Memory.allocUtf8String('String'));
      const fixed = (key) => {
        const fix = ASSET_KEY_FIXES.find(([from]) => key.endsWith(from));
        if (!fix) return null;
        log('asset key fixed', fix[0], '->', fix[1]);
        return str(key.slice(0, -fix[0].length) + fix[1]);
      };
      const locate = method('Unity.Addressables.dll', 'UnityEngine.AddressableAssets.ResourceLocators', 'ResourceLocationMap',
                            'Locate', 3);
      const js = {
        onEnter(args) {
          if (args[1].isNull() || !objectClass(args[1]).equals(stringClass)) return;
          const key = fixed(read(args[1]));
          if (key) args[1] = key;
        },
      };
      if (ASSET_KEY_FIXES.length !== 1) return void Interceptor.attach(locate, js);   // the C form checks one ending
      const [[ending]] = ASSET_KEY_FIXES;
      const suffix = Memory.alloc(ending.length * 2 + 2);   // and the terminator writeUtf16String adds
      suffix.writeUtf16String(ending);
      const onKey = new NativeCallback(key => {
        try {
          return fixed(read(key)) || key;
        } catch (e) {
          return key;
        }
      }, 'pointer', ['pointer']);
      callbacks.push(onKey);
      fastHook('asset keys', locate, `
        #include <gum/guminterceptor.h>
        extern void * string_class;
        extern unsigned short suffix[];
        extern void * on_key (void * key);
        void onEnter (GumInvocationContext * ic) {
          void * key = gum_invocation_context_get_nth_argument (ic, 1);
          if (key == 0 || *(void **) key != string_class) return;
          int n = *(int *) ((char *) key + 0x10), length = ${ending.length};
          if (n < length) return;
          unsigned short * chars = (unsigned short *) ((char *) key + 0x14) + (n - length);
          for (int i = 0; i < length; i++) if (chars[i] != suffix[i]) return;
          gum_invocation_context_replace_nth_argument (ic, 1, on_key (key));
        }`, { string_class: stringClass, suffix, on_key: onKey }, js);
    });
    // Texts the server supplies: the bestiary's occurrences from the wiki, the trinkets' bonuses, the weather items' names.
    // A term is looked up only when its length is one of theirs, since some windows ask for texts every frame.
    // Texts by language are {"en": …, "pl": …}: the game's language code before any "-" picks one, else English.
    // In C (every frame, from timers and Update methods): only a term with one of those lengths reaches JS.
    stage('texts', () => {
      const languageCode = new NativeFunction(m.base.add(RVA.current_language_code), 'pointer', ['pointer']);
      language = () => (read(languageCode(NULL)) || 'en').toLowerCase().split('-')[0];
      const answer = (term, text) => {
        const found = term && TEXTS.get((packWindow && PACK_TERMS[term]) || term);
        return found ? str(found.replace !== undefined ? pick(found.replace) : (read(text) || '') + pick(found.append)) : null;
      };
      const onTerm = new NativeCallback((term, text) => {
        try {
          return answer(read(term), text) || text;
        } catch (e) {
          return text;   // the game's own text: a throw here would reach the game
        }
      }, 'pointer', ['pointer', 'pointer']);
      callbacks.push(onTerm);
      fastHook('texts', m.base.add(RVA.get_translation), `
        #include <gum/guminterceptor.h>
        extern unsigned char lengths[];
        extern void * on_term (void * term, void * text);
        typedef struct { void * term; } State;
        void onEnter (GumInvocationContext * ic) {
          State * s = GUM_IC_GET_INVOCATION_DATA (ic, State);
          void * term = gum_invocation_context_get_nth_argument (ic, 0);
          int n = term == 0 ? 0 : *(int *) ((char *) term + 0x10);
          s->term = n > 0 && n < ${TERM_LENGTHS} && lengths[n] ? term : 0;
        }
        void onLeave (GumInvocationContext * ic) {
          State * s = GUM_IC_GET_INVOCATION_DATA (ic, State);
          if (s->term == 0) return;
          void * text = gum_invocation_context_get_return_value (ic);
          void * replaced = on_term (s->term, text);
          if (replaced != text) gum_invocation_context_replace_return_value (ic, replaced);
        }`, { lengths: termLengths, on_term: onTerm }, {
        onEnter(args) {
          this.term = !args[0].isNull() && textLengths.has(args[0].add(0x10).readS32()) ? read(args[0]) : null;
        },
        onLeave(ret) {
          const text = answer(this.term, ret);
          if (text) ret.replace(text);
        },
      });
      setTimeout(loadTexts, 0);  // off the game's start; the game reads its static texts after the login
    });
    // Effects-panel icons: an effect is drawn with the preset of its modifier id (PlayerModifiersSettings.ModifierGUIPresets,
    // ids 1-12 and 15-24); any other id gets the default, which has no icon (a white square). The server's own modifiers
    // borrow an original one: the trinkets' attack bonuses (921-926) the blacksmith's sword (1), the debug tools'
    // invincibility (901) Maiden's Skin (16) and one-hit kills (902) Dead Honey (18).
    stage('effect icons', () => {
      const borrow = (id) => (id >= 921 && id <= 926 ? 1 : id === 901 ? 16 : id === 902 ? 18 : 0);
      let presets = null;  // modifier id -> its ModifierGUIPreset
      Interceptor.attach(m.base.add(RVA.modifiers_gui_update), {
        onEnter(args) {
          if (presets) return;
          const settings = args[0].add(0x20).readPointer();
          const list = settings.isNull() ? NULL : settings.add(0x18).readPointer();  // List<ModifierGUIPreset>
          if (list.isNull()) return;
          presets = {};
          const items = list.add(0x10).readPointer();
          for (let i = 0; i < list.add(0x18).readS32(); i++) {
            const preset = items.add(0x20 + i * 8).readPointer();
            if (!preset.isNull()) presets[preset.add(0x10).readS32()] = preset;   // ModifierId; Icon +0x18, Frame +0x20
          }
        },
      });
      Interceptor.attach(m.base.add(RVA.modifier_slot_init), {
        onEnter(args) {
          const id = args[2].isNull() ? 0 : args[2].add(0x18).readS32();   // ExpiringPlayerModifier.Id
          const preset = presets && presets[borrow(id)];
          if (preset && (args[1].isNull() || args[1].add(0x18).readPointer().isNull())) args[1] = preset;   // only for the empty default
        },
      });
    });
    // Packs opened from the inventory (Tuning inventory.openPacks; the server sends REVIVAL/OPEN_PACK and _HEADER only then):
    // - a pack's info window (InventoryItemWindow) has one button, Send, which opens the friends panel (OpenFriendsPanel): it
    //   reads Open and opens the pack's count window instead, as the inventory slot's management button does
    //   (AlchemyItemSlot.OnManagementPressed on the slot tapped last, AlchemyItemSlot.OnClick); the friends panel still sends;
    // - the count window (ItemManagementWindow) drops packs with DropFriendPack 109, which the server opens. While it shows a
    //   pack its question and button read as opening (PACK_TERMS in the texts stage; the button's label is also set after
    //   LoadData and given back for other items, as the window is reused);
    // - what the packs held follows the reply's own fields (PlayerService.HandleDropItems: [int n][int type][int item][int
    //   amount] x n, which the game leaves unread); once the window has its answer, the game's item-claim window (the one
    //   crafted items are collected with) shows them, one at a time with the reward sound. The items themselves come with the
    //   server's inventory push.
    stage('open packs', () => {
      const fn = (rva, ret, args) => new NativeFunction(m.base.add(rva), ret, args);
      const packClass = classFromName(images['Game.dll'], Memory.allocUtf8String('WitcherWorld.Modules.DataManager'),
        Memory.allocUtf8String('Pack'));
      if (packClass.isNull()) throw new Error('class Pack not found');
      const gameObjectOf = fn(RVA.component_game_object, 'pointer', ['pointer', 'pointer']);
      const transformOf = fn(RVA.component_transform, 'pointer', ['pointer', 'pointer']);
      const childCount = fn(RVA.transform_child_count, 'int', ['pointer', 'pointer']);
      const childAt = fn(RVA.transform_get_child, 'pointer', ['pointer', 'int', 'pointer']);
      const componentNamed = fn(RVA.game_object_component_by_name, 'pointer', ['pointer', 'pointer', 'pointer']);
      const getText = fn(RVA.tmp_get_text, 'pointer', ['pointer', 'pointer']);
      const setText = fn(RVA.tmp_set_text, 'void', ['pointer', 'pointer', 'pointer']);
      // the button's label: the first TextMeshProUGUI among its children and theirs
      const label = (transform, depth) => {
        for (let i = 0; i < childCount(transform, NULL); i++) {
          const child = childAt(transform, i, NULL);
          const text = componentNamed(gameObjectOf(child, NULL), str('TextMeshProUGUI'), NULL);
          if (!text.isNull()) return text;
          const deeper = depth > 0 ? label(child, depth - 1) : NULL;
          if (!deeper.isNull()) return deeper;
        }
        return NULL;
      };
      const isPack = (item) => !item.isNull() && objectClass(item).equals(packClass);
      const opening = () => TEXTS.get(OPEN_PACK);
      const said = new Set();
      const once = (what, ...parts) => {
        if (!said.has(what)) log('open packs:', what, ...parts);
        said.add(what);
      };
      // the info window
      let tapped = NULL;  // the inventory slot tapped last
      Interceptor.attach(m.base.add(RVA.alchemy_slot_click), { onEnter(args) { tapped = args[0]; } });
      Interceptor.attach(m.base.add(RVA.inventory_item_load), {
        onEnter(args) {
          this.window = args[0];
          this.item = args[1].isNull() ? NULL : args[1].add(0x10).readPointer();   // InventoryItemData.Item
        },
        onLeave() {
          const open = opening();
          const button = this.window.add(0x128).readPointer();                   // _actionButtonText
          if (!open || button.isNull() || !isPack(this.item)) return;
          setText(button, str(pick(open.replace)), NULL);
          once('info window', 'Send reads', pick(open.replace));
        },
      });
      const manage = fn(RVA.alchemy_slot_management, 'void', ['pointer', 'pointer']);
      const friends = m.base.add(RVA.inventory_item_friends);
      const sendOriginal = new NativeFunction(friends, 'void', ['pointer', 'pointer']);
      // A window's own Close() (Window<T>, vtable slot 17: code +0x240, method +0x248), as OpenFriendsPanel and
      // UseSummoningScroll end. Without it the count window (shown with hideCurrentWindow) only hid this one, which came back
      // when the count and claim windows closed: the pack's window, still offering Open, with no pack left. It closes first:
      // a window shown with hideCurrentWindow waits for the current one's hide to end, and closing it then left the count
      // window waiting for good; asked while a window closes, the manager queues it and shows it once that one has closed
      // (WindowsManager.OnShowWindow 0x181FBAC, OnWindowClosed 0x182006C).
      const closeWindow = (window) => {
        const klass = window.readPointer();
        new NativeFunction(klass.add(0x240).readPointer(), 'bool', ['pointer', 'pointer'])(window, klass.add(0x248).readPointer());
      };
      const send = new NativeCallback((window, info) => {
        try {
          const data = window.add(0x78).readPointer();                            // Window<InventoryItemData>.Data
          const item = data.isNull() ? NULL : data.add(0x10).readPointer();
          if (opening() && isPack(item) && !tapped.isNull() && tapped.add(0x80).readPointer().equals(item)) {
            once('open', 'the count window from the info window');
            closeWindow(window);
            manage(tapped, NULL);
            return;
          }
        } catch (e) {
          once('error', e.message);
        }
        sendOriginal(window, info);
      }, 'void', ['pointer', 'pointer']);
      callbacks.push(send);
      Interceptor.replace(friends, send);
      // the count window
      let own = null;  // the button's own text, put back for other items
      Interceptor.attach(m.base.add(RVA.item_management_load), {
        onEnter(args) {
          this.window = args[0];
          this.item = args[1].isNull() ? NULL : args[1].add(0x10).readPointer();   // ItemManagementData.Item
          packWindow = !!opening() && isPack(this.item);
        },
        onLeave() {
          packWindow = false;
          const open = opening();
          const button = this.window.add(0xb0).readPointer();                    // _removeButton
          if (!open || button.isNull()) return;
          const text = label(transformOf(button, NULL), 1);
          if (text.isNull()) return;
          const current = read(getText(text, NULL));
          const word = pick(open.replace);
          if (isPack(this.item) && current !== word) {
            own = current;
            setText(text, str(word), NULL);
            once('count window', 'Remove reads', word);
          } else if (!isPack(this.item) && current === word && own !== null) {
            setText(text, str(own), NULL);
          }
        },
      });
      // what the packs held
      const claimClass = classFromName(images['Game.dll'], Memory.allocUtf8String('WitcherWorld.Modules.GUI.ItemClaim'),
        Memory.allocUtf8String('ItemClaimWindowData'));
      const showClass = classFromName(images['Game.dll'], Memory.allocUtf8String('WitcherWorld.Modules.GUI.WindowsManager'),
        Memory.allocUtf8String('ShowWindow'));
      if (claimClass.isNull() || showClass.isNull()) throw new Error('class ItemClaimWindowData or ShowWindow not found');
      const objectNew = fn(RVA.object_new, 'pointer', ['pointer']);
      const invoke = fn(RVA.runtime_invoke, 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
      const getItem = fn(RVA.inventory_get_item, 'pointer', ['pointer', 'int', 'int', 'int', 'pointer']);
      const claimData = fn(RVA.item_claim_data, 'void', ['pointer', 'pointer', 'int', 'bool', 'pointer']);
      const showWindow = fn(RVA.show_window, 'void', ['pointer', 'pointer', 'bool', 'pointer']);
      const safeFire = fn(RVA.safe_fire, 'void', ['pointer', 'pointer', 'pointer', 'pointer']);
      // [itemType, item, amount] x n that a reply lists after its own fields (the server's additions, which the game's reader
      // leaves unread): the reply's TypeMessage.Data (+0x10), a ByteBuffer (_buffer +0x10, _readPosition +0x1C, _writePosition
      // +0x20), big-endian. Each step is logged (opening packs is rare), so a report shows where a claim window stopped.
      const readStacks = (message, what) => {
        try {
          const buffer = message.add(0x10).readPointer();
          const bytes = buffer.add(0x10).readPointer().add(0x20);       // _buffer's elements
          let at = buffer.add(0x1c).readS32();                          // past the reply's own fields
          const end = buffer.add(0x20).readS32();
          const int = () => {
            const value = new DataView(bytes.add(at).readByteArray(4)).getInt32(0);
            at += 4;
            return value;
          };
          if (end - at < 4) return void log(what + ': the reply holds no list of what was found (' + (end - at) + ' bytes left)');
          const n = int();
          if (n < 0 || n > 64 || end - at < n * 12) return void log(what + ': the reply lists', n, 'stacks in', end - at, 'bytes');
          const stacks = [];
          for (let i = 0; i < n; i++) stacks.push([int(), int(), int()]);
          log(what + ': the reply lists', JSON.stringify(stacks));
          return stacks;
        } catch (e) {
          log(what + ': the reply could not be read -', e.message);
          return null;
        }
      };
      // The game's item-claim window (the one crafted items are collected with) for [stacks], fired on [bus]. With
      // [hideCurrent] it covers the window now showing; without, it waits until that one closes (the manager's queue).
      const showClaim = (bus, inventory, stacks, hideCurrent, what) => {
        try {
          const items = stacks.map(([type, id, amount]) => [getItem(inventory, type, id, amount, NULL), amount])
            .filter(([item]) => !item.isNull());
          if (items.length === 0) return void log(what + ': the game has none of the', stacks.length, 'items found');
          const data = objectNew(claimClass);
          claimData(data, items[0][0], items[0][1], 1, NULL);
          const list = data.add(0x10).readPointer();                    // its List<Pair<Item, int>>, the first item in it
          const pairClass = objectClass(list.add(0x10).readPointer().add(0x20).readPointer());
          const add = methodFromName(objectClass(list), Memory.allocUtf8String('Add'), 1);
          const param = Memory.alloc(8), thrown = Memory.alloc(8);
          for (const [item, amount] of items.slice(1)) {
            const pair = objectNew(pairClass);
            pair.add(0x10).writePointer(item);                          // Pair.first
            pair.add(0x18).writeS32(amount);                            // Pair.second
            param.writePointer(pair);
            thrown.writePointer(NULL);
            invoke(add, list, param, thrown);
            if (!thrown.readPointer().isNull()) throw new Error('List.Add threw');
          }
          const signal = objectNew(showClass);
          showWindow(signal, data, hideCurrent ? 1 : 0, NULL);   // a 'bool' argument takes a number, not true/false
          safeFire(bus, signal, NULL, NULL);
          log(what + ': shown', items.length, 'items');
        } catch (e) {
          log(what + ': the claim window failed -', e.message);
        }
      };
      // packs opened in the inventory (DropFriendPack 109): every stack, once the count window has its answer
      let found = null;  // the last reply's stacks, until its window has the answer
      Interceptor.attach(m.base.add(RVA.drop_pack_reply), {
        onEnter(args) { this.message = args[1]; },
        onLeave() { found = readStacks(this.message, 'open packs'); },
      });
      Interceptor.attach(m.base.add(RVA.drop_items_response), {
        onEnter(args) { this.window = args[0]; },
        onLeave() {
          const stacks = found;
          found = null;
          if (!stacks || stacks.length === 0) return;   // not a pack
          // ItemManagementWindow._playerInventory +0xD8, Window._signalBus +0x18
          showClaim(this.window.add(0x18).readPointer(), this.window.add(0xd8).readPointer(), stacks, true, 'open packs');
        },
      });
      // a gift opened (OpenPack 107): the game's pack window shows the stack its reply names, the rest follows after it
      let gift = null;
      Interceptor.attach(m.base.add(RVA.open_pack_reply), {
        onEnter(args) { this.message = args[1]; },
        onLeave() { gift = readStacks(this.message, 'gift'); },
      });
      Interceptor.attach(m.base.add(RVA.open_pack_response), {
        onEnter(args) { this.module = args[0]; },
        onLeave() {
          const stacks = gift;
          gift = null;
          if (!stacks || stacks.length === 0) return;
          // FriendsModule._signalBus +0x30, _playerInventory +0x20
          showClaim(this.module.add(0x30).readPointer(), this.module.add(0x20).readPointer(), stacks, false, 'gift');
        },
      });
      // the window manager took it (crafted items are collected through the same window)
      Interceptor.attach(m.base.add(RVA.item_claim_load), {
        onEnter(args) {
          const items = args[1].isNull() ? NULL : args[1].add(0x10).readPointer();
          log('claim window: loads', items.isNull() ? 0 : items.add(0x18).readS32(), 'items');
        },
      });
    });
  }
  log('hooks installed');
  stage('map tiles', () => setTimeout(freshTiles, 0));  // off the game's start; the map comes seconds later
  stage('gps', () => startGps(m, log));
  stage('diagnostics', startDiagnostics);
}

// Map tiles. The game keeps every tile it was sent on disk (Google.Maps/Feature in its cache) and never asks for one again,
// so after a new map (rebuilt, another region, or tiles sent before the map was built) it kept drawing the old ones. The tile
// service names the map its tiles come from (/health "map"); when that differs from the one the cache was filled from, the
// cached tiles go, before the game shows the map.
function freshTiles() {
  Java.perform(() => {
    try {
      const JFile = Java.use('java.io.File');
      const cache = Java.use('android.app.ActivityThread').currentApplication().getExternalCacheDir().getPath() + '/Google.Maps';
      const health = Java.cast(Java.use('java.net.URL').$new('http://' + CONFIG.gameHost + ':' + CONFIG.tilePort + '/health')
        .openConnection(), Java.use('java.net.HttpURLConnection'));
      health.setConnectTimeout(1000);
      health.setReadTimeout(1000);
      const reader = Java.use('java.io.BufferedReader').$new(Java.use('java.io.InputStreamReader').$new(health.getInputStream()));
      const map = JSON.parse(String(reader.readLine())).map;
      reader.close();
      let kept = null;
      try {
        kept = File.readAllText(cache + '/revival-map');
      } catch (e) {
        // not recorded yet
      }
      if (!map || map === kept) return;
      let removed = 0;
      const remove = file => {
        const inside = file.listFiles();
        if (inside !== null) for (let i = 0; i < inside.length; i++) remove(inside[i]);
        if (file.delete()) removed++;
      };
      remove(JFile.$new(cache + '/Feature'));
      JFile.$new(cache).mkdirs();
      File.writeAllText(cache + '/revival-map', map);
      log('map tiles: a new map,', removed, 'cached files removed');
    } catch (e) {
      log('map tiles: not checked -', e.message);
    }
  });
}

// The server's texts (GET /revival/texts on the game server: {"replace": {term: text}, "append": {term: text}}, a text being
// one string or one by language), which follow the dashboard's settings: Revival's bestiary occurrences and trinket bonuses,
// the weather items' names, a pack's Open texts.
const TEXTS = new Map();
// ClientTexts.OpenPackButton and OpenPackHeader: no game terms, only this hook asks for them
const OPEN_PACK = 'REVIVAL/OPEN_PACK', OPEN_PACK_HEADER = 'REVIVAL/OPEN_PACK_HEADER';
// The count window's throw-away texts, read as opening while it shows a pack (the open packs stage sets packWindow)
const PACK_TERMS = { 'UI/PANELS/ALCHEMY/MANAGEMENT_REMOVE_HEADER': OPEN_PACK_HEADER, 'UI/PANELS/ALCHEMY/MANAGEMENT_REMOVE': OPEN_PACK };
let packWindow = false;
let textLengths = new Set();
// The same lengths for the C form of the texts hook: one byte per length, 1 for a length of the server's terms.
const TERM_LENGTHS = 1024;
const termLengths = Memory.alloc(TERM_LENGTHS);
// The dashboard's settings the game follows (WorldTuning.GameSettings, with the texts): {key: value}, and what applies them.
const SETTINGS = {};
const settingsUsers = [];
function whenSettings(apply) {
  settingsUsers.push(apply);
}
let language = () => 'en';  // the game's language (the texts stage asks I2)
// A text that is the same in every language (a string), or one by language ({"en": …, "pl": …}).
function pick(value) {
  return typeof value === 'string' ? value : value[language()] || value.en;
}
function loadTexts() {
  Java.perform(() => {
    try {
      const connection = Java.cast(Java.use('java.net.URL').$new('http://' + CONFIG.gameHost + ':' + CONFIG.httpPort +
        '/revival/texts').openConnection(), Java.use('java.net.HttpURLConnection'));
      connection.setConnectTimeout(1000);
      connection.setReadTimeout(2000);
      const reader = Java.use('java.io.BufferedReader').$new(
        Java.use('java.io.InputStreamReader').$new(connection.getInputStream(), 'UTF-8'));
      let body = '';
      for (let line = reader.readLine(); line !== null; line = reader.readLine()) body += line;
      reader.close();
      const texts = JSON.parse(body);
      for (const term of Object.keys(texts.replace || {})) TEXTS.set(term, { replace: texts.replace[term] });
      for (const term of Object.keys(texts.append || {})) TEXTS.set(term, { append: texts.append[term] });
      textLengths = new Set([...TEXTS.keys(), ...Object.keys(PACK_TERMS)].map(term => term.length));
      for (const length of textLengths) if (length < TERM_LENGTHS) termLengths.add(length).writeU8(1);
      log('texts:', TEXTS.size, 'from the server');
      Object.assign(SETTINGS, texts.settings || {});
      log('settings:', JSON.stringify(SETTINGS));
    } catch (e) {
      log('texts: not loaded -', e.message);
    }
    // without them (an older server, no answer) the game keeps its own behaviour: every setting reads as off
    for (const apply of settingsUsers) {
      try {
        apply();
      } catch (e) {
        log('settings: not applied -', e.message);
      }
    }
  });
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
