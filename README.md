# Witcher: Monster Slayer — Revival Project

## Overview
This project resurrects the discontinued augmented reality game **The Witcher: Monster Slayer** (`com.spokko.witchermonsterslayer`, servers shut down June 2023). It targets client **1.1.116 (version code 300085)**, the last version before update 1.2.

The original backend is gone, so the project runs a reconstructed game server and modifies your own installation of the game to talk to it. The game's files are not distributed here: you install the game yourself (from Google Play through the Aurora Store, or from APKMirror) and the tools build a playable client from that installation.

> **Thank you, Villainser.** This project is using Villainser's fork of this project that contributed immense amounts of code to this project. The game server, the operator panel, the OpenStreetMap map services, the majority of the story and protocol tools, the backend tests and the in-game client fixes all started there. Without it, this project would not exist in its present form. See [Credits and Licensing](#credits-and-licensing).

**Community:** questions, setup help and news are in the unofficial Discord, https://discord.gg/dEJQfecqnU. Bugs still go to GitHub issues.

## How it works
- **Client:** `tools/client116/build_client.py` merges your installed APK splits and the 26 asset packs Google Play downloads after install into one APK. It patches the manifest, adds Frida Gadget, and re-signs it. Gadget runs `tools/client116/hook.js` inside the game, which:
  - redirects the original server hosts to your server;
  - rewrites the news and map-tile URLs;
  - applies client fixes: a missing reward-popup asset, and the coin-preview crash when opening contracts.
- **Server:** `server/WitcherRevival.Server` (ASP.NET Core, .NET 10) serves:
  - the game's binary protocol on TCP `4253`;
  - static data and news over HTTP on `18080`;
  - an operator panel (players, map, news, tasks, weather).
- **Maps:** the map comes from OpenStreetMap. `server/connection/map-road-fixture-01/` holds a tile service (`18082`) and a monster-placement service (`18093`), both reading a regional SQLite index built from an OSM extract.
- **Running it:** `tools/restart.py` starts all of it and connects the phone over USB (`adb reverse`).
- **Phone-only:** the companion app in `companion/` runs the server and the map services on the phone, and builds the playable client there, so no PC is needed. See the next section.

## Phone-only play: the companion app
The companion app, **Witcher Monster Slayer - Revival**, runs the server and the map on the phone and builds the playable client there, so no PC is needed, for setup or for playing. It needs an arm64 phone with Android 11 or later.

