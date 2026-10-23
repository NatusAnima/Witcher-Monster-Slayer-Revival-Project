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

## 0.2.0, third batch (2026-10-09): PR #3, weather, bags, What's new, place mix
Plan: `C:\Users\iyave\.claude\plans\there-have-been-quite-eager-pebble.md` (Phase 1 done here; Phase 2 = debug tools and the quest audit/runner,
Phase 3 = central-server and later-content research).
- **PR #3 (MasterpiecePL, memory + Android 12+ hook):** merged locally as `6c1d73f` (their squash, author kept, no Claude lines) plus `f8c6546` (ours: tiles
  are clipped in Mercator, the test fakes take `clip`, one in-place game update: the PR's REHOOK and `phone_rehook.py` dropped, its "hook changed"
  check kept as `ClientBuildService.hookChanged`). Pushed to `main` 2026-10-09 (with the 0.2.0 commit `a494f3c` before them). GitHub cannot mark
  the PR merged (different SHA): close it by hand with a link to `6c1d73f`. Everything below is commit `0fbde39` (2026-10-10, not pushed).
- **Weather:** the app and `restart.py` pass `--Weather:Url https://api.open-meteo.com/v1/forecast`. The runtime ships Alpine's `ca-certificates-bundle`
  as `etc/ca-certificates.crt`, and the server gets `SSL_CERT_FILE`. Tuning `weather.real` turns it off. Checked under qemu with the phone build: with only
  the bundled roots Open-Meteo answered (rain); with no roots, Clear. **Superseded in 0.3.0:** on the phone it never worked (no resolv.conf for
  musl); the app now relays the request, see the 0.3.0 section.
- **Alchemy "Add Station":** the client offers brewer ids 2 and 3 (`AlchemyBrewingPanel`: 1 infinite, 2 small, 3 big); ours were 1201-1203. Now 1/2/3;
  saves with 1201-1203 come back as 1-3 (`EnsureBrewers`); the bundles keep ids 2202/2203.
- **Bags:** bundles 95-99, one-time, in Equipment → Items (the client has no bag group). The client texts give the names and sizes (Bag 50, Small pouch 50,
  Medium-sized pouch 100, Spacious pouch 200, Set of saddlebags 400); the wiki gives the prices (500/500/1000/2000/4000). A bag item (type 11) adds its
  amount to the inventory size (`PlayerInventory.TryAddItem`). `Economy.BagSize` = Tuning `inventory.startSize` (200) + bags bought, at most 1000; RPC 5
  sends it. `inventoryIncrement` 50 is the shop's amount label for every bag. Space is counted as the client counts it: all stacks, stations and crafts
  (`SocialPolicy.Occupied`). A full bag refuses shop items (as `CanBuyThisShopItem`) and the pre-fight purchase, cuts fight and nest loot to the free
  space, refuses herbs when nothing fits and gifts that do not fit. Story, task, level-up and crafting rewards are always given. A profile that is
  already over 200 (nothing was limited before) gets no loot until it buys bags or uses items.
- **What's new:** `GatekeeperNewsLoader.Fetch` uses System.Net `WebRequest.CreateHttp(string)` (RVA 0x20A4A28), not UnityWebRequest, on
  `https://gatekeeper.test.dev.spokko.com/news/<lang>`, and the hook refuses port 443. hook.js stage "news requests" rewrites `https://gatekeeper.*/news/`
  to `http://127.0.0.1:18080/news/`. It reaches players with 0.2.0's in-place game update. **Not run on a device yet.**
- **Patch notes in What's new:** `server/WitcherRevival.Server/news/release.json` (the feed format) holds the update's own notes. The app copies it over
  `state/news/release.json` at every start (`restart.py` too). `NewsFeed` puts its items first in every language and features its item unless the
  owner's feed features a newer one. **Each release:** a new id, `group_id`, date and text.
- **Place mix (Tuning → Places, replaces `woods.maxPlaces`):** every candidate has a ground (woods, then water within 60 m, then parks, then urban within
  60 m of a building, then paths). The default draw takes places by smooth weighted round-robin over the shares (paths 40, parks 25, woods 15, water 10,
  urban 40). A ground with no point left at the spacing gives its share to the rest. Also: places per cell (24, 4-48), spacing (50 m, 30-200) and street
  clearance (12 m, 10-30). Below 13 m, places line both sides of streets, 13 m from the middle: residential, living-street and service streets
  everywhere, tertiary and unclassified ones only within 60 m of a building (a country road often has no pavement). A scheduled placement policy keeps
  its own rules (20 m, no street places). `PLACEMENT_VERSION` 5, golden changed on purpose. The Python `Tuning.SETTINGS` and C# `WorldTuning` hold the
  same keys (`test_place_settings_match_the_placement_service`).
