# TWMS Complete Client Boot & Initialization Sequence

This document maps out the lock-step network handshake and initialization timeline required to clear the game's boot sequence and reach an active gameplay state.

---

## Phase 1: Pre-Boot & Directives (Low-Level Networking)
Before the Unity game engine can construct its main scene, the client sets up its network bridges.

1. **Low-Level Socket Redirection**
   * **Trigger:** App launch invokes libc `connect()`.
   * **Observed Sequence:**
     * Intercepts `DEAD_IP:80` $\rightarrow$ Redirects to local `127.0.0.1:4253` (Game TCP Channel).
     * Intercepts `DEAD_IP:8080` $\rightarrow$ Redirects to local `127.0.0.1:8080` (HTTP Asset/Tile Server).
     * Intercepts port `443` $\rightarrow$ Forced to fail instantly to strip SSL pinning.

2. **Preloader Sync Config**
   * **Trigger:** `OnetimeWebstuffPreloader.ctor` executes.
   * **Logic:** Client reads internal configuration to verify Host, Port, and Gatekeeper requirements.
   * **Override:** `Preloader.Connect()` forces `UseGatekeeper=false` and switches connection straight to our local port.

---

## Phase 2: Channel Initialization & Static Assets
Once the socket connection is bound to your local environment, the client initializes its operational channels[cite: 3].

1. **Channel Setup Loop**
   * **Channel 3 (Auth):** Opens immediately to authenticate the client handshake[cite: 3].
   * **Channel 4 (StaticGameData):** Opens to deliver the static content[cite: 3].
   * **Payload Request:** `CreateRequestPayload` pushes a 17-byte request verification array[cite: 1].
   * **Payload Response:** Server replies with the gzipped `Container` JSON containing the definitions for items, monsters, and skills[cite: 1, 3].

---

## Phase 3: The Core Batch Sync (Method 115)
This is the critical synchronous gateway. The client blocks the thread until `GetInitialPlayerData` (Method 115) returns its full nested array batch[cite: 2, 3].

### Sub-Response Execution Order
*Fill this list based on the chronological sequence emitted by your `readResponse methodId=X` hook[cite: 1]:*

1. **Method 3: GetPlayerInfo**
   * **Client State:** Updates structural data values (`Gold`, `Exp`, `Gender`, `TutorialFinished`)[cite: 2].
2. **Method 5: GetInventory**
   * **Client State:** Instantiates the 9 primary item dictionaries[cite: 2].
3. **Method 6: GetKnownRecipes**
   * **Client State:** Resolves item crafting paths[cite: 2].
4. **Method 7: GetKilledMonsters**
   * **Client State:** Fills `BestiaryKnowledge` state models[cite: 2].
5. **Method 9: GetEquipment**
   * **Client State:** Binds the primary weapon/armor inventory references[cite: 2].
6. **Method 24: GetAchievements**
   * **Client State:** Pre-loads trophy metadata[cite: 2].
7. **Method 59: GetAllFacts**
   * **Client State:** Populates `ServerFactDatabaseModule` to drive narrative gates[cite: 3].
8. *[Insert next Method ID here from your server logs]*

---

## Phase 4: World Construction & Module Handshake
After Method 115 finishes parsing without throwing an exception, individual subsystems break out of their bypass frames and instantiate their internal properties[cite: 1, 3].

1. **LoadCells Execution**
   * **Trigger:** Client requests Method 88 (`LoadCells`)[cite: 3].
   * **Response:** Returns `BooleanResponse(true)` to declare the spatial matrix active[cite: 3].
2. **Map Render and Bypasses**
   * **Trigger:** `WwwRequest.CreateGetRequest` attempts to fetch map vector tiles from Google[cite: 1].
   * **Override:** In-place string rewrite forces the client to accept a mock HTTP 200 frame from your local server, ending the typical 60-second map freeze[cite: 1].
3. **Synchronization True Gate**
   * **Logic:** `SynchronizationStatus.get_IsSynchronized` is checked by the state engine[cite: 1].
   * **Status:** *(Document if you currently force this to 1 or if it naturally resolves to 1 after your server updates)*[cite: 1].

---

## Phase 5: Tutorial Activation Gating
This is your active development boundary.

1. **CheckTutorial Validation Loop**
   * **Trigger:** `TutorialController.CheckTutorial()` fires[cite: 1, 3].
   * **Data Check:** Queries `FactDatabaseModule` for the tutorial state[cite: 1].
   * **Behavior:** 
     * If `TutorialFinished = 1` $\rightarrow$ Jumps straight to normal Map state HUD[cite: 2].
     * If `TutorialFinished = 0` $\rightarrow$ Triggers `ToggleTutorialFeatures` to hide standard navigation and initializes the data-driven **S00 Story Chapter** cutscenes and dialog trees[cite: 2].