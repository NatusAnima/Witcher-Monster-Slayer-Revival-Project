# Session Entrypoint

> **Start here for every new session.** It holds only the context needed to resume development.
> The setup and repository layout are in `README.md`. The 1.0.43-era notes are in git history; tag `legacy-1.0.43` is
> the last 1.0.43 state.

## Current Goal
Two tracks:
1. **Playtest 1.1.116 end to end over USB** and fix what breaks.
2. **Stage B: a phone-only companion app**, named "Witcher Monster Slayer - Revival", published on GitHub: `companion/`, designed in `docs/phone-only-companion.md`.
   - **Done:** the app runs the server, the tile and placement services and the map index builder on the phone, with no PC.
     - The server is self-contained .NET (CoreCLR, not NativeAOT) for linux-musl-arm64. Python is Alpine's, with pyosmium.
     - `companion/runtime/seccomp_shim.c` answers the NUMA syscalls that Android's app seccomp filter would otherwise kill .NET for.
   - **Built, not yet tested on the device:** the setup checklist (Aurora, the game at 300085, Play copy or playable client), the region picker (Geofabrik), the in-app dashboard (the panel accepts its key as a cookie), self-update from GitHub Releases, release signing, and **the on-phone client build (no PC — see below)**.
     - The release key is in `local/keys/`. Without a backup of it, installed copies can never update.
   - **No PC needed any more:** guided-setup step 5 builds the playable client on the phone and installs it, with no adb and no Wireless debugging: the packs come from the Google Play download, Android's own dialogs replace the Play copy, and the hook travels inside the client's APK. It compiles; **the device test is pending.**
   - **Built and installed (2026-10-05 23:08):** `local/release/Witcher-Monster-Slayer-Revival-0.1.0.apk` is the release APK with the on-phone client build (arm64 only, signed with the release key).
     - Smoke-tested on the Xiaomi: it launches, shows the new Step 3, and the server starts and stops from the new runtime.
     - The on-phone client build itself has not been run on the device yet.
     - Fixed on the way: `build_runtime.py`'s closure check skips `client/` (Android libraries the game loads, never this runtime).
     - To rebuild: `python companion/runtime/build_runtime.py`, then `cd companion; ./gradlew assembleRelease`, then copy the APK to `local/release/`. A failed runtime build deletes `local/companion/`.
   - **New (2026-10-06): the 26 packs come straight from Google Play, inside the app** (`PlayAccount`, `GoogleLoginActivity`, `PlayPacks`, `PackDownloadService`, and the guided `SetupActivity`, opened from the main screen's Setup card). It compiles; **the device test is pending** and needs a Google account that had the game.
     - Sign-in: Google's own EmbeddedSetup page in a WebView, then the AC2DM exchange, then gplayapi (`AuthHelper.build`, Pixel 9a profile). The account is forgotten when the download ends.
     - Packs: `POST https://play-fe.googleapis.com/fdfe/assetModuleDelivery` (protocol and headers from microG), smallest pack first. Each pack is verified against `assets/packs.txt` (size and SHA-256 of the originals) and lands in `files/game/packs/<pack>`: the same files `extract_packs.py` writes, so `phone_build.py --packs <that dir>` takes them as they are.
     - A refused or odd answer goes to `files/logs/play.log` (no tokens). The guided setup has a **Copy debug info** button.
   - **Done (2026-10-06): Wireless debugging is out of the client build.** `ClientBuildService` no longer uses adb. `Adb.kt`, `PairActivity`, `PairingService` and the libadb-android, sun-security and Conscrypt dependencies are gone.
     1. The packs come from `PackDownloadService.dir(this)` (checked with `PackDownloadService.complete`). `phone_build.py --packs` takes them as they are, and they are deleted once the signed client exists.
     2. The Play copy is removed with `PackageInstaller.uninstall` (`REQUEST_DELETE_PACKAGES`): Android's own dialog, which the player confirms. The client then goes in through a `PackageInstaller` session, which the player confirms too. A notification offers each confirmation when Android won't open it over another app.
     3. The hook is inside the client APK as `lib/arm64-v8a/libhook.js.so`, beside Gadget. Gadget's config (`EMBEDDED_CONFIG` in `build_client.py`) names it by a relative path. Gadget resolves a relative script path against its own folder, and reads it out of the APK when the libraries are not unpacked (checked in Frida 17.15.3's `gadget.vala`). `phone_build.py` takes `--hook`, and `assemble(..., hook=None)` leaves the PC build as it was.
     - The assembly was checked on the PC with the real inputs: the result matches the PC-built client except for the new hook entry and the config. The Kotlin side, Gadget's relative path on the phone and the two confirmations are **not yet tried on the device.**
     - **A client's hook is fixed when it is built.** A hook fix needs a rebuilt client, which needs the packs again (another Google Play download). `restart.py --hook-only` only reaches a client that `build_client.py` made on a PC. If that becomes a chore, ship a small loader as the embedded hook that fetches the real one from the app's server on 127.0.0.1, or rebuild from the installed client APK by swapping that one entry.
   - **Next:** the user tests the whole guided setup on the device from scratch (the extra-data download already works), then release v0.1.0.
   - It never distributes the game itself.

