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
- The user has clicked Thorstein and successfully triggered the tutorial dialogue.

## Immediate Next Steps (Blockers)
1. **Analyze post-dialogue API traffic:** Check the server logs (or Frida logs) from the client's execution immediately after the tutorial dialogue finishes.
2. **Implement Fact Handlers:** Identify if the client sends `SetFacts (78)` or `EndBehaviourGraph (57)` to record quest progress.
3. **Persist State:** Update `GameSocketService.cs` to store any SetFacts received so they can be echoed back in `GetFacts (58)` if the client reboots.

## Workflow / Run Commands
Run these commands in separate terminals to launch the backend and connect the patched game:

```bash
# 1. Start the game server in tutorial mode (TutorialFinished=0)
cd server/WitcherRevival.Server
dotnet build -v q
ASPNETCORE_ENVIRONMENT=Production dotnet run --no-build

# 2. Establish ADB tunnels for the TCP socket and HTTP static data
adb forward tcp:27042 tcp:27042
adb reverse tcp:4253 tcp:4253
adb reverse tcp:8080 tcp:8080

# 3. Relaunch the client and attach Frida
adb shell am force-stop com.spokko.witchermonsterslayer
adb shell monkey -p com.spokko.witchermonsterslayer -c android.intent.category.LAUNCHER 1
python tools/patch/frida_run.py 120
```

## Recent Milestones
- **2026-07-08:** Cleaned up the workspace and initialized Git. Discarded heavy RE dumps and APKs.
- **2026-07-08:** Client successfully spawned the first NPC (Thorstein) and the tutorial dialogue was activated!
- **2026-07-08:** Explicit handlers added to `GameSocketService.cs` to avoid catch-all deserializer under-runs.
- **2026-07-05:** Solved the `PoiModule` linchpin. World boots cleanly to 200/200 progress.
