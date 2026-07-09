# Session Entrypoint

> **Start here for every new session.** This file contains only the immediate context needed to resume development.
> For architecture, memory maps, and protocol specs, see `README.md` and the `docs/` folder.

## Current Goal
**Drive the S00 Tutorial Sequence via API.** 
We are working to map out the API requests the client sends when navigating the first tutorial dialogue with the NPC (Thorstein) and implement the necessary server responses (`SetFacts`, `EndBehaviourGraph`, etc.) so the client successfully completes the tutorial phase and unlocks the main UI (Inventory, Bestiary, Quests, etc.).

## Current State
- The proof-of-life boot milestone is complete. The client successfully boots against the custom server and reaches the 3D map.
- The `GetInitialPlayerData` batch sync correctly populates initial stats, enabling the client to render the avatar with equipped weapons and armor.
- The server successfully parses the client's S2 cell IDs to spawn the first tutorial NPC (Thorstein) next to the player using `GetActiveQuestNodeInstances (60)`.
- Clicking Thorstein triggers the tutorial dialogue; the client runs its full local S00 prolog BehaviourGraph (`s00/prolog/prolog_01_thorstein`, 30 nodes: cutscene → dialog → `SetFactNode`s → `SetTrackedQuestNode` → `FactRequirementNode`/`BranchingNode` gates) and completes it (cutscene plays, `EndBehaviourGraph (57)` fires).
- **Root cause #1 found and FIXED, live-verified (2026-07-10):** the server was fully stateless for facts — `SetFacts (78)` had no handler, `EndBehaviourGraph (57)` parsed nothing from the request, `GetFacts (58)`/`GetAllFacts (59)` always returned empty/hardcoded data. Added a persisted fact store (`GameSocketService.cs`, flushed to `server/WitcherRevival.Server/data/facts.json`). **Live phone test confirms the full round trip works**: `SetFacts` x3 and `EndBehaviourGraph` (instanceId=1, output='thorstein', 6 facts) all parsed and stored correctly; final store `{"2":1,"123":0,"113":1,"10145":1,"77":2,"95":1,"107":1}`; `FactDatabaseModule.GetFact(10145)` correctly returns `1` post-tutorial (was always `0` before).
- **Root cause #2 found and FIXED, live-verified (2026-07-10):** fixing facts alone did not unblock the quest. Live trace showed the exact failure: right after the tutorial graph completes, the client re-evaluates its quest node list and calls `PoiModule.SetActiveQuestNodes nodes=0 tracked=145` (was `nodes=1` before) — it correctly sees Thorstein's step is done and filters that POI out, but `GetActiveQuestNodeInstances (60)` always served the same single hardcoded `prolog_01_thorstein` instance. **Fixed:** `GameSocketService.cs` now checks fact `10145` (the flag `prolog_01_thorstein`'s `EndBehaviourGraph` sets to 1) and serves `prolog_01_dead_horse` instead once that step is done.
- **Root cause #3 found and FIXED, live-verified (2026-07-10):** the first `dead_horse` attempt used a fabricated `InstanceId=2` for the `QuestNodeInstance`, which threw two `"key was not present in the dictionary"` exceptions the moment the POI was clicked and `StartQuestGraph` fired (the graph has `DataConsumer`/`DataProvider` nodes that look up cross-graph state keyed by instance ID). **Fixed** by extracting the *real* `QuestNodeInstanceId` baked into each graph asset (see AssetBundle breakthrough below) and sending that instead — `prolog_01_thorstein` = `5124757777905877225`, `prolog_01_dead_horse` = `5124756197357912298`. Retested live: no more dictionary exception, `StartQuestGraph` fires cleanly, `graphStarted` flips 0→1.
- **New subsystem discovered, NOT yet implemented:** `prolog_01_dead_horse` is not a dialogue node like Thorstein — it's an **Investigation** node (`_investigationSlug: 's00/prolog_dead_horse/prolog_dead_horse'`), the WitcherSenses AR clue-tracking mechanic. It has its own separate 43-node local scene graph in `s00_story_investigations_assets_all.bundle` (GameObjects `prolog_dead_horse_bush`, `prolog_dead_horse_alghouls` — an ambush near the corpse). After clicking the POI, nothing visible happens yet (confirmed live: only the map, 2 HUD elements, and the `?` POI marker are on screen) — this is a self-contained gameplay system, not a continuation of the facts/quest-node bug, and hasn't been reverse-engineered yet.
- **Major tooling breakthrough (2026-07-10): Unity AssetBundle extraction now works.** Installed `UnityPy` (`pip install UnityPy`) and wrote `tools/unity_extract/bundle_explorer.py` (list/search/graph subcommands) to read Unity `MonoBehaviour`/`NodeGraph` asset data directly out of bundles extracted from the OBB (`Original APK and OBB/.../main.*.obb`, itself a zip; bundles live under `assets/aa/Android/*.bundle`). **This is the tool that finally let us read real game-design data (quest chains, node graphs, fact IDs) instead of guessing from IL2CPP code shape alone** — `tools/dump/dump.cs` only has class/method *shapes*, never the serialized asset *data*. Relevant bundles for S00 prolog: `s00_story_graphs_assets_all.bundle` (all BehaviourGraph node data), `s00_story_investigations_assets_all.bundle` (Investigation-mechanic scene data), `s00_story_poi_settings_assets_all.bundle` (POI settings assets).
- The S00 prolog chain per `scratch/bgraphs.txt` + the now-decoded graph data: `prolog_01_thorstein` (done) → `prolog_01_dead_horse` (Investigation, next) → `prolog_01_footprints_01`, `prolog_01_tracks_01/02/03`, `prolog_01_griffin` (all `QuestNodeInstanceId=0` in-asset except griffin=`5124757777905877227` — likely filled server-side too) → `prolog_02_*` (crown/gargoyle/heart/map/obelisk/sword — loot/investigation-clue items referenced *within* graphs, not separate quest-node POIs). **`QuestNodeId` itself is baked as `0` in every graph asset** — it's server-assigned and not meaningful to the client (matches the pre-existing code comment "spawn is independent of QuestNodeId; click needs StoryGraph"); only `QuestNodeInstanceId` (the `InstanceId` wire field) needs to be real.