## 0.2.0 work (2026-10-07): reports, map, APKMirror, stability
One release, 0.2.0 (`appVersion`), because the hook changes raise `y`: every installed game is offered "Update the game" (the first real
in-place update, never run on a device; there is no rollback, a z bump never re-offers it). Plan and reasons: memory `twms-field-reports-2026-10`.
- **Reports and logs (the priority):** `EventLog` (`logs/events.log`, written by every service's `update()`), a flight recorder line every 15 s while the
  server runs, `DebugInfo.share` (zip in Downloads + share sheet; phone snapshot, `ApplicationExitInfo`, own logcat, all logs, masked), server log
  flags (single line, timestamps), a loopback sink (`ServerService.LOG_PORT` 18094) that writes the game hook's log to `logs/game.log`.
- **Hook (`tools/client116/hook.js`):** every install stage reports ok/FAILED; the log is mirrored to the sink; a 10 s heartbeat; 20 s after start it reads
  the previous run's exit reasons and `logcat -d -b crash` / `*:E`. A marker file `.../files/crash-test` makes it `abort()` 20 s after start (test only).
  `Script.setUnhandledExceptionCallback` and `Process.setExceptionHandler` are deliberately not used (see the memory note). **Not run on a device yet.**
- **APKMirror:** `build_client.assemble` sorts the game's APKs by content (a split set or one universal `base.apk`; extra splits ignored; fails with the
  pack count). The app accepts an install whose libraries are in a split or inside a single APK (`GameFiles`), and Setup step 2 offers Aurora or APKMirror.
  Not tested on the real APKMirror files yet: if the 1.1.116 single APK has neither `com.android.vending.splits.required` nor
  `com.android.dynamic.apk.fused.modules` in its manifest, `axml.py` needs element insertion.
- **Map:** the builder prints `PHASE`/`PROGRESS` lines (progress and ETA only after the node phase: pyosmium holds the GIL before), has `--low-memory`
  (file-backed node index; on the PC Israel took 12.3 s vs 12.0 s), exits 3/4 for out-of-memory/disk full. `Geofabrik.kt` resolves `-latest` to the dated
  file and resumes it; `MapService` keeps the download after a failed build, persists the request and failure (`Maps`), and Setup step 6 offers Try again.
  `RegionActivity` checks size, memory and disk, picks low-memory mode when RAM is short, and has a Smaller regions button. **Timings on a phone are guesses**
  (3-6 s/MB) until the Xiaomi runs Monaco and Israel: if low-memory is within ~1.3x of in-memory there, make it the default and delete `flex_mem`.