1. **Install the app.** Download `Witcher-Monster-Slayer-Revival-<version>.apk` from [Releases](https://github.com/NatusAnima/Witcher-Monster-Slayer-Revival-Project/releases) and open it on the phone. When Android asks, allow your browser or file manager to install apps.
2. **Follow the guided setup**, which opens from the app's main screen. It ticks each step off by itself and opens the next:
   1. **Check the phone.** It shows your free space and what the setup needs.
   2. **The game, version 1.1.116 (code 300085).** Get it from either source; the app checks what is installed and ticks the step. It shows the steps for the one you pick and can switch between them.
      - **Aurora Store** downloads it from Google Play. Google removed the game from Play in January 2023, so only a Google account that had it before can still download it. In Aurora, sign in with that account (anonymous sign-in can't download it), open the game's page, tap the three dots → **Manual download** and enter **300085**. Then, in the Play Store, use the Google account that previously had the game and untick **Enable auto update** on the game's page. Never tap **Update** there. The app has a button for each.
      - **APKMirror** needs no Google account for this step. Open version 1.1.116 of The Witcher: Monster Slayer on apkmirror.com, download the **APK** (one file, about 700 MB; the bundle also works, but needs the APKMirror Installer app), and open the file to install it. The app's **Open APKMirror** button opens the search. The extra data in step 4 still comes from a Google account that had the game.
   3. **Sign in to Google.** The game's 26 extra data packs (1.3 GB) exist only on Google's servers, and the app asks Google Play for them the way the Play Store does. Google removed the game in 2023, so it may only offer them to an account that had the game before. The account stays on the phone, private to the app, and the app signs out when the download ends. Your Google account's device list will show this phone as a Pixel 9a: remove it there afterwards if you like. This is not an official Google method, so use an account you are comfortable with.
   4. **Download the extra data.** It carries on in the background, even with the screen off.
   5. **Build the playable client.** The app builds it on the phone from your copy of the game and the extra data, with no PC and no Wireless debugging. Android then asks you twice: to uninstall the game, which the client replaces, and to install the client. Confirm both. It needs about 6–7 GB of free space and a few minutes. The game's own files never leave the phone.
   6. **Your map region.** Pick it from Geofabrik's OpenStreetMap extracts. The app shows the download size, the map's size on the phone and your free space. It then downloads the extract and builds the map on the phone.
3. **Tap Play.** It starts the server and opens the game when the server is ready.

While the server runs, **Dashboard** opens the operator panel (players, map, news, tasks, weather, and a Tuning page for simple values such as the forest limit, experience and herb rates) inside the app.

The app checks Releases for a newer version and offers to update itself (Android asks you to confirm the install). Updates keep your progress, but uninstalling the app deletes it.

If a release also changes the game, the update says so, and the app then offers **Update the game**. It patches the game it built in place: no Google sign-in and no download, about 6 GB free for a few minutes, and one install confirmation.

**Send a report** (on the main screen, in the guided setup, and next to any failure there) saves a zip in your Downloads folder and opens the share sheet. It holds your phone's model and versions, the game's install state, why the app's processes last ended, and every log, with emails, token-like strings and coordinates masked. Nothing is sent until you pick where: send it to the maintainers on the Discord above. After a game crash, open the game once more before sending, so it can report why it closed. **Report on GitHub** opens a prefilled issue with the phone's details only: attach the zip, and remember that issues are public.

**Troubleshooting**
- **The map fails, or takes very long.** Most countries are over 1 GB, which is a lot for a phone. Pick the smallest region that covers where you play (the region dialog's **Smaller regions** button lists the parts of a country). Big regions are built in a slower mode that keeps working data on disk and needs several times the extract in free space. A failed build keeps its download: tap **Try again** in the guided setup.
- **Android blocks an install.** Allow this app to install apps (the setup opens that screen). On a Samsung phone turn off Auto Blocker (Settings, Security and privacy). If Play Protect asks, tap More details, then Install anyway.
- **The game stops or can't connect.** Keep this app in the recent apps screen: swiping it away stops the server on some phones (Xiaomi). In the guided setup's last step, allow background running and follow the line for your phone's brand (Samsung: Never sleeping apps, Keep open).

### Building the companion app
**Prerequisites:** WSL with Ubuntu, the .NET 10 SDK, Python 3.10+, JDK 21, Node.js (to bundle the game hook), and the Android SDK, with its path in `companion\local.properties` (`sdk.dir=...`).
1. Build pyosmium and the seccomp shim for arm64 Alpine. It runs without root or Docker, and the first build takes a few minutes:
   ```powershell
   wsl -d Ubuntu -- sh companion/runtime/build_natives.sh
   ```
2. Assemble the phone runtime (musl, the server, Python, the map services, and the on-phone client builder) into `local\companion\`:
   ```powershell
   python companion\runtime\build_runtime.py
   ```
3. Build the APK, which lands in `companion\app\build\outputs\apk\release\`:
   ```powershell
   cd companion; .\gradlew assembleRelease
   ```
   Release builds are signed with the key that `local\keys\companion.properties` names. Without it the APK is unsigned. Self-updates only install over a copy signed with the same key, so keep a backup of `local\keys\`.

**Releasing.** Versions are `x.y.z`, set as `appVersion` in `companion/app/build.gradle.kts`:
- `x` is the stage (alpha, beta, ...).
- Raise `y` for a release that changes the game itself: the hook or Frida Gadget inside the client. Installed games are then updated in place. The in-place update swaps only those files (`patch_client` in `tools/client116/build_client.py`). A change to the manifest or `libmain.so` patch needs a full rebuild, so say so in the release notes.
- Raise `z` for a change to the app alone. The game is left as it is.

Publish the APK as a GitHub release tagged `v<version>`. Do not mark it as a pre-release: the app asks GitHub for the latest release, which skips those.

Before a release run `./gradlew lintRelease` in `companion/` and look for `NewApi` errors (a call that only exists in newer Android crashed an Android 11 phone once). `companion/local.properties` needs an escaped drive letter in `sdk.dir` (`G\:/...`), or lint reports `PropertyEscape`.

## Setup From a Fresh Clone (Windows)
**Prerequisites:**
- an arm64 Android phone with USB debugging;
- the .NET 10 SDK;
- Python 3.10+ with `pip install -r tools/requirements.txt`;
- Python 3.12+ (for the map tools venv);
- JDK 21 on `PATH`;
- Node.js, whose `npm` installs what the game hook is bundled with;
- Android platform-tools unzipped into `tools/platform-tools/`.

Commands are PowerShell, run from the repository root, with `$adb = "tools\platform-tools\adb.exe"`.

1. **Install 1.1.116 from Google Play through the Aurora Store.**
   1. Install Aurora Store from its official source (https://gitlab.com/AuroraOSS/AuroraStore) and finish its setup. Sign in with a Google account that had the game before: Google removed the game from Play in January 2023, and Aurora's anonymous sign-in can't download it.
   2. Open the game's listing in Aurora:
      ```powershell
      & $adb shell am start -a android.intent.action.VIEW -d "market://details?id=com.spokko.witchermonsterslayer" -p com.aurora.store
      ```
   3. Choose **Manual download** and enter the version code **300085** (not `1.1.116`), then install.
   4. In the Play Store, select the Google account that previously had the game.
   5. Turn off auto-update for the game: game page → ⋮ → untick **Enable auto update**. Otherwise Play replaces it with 1.3.102.
2. **Pull the installed APKs** (23 files, about 615 MB):
   ```powershell
   $out = "$HOME\witcher_1.1.116_300085"; mkdir $out
   & $adb shell pm path com.spokko.witchermonsterslayer | % { & $adb pull ($_ -replace '^package:','').Trim() $out }
   ```
3. **Reinstall with Google Play as the installer**, so Play delivers the additional game data:
   ```powershell
   & $adb install-multiple -r --no-incremental -i com.android.vending (Get-ChildItem $out\*.apk).FullName
   ```
   Don't uninstall first, and don't use `pm set-installer`, which fails. Then launch the game once and accept the additional data download. Downloading this data is not an update: don't tap **Update** in the Play Store.
4. **Back up the 26 downloaded packs and extract them.** Approve the backup on the phone and leave the password empty:
   ```powershell
   cmd /c "tools\platform-tools\adb.exe exec-out bu backup -noapk com.spokko.witchermonsterslayer > %USERPROFILE%\witcher_appdata.ab"
   python tools\client116\extract_packs.py $HOME\witcher_appdata.ab $HOME\witcher_1.1.116_packs
   ```
   The backup also contains your account data, so keep it private.
5. **Build and install the client.** It is signed with a different key, so the Play copy has to be uninstalled first; the packs are already extracted. On Xiaomi phones, tap **Install** on the USB-install prompt.
   ```powershell
   python tools\client116\build_client.py --apks $out --packs $HOME\witcher_1.1.116_packs
   & $adb uninstall com.spokko.witchermonsterslayer
   & $adb install --no-incremental local\client\witcher116.apk
   ```
6. **Build the map index for your area.**
   1. Create the venv and install osmium:
      ```powershell
      py -3.12 -m venv local\venv; local\venv\Scripts\python -m pip install osmium
      ```
   2. Download your region's `.osm.pbf` from https://download.geofabrik.de/ into `local\maps\`.
   3. Build the index:
      ```powershell
      local\venv\Scripts\python -B server\connection\map-road-fixture-01\osm_extract_index.py --input local\maps\<region>.osm.pbf --output local\maps\<region>-features.sqlite
      ```
7. **Play:**
   ```powershell
   python tools\restart.py --index local\maps\<region>-features.sqlite
   ```
   - It builds and starts the server and the map services, sets up the USB tunnels, pushes the hook and launches the game.
   - Keep the phone plugged in. While it runs you can also start the game from its icon.
   - The operator panel is at http://127.0.0.1:18090/. Use `127.0.0.1`, not `localhost`, or saves are refused.
   - Rerun it to restart everything. Logs go to `scratch/`.
   - Everything machine-specific (build output, profiles, map data, the built APK) lives in the git-ignored `local/` folder.

## Repository Structure
The code under `server/` originates from Villainser's 1.1.116 reconstruction (see [Credits and Licensing](#credits-and-licensing)).

- `server/WitcherRevival.Server/`: the game server.
  - `Net/`: protocol handlers, player state, world, story, tasks.
  - `Admin/`: the operator panel.
  - `Story/`: season 1 story data.
  - `tasks/` and `news/`: default content.
- `server/connection/map-road-fixture-01/`: the OSM tile service, placement service and index builder, with their tests and the technical record `OSM-LIVE.md`. `connection/map-tile-fixture-01/generated-terrain01/` holds the flat terrain tile the tile service serves.
- `server/story-1.1.116/`: the generators for the story and bestiary JSON. They need the original game assets.
- `server/contract-1.1.116/`: per-RPC protocol coverage and the static-data catalogue for 1.1.116.
- `server/tests/`: backend integration tests. `server/dev.py` expects the Linux toolchain layout.
- `tools/client116/`: the client builder (`build_client.py`, and `phone_build.py` for the app), manifest editor (`axml.py`), pack extractor (`extract_packs.py`) and in-game hook (`hook.js`).
- `tools/restart.py`: one-command start/restart of everything, including the operator panel.
- `companion/`: the Android companion app (`app/`) and the scripts that build its phone runtime (`runtime/`).
- `HANDOFF.md`: the active session tracker. **Start here when resuming development.**
- **Legacy (client 1.0.43, kept for reference):**
  - `tools/patch/` (`patch_apk.py` still supplies the Gadget and signer downloads);
  - `tools/data_sources/`, `tools/unity_extract/`, `tools/ghidra_decomp.py`, `tools/il2cpp_callers.py`;
  - the notes in `docs/`;
  - the 1.0.43 server, at git tag `legacy-1.0.43`.

## Reference Documentation
- `server/contract-1.1.116/RPC_COVERAGE.md`: every 1.1.116 API method and what the server answers.
- `server/CONTRACT.md`: the wire contract.
- `server/connection/map-road-fixture-01/OSM-LIVE.md`: how OSM data becomes game map tiles.
- `docs/phone-only-companion.md`: the design for phone-only play (companion app, server on the phone, shared servers).
- `docs/` (1.0.43): protocol notes, memory maps, and the original server's feature inventory.

## Credits and Licensing
- This project is licensed under GPLv3 (`LICENSE`).
- **Villainser's contribution to this project is immense.** This project is built on Villainser's 1.1.116 reconstruction, which is the source of:
  - the game server and its operator panel (`server/WitcherRevival.Server/`): the protocol, player state, world, story, tasks and weather;
  - the OpenStreetMap map services and the index builder (`server/connection/`);
  - the story and bestiary generators (`server/story-1.1.116/`);
  - the protocol coverage documentation and the wire contract (`server/contract-1.1.116/`, `server/CONTRACT.md`);
  - the backend integration tests (`server/tests/`);
  - the ported client fixes in the game hook (`tools/client116/`): the missing reward-popup asset, the coin-preview crash, and the GPS collector.

  The reconstruction was forked from this project's commit `3cb353b`, is GPL-3.0-only, and is used with permission; see `server/LICENSE` and `server/upstream-provenance.json`. Some copied documents link to that project's own docs, which are not included here.
- The Earcut triangulation port is under the ISC licence; its notice is kept in `server/connection/map-road-fixture-01/osm_area_geometry.py`.
- Map data is © OpenStreetMap contributors (ODbL 1.0). Indexes and tiles generated from it are derived from OpenStreetMap.
- The PC tools download Frida Gadget and uber-apk-signer at build time; neither is in this repository.
- The companion app's APK also bundles what its on-phone client build uses:
  - Frida Gadget 17.15.3 (wxWindows Library Licence 3.1, an LGPL variant; source: https://github.com/frida/frida);
  - LIEF 0.17.6 (Apache-2.0);
  - apksig (Apache-2.0);
  - gplayapi 3.6.4 by Aurora OSS (GPL-3.0-or-later; https://gitlab.com/AuroraOSS/gplayapi), with OkHttp, Gson, kotlinx.serialization and kotlinx.coroutines (Apache-2.0) and Protocol Buffers Lite (BSD-3-Clause).
- Signing in to Google and downloading the game's extra data follow the open source of Aurora Store (the sign-in flow, GPL-3.0-or-later) and microG (the asset-delivery request and its headers, Apache-2.0). The app only asks Google Play for data your own account may download.
- The companion app bundles third-party software, each under its own licence:
  - from Alpine Linux 3.22: musl (MIT), CPython 3.12 (PSF-2.0), OpenSSL 3.5 (Apache-2.0), SQLite (public domain), libstdc++ and libgcc (GPL with the GCC Runtime Library Exception), zlib (Zlib), libffi and expat (MIT), bzip2 (bzip2), xz/liblzma (0BSD), mpdecimal and lz4 (BSD-2-Clause). Their sources are in Alpine's `aports` repository;
  - the .NET runtime and ASP.NET Core (MIT), compiled into the server;
  - pyosmium 4.3.1 (BSD-2-Clause), with libosmium (Boost Software License 1.0) and protozero (BSD-2-Clause).
- This project is not affiliated with CD PROJEKT RED or Spokko. No original game files are included; you provide your own installation.