- **Why streets:** the maintainer's report (2026-10-09): in towns monsters spawn mainly in parks and must also spawn in plenty on ordinary streets.
  Towns have few path candidates (sidewalks are rarely mapped, and a 20 m clearance removed everything along a street), so before this they ran out
  of everything but parks; the first try (the mix with the 20 m clearance, urban 10) hardly changed them. Measured with `tools/place_mix.py` (Israel
  index, a spot's cell and its 8 neighbours; places per cell and the biggest shares):

  | Spot | Before | Mix only (20 m, urban 10) | Now (12 m, town streets, urban 40) |
  |---|---|---|---|
  | Tel Aviv centre | 6.7: parks 50%, urban 42% | 7.1: parks 52% | 18.6: urban 68%, parks 25% |
  | Jerusalem centre | 9.6: parks 42%, woods 23% | 10.9: parks 35%, woods 30% | 23.3: urban 61%, parks 18% |
  | Kfar Saba (suburb) | 13.7: urban 61%, parks 26% | 13.8: urban 56%, parks 30% | 23.2: urban 69%, parks 19% |
  | Ein Kerem (forest edge) | 17.8: woods 68% | 23.2: woods 74% | 23.6: urban 43%, woods 38% |
  | Haifa (coast) | 18.6: parks 60% | 19.8: parks 53% | 21.7: parks 41%, urban 41% |
- **Monsters per cell 6-36** (was 6-18): `WorldPolicy`, `WorldSpawns`, the World page (input, hint in 10 languages), and the Tuning page, which saves it
  through `/api/world`. A cell needs the places for them (`test_world_density_reaches_its_maximum_where_a_cell_has_the_places`, 48 places).
- **Nest gold** (Tuning `nests.gold`, 50): the nest window and the payment both use it.
- Not on the Tuning page, on purpose: the friend-gift numbers (they only matter between players on one server), and the nest minimum level, the nest
  daily limit and task gold (the client reads these from static data, so a change would need a static-data rebuild).
- Tests (Windows): the full server suite (290) has only the known Windows-only failures; the map tests, `tools/client116` tests and the hook bundle pass.
- Built 2026-10-09 22:54 (with the street places): runtime rebuilt, `local/release/Witcher-Monster-Slayer-Revival-0.2.0.apk` (same release key,
  `apksigner verify` ok), **installed on the Xiaomi 22:55** at the maintainer's request (`adb install -r`, data kept). The previous build is kept as
  `...-0.2.0-second.apk`. Device checks: "Update the game" offered (the hook changed), What's new, Add Station, a bag purchase and the bigger
  inventory, real weather, monsters on town streets. The maintainer confirmed them on 2026-10-10 ("the monster spawning is much better").

## Phase 2 (2026-10-10): debug tools, quest audit and runner
Uncommitted. Plan §5 and §6 (same plan file).
- **Debug tools (Players → a profile → Debug tools):** `Admin:DebugTools`, off by default; the app and `restart.py` turn it on (the phone is the
  player's own server). `POST /api/profiles/{id}/debug {action, ...}` (`Admin/PlayerDebugRoutes.cs`, `Net/PlayerDebug.cs`): `gold`, `level` (1-40:
  experience at the level's threshold, 5 skill points per level up or down, no level-up rewards), `skillPoints`, `allSkills`, `item` {kind, item,
  amount} (stacks, lures, friend packs, summoning scrolls, swords and armours, stations 2/3; the starting sword and armour stay), `invincible` and
  `oneHit` {on}, `questsHere`. Works while the game runs: `LocalProfileStore.DebugUpdate` saves without any task or trinket counting it and marks
  the profile `Debug` (a badge on the Players list); every change has a `profile-debug-*` receipt and backup, so History restores it (offline).
- **Live changes:** the game turns every message into a signal, and the subscribers of GetPlayerInfo 3 (orens, experience), GetInventory 5, GetKnownRecipes
  6, GetEquipment 9, GetSkills 63, GetBrewers 69 and GetPlayerModifiers 91 replace their state, so the server pushes those replies. Pushes queue
  until a session has passed ResolveRewards 119 and go out after its next reply; a boot (115) drops them. **That the client takes them unasked is
  static analysis only:** the device test decides; otherwise the changes show at the next start.
- **Invincibility and one-hit kills:** player modifiers 901 and 902 (the client's unused slugs `modifier_maidens_skin` and `modifier_dead_honey`) with
  effects ImproveHealth 40 and ImproveAttackPower 41 at power 100000 when a fight starts. The client applies player modifiers to world, story and nest
  fights (`PlayerModifiersModule.GetActiveEffects`). They are static-data rows (`player_modifier_to_effect` was empty before); AddPlayerModifier 90
  refuses them, so gameplay never grants them. **Device checks:** they work in a fight, and the effects panel shows them without breaking.
- **Quests next to me:** the places of the active story steps and the givers of the quests on offer move to the playable places nearest the latest GPS
  fix (the map's centre without one), with new place ids; the game shows them after a restart (it keeps the places it has). Refused while no quest has a
  place or no map is loaded.
- **Quest runner (Debug tools → Quests):** every quest in story order (tutorial "Final Exam", "Winged Bandit", "A Joint Venture",
  the 12 of season 1) with its state and next step (`QuestRunner.cs`, `questStep` action). A next step names its trigger
  ("Talk to", "On the map:", "Beside you:", "Journal:", "Wait 12 h") and says "(not shown yet)" when the player cannot see
  it: that is the live trigger check. "Complete" sends the step as the game would (the graph output with its facts, through
  the RPC 57 handler, so rewards, tasks and trophies count it), or moves the story clock on for a wait; the game shows it
  after a restart. Season 1 steps are the story's walk-throughs (now loaded by `StoryEngine.WalkOf`); the earlier quests
  follow their stages with the facts their tests send. With "Bring quests next to me" the maintainer can play every quest in
  order beside the phone. `test_the_quest_runner_plays_every_quest_in_order_from_a_new_profile`: from a new profile, all 15
  quests, every next step shown before it is completed.
- **Quest audit against the client** (`server/story-1.1.116/story_audit.py`, maintainer tool, needs the packs):
  `python season1_graphs.py --assetpacks ~/witcher_1.1.116_packs --output <x>/season1-graphs.json`, then `python story_audit.py
  --graphs <x>/season1-graphs.json --catalog <assets/aa/catalog.json of local/client/witcher116.apk>`. It checks the shipped story
  against the 1.1.116 client's own graphs: every quest offered and finishable and every node able to show by the facts the
  graphs set (each condition atom on its own), every output the client sends known, every walk-through fact set by its graph,
  every fight and scene monster with a row (story, inherited or world), the bestiary credit and gold notices, the queued nodes,
  and journal buttons sent without an instance. `test_story_audit.py` is its self-check.
- **What it found (2026-10-10):** the story was built from the 1.3.102 graphs. The 1.1.116 ones reproduce it exactly except:
  the firefly nest (client announces 50 gold, we paid 100; the walk sent f175 = 100), the mushroom hunt's forktail (the client
  fights a forktail, world row 138; we credited the small draconid and paid none of the announced 50), and two output
  names. Fixed by regenerating from the 1.1.116 graphs: `season1_story.py` now counts world-bestiary monsters, keeps the
  1.3.102 name `mushroom_timer_start` (saved progress uses it; `OutputAliases` answers both) and writes LF; the M01 sheet
  rows it needs are now `m01-season1.csv` (recovered from the story file). Also: s01hq02's two notebook items both end with
  `notebook` and send no instance, so the server dropped the press (the facts still moved the quest on); `Resolve` now
  takes such buttons of one quest as one step, and the season 1 playthrough checks that every walked output is recorded.
  Left as warnings: the blacksmith's graphs queue nodes 383, 467, 469 and 471 (after-quest and "alarmed" scenes) that the
  story does not serve; the quest goes on through Lothar's forge, so nobody is stuck.
- **Tasks:** types 8 (skills), 9 (quests) and 13 (story outputs) now have a test; every kill task's species spawns in the
  world or falls in a story fight, and every story trinket's outputs exist (`test_tasks_every_kill_and_story_target_can_be_met`).
  Five trinkets (20004-20008) are the mushroom contest's placings, which exclude each other.
- **Not done from plan §6:** walk-throughs for the alternative endings (29 pay a reward; trinkets 20004-20010 need them; the
  audit only shows they can be reached), a dashboard audit page (the audit needs the client's packs, so it stays a script),
  and the timed-event tools (a task-clock offset, staging an event); the only event ended on 2026-10-08.
- Tests: `server/tests/test_debug.py` (7), `test_story_audit.py` (3). Full server suite on Windows (300 tests, 2026-10-10): only the
  known Windows-only failures (the 17 above, and `test_trinket_repair`, which cannot import `fcntl`).
- The dashboard's "Proces gry" (shown as "Game process") was the .NET server's own memory, not the game's; it is now "Serwer gry"
  ("Game server") in all 10 languages. For the 5-7 GB report (plan §1b) the next step is a report zip taken right after a
  big-region reload: `events.log` already samples every service's memory every 15 s.
- **Field reports 2026-10-10** (`reports/`, not tracked):
  - *Monaco "map not loading" (report 000434):* the builds worked (Monaco 1 s, Liechtenstein 4 s; Israel 371 s on 10-08). The game
    stood at 43.71 N 7.26 E (Nice, outside the Monaco extract), so there was nothing to draw; the tile service answered every tile
    with 503 ("try again") and logged ~1,100 bare `osm_live_prefetch_failed LookupError` lines, which read like a failed
    conversion. Now an offline tile outside the map is served empty (200) with one `osm_live_outside_map` line
    (`test_offline_tiles_outside_the_map_are_empty_and_said_once`). An in-app "you are outside your map" notice is not built.
  - *Good Money's giver never showed (report 120942):* the server served Margit at every full map load (RPC 40 `givers=1`), but
    the client draws a giver only within 350 m of the player (questOnMapHideDistance), and the server did not know where the
    player was: the hook's GPS collector has never captured a fix on this Xiaomi (Android 11; none in any log, before or after
    PR #3), so givers stood 80-300 m around the centre of the 3×3 loaded cells, up to ~700 m from the player. Fixes: the
    server keeps the position from the game's own weather request (RPC 67: at boot and every few minutes; memory only, never
    logged) and uses it when there is no GPS fix and it lies within 1 km of the loaded area (`PlayerPositionIn`: story places,
    "Bring quests next to me", relocation); a giver of a quest not yet started that is farther than 350 m from that position
    gets a new place at the next full map load; `gps.js` polls LocationManager on every Android version (it was Android 12+
    only) and makes no Java calls while Unity is not ticking (in the background). Tests:
    `test_a_giver_stands_within_sight_of_where_the_game_says_the_player_is`, the weather step of
    `test_quests_come_next_to_the_player`. The hook change reaches the phone through "Update the game".
  - *Memory (7,115 samples, 10-07 to 10-10):* our processes are small. Game server: median 12 MB, p95 78, peak 116; tiles 17/30/50;
    placement 18/24/29; the map builder ~810 MB, peak 901 MB, only while building Israel. In the 7 "low memory" samples ours used
    ~110 MB. The dashboard's 5-7 GB is the whole phone (7.8 GB, 1.2-3.3 GB available): mostly the game (RSS 0.75-1.0 GB, PSS
    up to 1.16 GB) and other apps. Game exits: one SIGSEGV 3 s after a start (00:25, 2 s after the previous game exited,
    2.1 GB free; no backtrace, the crash buffer is read 20 s after start), one kill for background CPU above 2% (01:21, after
    18 min in the background), the rest swipes and cleaners. No memory change needed in our services.
- Builds: 2026-10-10 11:50 (debug tools, quest runner and audit fixes; kept as `...-0.2.0-fourth.apk`) was installed on the
  Xiaomi at 12:04 and produced report 120942. 2026-10-10 12:36 adds the field-report fixes: `local/release/Witcher-Monster-
  Slayer-Revival-0.2.0.apk` (runtime rebuilt, same release key, `apksigner verify` ok; its hook differs, so the app offers
  "Update the game"). **Installed on the Xiaomi 2026-10-10 13:07** at the maintainer's request (`adb install -r`, data kept);
  the maintainer tests the quests. Full server suite (301 on Windows): only the known Windows-only failures; map
  tests pass. Device checks: after "Update the game", `game.log` shows `gps counts captured=` above 0; Good Money's giver
  stands near the player after a restart (or after "Bring quests next to me"); the Debug tools checks above.

## Season 1 rules (2026-10-10, evening): prerequisites, trinkets, broken steps, time for quests
Uncommitted. From the maintainer's quest test on the 13:07 build and their list of how each quest starts and what it awards.
- **What the client does (read-only, 1.1.116):**
  - The quest book lists a quest when its row condition and its root's hold on the **phone's facts**
    (`StoryModule.RefreshQuestGivers` after every story step). Server facts reach the phone only at game start: the fact module
    reads the boot batch once (`Synchronize<GetAllFactsResponse>` is a one-shot read; nothing requests `GetFacts`).
  - Givers come only with the map-cell reply (RPC 40), which the game asks for again and again in a session.
  - Every map node carries a display mode the server picks (`PoiDisplayMode`). We sent Normal for every season 1 node.
    **Collecting (7)** is drawn beside the player after 200 m of walking and hides when used (`CollectingQuestPoi.OnUpdate`).
  - The effects panel hides a modifier's timer only for a negative expiry; at 0 it counted down to 1970.
  - `AstroConditionNode` (full moon, sunrise, sunset, day) reads the phone's own sun and moon, not the server's.
- **Prerequisites** (`season1_quests.py` "criteria"):
  - Evil Never Sleeps and To the Rescue need only "A Joint Venture" (f100≥4).
  - Pride, the Dark Side and What Lurks need Good Money (f1001, f1003).
  - Sins needs Pride's completion fact (f178), Mushrooming needs Sins (f179), Wisp needs What Lurks (f184).
  - Intruder keeps the game's own rule (f31≥5: the five main quests; the maintainer chose it over "after Mushrooming").
  - Monster Slayer opens on a server trigger (f1010). Sword in the Stone keeps f46.
  - Each quest's completion fact (177-188, "done") is also saved by the server when it records the ending, together with
    fact 31 = finished main quests (`StoryEngine.Advance` → `Step.Facts`), so the next game start is right even when the
    ending's step did not carry them.
- **Monster Slayer trigger** (`PlayerService.TrollFight`, server facts 1010/1011, unused by every graph):
  - It applies after Good Money (fact 1000 = 1).
  - A won fight against a Rock Troll (world monster 22, world or summoned) starts the count, and each lost one adds 1.
  - At Tuning "Monster Slayer: troll defeats" (Story group, default 3) the quest is offered and Grub is placed beside the player.
  - The game shows it from its next start.
- **To the Rescue and the mushrooms are Collecting nodes:**
  - Kienan, the giver, is placed as before and sent with display 7.
  - `s01mq05_mushroom` is now one node beside the player, instead of five fixed spots that never disappeared (so only the
    pick-3 event ever came). The events stay queued nodes the game fires at picks 3, 11, 20 and 28.
  - `Node.BesidePlayer` (queued or Collecting) keeps them out of placement, relocation and "Bring quests next to me".
  - A started quest's hidden relocation giver always goes out as Normal, so Kienan's cannot come up again beside the player.
  - **Device check:** a Collecting giver (Kienan) works the same way.
- **Lothar's map:**
  - Six graphs queue the map (node 399), and the game opens a queued node only if it already has it. It never had it: 399 was
    served only at f46=1, which the map's own graph sets. So the map stands invisible beside the player from Good Money until
    Sword in the Stone starts.
  - **Superseded in 0.3.0:** nothing starts `s01hq03_map_payment` ("payment"); the sale ends in the map graph's
    `map_bought`, which now costs the 500 orens (see the 0.3.0 section). The two lines below were wrong.
  - Lothar's `s01hq03_map_payment` sends "payment" (no node): the server takes 500 orens (`PRICES`), and the reply's gold
    (−500) is a change the game adds.
  - The blacksmith graph's direct sale path (dialogue sets f118 = 1, then queue 399) needs no payment step.
- **Intruder's endings:** the ending graph (`s01mq06_vogt_02`) sends one of eight outputs. Five were not marked as endings
  (`reward`, and the `_dhl` twins sent when Dehael was not advised, f13 ≤ 0), so those playthroughs could never finish.
  All eight end the quest now (500 XP).
- **Curse "indefinite":** permanent modifiers (the curse, the debug ones) go out with expiry −1 (`PlayerService.Expiry`).
- **Real timers** (the maintainer's choice): Vesemir wakes after 12 h, the mushroom contest lasts 24 h. AddPlayerModifier keeps
  the graphs' own times (the 24-minute LAB pacing of 30 September is gone). The runner's "Complete" moves the story clock and
  now says "Wait 12 h".
- **Trinkets:** all 25 of the client's are in `tasks/trinkets.json` (12 new, 20014-20025):
  - Good Money, A Joint Venture (kind 9 on quest 146, counted from its "joint_venture" reward key), Pride.
  - Something More (curse lifted), Cursebreaker (amulet thrown far, 1043, and either ending).
  - The Werewolf's Lot spared and killed, the Mushroom Sentinel (the Emlyn event's leshen).
  - Dehael's Pride: the refusal endings; the bloody one is `bad_reward_dhl`.
  - The season journal (all 12 quests), and The Best Vintage (level 1: every player).
  - Saved outputs, finished quests and levels catch up at the next saved action.
  - The app and `restart.py` copy `trinkets.json` over the working one at every start (rows are append-only; staged catalogues
    are applied only by the Linux maintenance script).
- **Time for quests** (Players → Debug tools): as on the phone, full moon night, dusk, dawn, night or day (`sky`, in memory per
  player).
  - The weather reply carries it as code + 16 × (1 + mask), and hook.js's "quest sky" stage strips it and answers
    `AstroConditionNode.HasDesiredValue` (0x17E1FAC; condition at +0x44: full moon 0, sunrise 1, sunset 2, day 3).
  - It applies at the game's next weather request (about 5 minutes) or next start, and needs the new hook ("Update the game").
- **Leshen moss (the hound "did not spawn at all", maintainer, 21:59):**
  - The hound, the Dark Side tracks and the Sins tracks used the only settings the client has for them,
    `s00/prolog/footprint_placeholder` (from the install-time pack in the APK), whose `PrefabPath` is empty, so as Normal nodes
    they drew nothing.
  - They are now **Hunt (4)** nodes: `HuntQuestPoi` has its own default view (the prologue griffin's shrinking search circle)
    and fires the graph when the player reaches it. `Node.BesidePlayer` covers only Collecting, so hunt nodes keep their places.
  - `test_season1_the_leshen_hound_and_the_tracks_are_hunt_circles`.
- **Will o' the Wisp black screen (fixed, confirmed by the maintainer 2026-10-10 ~23:00):** a game bug fixed in 1.2.
  - `adb logcat` (tag Unity) while the stump was tapped: "Load Enviro (LoadEnviroNode) in s01hq04_stump graph doesn't have
    following node connected". The graph walks on through the node's `GetNextOutputPort` ("NextNode"), but the stump and catch
    graphs (the only ones in either story pack) hang their next step on its "ResultNode" port.
  - hook.js "graph wiring": before the game reads a LoadEnviroNode's next port, ResultNode connections move onto NextNode.
- **Wisp treasure chest stuck after opening (fixed, needs the device check):** logcat 23:29:48: "Investigation
  (InvestigationNode) in s01hq04_treasure graph doesn't have following node connected".
  - `TraversableGraph.GoToTheNextNode` gives the next port's nodes to `NodeSwitcher.GetToTheNextNode`, which runs action nodes
    (`IActionNode`) on the spot and steps only to another node. The treasure's investigation leads to `AddExpiringEffect` alone;
    its "Fadeoutblacktransition" runner (QuestEndRequest "treasure", fact 186, fade out) has nothing leading in. In the catch
    graph the investigation leads to both.
  - hook.js "graph wiring" now also connects, before an investigation's next port is read, a "Fadeoutblacktransition" runner
    with nothing leading in. A scan of every behaviour graph in both story packs found this the only flow dead end
    (`dead_ends.py` in the session scratchpad; the blacksmith's orphans are unreachable leftovers).
  - The same graph adds the wisp's timer (effect 8, 900 s in the catch graph) again with **0 s** to end it, and the server
    stored 0 as permanent. Now only a negative time is permanent and 0 ends the effect (`HandleAddPlayerModifier`,
    `test_season1_the_wisps_treasure_ends_its_timer`). The maintainer's stuck run already saved effect 8 as permanent;
    tapping the chest again sends the 0 s, which removes it.
  - Its first-time branch (f226 = 0) sets 226 and leads nowhere. Play never takes it, because the nemeton, stump and catch set
    226 first. The nemeton's quest-runner walk now sends 226 too, so skipping those steps with "Complete" cannot reach it.
- **Mushrooms never appeared (no change; the maintainer used fake GPS):**
  - `PoiModule.SetActiveQuestNodes(newNodes, trackedQuest)` (0x1900C48) activates only the tracked quest's nodes. A quest is
    tracked by its start graph (`SetTrackedQuestNode`; the Mushrooming's is `s01mq05_madman`) or in the quest window, so tracking
    another quest hides the mushrooms (the walkthroughs say the same).
  - `CollectingQuestPoi` shows when its instance's walked distance reaches 200 m. `PlayerController` fires
    `DistanceWalkedSignal` per 100 m that the player's figure moves on the map. The instance (and its distance) is rebuilt
    at every story step reply, so each pick needs another 200 m.
- **Quest rewards = the maintainer's reward list (2026-10-10, late evening).** Season 1 in `season1_quests.py` "end", the
  tutorial and prologue in `Reconstruction.RewardFor`. Changed:
  - Final Exam: nothing (was 1500 XP and 300). Winged Bandit: 250 XP and 45 (was 1000 and 100). A Joint Venture: 275 XP
    (was 60 orens).
  - Good Money: 250 XP and 40 (was 1200 XP). Sword in the Stone: 150 XP and the Dawnbringer (was 500 XP).
  - Will o' the Wisp: 100 orens at the treasure (as well as 250 XP).
  - Monster Slayer: 300 XP; 35 orens on `won`, the stones on `grey_rocks` (the graph gives them as a quest item).
  - Pride: also Necrophage Oil (302) and a Grapeshot (402).
  - Sins: 60 orens on every ending, and 750 XP with Hermit's Armor for the curse (killing the striga stays 500 XP).
  - Intruder: 2000 XP and 100 orens on all eight endings.
  - Unchanged: To the Rescue, Evil Never Sleeps, What Lurks, the Dark Side, the Mushrooming.
  - Coin notices inside quests (fact 175 + `REWARD_GOLD_COINS`: the journal, the nemeton, the figurine, the forktail, the
    mushroom treasure) are paid on top by the outputs that show them. Two notices belong to graphs no node serves
    (`s01mq03_no_striga`, `s01mq06_massacre_02`).
  - An output pays once. Endings already reached keep what they paid.
  - New players now leave the tutorial at level 1 (the exam made them level 2). The tests that used the exam to level up
    now use the griffin, a wraith and the gargoyle king (1100 XP).
  - The maintainer expects to change amounts and items later. Today that means editing those two places and regenerating
    the story; making them editable from the dashboard was offered, not built.
- **Sins not offered:** now on f178, plus the server-saved completion facts; unconfirmed on the device.
- **Not served, as before:** the Intruder's 24-hour timer graph (`s01mq06_timer`, fact 33), the troll attack (474), the
  blacksmith's after-quest scenes (383, 467-471).
- **Builds:** 21:34 (`...-0.2.0-sixth.apk`), 22:07 (`-seventh`), 22:18 (`-eighth`: the Wisp stump wiring, installed and
  confirmed by the maintainer).
  - **2026-10-11 00:02:** `local/release/Witcher-Monster-Slayer-Revival-0.2.0.apk`, with the chest wiring, the 0 s effect and the
    reward list. Runtime rebuilt (its client builder carries the new hook), release key, `apksigner verify` ok. The hook
    differs, so the app offers "Update the game". **Not installed yet:** the phone had left adb.
  - Device check: install, "Update the game", restart the game, tap the treasure again. The chest should fade out and end
    the quest with 250 XP and 100 orens. The wisp's effect should be gone, and logcat (tag Frida) should show
    `graph wiring fixed: Investigation FollowingNode -> Fadeoutblacktransition`.
  - `lintRelease` stops on its only error, `companion/local.properties`' unescaped `G:` (the machine's own file, unchanged since
    10-05), so the APK was built with `assembleRelease` as before.
- **Tests:**
  - `server/tests/test_season1.py` (9): the order of offers, completion facts, the map sale, the mushrooms, the hunt circles,
    the troll trigger, a hidden giver kept Normal, a permanent effect without a timer, the wisp's timer ended by 0 s.
  - The reward list changed the expected amounts in the exam, griffin, Joint Venture and Good Money tests. The shop test now
    sets a 300-oren purse in the profile, and the level-up and skills tests reach level 2 with three prologue rewards.
  - `test_tasks_season1_trinkets_follow_endings_and_catch_up`, `test_time_for_quests_rides_on_the_weather`.
  - The playthrough runs in an order the prerequisites allow and checks facts 177-188 and 31.
  - Full server suite (310 on Windows): only the 18 known Windows-only failures. `story_audit.py`: 0 errors, the same 4 warnings.
    `tools/client116` tests and the hook bundle compile pass.

## 0.2.1 (2026-10-11): Report on GitHub, in-game notes
- **Published:** `0.1.0-alpha` (release) and `0.2.0-alpha` (a **pre-release**: the 00:02 build, without Save Data). The app's update
  check reads `releases/latest`, which skips pre-releases. Remote tags carry no `v`; `Updates.newer` ignores the `-alpha` suffix.
- **Report on GitHub (`DebugInfo.issue`):** signed out, GitHub's sign-in carries the whole link in `return_to`, and with the full
  phone header (~2,000 characters) signing in ended on a 500 at `github.com/session`. The issue now gets a two-line summary
  (~600 characters). The button first makes the same zip as Send a report (after a "this goes public" dialog), and the issue
  names the file to attach. Tested on the Xiaomi: sign-in with 2FA lands on the prefilled issue, and the zip is in Downloads.
- **Version 0.2.1** (z: app only). Against 0.2.0-alpha the runtime differs only in `defaults/news/release.json` (hook bundle and
  Gadget byte-identical), so its players keep their game; 0.1.0 clients (`builtFor` 0.1) are still offered "Update the game".
- **What's new:** `news/release.json` holds the 0.2.1 notes, everything since 0.1.0 (one item, plain ASCII, 4,045 characters:
  without a `{{img=` tag the news window is one TMP text, so no `<`). `test_news` passes. The posting copies (GitHub, Discord
  in six messages under 2,000 characters, Reddit) are in `local/release/notes-0.2.1/`.
- **Build:** runtime rebuilt, `local/release/witcher-monster-slayer-companion-app-0.2.1-arm64-v8a.apk`, installed on the Xiaomi.
- **Server tests on this PC:** `server/.toolchain` is not installed, so `dev.py` refuses to build. The system SDK works
  (`C:\Program Files\dotnet`, 10.0.401): set `dev.DOTNET` to it before importing the tests.
- **Open, Save Data restore** (`MainActivity.onActivityResult`, request 2): it deletes `state/profiles` before reading the zip (a
  wrong or empty file wipes the progress and still says "restored"), the running server keeps the profile in memory and writes
  it back on its next save, and entry paths are not checked (zip slip inside the app's files). The 0.2.1 notes tell players
  to stop the server first.

## 0.3.0 (2026-10-22): the eight field reports, weather and heads
Uncommitted. Plan: `C:\Users\iyave\.claude\plans\here-are-some-issues-encapsulated-dream.md`. Version 0.3.0: hook.js changed (y), so
every installed game is offered "Update the game". Causes were found in the 1.1.116 binary with capstone (`local/il2cpp116/in`,
names from `script.json`); none of these is confirmed on a device yet.
- **Oils and skills gave no bonus:** every effect went out at apply time 1 (OnStart). `Player.Construct` (0x18B7064) applies those
  before the fight has a target or a critical-hit meter (`AdrenalineModule`, added from NotifyTargetSet), so the family oils
  (`TryToImproveAttacksAgainstFamily` 0x1B0487C), the oil skills (`HasUsedProperOil`) and every meter effect returned without a
  change. `Reconstruction.FightStart` gives effects 4, 15, 22, 23, 27, 28, 29-39, 56, 59, 80 apply time 22 (OnTargetSet, applied once per
  fight by `Player.NotifyTargetSet` 0x18BA58C). Blizzard is now effect 4, 25 meter points (59 only keeps a floor). Static data only.
  Guard: `test_target_and_meter_effects_wait_for_the_fight_target`. **Device check:** a ghoul falls faster with Necrophage Oil.
- **Nemeton stuck after completion:** with no bomb equipped EndNestCombat (53) sends BombId −1, `checked((int)ReadUInt())` threw,
  and 53 had no refusal, so the game waited for good. Now `ReadInt()`, and 53 is refused with `[0]` on any fault.
- **Lothar's map was free:** nothing starts `s01hq03_map_payment` ("payment"); the sale ends in the map graph's `map_bought`
  (node 399, output 1118; `map` is the earned hand-over, f116 ≥ 2 or f154 ≥ 2). `PRICES` is per node output
  (`s01hq01_map.map_bought`: 500), taken the first time, only when the player has it (`StoryEngine.PriceOf(node, output)`); the
  no-node price path is gone. Story JSON regenerated from `local/cache/story/` (only the prices changed); `story_audit.py` 0 errors.
- **Nemeta moved every day:** `playable_locations.py` picks a cell's anchor from its raw candidates by a hash of the position
  (`nest-v3`, no epoch), sends it every day as an extra place `lab-<cell>-<epoch>-5999`, and drops the day's places within the
  spacing of it. Kind and monsters still change daily (`WorldNests.ForCell` unchanged): the maintainer's choice. A map rebuild can
  move it. Story nemeta are givers and still follow the player (350 m).
- **Bestiary entries vanished after a restart:** the game lists a monster from the fight's start (`FightNode.EnterNode` adds it
  with 0 kills); the server saved only wins and RPC 7 dropped zeros. A lost or fled world or summoned fight, and the fights a lost
  nemeton run reached (the client sends an empty details array for the rest), now keep `Kills[m] = 0`, and RPC 7 sends zeros.
  `worldEncountered` and `SummonedMonsters` keep the encountered monster itself (a map request during a fight dropped expired
  spawns, so the win was lost). Not covered: a server restart mid-fight, a lost story fight.
- **Head reverted to the first one:** SetCustomizationHead (28) was only echoed and GetPlayerInfo always sent head 1. Now
  `PlayerState.Head` (customization_heads ids 1-3), in RPC 3 and the friends list (`FriendData.HeadId`). The client also ships
  `head_east_1` (male and female) with no row; not added.
- **Weather never worked on the phone:** musl reads `/etc/resolv.conf`, which Android lacks, so the server's lookups went to
  127.0.0.1 and every answer was Clear (all field logs: code 6; the log's `source=` only says a URL is set). The app relays
  Open-Meteo (`ServerService.startWeatherRelay`, loopback 18095, the forecast path only) and the server gets
  `--Weather:Url http://127.0.0.1:18095/v1/forecast`. The CA bundle and `SSL_CERT_FILE` left the runtime. `restart.py` (PC) still
  asks Open-Meteo directly. **Device check:** the dashboard's weather `lastFetchOutcome` is success.
- **No game without internet:** `PreGameConditionsModule.CheckNetworkAvailability` (0x199F464) needs `internetReachability` ≠
  NotReachable, then TCP to `ConnectionTester.KNOWN_HOSTS` (google.com:80, facebook.com:80); `SyncedTime` sets Initialized and
  unblocks input only after a non-zero NTP answer (`HandleTimeSyncRequests` 0x19B0D40). hook.js stage "offline play": reachability
  0 → 2, `ConnectionTest.FromHost` non-loopback → 127.0.0.1:18080, `TimeSyncTask.Run` replaced by the phone's clock (the
  server's too); `offlineHosts` (those and the NTP hosts) resolve to 127.0.0.1. **Device check in airplane mode.**
  - **The first 0.3.0 install (12:23 build) showed no monsters:** `Run` answers NTP milliseconds counted from 1900, and
    `HandleTimeSyncRequests` adds −2208988800000 (`x28`, 0x19B0DD4) before `FromUnixTimeMilliseconds`; the replacement gave
    Unix milliseconds, so the game's clock stood in 1956, before every monster's window. It now answers `Date.now() + 2208988800000`.
- **Device test 2026-10-22 (maintainer):** airplane mode, oils, Resolve, nemeta without a bomb and their fixed spot, the
  bestiary, the head and the sea all work. Two follow-ups:
  - **Hit Reflection ("Retribution") dealt no damage:** the skill (`hit_deflection`, 6) had only the unlock (50, which installs
    the deflect); the reflected share is `SwordModifiers.DeflectModifier` (+0x108, +0x60), which only ImproveDeflect (82) raises
    (`SwordModule.DealDeflectDamage` scales the incoming hit by it). Now (82, 30, OnStart): 30 % from the later wiki table (the
    pre-1.2 one gives no number); the sword module exists at OnStart. Audit of every combat effect's `Apply` (module it reads,
    with the generic `GetModule<T>` resolved through `.rela.dyn` and `ScriptMetadataMethod`): Sword, Health, Signs and Bomb3D
    effects work at OnStart (`Player.Construct` builds those modules first); the meter effects needed OnTargetSet (done); and
    TryDealFireDamage (58) builds `DealFireDamage(100, power)`, which strikes the caster's target, so at OnStart the Melltith
    sword never burned: now OnAttack (2, applied by `SwordModule.DealSwordDamage` on every hit). Every skill description's `#0`
    now has its effect row.
  - **Weather "failed-clear-fallback":** the relay answers through `adb forward` in 0.1-0.16 s with Open-Meteo's JSON; the failure
    was the airplane-mode test's, kept for the whole 15-minute period. A failed look is now retried after a minute
    (`WorldWeather.FailedRetry`), the reason goes to server.log ("Weather fetch failed: ..."), and the GetWeather line shows
    the answer's real `source`/`value` (observed, cached, stale-cache, fallback) instead of only "open-meteo".
- **No Google sign-in in the game (maintainer, 2026-10-22):** hook.js stage "no sign-in window". `LoginWindowAdapter.Show`
  (0x17AE78C) is skipped when `gameStarted` (after a failed silent sign-in, or from the settings); the window before the game is
  unchanged. After `SettingsWindow.UpdateLoginInfo` (0x1819B48, also run by `OnInitialized`) the settings' `_loginParent` (+0xF0)
  and `_signInText` (+0x138) are set inactive. **Device check:** no sign-in pop-up in the game, no sign-in part in the settings.
- **The sea:** the builder keeps `natural=coastline` in a new `coastlines` table + R-tree and the extract's header box in
  `meta["bounds"]` (`covers()` uses it). Maps built earlier have neither and work as before (no schema bump): players rebuild.
  `FeatureIndex._document` adds water areas from `sea_rings`: the coastline cut to the box in Mercator and joined, the box edge
  walked clockwise (the sea is right of a coastline), islands as holes, a box no coast crosses decided by the nearest coastline's
  side (`coast_side`, within 50 km, else land), no sea where a coastline ends inside the box. Monaco: offshore tiles all sea, Port
  Hercule 46 %, the Rock 47 %, 1-4 ms a tile. Placement sees the sea as water: points at the waterline and on piers go (Monaco's
  casino cell 17 → 11 places).
- **Old tiles after a new map:** the game keeps every tile on disk (`cache/Google.Maps/Feature`) and never asks again, so a
  rebuilt or other region (or tiles sent before a map existed) kept the old look. The tile service names its map in `/health`
  (`map`: codec version, source file, timestamp, coastlines); hook.js stage "map tiles" removes the cached tiles when it changes
  (marker `Google.Maps/revival-map`). **Device check:** after a rebuild game.log shows `map tiles: a new map`.
- **Tests (Windows, 2026-10-22):** full server suite 313: 20 fail, every one also failing at HEAD (`2847552`, checked in a scratch
  worktree): the 18 Windows-only ones, and two that still level up and buy with the Final Exam's reward, which became nothing on
  10-10 (`test_reconstructed_skill_purchase_checks_level_points_and_persists`, and `..._world_monsters_spawn_on_safe_places_...`
  after its fight and herb parts): not fixed, they fail on Linux too. Map suite 75 (+ 2 Monaco tests with `local/venv`), `tools/client116`
  tests, `story_audit.py` (0 errors, the same 4 warnings) and the hook bundle pass. New tests: the apply-time guard, nest `bomb=-1`, the
  map sale, the head across a restart, zero-kill bestiary entries (summons, nemeta), nemeton spot across days and tuning, `SeaTests` (6),
  Monaco's sea, the tile service's map name.
- **Build 2026-10-22 12:23:** runtime rebuilt (no CA bundle; checked: sea, nest-v3, map name, both new hook stages, 0.3.0 notes in
  `runtime.zip`), `local/release/witcher-monster-slayer-companion-app-0.3.0-arm64-v8a.apk` (versionCode 300, release key, `apksigner
  verify` ok, the same certificate as 0.2.1). Installed on the Xiaomi 14:18 (`adb install -r`); the maintainer found no monsters
  (the clock, above). Rebuilt 2026-10-22 ~14:50 with the clock fix, the sign-in removal and their notes: the same file name (verified,
  same certificate). `...-0.3.0-clockfix-arm64-v8a.apk` is the clock fix alone, kept as a fallback. After installing: start the
  server once, then "Update the game" (the hook changed again).

## 0.3.0 rebalance (2026-10-22/23): presets, rewards, wiki spawns, XP, scrolls, consumables, trinkets
Uncommitted, beside the field fixes above. Plan: `C:\Users\iyave\.claude\plans\we-are-working-on-breezy-trinket.md`.
Maintainer's rule: **anything not vanilla is tunable**.
- **Presets** (`Net/WorldTuning.cs`, `Admin/TuningRoutes.cs`, the Tuning page's preset bar):
  - Revival (defaults) and Vanilla (each `Setting`'s `VanillaValue`) are built in and read-only; the player's own presets are
    `world/presets/custom[-n].json` `{name, values, rewards}`.
  - `world/tuning.json` is schema 2: the active preset and its resolved values (the placement service reads `places.*` as before).
  - A v1 file becomes the preset "Custom" and stays active, so nobody's settings reset. Editing a built-in one forks a copy.
  - Routes: `PUT /api/tuning`, `POST /api/tuning/presets`, `PUT|DELETE /api/tuning/presets/{id}`, `PUT /api/tuning/active`.
  - New settings: spawns.* (wiki tags, natural off streets, boosts ×3/×6, rain roaming, level gate: all vanilla behaviour per the
    maintainer), xp.baseByRarity, xp.vanillaCurve (Revival 0), nests.expPercent 200, nests.gold 100, tasks.goldPercent 200,
    tasks.exp 200, inventory.startSize 400 / maxSize 2000, bestiary.* (Revival 3/25/100, 2/10/20, 1/2/4; Vanilla pre-1.2
    3/50/150, 2/10/30, 1/2/6), quests.softCap/hardCap 800/1000, trinkets.buffs, shop.scrolls, shop.weatherItems.
- **Rewards page** (`Net/Rewards.cs` `RewardTables`, `/api/rewards`, dashboard "Rewards"):
  - Quest endings: `RewardTables.Groups`, keys `node.output` or `prologue.<key>`. Vanilla = the story file's and `RewardFor`'s
    amounts (the wiki's v1.1). Revival = the plan's table.
  - Daily pool: items per claim and weighted rows. Level-up rewards: levels 2-40 (Vanilla = the wiki's pre-1.2 list).
    **Every level needs an item:** `LevelUpWindow` waits forever without one.
  - Paid in `StoryEndBehaviourGraph` and the prologue branch (`GrantItems`, `WriteGear`). Mid-quest outputs (fights, coin
    notices) keep the story's amounts. Quest bag slots come from reached outputs (`Economy.QuestSlots`).
- **Spawns from the wiki** (`story-1.1.116/wiki_bestiary.py` + `wiki-bestiary.json` snapshot of EN rev 580603 / PL rev 235511):
  - Sentences map to the client's own `MONSTERS/OCCURANCE/*` phrases (EN and PL; a few PL keywords). Per category EN wins,
    then PL, then the client's tags.
  - `world-bestiary.json` keeps `client_tags` and `tags_source`. 21 species changed tags, 8 rarity, 1 skulls.
  - Rules in `WorldSpawns.Fits` and `BoostOf`. NEUTRAL2 never on urban ground (town parks are grassland). Rain lets WATER+RAIN
    roam off water. Boosts multiply: increased ×3, significantly ×6.
  - Level gate: `WorldSpawns.Allowed`, through `ForCell(playerLevel)`. The Aura now uses `DrawBalanced` with the balance rules.
- **The bestiary's text:** `ClientTexts` (`GET /revival/texts`) serves INFO_2 overrides (term references, so translated),
  trinket bonus lines, trinket modifier names and the weather charms' names. hook.js stage **"texts"** hooks
  `I2.Loc.LocalizationManager.GetTranslation` (0x1C933D8) and fetches them at start.
- **XP** (audit: the client adds exactly what the server saves; the field logs fit):
  - `Reconstruction.FightExp`: by rarity 100/250/600; xp.baseByRarity 0 goes by skulls.
  - Nests: vanilla amounts (base by rarity per monster, 250 clearing) × nests.expPercent.
  - First-kill uses `AllKills`.
  - `PlayerState.Fight` persists world, summoned and nest encounters across restarts.
  - In-flight retries wait for the first reply (`ReplayedResponseAsync`, `inflight`).
  - `LevelShown` re-sends a lost LevelUp window after the next boot; level-ups also pay the preset's orens.
  - Push 3 after XP-granting replies (the client's `QuestEndRequestNode` double-apply).
  - `xp.vanillaCurve` with `PlayerState.Curve` conversion at boot (level and progress kept); the curve is fixed per process.
  - Every grant logs its parts.
- **Trinket buffs** (`Net/TrinketBuffs.cs`, all 24 earnable): herbs, XP (+ attack vs family: player modifiers 921-926, effect
  28+family at apply time 22, derived and not removable), ingredients, nest gold, bag slots, a second unlimited station
  (instance 1020024).
- **Summoning scrolls** (`Net/SummonScrolls.cs`, ids 2-17, client slugs and texts):
  - Groups follow the descriptions with FULL_MOON_ONLY, but no level gate (round 2 below); a rarity falls back only when the
    family has none.
  - Rows are now always in static data (Reconstruction, not TaskCatalog).
  - Shop bundles 5000+id under Alchemy → Baits.
- **Consumables** (`Net/Consumables.cs`, type 7):
  - Items: Experience Scroll (modifier 9, +100%, 30 min), Ingredients Scroll (11, +50%), Rain/Fog/Clear charms (12, 22, 17; 1 h; slugs
    `interaction_booster`, `consumable_perfume`, `consumable_ringshaped_cracknel`, names from the hook).
  - RPC 99 replies `[ok][id][expiry]`; RPC 100 drops.
  - Weather: forced per player in RPC 67, and in the spawns for generations starting in the window. Push 91 and 67.
- **Capacity:** `BagSize` = start + bags + quest slots + trinket slots, capped by inventory.maxSize. hook.js native fix **"bag
  limit"** (`CanExpandInventory` 0x1A0E060 `cmp w8,#1000` → `#4095`).
- **Quest distance:** `ChooseStoryPlace` keeps places within the soft cap of the player, then the hard cap, then the nearest within
  it. `TooFar` re-chooses a saved place more than the hard cap from a known position, with a new place id.
- **Tests:**
  - `test_rebalance.py` (10, only its own: `load_tests`), `test_spawn_probe.py` (runs `tests/world_spawn_probe` with the new
    rule checks and re-pinned hashes), presets and Rewards in `test_tuning.py`.
  - Pins updated on purpose: Revival amounts, bag 400 (the boot-batch hashes: verified that only the bag size moved them),
    static rows.
  - Season 1 playthrough and the pre-1.2 bestiary audit run on the Vanilla preset (`PrototypeTests.tuned`). The 88/18/3 test
    runs with the level gate off.
  - Full suite (Windows): 327 tests, only the 20 known failures (16 Windows-only errors, file modes, the failed-save case and the two Final Exam tests; the world-spawn one now gets as far as its Final Exam purchase); `tools/client116` tests and the hook bundle pass.
- **Build 2026-10-23 00:49:** runtime rebuilt (its hook has the texts stage and the bag limit; its notes have the rebalance), then
  `local/release/witcher-monster-slayer-companion-app-0.3.0-arm64-v8a.apk` (`apksigner verify` ok, the same certificate). The
  field-fix build of 10-22 18:54 is kept as `...-0.3.0-fixes-arm64-v8a.apk`. **Installed on the Xiaomi 2026-10-23 00:54** at the
  maintainer's request (`adb install -r`, data kept; versionCode 300). The hook changed, so the app offers "Update the game".
- **Device checks still open:**
  - the texts stage (bestiary line in EN and PL, trinket Bonus lines, charm names);
  - the effects-panel icons (round 2: original ids for consumables, the "effect icons" stage for 901/902/921-926);
  - a 0-kill bestiary tier (equal cumulative values);
  - pushes 3, 5, 67, 69 and 91 taken live;
  - a bag over 1000;
  - the Use button on consumables.

## 0.3.0 field round 2 (2026-10-23): the maintainer's first device test of the rebalance
- **Presets always showed Custom:** the preset `<select>` sits inside `tuning-form`, so choosing one marked the form dirty and
  `presetAction` asked "Drop the unsaved changes?" with `window.confirm`. The phone's `DashboardActivity` WebView had no
  `WebChromeClient`, so confirm() answered false (and prompt() null) without showing anything: the switch was undone, and Copy,
  Rename and saving a built-in preset's copy did nothing. Fixed both (the select is no edit; `webChromeClient = WebChromeClient()`).
- **"Bag capped at 1000":** most likely the migrated Custom preset (startSize 200) + all five bags (800) = 1000, kept by the
  preset bug. Revival gives 400 + 800 = 1200: the >1000 device check is still open.
- **Rewards page on a phone:** items are a wrapping textarea (the daily pool's one item keeps the datalist); at <=650px each row is
  a card with column names (`labelCells`, `#view-rewards` in style.css).
- **Trinkets in the debug tools:** item kind `trinkets` (catalogue table `achievements`) adds or removes
  `Tasks.Achievements[id]`; pushes 24, 91, 69, 5.
- **Legendary scroll gave a drowner at level 2:** the level gate emptied the legendary pool and the fallback went down to common.
  Scrolls no longer use the level gate.
- **White effect icons:** the panel draws a modifier with `PlayerModifiersSettings.ModifierGUIPresets` (sharedassets1 path 3341;
  ids 1-8 the season buffs, 9-12 the boosters `consumable_01-04` = xp/alchemy/gathering/interaction, 15-24 the treats'
  `modifier_*`); any other id gets the default preset, which has no icon. Consumables now use the original ids (9, 11, 12, 22,
  17; live 911-915 modifiers in saves are ignored, they last an hour at most). hook.js stage **"effect icons"** lends presets:
  921-926 → 1 (sword), 901 → 16, 902 → 18 (`PlayerModifiersGUI.UpdatePlayerModifiersGUI` 0x1822CA8 caches the presets,
  `PlayerModifierGUISlot.Initialize` 0x18224B8 swaps the empty default).
- **No oren packs, no "buy orens" offer:** Tuning `shop.orenPacks` (Revival 0, Vanilla 1) filters bundles 77-82 and refuses RPC 76.
  Without packs `GoldOfferWindow` would throw, so hook.js native fixes **"no gold offer: shop/quick buy"** make the not-enough
  branches of `ShopPurchaseWindow.TryPurchase` (0x181A2DC) and `RecommendedPreparationWindow.TryPurchase` (0x1814864) return
  (each method's own epilogue). Short of orens, the purchase button now does nothing.
- **Open packs from the inventory** (Tuning `inventory.openPacks`, Revival 1, Vanilla 0): the inventory slot's management window
  (`ItemManagementWindow`, opened by `AlchemyItemSlot.OnManagementPressed`) drops packs with RPC 109; the server opens them
  instead (`Social:GiftIngredientAmount` Herba each, refused when the bag can't hold them) and pushes 5. `ClientTexts` sends
  `REVIVAL/OPEN_PACK` = "Open" while on; hook.js stage **"open packs"** relabels the window's Remove button
  (`_removeButton` +0xB0, the first TextMeshProUGUI below it via `GameObject.GetComponent(string)`) while it shows a `Pack`, and
  puts the button's own text back for other items.
- **Several map areas at once:** `osm_extract_index.FeatureIndexes` / `open_indexes` (both services take `--index` once per area;
  covers = a 5x5 grid in some extract, documents joined: each extract's areas and sea cut at its own bounds, roads once, area ids
  of later extracts prefixed `n-`; `meta.source_file` names the set, so the tile cache drops on a change). Companion: `Maps.all`
  (oldest first), names and links per file, `add`/`remove`; `ServerService.startMap` passes them all; `RegionActivity` is
  "Map areas" (each area with Update when its link is known, Delete; the list adds one). A map from before is the first area.
- **The settings' account section:** the "no sign-in window" stage hid only `_loginParent` (the sign-in buttons) and
  `_signInText`; the rest of the section stayed (settings_window / Content: the heading "--- ACCOUNT ---", and "Login" with its
  Title, UserIdTile and LogoutButton). It now hides the "Login" block (`_loginParent`'s parent) and the heading
  (`Transform.Find` on Content), in `UpdateLoginInfo`.
- **Device checks:** the effect icons, the Open label and the account section (hooks), the shop when short of orens, two map
  areas.

## 0.3.0 field round 3 (2026-10-23): Open in the pack's own window, the account heading, yourself as a friend, nine languages
- **"Packs only have a Send button":** the pack's info window (`InventoryItemWindow`) has one button, Send (`OpenFriendsPanel`
  0x17D2A0C opens the friends panel); the count window is behind the inventory slot's small management button. hook.js "open
  packs" now also: labels that button with the server's Open text (`_actionButtonText` +0x128 after `LoadData` 0x17D14B8) and
  replaces `OpenFriendsPanel`: for a pack it calls `AlchemyItemSlot.OnManagementPressed` (0x18C9F18) on the slot tapped last
  (`AlchemyItemSlot.OnClick` 0x18C99E0; its item +0x80 must be the window's `Data.Item`, Window<T>.Data +0x78), which opens the
  count window with the right count; anything else goes to the friends panel as before. While the count window shows a pack,
  its question and button terms (`UI/PANELS/ALCHEMY/MANAGEMENT_REMOVE_HEADER`, `MANAGEMENT_REMOVE`: "Do you want to throw away
  this item: #0?", "Throw away") answer the server's `REVIVAL/OPEN_PACK_HEADER` / `REVIVAL/OPEN_PACK` (`packWindow`,
  `PACK_TERMS`).
- **Account heading still showing:** the name lookup is exact ("--- ACCOUNT ---", sibling 9 before Login 10 in settings_window /
  Content), so the stage now also takes Login's preceding sibling and logs `settings: hidden <names>` once: the next report says
  which objects went.
- **Yourself in the friends list** (Tuning `friends.self`, Revival 1, Vanilla 0; `SocialService`): the list starts with your own
  entry (no stored edge); 106/107 accept your own id (a gift to yourself needs only the last one opened, its day is sent as 0 so
  the game's countdown never waits); 103/104/105/108 still refuse it. `ValidGift` allows sender == receiver.
- **Nine languages** (I2Languages order en, pl, de, es, it, fr, ru, pt(-BR), ja):
  - `Net/GameTexts.cs` holds every server text the game shows, worded with the game's own terms (family names, "gold coins",
    "crafting station", the Spanish "santuario", trinket names); `TrinketBuffs.Line` builds the bonus lines from it.
  - `/revival/texts` values are a string (bestiary lines: term references) or `{"en": …, "pl": …}`; hook.js `pick` uses
    `LocalizationManager.get_CurrentLanguageCode` (0x1C8EB68) before any "-", else English.
  - What's new: `news/release.<language>.json` beside the English `release.json` (same id and items;
    `NewsFeed.ReleaseNotesFor`: the player's language, its base, English); the app copies every `release*.json` at start.
    Change all nine together: test_news checks each translation keeps the English file's id, title and number of items.
- **Device checks:** the info window's Open and the count window's texts in a few languages, yourself in the friends list,
  `settings: hidden` in the report, What's new in another language.

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