- **Stability:** `ServerService` races fixed (one lock, liveness check, no orphan after stop, "Stopped" not overwritten); Play refuses the Play-signed original;
  step 7 has Allow background running + a line per phone brand; the build checks "install unknown apps" first; install failures are explained; a pending
  confirmation has a Confirm now button (Setup and the main screen).
- **Second batch of field reports (2026-10-07), also in 0.2.0:**
  - *Mobs favour forests:* `playable_locations.sample` drew the day's places evenly from every candidate point, and a wood is a 35 m grid over its whole
    polygon, so woods filled every cell they touched (93-99% of the places around a big forest on the Israel extract, 77% near a town by woods).
    Woods now hold at most `FOREST_MAX_PER_CELL` (12 of 24) places; the rest of the cell is paths and parks. Place ids carry `PLACEMENT_VERSION` 4, and the
    legacy golden in `test_placement_policy` was changed on purpose. A scheduled placement policy keeps its own spread. The limit is a knob: 8 gives
    36-57% forest near the same towns; towns with few mapped footways stay short of places whatever the draw does (the clearance from streets is policy).
    The limit is now a dashboard setting (Tuning page, `woods.maxPlaces`, see below); `FOREST_MAX_PER_CELL` is only its default.
  - *Wolven armor showed "0%":* `Effects.GetEffect` (0x194E178) builds `Dummy(power 0)` for effect ids 0, 42-55, 60, 62, 63, 66, 68, 73, 77-79 and 81; only 70 and
    71 keep the row's power. The armor now uses 71 (`Reconstruction.ExtraIngredientEffect`); `test_item_effects_keep_their_power_in_the_client_descriptions`
    checks every item effect against that list.
  - *The game build's notification never went away:* `ClientBuildService.finish` detached the ongoing, spinning notification. The outcome is now an ordinary one
    (static icon, swipeable, tap clears it); the pack and map outcomes got the static icon too.
  - *Region list:* Geofabrik names every US state `us/texas` (Georgia alone is "Georgia"), parents them to North America, and the ids with a slash became
    sub-folders (a US state's map was built into `maps/us/`, which `Maps.selected` never searched, so the server ran without a map). Names are made readable, states are listed under United States of America, ids are flat
    (`us-georgia`), and the Polish and Norwegian names lose their `<br />`.
  - *Daily "On the Path" (walk 1 km), "no reward":* the real server pays 75 gold, shows 75 and returns the new wallet total (walk 10 x 100 m, claim; a second claim is
    refused). The wiki says 50 before May 2022. The likely cause of "walked it, nothing paid": the client counts the walk done as it happens but reports it in
    steps of 100 m (RPC 27), so its claim can reach the server a step behind (or after a lost report) and was refused. A distance daily is now paid on the
    client's claim unless the profile's movement is protected (`PlayerService.WalkedEnough`; RPC 27 already takes any delta, so nothing new is trusted); a protected
    profile still counts only the server's own fixes. `test_distance_claim_is_paid_ahead_of_the_reports_unless_protected`. Every claim (paid / refused and why,
    with progress) and every distance report is logged, so a report shows which it was. Changing a shipped task needs a new id: the app copies `tasks/` once and the
    server refuses to redefine a persisted id.
  - *Dashboard Tuning page (new):* simple numbers a player can set, saved in `world/tuning.json` (`WorldTuning`; read again about once a second, a save applies at
    once, a missing/damaged file means the defaults, bad values are refused on save, receipts and backups like the other pages). Settings: woods limit per cell
    (`woods.maxPlaces`, read by the placement service through `--tuning`, drawn places from then on), experience % and ingredients % of a won fight, herb respawn
    minutes, herbs per cell. Not exposed on purpose: task rewards (a shipped task needs a new id), the walking multiplier, nest limits. Monsters per cell was already
    on the World tab. `test_tuning.py` and `test_dashboard_tuning_sets_fight_rewards_and_herbs`.
  - *Map "still fails":* nothing reproduced offline (download/resume/build/placement all run under qemu). One real gap fixed: the tile and placement services read the map
    once when they start, so a map built while the server ran (the server shows "Running without a map: choose a region" until then) stayed unused until the server
    was stopped and started. `MapService` now calls `ServerService.reloadMap` and the server restarts just those two children (`restartMap`), the game server stays up.
    Needs the exact failure text or a "Send a report" zip from a player to go further.
  - Built 2026-10-07 20:08 with all of this: `local/release/Witcher-Monster-Slayer-Revival-0.2.0.apk` (runtime rebuilt, same release key, `apksigner verify` ok and the
    same certificate as the first build). The earlier sideloaded build, which is what the Xiaomi runs, is kept as `...-0.2.0-first-sideload.apk` (same versionCode,
    so `adb install -r` works either way). NOT installed on the phone: the second build waits for the maintainer's go-ahead.
    Server tests on the PC (283, one run of every class's own tests): all pass except 17 that only fail on Windows: `/proc/net/tcp`, file modes, `fcntl`
    (`apply_staged_tasks.py`, `test_trinket_repair`), `.lock` files the server holds open (the profile-label, server-metrics and `test_admin_transport` tests read them),
    Python 3.10's `fromisoformat` on 7-digit fractions, a failed-save case, the aura bootstrap. Run them on Linux (or 3.11+) before a release.
- **To do before release:** rebuild the runtime (`python companion/runtime/build_runtime.py`, it bundles the changed map script and hook), `./gradlew
  assembleRelease`, then the device gates: Monaco/Israel builds, airplane-mode resume, APKMirror file, report zip, and the 0.1.0 -> 0.2.0 "Update the game" gate
  (also with the screen off, notifications denied, and on a Samsung phone). Tests: `python tools/client116/test_assemble.py`,
  `python tools/client116/test_patch_client.py`, map tests with `local/venv` (`test_osm_extract_index`, one old test errors on Windows at temp cleanup).

## Current State (2026-10-05)
**The client:**
- The phone runs our built client: `local/client/witcher116.apk`, made by `tools/client116/build_client.py` from the clean Play export (`~/witcher_1.1.116_300085`) and the extracted packs (`~/witcher_1.1.116_packs`).
- Gadget runs in script mode. The PC-built client loads `/sdcard/Android/data/com.spokko.witchermonsterslayer/files/hook.js`: `restart.py` pushes it, and pushing a new copy reloads it into the running game. The client the companion app builds carries its hook inside the APK (`libhook.js.so`) instead, so a push does nothing there.
- Hook output goes to logcat under the tag `Frida`, and is copied into `scratch/game.log`.

**On-phone client build (2026-10-06 — compiles, device test pending):**
- Guided-setup step 5 builds the client on the phone instead of on a PC. Flow in `ClientBuildService`:
  assemble the APK from the installed game and the downloaded packs (`phone_build.py`, reusing
  `build_client.assemble()` with `lief` on the phone, the hook inside) → sign with apksig (`ClientSigner`,
  AndroidKeyStore key) → delete the packs → the player confirms removing the Play copy
  (`PackageInstaller.uninstall`) → install via a `PackageInstaller` session, which the player confirms. No adb.
  The reversible work runs first; the removal and install are last. Resumes there if `files/client/signed.apk`
  exists. A copy of the game signed with any key but this app's goes first, whatever it is (the Play copy, or a
  client built elsewhere).
