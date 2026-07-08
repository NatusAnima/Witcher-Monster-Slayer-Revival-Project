# Memory Map & IL2CPP Reverse Engineering Reference

This document tracks the Relative Virtual Addresses (RVAs), IL2CPP offsets, and the status of modules being bypassed or hooked via Frida (`tools/patch/hook.js`). All RVAs are for `arm64 v1.0.43`.

> **Note:** For deep structural queries, use `grep_search` on `tools/dump/dump.cs` and `tools/dump/script.json`. Do not attempt to read these heavy files entirely into context.

## Core Game Loop & State
| RVA | Symbol | Description |
|---|---|---|
| `0x17D5D30` | `Game.get_ModulesInitialized()` | True when all required modules finish loading. |
| `0x1F3DE50` | `ResetGame..ctor` | Game reset hook point. |
| `0x1F9A10C` | `Tutorial.CheckTutorial()` | Entry point for the S00 tutorial. |
| `0x1F9A530` | `Tutorial.ForceTutorialFinished` | Forces tutorial completion. |
| `0x1F9A69C` | `Tutorial.EndTutorial` | Called when the tutorial finishes successfully. |

## Networking & Boot
| RVA | Symbol | Description |
|---|---|---|
| `0x2F85970` | `ThreadedClient.Connect` | The active boot client's connect loop. |
| `0x2F85B74` | `ThreadedClient.Run` | The active boot client's main loop. |
| `0x2F860E8` | `ThreadedClient.Close` | Closes the connection. |
| `0x17A4598` | `SynchronizationModule.OnGetInitialPlayerDataResponse` | Receives the Method 115 batch. |
| `0x1F99FD4` | `SynchronizationStatus.get_IsSynchronized` | True when the player batch is fully processed. |
| `0x30F55A8` | `WwwRequest.CreateGetRequest` | Used to redirect map tile URLs to our HTTP server. |

## Modules and Bypass Status
Modules are initialized dynamically during boot. If a module crashes, the game hangs on the loading screen. We bypass crashing modules in `hook.js` by forcing `InitializeModule` to return immediately and `get_Initialized` to return `true`.

| Module | Init RVA / get_Init RVA | Current Status | Notes |
|---|---|---|---|
| **PlayerData** | `0x17436E8` / `0x17436B4` | **Un-bypassed** | Handles inventory, gold, stats. Needs valid Method 115 sub-responses. |
| **PlayerModule** | `0x173862C` / `0x17384F8` | **Un-bypassed** | Core player state. |
| **GuiModule** | `0x17F04E0` / `0x17F04CC` | **Un-bypassed** | Renders the HUD. Screens (Equipment, Bestiary) inject synced data models here. |
| **ServerFactDatabaseModule** | `0x178A3D0` / `0x178A3BC` | **Un-bypassed** | Fact-driven progression (e.g., quests). Relies on `GetAllFacts (59)`. |
| **StoryModule** | `0x17A0F94` / `0x17A0F80` | **Un-bypassed** | Hard-depends on `PoiModule`. |
| **PoiModule** | `0x17B34B8` / `0x17B3328` | **Un-bypassed** | Linchpin for tutorial. Displays map pins. |
| **DailyContractsModule** | `0x17E850C` / `0x17E847C` | **Un-bypassed** | Requires `GetDailyContracts (20)`. |
| **WeeklyContractsModule** | `0x17EE69C` / `0x17EE630` | **Bypassed** | `OnNewDay` (0x17EEDD8) throws NRE on empty `weekly_quests_rewards`. |
| **WitcherSensesModule** | `0x190DAF8` / `0x190D4CC` | **Un-bypassed** | Injects `PoiModule` and `StoryModule`. Needs `GetSensedMonsters (43)`. |
| **BehaviourGraphModule** | `0x31972F8` / `0x319726C` | **Un-bypassed** | Drives combat AI and tutorial scripting. Requires DI-bound settings at `0x18`. |

## SignalBus and Diagnostics
| RVA | Symbol | Description |
|---|---|---|
| `0x1C5C6DC` | `SignalBus.Fire(object)` | Frida null-Data bypass site (swallows signals with null Data to prevent NREs). |
| `0x1CE3728` | `Exception throw helper` | Backtrace hook site to catch crashes. |
| `0x31BAF6C` | `Loader.SetText(string)` | Loading screen text. |
| `0x31BAFC4` | `Loader.SetProgress(int, int)` | Loading screen progress bar. |
| `0x184C9F4` | `SynchronizationModule.Synchronize<T>` | Hooked to trace requested methodIds during boot. |
