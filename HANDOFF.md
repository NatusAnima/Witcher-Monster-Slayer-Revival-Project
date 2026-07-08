# The Witcher: Monster Slayer — Revival Project · Handoff

> Continuity doc for resuming in a fresh conversation. **Read this first**, then `docs/protocol-boot.md`.
> Last updated: 2026-07-04.

## The Goal
Resurrect the dead AR game **The Witcher: Monster Slayer** (`com.spokko.witchermonsterslayer`, Spokko/CDPR; servers shut 30 Jun 2023) by reverse-engineering its Unity **IL2CPP** client (arm64 v1.0.43) and standing up a custom backend.

---

## Current State — What Works

The **proof-of-life boot milestone is complete.** The client boots against our custom server in ~10.6 seconds and reaches the fully rendered Map/Home state. Additionally, the first NPC has successfully spawned and tutorial dialogue has been activated!

| Feature | Status |
|---|---|
| Auth handshake (TCP channel 3) | ✅ Working |
| Static data delivery (gzip JSON Container, 82 arrays) | ✅ Working |
| Initial player data sync (13-response batch) | ✅ Working (Methods 3,5,6,7,9,24,27,59,63,69,79,83,91) |
| LoadCells (Method 88) | ✅ Returns `BooleanResponse(true)` |
| Post-boot Api methods (Weather, Locations, Friends, etc.) | ✅ Empty/stub responses (10 explicit + catch-all) |
| Map tile loading (Google Maps SDK redirect) | ✅ ~10.6s boot (empty tiles = grass only, no roads) |
| 3D map, avatar, camera controls | ✅ Visible and interactive |
| Weather, compass, top-screen icons | ✅ Rendered |
| Bottom HUD (Inventory, Bestiary, Contracts) | ✅ Working (Modules un-bypassed, sync packets added) |
| Story/Quest UI | ✅ Working (PoiSettings manually injected to bypass DI timing issue) |
| Post-boot "Waiting for server" overlay | ⚠️ Should be fixed (catch-all replies to all methods) — needs phone verification |

### Un-bypassed Modules (running normally)
PlayerData, PlayerModule, GuiModule, ServerFactDatabaseModule, ShopKeeperModule, ShopStorageModule, TransactionModule, CameraModule, EnviroModule, PlayerModifiersModule, FriendsModule, RewardsModule, RateGameModule, TargetCompassModule, StoryModule, PoiModule, DailyContractsModule, WeeklyContractsModule, WitcherSensesModule, WeatherModule.

### Still-Bypassed Modules (InitializeModule replaced with no-op, get_Initialized returns 1)
BehaviourGraphModule.

---

## Architecture Overview

