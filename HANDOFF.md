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
- The user has clicked Thorstein, triggered the tutorial dialogue, and the client runs its full local S00 prolog BehaviourGraph (`s00/prolog/prolog_01_thorstein`, 30 nodes: cutscene → dialog → `SetFactNode`s → `SetTrackedQuestNode` → `FactRequirementNode`/`BranchingNode` gates) — but the quest did not advance past the first cutscene; the tracked-quest text renders top-right and then nothing further loads.
- **Root cause found (2026-07-09):** the server was fully stateless for facts. `SetFacts (78)` had no handler at all (silently ACKed via the catch-all), `EndBehaviourGraph (57)` parsed nothing from the request and always replied with an all-zero stub, and `GetFacts (58)`/`GetAllFacts (59)` always returned empty/hardcoded data. Every `FactDatabaseModule.GetFact(...)` call the client made (facts `9999`, `70`, `10145` traced live) saw 0 — even right after the client itself told the server what those facts should be. The graph's `FactRequirementNode`/`BranchingNode` gates almost certainly stall on this.
- **Fixed:** `GameSocketService.cs` now has a real fact store (in-memory `Dictionary<int,int>`, flushed to `server/WitcherRevival.Server/data/facts.json` on every write, survives client reboots and server restarts). `SetFacts (78)` and `EndBehaviourGraph (57)` now parse and persist the client's facts; `GetFacts (58)`/`GetAllFacts (59)` (standalone and the boot-batch sub-response) now echo the real store instead of empty/hardcoded data. Decoded wire formats for `SetFacts` and `EndBehaviourGraph` requests — previously undocumented — are now in `docs/protocol-reference.md`. Build verified clean (`dotnet build -v q`, 0 warnings/errors). **Not yet verified live on the phone.**

## Immediate Next Steps (Blockers)
1. **Live-verify the fact fix:** rebuild, run the usual workflow, click Thorstein, complete the cutscene, and confirm via `server.log` that facts round-trip and via the Frida log that `FactDatabaseModule.GetFact(...)` returns non-zero — and most importantly, whether the quest now actually advances past the cutscene on-screen.
2. **If facts alone don't unblock it:** the next suspect is `GetActiveQuestNodeInstances (60)` — it always serves the same single hardcoded `prolog_01_thorstein` quest node regardless of tutorial state. The S00 prolog is actually a graph chain (`prolog_01_tracking`, `prolog_01_footprints_01`, `prolog_01_griffin`, `prolog_02_*`, per the bundled asset list) — the server may need to serve the next node in that chain once facts show the first step is done.
3. **Known-uncertain area to watch:** the `SetFacts (78)` leading-int convention (count-of-ints vs. something else) was inferred from 3 captured payloads, not from a disassembled `Serialize()` body — the parser is written to be convention-agnostic (consumes pairs until the payload runs out) but cross-check the `Facts stored:` log lines against fresh captures.
4. **Deprioritized, chase only if it still reproduces:** a "Cannot access a disposed object" exception recurring every ~6s in `frida_6.log`, correlated with the client repeatedly tearing down and reopening its socket (26 connect/disconnect cycles seen in one `server.log` capture). Not addressed this pass.

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
- **2026-07-09:** Root-caused the tutorial stall: server was stateless for facts, discarding `SetFacts (78)` and `EndBehaviourGraph (57)` writes. Added a persisted fact store to `GameSocketService.cs` and decoded both request wire formats byte-exactly against `tools/dump/dump.cs`. Build clean; live phone verification pending.
- **2026-07-08:** Cleaned up the workspace and initialized Git. Discarded heavy RE dumps and APKs.
- **2026-07-08:** Client successfully spawned the first NPC (Thorstein) and the tutorial dialogue was activated!
- **2026-07-08:** Explicit handlers added to `GameSocketService.cs` to avoid catch-all deserializer under-runs.
- **2026-07-05:** Solved the `PoiModule` linchpin. World boots cleanly to 200/200 progress.
