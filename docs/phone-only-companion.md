# Phone-only play: the companion app (design)

Status: design, decided 2026-10-05. Nothing in this document is implemented yet.

## Goal
A player with only a phone downloads one app from this project's GitHub Releases. The app:
- walks them through installing the game legally;
- builds the playable client from their own installation;
- runs the server on the phone.

Players who want multiplayer can switch to a shared server. Server fixes and balance changes ship as app updates; the game APK is never touched again after the first install.

**The game itself is never distributed.** Its APK, native libraries and assets belong to CD PROJEKT RED/Spokko. Releases contain only this project's code, plus Frida Gadget.

## Architecture
**Companion app** (Kotlin, own signing key, neutral name, non-affiliation note):
1. **Guided legal install.**
   - Install the Aurora Store from its official source, then deep-link to the game.
   - The player picks *Manual download → 300085*.
   - The app checks the installed version and that it carries the Play signature.
2. **On-device adb.** The app pairs with the phone's own *Wireless debugging* (Kadb or libadb-android), with no PC:
   - `pm install -i com.android.vending` with the installed splits, so Google Play delivers the additional data. The player then opens the game once.
   - `bu backup -noapk com.spokko.witchermonsterslayer`, confirmed on screen, then stream-extract the 26 asset packs. This is a port of `tools/client116/extract_packs.py`.
3. **Client build on the phone.**
   - Ports of `tools/client116/build_client.py` and `axml.py`: merged APK, manifest patch, Gadget, hook.
   - Signing with apksig and a persistent key the app generates. Losing the key means an uninstall, which wipes game data.
   - Uninstall the Play copy, then install through PackageInstaller.
   - The inputs are cached, so the app can rebuild when a client fix ships.
4. **Server as a foreground service.**
   - A "Play" button starts the service, then launches the game. The hook always connects to `127.0.0.1`.
   - The server is the same project, published as a fully static `linux-musl-arm64` NativeAOT executable. No ASP.NET Core runtime pack exists for Android's bionic libc. It ships as `lib*.so` inside the app and is started by the service.
   - Phone defaults:
     - workstation GC;
     - data under the app's `files/`;
     - log to a file;
     - the operator listener off or protected by a random key, since any app on the phone can reach loopback ports.
5. **Map services.**
   - A bundled static Python (python-build-standalone, musl aarch64, with sqlite3 and R-tree support) runs the existing tile and placement scripts unchanged.
   - Index building has to be ported, because pyosmium cannot load into a static Python.
6. **Region picker.**
   - Lists the regions in Geofabrik's `index-v1.json`.
   - Shows the PBF download size and the projected index size against free space. Israel was a 120 MB PBF and became a 232 MB index, so the projection is about 1.9× the PBF size.
   - Downloads the PBF, then builds the index on the phone.
7. **Solo or shared.**
   - In shared mode the app relays the game's connections to a remote server: first a friend's PC over Tailscale, later the internet with TLS, using the reconstruction's transport in `server/WitcherRevival.Server/Transport/`.
   - Progress moves between servers through the server's `/api/profiles` admin API.
8. **Self-update** from GitHub Releases, carrying the server and map services.

## Milestones
- **S1, the go/no-go spike.**
  - Build a static musl NativeAOT probe in an arm64 Alpine container. It runs Kestrel `/health` and a TCP echo on loopback, does SHA-256/HMAC/RNG, a file lock plus a temp-file-then-rename write, and a source-generated JSON round trip.
  - Run it from `adb shell`, then started from an app's extracted native-library folder.
  - Pass:
    - it serves on loopback;
    - it survives 15 minutes;
    - there is no `SIGSYS` or `avc` denial;
    - it exits on force-stop.
  - Fallback: a bionic NativeAOT build with a rewritten HTTP host.
- **S1b:** count the server's NativeAOT warnings.
- **S1c:** with an on-device adb app, prove `bu backup` and `pm install-create -i com.android.vending` work without a PC.
- **M1:** make the server NativeAOT-clean (source-generated JSON, named records); verify with `server/tests` against a native build.
- **M2:** a companion skeleton. The service runs the server and the map services; "Play" launches the game.
- **M3:** the setup wizard, from the Aurora walkthrough to installing the client.
- **M4:** the region picker and the on-device index builder.
- **M5:** the shared server over Tailscale, plus export/import.
- **M6:** internet hosting over TLS, and release CI. CI builds on arm64 and publishes the corresponding source and licence bundle for each release.

## Licensing obligations for releases
- GPLv3: link each release to its exact tagged source, including the build scripts and flags. Reconstruction-derived files are GPL-3.0-only.
- Bundle licences and notices for:
  - Frida Gadget (LGPL-2.0 with the wxWindows exception), plus its version and source;
  - apksig (Apache-2.0);
  - Kadb (Apache-2.0) or libadb-android (GPL option);
  - .NET, musl and OpenSSL, which are statically linked;
  - Python (PSF).
- OpenStreetMap: show "© OpenStreetMap contributors" visibly. Generated indexes are ODbL derivative databases.
- Risk: new players need Google Play, via Aurora, to keep serving 1.1.116 (300085) and its asset packs.