## Immediate Next Steps (Blockers)
1. **Reverse-engineer the Investigation/WitcherSenses mechanic** — what triggers it client-side after `StartQuestGraph`, whether it needs new server API support (e.g. `UseSenses (42)`, `GetSensedMonsters (43)`), and how the `prolog_dead_horse_alghouls` ambush factors in. Use `tools/unity_extract/bundle_explorer.py graph <bundle> prolog_dead_horse` (in `s00_story_investigations_assets_all.bundle`) to read its 43-node structure the same way the quest-chain graphs were decoded.
2. **Extend the quest-chain fact-gating pattern** to the rest of the S00 prolog chain (footprints_01 → tracks_01/02/03 → griffin) once dead_horse's Investigation flow is understood — same `GetActiveQuestNodeInstances (60)` pattern, real `QuestNodeInstanceId` per node (see table above / `docs/api-and-content-reference.md` §10).
3. **Known-uncertain area to watch:** the `SetFacts (78)` leading-int convention (count-of-ints vs. something else) was inferred from captured payloads, not a disassembled `Serialize()` body — parser is convention-agnostic (consumes pairs until the payload runs out) but keep cross-checking `Facts stored:` log lines against fresh captures.
4. **Deprioritized, chase only if it still reproduces:** a "Cannot access a disposed object" exception recurring every ~6s in Frida captures, correlated with the client repeatedly tearing down/reopening its socket. Seen again in the 2026-07-10 live session; still not addressed.

## Toolchain note (2026-07-10)
`tools/platform-tools/`, `tools/dump/`, `tools/apk_extracted/`, and `Original APK and OBB/` are gitignored
(large/proprietary) and must exist locally to do any of this work. If missing: platform-tools is a plain
Google download; `tools/dump/*` regenerates from `tools/apk_extracted/lib/arm64-v8a/libil2cpp.so` +
`.../global-metadata.dat` via Il2CppDumper (`Perfare/Il2CppDumper` GitHub releases) run against the APK
(a plain zip — `unzip` it into `tools/apk_extracted/`); `catalog.json` and the `.bundle` files come from
inside the OBB (also a plain zip) under `assets/aa/catalog.json` and `assets/aa/Android/*.bundle`.

## Workflow / Run Commands
Run these commands in separate terminals to launch the backend and connect the patched game:

```bash
# 1. Start the game server in tutorial mode (TutorialFinished=0), logging to scratch
cd server/WitcherRevival.Server
dotnet build -v q
ASPNETCORE_ENVIRONMENT=Production dotnet run --no-build > ../../scratch/server.log 2>&1

# 2. Establish ADB tunnels for the TCP socket and HTTP static data
adb forward tcp:27042 tcp:27042
adb reverse tcp:4253 tcp:4253
adb reverse tcp:8080 tcp:8080

# 3. Relaunch the client and attach Frida, logging output to scratch
adb shell am force-stop com.spokko.witchermonsterslayer
adb shell monkey -p com.spokko.witchermonsterslayer -c android.intent.category.LAUNCHER 1
python tools/patch/frida_run.py 120 > scratch/frida.log 2>&1
```

## Recent Milestones
- **2026-07-10:** Live-verified fact persistence, then found and fixed two further live-confirmed bugs in the same session: (1) `GetActiveQuestNodeInstances (60)` now serves `prolog_01_dead_horse` once Thorstein's facts show completion, instead of forever re-serving the same finished node; (2) the served `InstanceId` must be each graph's *real* `QuestNodeInstanceId` (not an arbitrary made-up id) or the client throws on cross-graph dictionary lookups — fixed by extracting real values via a new Unity AssetBundle extraction tool (`tools/unity_extract/bundle_explorer.py`, built on `UnityPy`). This tool is the session's biggest lasting unlock: it reads actual game-design data (quest chains, node graphs, fact IDs) straight out of the OBB's bundles, something the IL2CPP dump alone could never provide. Landed on the edge of a new subsystem (the Investigation/WitcherSenses AR mechanic) as a clean stopping point.
- **2026-07-09:** Root-caused the tutorial stall: server was stateless for facts, discarding `SetFacts (78)` and `EndBehaviourGraph (57)` writes. Added a persisted fact store to `GameSocketService.cs` and decoded both request wire formats byte-exactly against `tools/dump/dump.cs`. Build clean; live phone verification pending.
- **2026-07-08:** Cleaned up the workspace and initialized Git. Discarded heavy RE dumps and APKs.
- **2026-07-08:** Client successfully spawned the first NPC (Thorstein) and the tutorial dialogue was activated!
- **2026-07-08:** Explicit handlers added to `GameSocketService.cs` to avoid catch-all deserializer under-runs.
- **2026-07-05:** Solved the `PoiModule` linchpin. World boots cleanly to 200/200 progress.
