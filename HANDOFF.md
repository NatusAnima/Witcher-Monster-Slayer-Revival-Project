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
   - **No PC needed any more:** Setup step 3 builds and installs the playable client on the phone, and pushes the hook. The Kotlin compiles (`gradlew :app:compileReleaseKotlin`), pending a device test.
   - **Built and installed (2026-10-05 23:08):** `local/release/Witcher-Monster-Slayer-Revival-0.1.0.apk` is the release APK with the on-phone client build (arm64 only, signed with the release key).
     - Smoke-tested on the Xiaomi: it launches, shows the new Step 3, and the server starts and stops from the new runtime.
     - The on-phone client build itself has not been run on the device yet.
     - Fixed on the way: `build_runtime.py`'s closure check now skips `client/` (it failed on `client/libgadget.config.so`, a config that only has a library's name), and the manifest drops three legacy permissions (READ_PHONE_STATE and storage) that the manifest merger added because libadb-android declares no SDK version.
     - To rebuild: `python companion/runtime/build_runtime.py`, then `cd companion; ./gradlew assembleRelease`, then copy the APK to `local/release/`. A failed runtime build deletes `local/companion/`.
   - **Next:** the user tests it on the device from scratch (including the on-phone build). Then push and publish release v0.1.0.
   - It never distributes the game itself.

## Current State (2026-10-05)
**The client:**
- The phone runs our built client: `local/client/witcher116.apk`, made by `tools/client116/build_client.py` from the clean Play export (`~/witcher_1.1.116_300085`) and the extracted packs (`~/witcher_1.1.116_packs`).
- Gadget runs in script mode and loads `/sdcard/Android/data/com.spokko.witchermonsterslayer/files/hook.js`. `restart.py` pushes it; pushing a new copy reloads it into the running game.
- Hook output goes to logcat under the tag `Frida`, and is copied into `scratch/game.log`.

**On-phone client build (new, 2026-10-05 — compiles, device test pending):**
- Setup step 3 in the app builds the client on the phone instead of on a PC. Flow in `ClientBuildService`:
  back up the game over on-device adb → extract the 26 packs (`extract_packs.py`) → assemble the APK
  (`phone_build.py`, reusing `build_client.assemble()` with `lief` on the phone) → sign with apksig
  (`ClientSigner`, AndroidKeyStore key) → uninstall the Play copy → install via `PackageInstaller` → push the
  hook. The reversible work runs first; the destructive uninstall/install is last. Resumes at the install if
  `cacheDir/client/signed.apk` already exists.
- **On-device adb** (`Adb.kt`, libadb-android): the player enables Wireless debugging and pairs once in
  `PairActivity` (IP:port + 6-digit code from the pairing dialog). adb is used only for `bu backup`, the hook
  push (sync) and the Play-copy uninstall. The adb key lives in `files/adb`.
- The runtime now ships `lief`, the four builder scripts, Frida Gadget and the compiled hook under
  `runtime.zip` → `client/` (see `build_runtime.py`). Game-derived transforms (manifest, `libmain.so`) are
  computed on the phone from the user's own copy — never shipped — so no game files are distributed.
- **Device test watch-items** (can't be verified off-device):
  - `connectTls` relies on mDNS to find the TLS connect port; if it doesn't resolve, connect fails without the
    pairing prompt. Pairing uses the IP:port the dialog shows (the phone's own Wi-Fi IP).
  - MIUI may still gate the `PackageInstaller` confirm; the player taps Install.
  - Needs ~6–7 GB free transiently (backup + packs + unsigned + signed APK, cleaned as it goes).
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
