# Session Entrypoint

> **Start here for every new session.** It holds only the context needed to resume development.
> The setup and repository layout are in `README.md`. The 1.0.43-era notes are in git history; tag `legacy-1.0.43` is
> the last 1.0.43 state.

## Current Goal
Two tracks:
1. **Playtest 1.1.116 end to end over USB** and fix what breaks.
2. **Stage B: a phone-only companion app** published on GitHub. The design is in `docs/phone-only-companion.md`.
   - The companion hosts the server as a foreground service, so the game APK never changes after install.
   - It walks players through the Aurora install, gets the Play-delivered packs via on-device adb (Wireless debugging), and builds, signs and installs the client on the phone.
   - It offers a region picker with projected storage, and an optional shared server for multiplayer.
   - It never distributes the game itself.
   - Next step: **spike S1**. Does a static linux-musl-arm64 NativeAOT build of the server run under Android 11's app sandbox (seccomp and SELinux) and serve on loopback?

## Current State (2026-10-05)
**The client:**
- The phone runs our built client: `local/client/witcher116.apk`, made by `tools/client116/build_client.py` from the clean Play export (`~/witcher_1.1.116_300085`) and the extracted packs (`~/witcher_1.1.116_packs`).
- Gadget runs in script mode and loads `/sdcard/Android/data/com.spokko.witchermonsterslayer/files/hook.js`. `restart.py` pushes it; pushing a new copy reloads it into the running game.
- Hook output goes to logcat under the tag `Frida`, and is copied into `scratch/game.log`.

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
- **The phone must stay plugged in.** All traffic goes through `adb reverse`, and the server binds only to loopback.

## Device and Tooling Notes
- **Xiaomi phone (2201116SG, Android 11):** `adb install` shows an on-screen "Install via USB" prompt. If nobody taps it within about a minute, the install fails with `INSTALL_FAILED_USER_RESTRICTED`.
- **Git Bash:** prefix `adb push` with `MSYS_NO_PATHCONV=1`. Otherwise `/sdcard/...` is rewritten to a Windows path. Python and PowerShell are not affected.
- **No `adb shell input tap` on this phone.** Taps and runtime-permission grants (for example camera for AR) must be done by hand. Observe the screen with `adb exec-out screencap -p`.
- **Before a live session, check the server is running:** `Get-NetTCPConnection -LocalPort 4253` should show it listening.
- **Reverse engineering 1.1.116:**
  - Il2CppDumper v6.7.46 is in `local/tools/Il2CppDumper/`. A 1.1.116 dump has not been generated yet. Its inputs are `libil2cpp.so` from the config split and `assets/bin/Data/Managed/Metadata/global-metadata.dat` from `base.apk`.
  - The `tools/dump/` and Ghidra helpers still describe 1.0.43.
- **Addresses:** IL2CPP export offsets for this library (`libil2cpp.so`, sha256 `c8a5556b…`) are in `hook.js` (`RVA`). Native fixes go in `NATIVE_FIXES` and are applied only over their exact original bytes.
