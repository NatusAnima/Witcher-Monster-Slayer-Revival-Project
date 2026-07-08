# Session 2026-07-05 — Content bring-up + Tutorial pivot (RESUME POINT)

Read this to resume. Companion to `docs/api-and-content-reference.md` (Method enum, wire formats, DTOs).

## THE KEY REFRAME (from the user, confirmed against gameplay videos)
- The map + **weather icon + compass icon only** IS the **correct pre-tutorial HUD**. It is NOT a bug.
- **The 5 bottom-menu elements (Inventory/Bestiary/Character/Quests/Shop) appear only AFTER tutorial COMPLETION.**
- Therefore the Equipment/Statistics/Achievements/Skills screens the user wants are gated behind **completing the S00 tutorial**. Setting `TutorialFinished=1` alone does NOT reveal them (tested — HUD stayed hidden). The reveal is done by the tutorial's own completion flow.
- **GOAL NOW: make the S00 tutorial run and complete.** Do NOT chase `Game.ModulesInitialized` / force the HUD — that was a wrong lead.

## VERIFIED WORKING THIS SESSION (runtime, physical phone)
- Static data fully populated + loads with **0 NULL Container fields** (client dump confirmed all 11 arrays: swords6/armors6/heads3/skills8/skill_req5/monsters8/monster_desc24/families11/achievements6/levelups10/difficulties3).
- Player batch applied — **avatar renders equipped** (armor + sword visible on the map).
- Boot reaches **job 200/200 + `SyncStatus.IsSynchronized=1`**.
- **BehaviourGraphModule un-bypass is SAFE** — `InitializeModule` runs ENTER→LEAVE clean (its `_settings` @0x18 is DI-bound, no NRE, no injection needed).
- All post-boot Api under-runs fixed → **zero catch-all hits**: ResolveRewards(119), and standalone GetPlayerInfo(3)/GetInventory(5).

## CURRENT ON-DISK FILE STATE
### `server/WitcherRevival.Server/Net/GameSocketService.cs` (built + verified)
- `BuildInitialPlayerData()`: gold 5000, exp 4500, Head 1, Gender 0; owns swords{1,2,3}/armors{1,2} equipped 1/1; killed {1:5,2:2,3:1}; achievements {1:1,2:1}; skills{1,2,3}+10pts; distance 15000.
- `TutorialFinished` is **config-driven**: `cfg.GetValue("Player:TutorialFinished", false)` → default 0 = tutorial ON. Stage-1 ran with env `Player__TutorialFinished=true` to force-skip it. **For the tutorial, run the server WITHOUT that env var.**
- Action handlers (explicit, replace catch-all): 27 DistanceTraveled, 11/55/12/13 Equip*, 28 SetCustomizationHead, 30 SetTutorialFinished, 64 AcquireSkill, 93 AddSkillPoints, 57 EndBehaviourGraph (all-zero stub, order-safe), **119 ResolveRewards** ([byte1][int0]), standalone **3 GetPlayerInfo** + **5 GetInventory** (shared `BuildGetPlayerInfoPayload`/`BuildGetInventoryPayload`).

### `server/WitcherRevival.Server/Net/PreloaderStaticData.cs` (built + verified)
- `ContentOverrides` dict fully populated (real catalog slugs + I2 loc keys). `BuildContainerJson` joins them. DONE.

