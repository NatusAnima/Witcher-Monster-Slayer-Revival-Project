# Witcher: Monster Slayer — Revival Project

## Overview
This project resurrects the discontinued augmented reality game **The Witcher: Monster Slayer** (`com.spokko.witchermonsterslayer`, servers shut down June 2023). It targets client **1.1.116 (version code 300085)**, the last version before update 1.2.

The original backend is gone, so the project runs a reconstructed game server and modifies your own installation of the game to talk to it. The game's files are not distributed here: you install the game yourself from Google Play (through the Aurora Store) and the tools build a playable client from that installation.

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

## Setup From a Fresh Clone (Windows)
**Prerequisites:**
- an arm64 Android phone with USB debugging;
- the .NET 10 SDK;
- Python 3.10+ with `pip install -r tools/requirements.txt`;
- Python 3.12+ (for the map tools venv);
- JDK 21 on `PATH`;
- Android platform-tools unzipped into `tools/platform-tools/`.

Commands are PowerShell, run from the repository root, with `$adb = "tools\platform-tools\adb.exe"`.

1. **Install 1.1.116 from Google Play through the Aurora Store.**
   1. Install Aurora Store from its official source (https://gitlab.com/AuroraOSS/AuroraStore) and finish its setup.
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
- `server/WitcherRevival.Server/`: the game server.
  - `Net/`: protocol handlers, player state, world, story, tasks.
  - `Admin/`: the operator panel.
  - `Story/`: season 1 story data.
  - `tasks/` and `news/`: default content.
- `server/connection/map-road-fixture-01/`: the OSM tile service, placement service and index builder, with their tests and the technical record `OSM-LIVE.md`. `connection/map-tile-fixture-01/generated-terrain01/` holds the flat terrain tile the tile service serves.
- `server/story-1.1.116/`: the generators for the story and bestiary JSON. They need the original game assets.
- `server/contract-1.1.116/`: per-RPC protocol coverage and the static-data catalogue for 1.1.116.
- `server/tests/`: backend integration tests. `server/dev.py` expects the Linux toolchain layout.
- `tools/client116/`: the client builder (`build_client.py`), manifest editor (`axml.py`), pack extractor (`extract_packs.py`) and in-game hook (`hook.js`).
- `tools/restart.py`: one-command start/restart of everything, including the operator panel.
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
- **Villainser** did a large part of the work in this project. The 1.1.116 server, map services, story and contract tools, and the ported client fixes all come from Villainser's 1.1.116 reconstruction. It was forked from this project's commit `3cb353b`, is GPL-3.0-only, and is used with permission; see `server/LICENSE` and `server/upstream-provenance.json`. Some copied documents link to that project's own docs, which are not included here.
- The Earcut triangulation port is under the ISC licence; its notice is kept in `server/connection/map-road-fixture-01/osm_area_geometry.py`.
- Map data is © OpenStreetMap contributors (ODbL 1.0). Indexes and tiles generated from it are derived from OpenStreetMap.
- Frida Gadget and uber-apk-signer are downloaded at build time and are not included.
- This project is not affiliated with CD PROJEKT RED or Spokko. No original game files are included; you provide your own installation.
