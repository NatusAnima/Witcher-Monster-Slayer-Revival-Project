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
  the bundled roots Open-Meteo answered (rain); with no roots, Clear.
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
