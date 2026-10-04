# 1.1.116 Api methods: server coverage

Every `Api.Method` value of the 1.1.116 client, classified against the local server's dispatch (`Net/GameSocketService.cs`).
"Client senders" are the client methods that build the request class, found by resolving IL2CPP metadata references in `libil2cpp.so`
(ADRP+LDR through the GOT to `<Request>_TypeInfo`). "Seen" counts requests in the private LAB 16 phone runs against Debian up to 2026-09-29.
For an unsupported method without a verified refusal body, the server keeps the connection but leaves the request unanswered. A waiting client callback can still block its UI. Known refusal bodies cover only the methods listed in `PlayerService.RefusalFor`.
The [roadmap](../../docs/ROADMAP.md) orders the remaining work. Task behavior is optional; see [implementation and device limits](../../docs/TASKS-20261001.md). Current alchemy and Aura additions are documented in the [finalization packet](../../docs/FINALIZATION-20261002.md); backend tests do not establish Android combat acceptance.

| Class | Methods |
| --- | ---: |
| Answered by the server | 98 |
| Reachable now, not answered | 0 |
| Unreachable until the server serves the feature | 1 |
| Server push not sent yet (the client never asks) | 2 |
| Out of scope (store, debug, other channel) | 4 |
| Dead in 1.1.116 | 19 |

## Reachable now, not answered

None.

## Unreachable until the server serves the feature

| Id | Method | Seen | Client senders | Notes |
| ---: | --- | ---: | --- | --- |
| 99 | UseConsumable |  | `PlayerModifiersModule.UseConsumable` | Use a consumable from the inventory. Needs consumables (none are sold or granted). |

## Server push not sent yet (the client never asks)

| Id | Method | Seen | Client senders | Notes |
| ---: | --- | ---: | --- | --- |
| 26 | DailyContractCompleted |  |  | Server push: daily contract done; no client subscriber in 1.1.116. |
| 96 | AddWeeklyStamps |  |  | Not pushed for fight stamps: the client already increments them locally. RPC94 reconciles saved state. |

## Out of scope (store, debug, other channel)

| Id | Method | Seen | Client senders | Notes |
| ---: | --- | ---: | --- | --- |
| 38 | AddGold |  | `PlayerData.ServerAddGold` | Debug: PlayerData.ServerAddGold, not called by game code. |
| 54 | SpawnMonster |  | `PoiModule.Spawn` | Debug: PoiModule.Spawn, not called by game code. |
| 66 | Log |  |  | Log is sent on the Logging channel, which the server accepts; this Api method is not built. |
| 76 | BuyInAppBundle |  | `ValidateReceiptStep.ValidateReceiptOnServer` | Purchase of an oren pack (bundles 77-82) with the store receipt. A LAB client uses the client's fake store (`TransactionModuleInstaller.BindStore`), so the purchase is free: the server grants the pack's orens once per transaction ([byte true][int bundle][int gold]) and refuses anything else. |

## Dead in 1.1.116

| Id | Method | Seen | Client senders | Notes |
| ---: | --- | ---: | --- | --- |
| 2 | GetLocations |  |  | No request class (the enum value is only reused by StaticGameData GET_DATA_URL on its own channel). |
| 14 | GetMonsterInstance |  |  | Request class never built. |
| 15 | GetNestInstance |  |  | Request class never built. |
| 16 | EndNestMonsterCombat |  |  | Response class without subscribers. |
| 17 | EndNestBossCombat |  |  | Response class without subscribers. |
| 32 | BuyPotion |  |  | No request class (replaced by BuyShopBundle 75). |
| 33 | BuyBomb |  |  | No request class (replaced by BuyShopBundle 75). |
| 34 | BuyOil |  |  | No request class (replaced by BuyShopBundle 75). |
| 35 | BuyLure |  |  | No request class (replaced by BuyShopBundle 75). |
| 36 | BuyArmor |  |  | No request class (replaced by BuyShopBundle 75). |
| 37 | BuySword |  |  | No request class (replaced by BuyShopBundle 75). |
| 73 | BuyItem |  |  | No request class. |
| 74 | DropItem |  |  | Request class never built. |
| 82 | AddExp |  |  | Request class never built. |
| 84 | AddExpiringEffect |  |  | Request class never built. |
| 116 | RespawnNest |  |  | Request class never built. |
| 120 | MoveBackStamps |  |  | Request class never built. |
| 121 | ResetDailyQuestsSettings |  |  | Request class never built. |
| 124 | ManageSeasonalQuest |  |  | Request class never built. |

## Answered by the server