### Server (`server/WitcherRevival.Server/`)
- **Program.cs** — ASP.NET Kestrel on `:8080`. Routes: `/staticdata` (gzip Container JSON), `/v1/featuretiles/{**rest}` (empty protobuf 200 for map tiles), gatekeeper fallback (JSON with Address/WitcherId).
- **GameSocketService.cs** — `BackgroundService` TCP listener on `:4253`. Handles 4 channels: Auth (ch 3), StaticGameData (ch 4), Api (ch 1), Logging (ch 2). Dispatches Api Methods 88/115 at boot, plus 10 post-boot methods (20/40/43/61/67/85/94/102/110/141) with empty responses. Catch-all replies `BooleanResponse(true)` for any remaining unknown method. `BuildInitialPlayerData()` sends 18 sub-responses.
- **PreloaderStaticData.cs** — Builds the 82-array Container JSON with `LoadoutOverrides` (swords/armors/heads id=1).
- **Protocol/** — `ByteBuffer.cs` (big-endian codec), `Frame.cs` (5-byte framed I/O + channel/method enums).

### Client Patch (`tools/patch/hook.js`)
- **Frida script** injected via `frida_run.py` after `libil2cpp.so` loads.
- `hookConnect()` — libc `connect()` interceptor: redirects dead prod IP `:80` → `127.0.0.1:4253`, `:8080` → `127.0.0.1:8080`, force-fails `:443`.
- `installIl2cpp()` — all IL2CPP-level hooks:
  - Preloader config redirect (Host/Port/UseGatekeeper overwrite).
  - Module bypass system: `BypassInitModuleRVAs` (replace InitializeModule with no-op) + `BypassInitRVAs` (force get_Initialized→1), minus anything in `UNBYPASS_RVAS` set.
  - `FORCE_SYNC=true` — forces `SynchronizationStatus.IsSynchronized` → 1.
  - SignalBus.Fire null-Data bypass — swallows MethodMessage signals with null Data.
  - Map tile URL rewrite — rewrites `https://vectortile.googleapis.com/...` → `http://34.107.152.195:8080/...` (then hookConnect redirects to 127.0.0.1:8080).
  - Diagnostic hooks: Loader progress, module ENTER/LEAVE, exception backtrace, avatar diagnostics, Container field dump.

### Wire Protocol (docs/protocol-boot.md)
- Every client message: `[4B magic 0x9043284A][1B channel type][4B BE size][payload]`.
- Server replies: NO magic, just `[1B type][4B size][payload]`.
- Api envelope: `[1B API_VERSION=1][1B MsgType][int rcvCount][long×rcvCount Received][long Id][int Method][method payload]`.
- GetInitialPlayerData (Method 115) response: `[int count][for each: int methodId, inline sub-response fields]`.

---

## Known Blockers (Next Steps)

### Blocker 1: Post-boot "Waiting for server" overlay
After reaching Map state, an in-game overlay **"Ожидание ответа сервера…"** ("Waiting for server response…") appears — the client sends an Api method our server doesn't answer. **Next action:** identify the method ID from the RX frames in the server log and implement a reply.

### Blocker 2: StoryModule + PoiModule — mutual dependency + DI null (RESOLVED)
- **Resolved**: Both modules are un-bypassed. StoryModule's sync methods 70 + 60 were added to the server's initial player data sync batch.
- **Resolved**: The PoiSettings DI timing null blocker on PoiModule was resolved by intercepting WebstuffClientModule.InitializeModule to capture the settings instance, and then injecting it into PoiModule._settings field (0x60) during PoiModule.InitializeModule.

### Blocker 3: Bottom HUD modules (Contracts/Senses) (RESOLVED)
- **Resolved**: DailyContractsModule, WeeklyContractsModule, and WitcherSensesModule are un-bypassed. Their required sync methods (20, 94, and 43) have been added to the server's initial player data sync batch.

### Blocker 4: Map has no roads
The `/v1/featuretiles` endpoint returns empty protobufs — valid but renders as grass only. To render roads: serve real Google SVT FeatureTile protobufs with road polylines in tile-local coords.

**Next action:** Deferred (cosmetic, not functional).

---

## Environment / Hardware

- **PC:** Windows 10 Pro N, AMD Ryzen 7800X3D. .NET 10 SDK, Python 3.10, Java 8, git, frida/frida-tools 17.15.3, lief 0.17.6, capstone.
- **Phone:** Xiaomi 2201116SG (veux), Android 11, arm64-v8a, adb id `0bdd6603bf4b`. Locale: Russian.
- **PC LAN IP:** `192.168.1.148`. Server ports: `4253` (game TCP) + `8080` (HTTP).
- **Emulator is a dead end** (Zen4 + AEHD kills qemu) — physical phone only.
- **Phone must be AWAKE and UNLOCKED before launching** (secure keyguard, adb can't dismiss).

## How to Resume (Exact Steps)

```bash
# scratchpad for logs
SCRATCH="C:/Windows/Temp/claude/g--Apps-Witcher---Monster-Slayer-Revival-Project/48fb152f-baf8-4550-9eb8-54ea85d89c9f/scratchpad"
adb="tools/platform-tools/adb.exe"

# 0) server — kill any old listener, rebuild, run
#    (PowerShell) Get-NetTCPConnection -LocalPort 4253 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }
cd server/WitcherRevival.Server && dotnet build -v q && dotnet run --no-build > "$SCRATCH/server.log" 2>&1 &

# 1) tunnels
"$adb" forward tcp:27042 tcp:27042
"$adb" reverse  tcp:4253  tcp:4253      # hook.js redirects dead game-server:80 -> 127.0.0.1:4253
"$adb" reverse  tcp:8080  tcp:8080

# 2) relaunch + capture
"$adb" shell am force-stop com.spokko.witchermonsterslayer
"$adb" logcat -c
"$adb" shell monkey -p com.spokko.witchermonsterslayer -c android.intent.category.LAUNCHER 1
PID=$("$adb" shell pidof com.spokko.witchermonsterslayer | tr -d '\r')
"$adb" logcat --pid $PID -v time > "$SCRATCH/logcat.log" 2>&1 &
python tools/patch/frida_run.py 120 2>&1 | grep -vE "connect\(\) ->|REDIRECTED|backtrace:|libil2cpp\+0x"
```

---

## Key RVAs (arm64 v1.0.43)

### Core Game Loop
| RVA | Symbol |
|---|---|
| `0x17D5D30` | `Game.get_ModulesInitialized()` |
| `0x1F3DE50` | `ResetGame..ctor` |
| `0x1F9A10C` | `TutorialController.CheckTutorial()` |

### Networking
| RVA | Symbol |
|---|---|
| `0x2F85970` | `ThreadedClient.Connect` |
| `0x2F85B74` | `ThreadedClient.Run` |
| `0x2F860E8` | `ThreadedClient.Close` |
| `0x17A4598` | `SynchronizationModule.OnGetInitialPlayerDataResponse` |
| `0x1F99FD4` | `SynchronizationStatus.get_IsSynchronized` |
| `0x30F55A8` | `WwwRequest.CreateGetRequest` (tile redirect target) |

### Key Modules
| RVA (Init / get_Init) | Module |
|---|---|
| `0x17436E8 / 0x17436B4` | PlayerData |
| `0x173862C / 0x17384F8` | PlayerModule |
| `0x17F04E0 / 0x17F04CC` | GuiModule |
| `0x178A3D0 / 0x178A3BC` | ServerFactDatabaseModule |
| `0x17A0F94 / 0x17A0F80` | StoryModule |
| `0x17B34B8 / 0x17B3328` | PoiModule |
| `0x17E850C / 0x17E847C` | DailyContractsModule |
| `0x17EE69C / 0x17EE630` | WeeklyContractsModule |
| `0x190DAF8 / 0x190D4CC` | WitcherSensesModule |

### SignalBus / Diagnostics
| RVA | Symbol |
|---|---|
| `0x1C5C6DC` | `SignalBus.Fire(object)` |
| `0x1CE3728` | Exception throw helper (backtrace hook) |
| `0x31BAF6C` | `Loader.SetText(string)` |
| `0x31BAFC4` | `Loader.SetProgress(int, int)` |

---

## Session History (Chronological Summary)

1. **2026-07-03:** Initial protocol reverse-engineering. Preloader + boot sequence decoded. PlayerData NRE bypass via SignalBus.Fire null-Data hook. MapModule 60s timeout discovery.
2. **2026-07-03 (late):** Static data loadout overrides. Avatar diagnostics. Module bypass toggle system. Player data batch staged behind flag.
3. **2026-07-04 (early):** Wire format byte-verification. GuiModule un-bypassed. Player:SendInitialData default flipped to true.
4. **2026-07-04 (runtime):** Boot reached 68% — GetKnownRecipes(6) NRE fixed (9th batch sub-response). SignalBus bypass converted from log-only to replace.
5. **2026-07-04 (runtime #2):** Boot reached 76% — PlayerModule NRE was bypassed FactDatabase, not a missing packet. ServerFactDatabaseModule un-bypassed + Method 59 added (10th sub-response).
6. **2026-07-04 (UI bring-up):** White screen fixed by un-bypassing Camera/Enviro/Weather modules. Shop modules un-bypassed (Methods 83, 79, 91 added = 13 sub-responses). HUD partially restored.
7. **2026-07-04 (runtime #3):** Map loading optimized 72s→10.6s via tile redirect. Story/Poi UI attempted but blocked on PoiModule null `_settings`. Reverted to 13-batch.
8. **2026-07-08:** `GetFacts(58)` explicit handler added (returning `[int 0]`) to `GameSocketService.cs` to avoid a deserializer under-run from the 1-byte Catch-All. Confirmed `SetFacts(78)` expects a `BooleanResponse`, which aligns with the Catch-All. Preparing to capture the tutorial interaction with Thorstein by spoofing player GPS.
9. **2026-07-08:** Cleanup of workspace and heavy reverse-engineering artifacts. The client successfully spawned the first NPC (Thorstein) and the tutorial dialogue was activated!
