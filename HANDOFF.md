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
  - Il2CppDumper v6.7.46 is in `local/tools/Il2CppDumper/`. A 1.1.116 dump has not been generated yet. Its inputs are `libil2cpp.so` from the config split and `assets/bin/Data/Managed/Metadata/global-metadata.dat` from `base.apk`.
  - The `tools/dump/` and Ghidra helpers still describe 1.0.43.
- **Addresses:** IL2CPP export offsets for this library (`libil2cpp.so`, sha256 `c8a5556b…`) are in `hook.js` (`RVA`). Native fixes go in `NATIVE_FIXES` and are applied only over their exact original bytes.