| Id | Method | Seen | Client senders | Notes |
| ---: | --- | ---: | --- | --- |
| 3 | GetPlayerInfo | 144 | `PlayerData.OnLevelUp`, `PlayerData.RequestWalletRefresh` |  |
| 4 | CraftItem |  | `BrewerInstance.TryCraftRecipe` | Requires base brewing/oil/bomb skill and any specific recipe unlock; consumes ingredients and saves the output quantity atomically. |
| 5 | GetInventory | 315 | `PlayerInventory.RequestInventorySynchronization` |  |
| 6 | GetKnownRecipes | 74 | `PlayerInventory.RequestAlchemySynchronization` | Returns recipes eligible under the same prerequisites as CraftItem; existing inventory and ongoing crafts remain intact. |
| 7 | GetKilledMonsters |  |  |  |
| 8 | CombatEnd | 1 | `Console.ServerFight`, `FightNode.SendServerEvent`, `FightNode.SendSurrenderRequest` |  |
| 9 | GetEquipment | 9 | `PlayerInventory.RequestEquipmentSynchronization` | The profile's owned and equipped swords and armours (starting gear for new profiles). |
| 10 | PrepareToCombat | 36 | `BehaviourGraphModule.PreNestGraphEnded`, `CombatPreparationNode.HandleCombatPreparationCompleted`, `Console.ServerFight` | Preparation rejects unknown, duplicate or over-capacity potion selections before inventory mutation. |
| 11 | EquipArmor | 1 | `ItemPreviewWindow.TryEquip` | Equips an owned armour and keeps it; refuses others. |
| 12 | EquipSteelSword |  |  | As EquipSword. |
| 13 | EquipSilverSword |  |  | As EquipSword. |
| 18 | UseLure |  | `NestWindow.OnAppliedLureToNest` | A cleared nemeton takes one owned bait whose class has monsters; the nest becomes Lured with that class. The client removes the bait itself. |
| 19 | GatherHerb |  | `HerbOnMapController.<OnClicked>b__16_0` | Two herbs per cell in GetLocationsByCell; gathering gives bundles of herbs (sometimes a root) and hides the herb for an hour. |
| 20 | GetDailyContracts | 1 | `DailyContractsModule.RefreshDailyContracts` |  With Tasks enabled, persisted daily slots and native-shaped progress arrays. |
| 24 | GetAchievements |  | `PlayerInventory.RequestTrophySynchronization` |  Persisted achievement ID/Unix-second pairs; length counts integers. |
| 27 | DistanceTraveled | 1134 | `PlayerController.TrySendServerWalkedDistance` | Legacy/shadow profiles persist the metre delta and replay receipt. Protected profiles refuse positive deltas; all responses retain the authoritative total. |
| 28 | SetCustomizationHead | 2 | `CustomizationHeadSlot.OnToggle` |  |
| 29 | SetName | 1 | `TutorialCharacterPanelController.OnNameSet` |  |
| 30 | SetTutorialFinished |  |  |  |
| 31 | LevelUp |  |  | Pushed after CombatEnd, CombatEndSummonedMonster, EndBehaviourGraph and EndNestCombat for every level reached, with the level rewards (message id 0, no acknowledgement). |
| 39 | ThrowBomb | 2 | `InventorableFightEquipment.OnBombUsed` |  |
| 40 | GetLocationsByCell | 1194 | `Factory.Deserialize`, `PoiModule.LoadCells` | Places, world monsters, herbs, nemeta and the quest givers of the season 1 quests the client offers. |
| 41 | EncounterMonster | 2 | `CombatPreparationNode.SendServerEvent`, `Console.ServerFight` |  |
| 42 | UseSenses |  | `WitcherSensesModule.OnTryDetectMonsters` | Keeps the revealed monsters; a potion that reveals nothing is not spent. |
| 43 | GetSensedMonsters |  |  | Lists the monsters revealed by the senses while they live. |
| 44 | GetCraftingQueue |  |  |  |
| 45 | CancelCrafting |  | `BrewerInstance.TryCancelCrafting` |  |
| 46 | SetGender | 2 | `CustomizationHeadSlot.OnToggle` |  |
| 47 | DropPotion |  | `ItemManagementWindow.OnRemovePressed` |  |
| 48 | DropBomb |  | `ItemManagementWindow.OnRemovePressed` |  |
| 49 | DropOil |  | `ItemManagementWindow.OnRemovePressed` |  |
| 50 | DropLure |  | `ItemManagementWindow.OnRemovePressed` |  |
| 51 | DropSensesPotion |  | `ItemManagementWindow.OnRemovePressed` |  |
| 52 | EncounterNest |  | `NestOnMapController.OnClicked` | One nemeton per cell in GetLocationsByCell; answers today's state, NotAllowed below level 10. |
| 53 | EndNestCombat |  | `BehaviourGraphModule.SurrenderFight`, `EndLostNestFightNode.EnterNode`, `GetNestRewardsNode.EnterNode` | After the third nest fight, a lost one or a surrender: 50 gold for the first three clears of a UTC day, rarity, first-kill, critical-hit, parry and clearing experience, loot, kills; thrown bombs are spent. |
| 55 | EquipSword | 26 | `CombatPreparationController.OnAppliedItemsForCombat`, `CombatPreparationController.TryStartEncounter`, `ItemPreviewWindow.TryEquip` … | Equips an owned sword and keeps it; refuses others. |
| 56 | GetKilledMonsterInstances |  |  |  |
| 57 | EndBehaviourGraph | 75 | `BehaviourGraph.CreateEndBehaviourGraphRequest` | Saves the facts; moves the prologue stages or the season 1 story on (node by instance or copy, journal buttons by output name), with one-time experience, gold, items and story kills. |
| 58 | GetFacts |  |  |  |
| 59 | GetAllFacts |  |  |  |
| 60 | GetActiveQuestNodeInstances | 4 |  | The current stage's node; after "A Joint Venture" the season 1 map nodes whose conditions hold, and queued nodes beside the player. |
| 61 | GetCurrentObjective |  |  |  |
| 62 | SetCurrentObjective |  | `SetQuestObjective.TriggerAction` |  |
| 63 | GetSkills |  |  |  |
| 64 | AcquireSkill | 5 | `PlayerSkills.RequestAcquireSkill` |  |
| 65 | ClaimMonsterKnowledgeReward | 37 | `PlayerData.OnClaimMonsterKnowledgeReward` |  |
| 67 | GetWeather | 557 | `RealWeatherProvider.UpdateWeather` | The real weather of the position's 0.1° cell (Open-Meteo, cached 15 min, positions never logged), as the client's OpenWeatherMap groups; Clear without a source. |
| 68 | ClaimRecipe | 2 | `BrewerInstance.TryClaimCrafted` |  |
| 69 | GetBrewers | 72 | `PlayerInventory.RequestAlchemySynchronization` |  |
| 70 | GetFinishedSeasonQuests |  |  | Finished quests (tutorial, prologue, season 1), the tracked quest and the started season 1 quests. |
| 71 | DropIngredients |  | `ItemManagementWindow.OnRemovePressed` |  |
| 72 | TrackQuest | 21 | `StoryModule.SetTrackedQuest`, `TrackQuestRequest..cctor` | Keeps the tracked season 1 quest. |
| 75 | BuyShopBundle | 9 | `SendBuyBundleRequestStep.SendBuyRequest` |  |
| 77 | RelocateQuest |  | `StoryModule.RelocateQuest` | Plans and atomically persists relocation using hidden per-area givers and fresh place IDs; full active-node response. Invalid/stale requests or no fitting place return empty refusal lists. Dead-horse relocation passed Android acceptance; other stages remain open. See [relocation](../../docs/RELOCATION-20261001.md). |
| 78 | SetFacts | 101 | `Console.SetFact`, `ImmediatelySetFactNode.EnterNode` |  |
| 79 | GetDailyShopBundles | 139 | `ShopStorageModule.SendGetDailyShopBundlesRequest` |  |
| 80 | GetTransactionStatus | 32 | `SendBuyBundleRequestStep.CheckTransactionStatus`, `ValidateReceiptStep.CheckTransactionStatus` |  |
| 83 | GetOneTimeShopBundles | 138 | `InvokeInAppPurchaseStep.CheckOneTimeBundlesBeforePurchase`, `ShopStorageModule.SendGetOneTimeShopBundlesRequest` |  |
| 85 | GetExpiringEffects |  |  |  |
| 87 | GetMonsterInstances | 13 | `PoiModule.RespawnMonsters` |  |
| 88 | LoadCells | 447 | `ClientWorker.WriteLoadCells` |  |
| 89 | UseOilPotions | 62 | `CombatPreparationNode.HandleCombatPreparationCompleted`, `NestUI.HandleStartFakeNest` | Potion capacity follows owned skills 54/58 (one to three slots); invalid selections are refused atomically. |
| 90 | AddPlayerModifier |  | `AddExpiringEffect.TriggerAction` | Keeps the season 1 modifiers (`player_modifiers` rows 1–8) in the profile; refuses unknown ids. |
| 91 | GetPlayerModifiers |  |  | Lists the modifiers that have not expired. |
| 92 | RemovePlayerModifier |  | `RemoveExpiringEffect.TriggerAction` | Removes a held modifier; removing one that is not held succeeds. |
| 93 | AddSkillPoints |  |  |  |
| 94 | GetWeeklyContractProgress |  | `WeeklyContractsModule.Tick` |  |
| 97 | FinishCrafting |  |  |  |
| 98 | BuyAutoEquipItems | 25 | `RecommendedPreparationWindow.InitializePurchase` | Recommended-item purchase applies the same potion capacity and identity checks before spending gold. |
| 100 | DropConsumable |  | `ItemManagementWindow.OnRemovePressed` |  |
| 101 | CheckInApp |  | `<ResolveWindows>d__21.MoveNext` | Answered true (no in-app offer); sent by the level-up windows at the recommended-bundle level. |
| 102 | GetFriends | 6 | `FriendsModule.UpdateFriendsData` |  |
| 103 | AddFriend |  | `FriendsModule.AddFriend` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 104 | AcceptFriendInvitation |  | `FriendsModule.AcceptFriendRequest` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 105 | RejectFriendInvitation |  | `FriendsModule.RejectFriendInvitation` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 106 | SendPack |  | `FriendsModule.SendGift` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 107 | OpenPack |  | `FriendsModule.OpenGift` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 108 | DeleteFriend |  | `FriendsModule.DeleteFriend` | Persistent multi-profile social operation; see [client audit](../../docs/CLIENT-AUDIT-20261002.md). Synthetic coverage; Android acceptance separate. |
| 109 | DropFriendPack |  | `ItemManagementWindow.OnRemovePressed` |  |
| 110 | GetFriendsNotifications | 2066 | `FriendsModule.InitializeModule`, `FriendsModule.OnTimeUpdated` |  |
| 111 | SummonLocalMonsters | 68 | `PoiModule.TrySpawnWitcherAuraMonsters`, `PoiModule.UseSummoningScroll` | Scroll behavior is retained. Skill 29 / type 13 creates one private Aura group with a saved cooldown; missing safe geometry or ownership is refused. |
| 112 | GetSummonedMonsters |  |  |  |
| 113 | EncounterSummonedMonster | 2 | `SummonedCombatPreparationNode.SendServerEvent` |  |
| 114 | CombatEndSummonedMonster |  | `SummonedFightNode.SendServerEvent`, `SummonedFightNode.SendSurrenderRequest` |  |
| 115 | GetInitialPlayerData | 157 | `SynchronizationModule.InitializeModule` | 21 inline parts for legacy profiles, 22 for reconstructed profiles including method 112. Both include method 117, required by Aura startup synchronization. |
| 117 | GetLastSummoningSkillUsageTime | 14 | `WitcherAuraController.Synchronize` | Returns the persisted Aura last-use Unix timestamp, matching the native cooldown consumer; zero before first use. Included in RPC 115 with the same result-byte/int32 body; reading it does not summon a monster. |
| 118 | DropSummoningScroll |  | `ItemManagementWindow.OnRemovePressed` |  |
| 119 | ResolveRewards | 134 | `RewardsModule.CheckRewards` |  |
| 122 | GetMonsterEventProgress |  | `SeasonContractsModule` | With Tasks enabled, active event progress or successful empty-event ID −1; legacy disabled mode keeps its failure fixture. |
| 21 | AddDailyContract | 24 | `DailyContractsModule.SyncDailyContracts` | With Tasks enabled, issues remaining daily slots and returns active IDs; unfinished tasks survive midnight. |
| 22 | ReshuffleDailyContract |  | `DailyContractsModule.ReshuffleContract` | One replacement per UTC day, returning the new ID; typed refusal otherwise. |
| 23 | RemoveDailyContract |  | `DailyContractsModule.RemoveDailyContract` | Removes the ID without replenishing the daily allowance. |
| 25 | AchievementReceived |  |  | With Tasks enabled, announces newly earned trinkets after gameplay. Boot/query synchronization uses RPC24. |
| 81 | ClaimDailyQuest |  | `DailyContractsModule.ClaimContract`, `SeasonContractsModule.ClaimSubContract` | Atomically claims a complete daily or timed task once. Returns resulting wallet and matching quest type on success or refusal. |
| 86 | AddSpecifiedContract |  | `DailyContractsModule.AddContract` | Explicit typed refusal; arbitrary task issuance is not supported. |
| 95 | ClaimWeeklyQuest |  | `WeeklyContractsModule.SendWeeklyClaimRequest` | Five stamps grant the owned basic scroll once. Nine-byte success/refusal body with reward IDs. |
| 123 | ClaimMonsterEvent |  | `SeasonContractsModule.Claim` | Once-only final reward for an active completed event; gold is a delta. The supplied schedule includes the [first LAB timed event](../../docs/TIMED-EVENT-20261001.md). |
| 125 | SynchronizeEvents |  | `SeasonContractsModule.Tick` | With Tasks enabled, succeeds to request RPC122, including the no-event clearing response. |

## LAB extension: timestamped distance

Method **2001** is an authored [GPS companion contract](../../docs/GPS-PANEL-20261003.md), not a recovered member of the original `Api.Method` enum or the counts above. It carries HELLO, bounded timestamped fix batches and acknowledgements on the authenticated API channel. LAB 24 consumes only its own extension responses before the original unknown-method decoder. Profile protection changes the credit source while preserving RPC 27's total-response layout.