### `tools/patch/hook.js` — MID-EDIT, needs finishing:
- `UNBYPASS_RVAS`: BehaviourGraphModule (0x31972F8/0x319726C) un-bypassed. StoryModule (0x17A0F94/0x17A0F80) + PoiModule (0x17B34B8/0x17B3328) **just RE-un-bypassed** (restored).
- **WeeklyContractsModule (0x17EE69C/0x17EE630) stays BYPASSED** — its `OnNewDay` NREs on empty `weekly_quests_rewards` (needs a weekly reward record + a valid backing item; separate follow-up, not needed for tutorial).
- **WitcherSensesModule (0x190DAF8/0x190D4CC) still BYPASSED (commented) — NEXT: un-bypass it** (it injects Poi+Story; NRE'd only because they were bypassed).
- PoiSettings injection (@0x60) + BehaviourGraphSettings injection (@0x18, disabled) blocks present.

## IMMEDIATE NEXT STEPS (the pivot, in order)
1. **hook.js — un-bypass WitcherSensesModule** (uncomment 0x190DAF8, 0x190D4CC in UNBYPASS_RVAS).
2. **hook.js — fix the PoiModule freeze at root:** the `getClass()` fallback (function ~line 659, used by the null-`Instantiate` DespawnFX bypass) enumerates the whole image and does `log("  Class "+i+...)` **per class** → tens of thousands of Frida `send()`s over USB = the 90% "Loading Points of Interest" hang. Remove/guard that per-class log (and ideally cache the resolved class) so PoiModule.InitializeModule returns fast. (PoiModule was only "hanging" due to this hook logging, not a game bug.)
3. **Restart server in tutorial mode:** kill :4253, `dotnet run --no-build` **without** `Player__TutorialFinished` (so TutorialFinished=0). Keep `ASPNETCORE_ENVIRONMENT=Production`.
4. **Boot + observe** `Tutorial.CheckTutorial` (RVA 0x1F9A10C): does it take the not-finished branch → `ToggleTutorialFeatures` → start the S00 story/behaviour graph? Watch for: PoiModule/StoryModule/WitcherSenses ENTER→LEAVE clean; new NREs; `SetText` tutorial strings; whether the tutorial UI/cutscene appears.
5. **Drive the tutorial:** it is Fact-driven (StoryModule.OBJECTIVE_FACT_PREFIX=10000) and runs BehaviourGraph. Likely needs: SetFacts(78)/GetFacts(58) handling, the S00 addressable assets present in APK, `SetTutorialFinished(30)` on completion (already stubbed), and possibly serving objective facts in sequence. Iterate on-device.

## ENVIRONMENT / RESUME COMMANDS
- Phone `0bdd6603bf4b` (veux Xiaomi), Awake. App `com.spokko.witchermonsterslayer`. adb at `tools/platform-tools/adb.exe`.
- Scratchpad logs: `C:/Windows/Temp/claude/g--Apps-Witcher---Monster-Slayer-Revival-Project/5dbdbcdd-e498-43d1-8a2e-9e90b7b14b42/scratchpad`
- Resume loop:
  ```bash
  adb=tools/platform-tools/adb.exe
  # server (tutorial mode = NO Player__TutorialFinished):
  cd server/WitcherRevival.Server && dotnet build -v q && ASPNETCORE_ENVIRONMENT=Production dotnet run --no-build > "$SCRATCH/server.log" 2>&1 &
  "$adb" forward tcp:27042 tcp:27042; "$adb" reverse tcp:4253 tcp:4253; "$adb" reverse tcp:8080 tcp:8080
  "$adb" shell am force-stop com.spokko.witchermonsterslayer; "$adb" logcat -c
  "$adb" shell monkey -p com.spokko.witchermonsterslayer -c android.intent.category.LAUNCHER 1
  python tools/patch/frida_run.py 60        # attaches to embedded Gadget, loads hook.js, resumes
  "$adb" exec-out screencap -p > "$SCRATCH/screen.png"
  ```
- frida_run.py uses the app's embedded frida-**Gadget** (wait-mode): launch app → it pauses → script attaches+resumes.

## UPDATE (2026-07-05, later) — DECISIVE FINDING: PoiModule is the tutorial linchpin
Ran the pivot on-device. Results:
- **hook.js getClass() fix landed:** (1) removed the per-class `log()` flood (the real "90% Loading POI" freeze
  cause); (2) added `getImageByName()` domain-enumeration so Assembly-CSharp resolves the real image. Both good.
- **Un-bypassing PoiModule → HANGS** ~63s inside InitializeModule after the NULL-Instantiate→fake-DespawnFX
  bypass (never LEAVEs; no exception). Boot stuck at job 180/200. DespawnFX `class_from_name` still resolves
  null on a 49-class image (DespawnFX is confirmed `WitcherWorld.Modules.POI.DespawnFX`, a MonoBehaviour).
  Also the client logs NonFatalError "GetInitialDataResponse: no handler for method GetLocations" (=Method 2)
  and "method 1" — PoiModule wants a GetLocations(2) response we don't serve.
- **Un-bypassing StoryModule (with Poi bypassed) → NRE at job 196/200.** Traced with a new
  `SynchronizationModule.Synchronize<T>` hook @0x184C9F4 (logs requested methodId). Ground truth:
  StoryModule.InitializeModule requests method **70 (GetFinishedSeasonQuests)** then **60
  (GetActiveQuestNodeInstances)**; its response handlers call **`PoiModule.SetActiveQuestGivers`** (0x17B7F00)
  and **`PoiModule.SetActiveQuestNodes`** (0x17B73E0), which iterate PoiModule's collections
  (Instances @0x98 / Locations @0x160) — **NULL because PoiModule.InitializeModule is bypassed** → NRE.
  Batch already CONTAINS methods 70 + 60 (correct empty format); the NRE is the Poi dependency, not missing data.
- No-oping SetActiveQuestGivers is whack-a-mole (SetActiveQuestNodes next, and quest nodes ARE the tutorial
  POIs), so it was removed.
- **CONCLUSION:** StoryModule + WitcherSensesModule both hard-depend on a genuinely-initialized PoiModule.
  There is no clean shortcut — **the tutorial gates on PoiModule.InitializeModule completing** (allocating its
  collections + loading Locations). Next real work = PoiModule bring-up: (a) find why InitializeModule hangs
  (disassemble 0x17B34B8 or Frida-trace its callees — is it awaiting GetLocations(2)? a coroutine? DespawnFX
  pool loop?), (b) serve GetLocations(2), (c) get Instances/Locations allocated so Set* calls work.
- **Current on-disk hook.js state: reverted to the known-good 200/200 boot** (Story/Poi/WitcherSenses bypassed,
  BehaviourGraph un-bypassed). KEPT (harmless/useful): getClass fixes, Tutorial trace (0x1F9A10C/530/69C),
  Synchronize<T> trace (0x184C9F4). Verified boot 200/200 + IsSynchronized=1 after revert.

## UPDATE (2026-07-05, later #2) — WORLD BOOTS + tutorial-NPC approach staged
**PoiModule linchpin SOLVED — game boots into the 3D world** (equipped avatar, map+weather+compass, 200/200).
Two fixes made it work:
1. `hook.js getFakeDespawnFX` now queries image **"Game"** (Game.dll), not "Assembly-CSharp" — DespawnFX is
   TypeDefIndex 12285 in Game.dll (image range 10273..15027). Wrong image → pool got a bare GameObject instead
   of a real DespawnFX/IMonoPoolable.
2. **Batch misalignment in method 24 (GetAchievements):** client deserializer (0x1F736E4) loops `add w24,#2`,
   so the count field is the number of INTS (2×entries), NOT pairs. Server wrote count=2 for 2 entries →
   client read 1 pair, left 8 bytes → batch loop `GetInitialPlayerDataResponse.Factory.readResponse`
   (0x1F785D8, dispatched from Deserialize 0x1F784C4) consumed them as phantom methodIds 2 & 1, eating 2 of
   the 19 loop iterations and DROPPING the last two batch methods (43 GetSensedMonsters + 56
   GetKilledMonsterInstances). Harmless while WitcherSenses+Poi were bypassed; fatal once un-bypassed. Fix:
   method 24 count 2→4. hook.js: Poi(0x17B34B8/0x17B3328) + Story(0x17A0F94/0x17A0F80) +
   WitcherSenses(0x190DAF8/0x190D4CC) all UN-BYPASSED now; all init ENTER→LEAVE clean.

**Tutorial NPC = a served quest node (method 60), assets are LOCAL (not dead CDN):** S00 bundles are in the
APK under `com.spokko.witchermonsterslayer/assets/aa/Android/` (s00_npcs, s00_story_cutscenes, s00_dialogs,
common_story_graphs). Quest-giver = **Thorstein**. Method-60 = GetActiveQuestNodeInstances =
`{List<Location>, List<QuestNodeInstance>, Dictionary<long,int> Expiring}`. Handler order (StoryModule
0x17A3614): UpdateLocations(Locations) registers PlaceId→coords FIRST, then SetActiveQuestNodes looks up
PlaceId (ContainsKey — skips node if missing) and positions via LocationModule.CoordsToWorldSpace.
Wire formats (verified from deserializers):
- Location (0x31D0B28): `[int placeIdLen][placeId][float lat][float lng][int biomeCount][int*biomes]`
- QuestNodeInstance (0x31D1334): `[long InstanceId][int QuestNodeId][int placeIdLen][placeId]`
  `[ReadString SettingsPath][ReadString BehaviourGraphName][int DisplayMode]` (ReadString=[int len][UTF8]).
- PoiDisplayMode: Normal=1..Collecting=7 (7→CollectingQuestPoiInstance, else QuestPoiInstance). Use 1.
- TryGetQuestIdByQuestNodeId (0x17A1B24→StoryGraph 0x18a7170) is null-safe; POI spawns regardless of nodeId.

**Player GPS decoded from method-40 GetLocationsByCell (9 S2 cells, 76B = [int9][ulong*9]):** center cell
`151d057240000000` (level 15) → **lat 32.453864, lng 35.058088** (northern Israel; matches Asia/Jerusalem).
S2 decoder script: scratchpad `s2decode.py`. Server now serves method 60 with a Thorstein QuestNodeInstance at
those coords (SettingsPath `assets/_bundledassets/story/poi_settings/_common/thorstein_lq.asset`,
BehaviourGraphName `assets/_bundledassets/story/bgraphs/s00/prolog/prolog_01_thorstein.asset`, placeId
`tut_thorstein`, DisplayMode 1). GameSocketService constants TutPlaceId/TutLat/TutLng. TEMP [LOC] logging added
for method 40/67/88 request bytes. hook.js has a quest-POI spawn trace (UpdateLocations / SetActiveQuestNodes /
QuestPoiInstance.ctor). **NEXT TEST (needs phone replugged):** boot, confirm readResponse sequence stays
aligned (43+56 read), watch for QuestPoiInstance.ctor + logcat "Creating questPoi"/"quest -", screenshot for
Thorstein near the player. Open item: addressable address case (lowercase vs catalog's capital "Assets/") —
avatar loaded lowercase OK, so betting lowercase; logcat will confirm. Two Fable subagents running on
(a) quest static-data/StoryGraph + valid questNodeId, (b) full tutorial-completion path + menu-reveal gate.

## KEY RVAs discovered this session
- Tutorial.CheckTutorial 0x1F9A10C; ForceTutorialFinished 0x1F9A530; EndTutorial 0x1F9A69C.
- WeeklyContractsModule.OnNewDay 0x17EEDD8 (NRE on empty weekly_quests_rewards).
- WitcherSensesModule injects PoiModule(0x30)+StoryModule(0x70)+IIntStorage<Monster>(0x58).
- Game.get_ModulesInitialized 0x17D5D30 (do NOT force — pre-tutorial HUD is correct).
- BehaviourGraphModule._settings @0x18 (DI-bound, inits clean).