- The runtime ships `lief`, the four builder scripts, Frida Gadget and the compiled hook under
  `runtime.zip` → `client/` (see `build_runtime.py`). Game-derived transforms (manifest, `libmain.so`) are
  computed on the phone from the user's own copy — never shipped — so no game files are distributed.
- **Device test watch-items** (can't be verified off-device):
  - Gadget finding `libhook.js.so` by its relative path (it should, per `gadget.vala`), then the hook running: look for
    the `Frida` lines in logcat.
  - MIUI's own uninstall and install screens; a notification offers each confirmation if Android won't open it.
  - Needs ~6–7 GB free transiently (packs + unsigned APK + signed APK; the packs go once the client is signed).
  - `phone_build` expects exactly the Aurora 300085 split set; a device with extra config splits trips the
    count check (`ponytail:` note in `build_client.assemble`).

**The server:**
- `server/` is the 1.1.116 reconstruction, vendored in from the privately shared repo. That copy stays untouched and git-ignored; never commit or publish it.
- `tools/restart.py` builds `server/WitcherRevival.Server` into `local/build/server116` and keeps data in `local/server116/` (profiles, news, tasks, world, admin key). It starts the map services against `local/maps/israel-features.sqlite`.

**Working on device:**
- boot and login;
- static data;
- the tutorial with combat;
- the map with OSM tiles;
- level-up rewards;
- contracts (after the coin-preview native fix);
- the operator panel at http://127.0.0.1:18090/.

**Known gaps:**
- **News is empty.** The game fetches it over System.Net HTTPS, and the hook refuses port 443. Porting the sharer's async-news fix (`client/news_async/` in the shared repo) would fix it.
- **The sharer's other client fixes are not ported yet:** the request watchdog and network-loss auto-recovery.
- **GPS collector (ported 2026-10-05, device check pending):** `tools/client116/gps.js` sends location fixes as RPC 2001.
  - Android 11 delivers them through Unity's `ReflectionHelper` proxy; Android 12+ uses the fused callback.
  - `restart.py` bundles it with `frida-java-bridge` into `local/client/hook.bundle.js`.
  - The server keeps the newest position for 120 s. Story goals and relocation are placed around it; without a position they fall back to the area estimate.
  - Distance policy stays observation (`shadow`) unless changed in the panel.
  - Look for `gps …` lines in `scratch/game.log` (`capture-ready`, `native-ready`, `shadow-ready`, `counts …`).
- **With `restart.py`, the phone must stay plugged in.** All traffic goes through `adb reverse`, and the server binds only to loopback. The companion app runs everything on the phone instead.

## Device and Tooling Notes
- **Xiaomi phone (2201116SG, Android 11):** `adb install` shows an on-screen "Install via USB" prompt. If nobody taps it within about a minute, the install fails with `INSTALL_FAILED_USER_RESTRICTED`.
- **Git Bash:** prefix `adb push` with `MSYS_NO_PATHCONV=1`. Otherwise `/sdcard/...` is rewritten to a Windows path. Python and PowerShell are not affected.
- **No `adb shell input tap` on this phone.** Taps and runtime-permission grants (for example camera for AR) must be done by hand. Observe the screen with `adb exec-out screencap -p`.
- **Before a live session, check the server is running:** `Get-NetTCPConnection -LocalPort 4253` should show it listening.
- **Reverse engineering 1.1.116:**
  - Il2CppDumper v6.7.46 is in `local/tools/Il2CppDumper/`. A 1.1.116 dump is in `local/il2cpp116/out/` (`dump.cs`, `script.json`; inputs in `local/il2cpp116/in/`: `libil2cpp.so` from the config split and `assets/bin/Data/Managed/Metadata/global-metadata.dat` from `base.apk`; the dumper's final "press any key" throws when stdin is redirected, the output is complete by then). `capstone` (pip) disassembles arm64 on Windows: file offset = RVA for the code, `script.json` `ScriptMethod` names the targets.
  - The `tools/dump/` and Ghidra helpers still describe 1.0.43.
- **Addresses:** IL2CPP export offsets for this library (`libil2cpp.so`, sha256 `c8a5556b…`) are in `hook.js` (`RVA`). Native fixes go in `NATIVE_FIXES` and are applied only over their exact original bytes.
