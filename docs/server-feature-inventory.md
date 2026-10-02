# Server feature inventory

What the original backend served, what `WitcherRevival.Server` serves today, and what is still missing.
Use it as the restoration checklist: update a row's status when a feature lands.

The original server is gone, so this list was rebuilt (2026-10-03) from the client itself:
- the `Api.Method` enum and every request/response class in `tools/dump/dump.cs` (118 API methods);
- the static-data `Container` DTOs (82 tables);
- the Addressables catalog (`tools/dump/catalog.json`) and the story bundles in the OBB, for how much content exists.

Wire formats live in [protocol-reference.md](protocol-reference.md), DTO and content details in
[api-and-content-reference.md](api-and-content-reference.md), and RVAs in [memory-map.md](memory-map.md).

**Status legend**

| | Meaning |
|---|---|
| ✅ | Real: behaves like the original, and state is persisted where it matters. |
| 🟡 | Stub: a valid reply with fixed or empty data; nothing is persisted. |
| 🔴 | Missing: no handler. It gets the 1-byte `BooleanResponse(true)` catch-all, which under-runs any reader expecting more, so the feature errors out client-side. |
| *live* | Seen in a live session's server log. |

---

## 1. Infrastructure

| Piece | What the original did | Ours | Status |
|---|---|---|---|
| Gatekeeper (HTTP) | `GatekeeperResponse {Type, Message, EndTime, Address, WitcherId}`: server status, maintenance window, game-server address, player id | Catch-all in `Program.cs` returns "OK" plus the LAN address | 🟡 no maintenance or version messages |
| Game socket (TCP 4253) | Channels Api (1), Logging (2), Authentication (3), StaticGameData (4) | All four accepted; Logging is ignored | ✅ |
| Authentication | `[apiVersion=15][clientVersion][deviceId][accountId]` → result code | Always succeeds | 🟡 one implicit player, no accounts |
| Static data | gzip JSON `Container` (82 tables), from a CDN URL (`GET_DATA_URL`) or inline (`FETCH`) | `/staticdata` and inline | 🟡 13 of 82 tables filled (§2) |
| Map tiles | Google Maps Gaming SDK vector tiles (Google's service) | `hook.js` redirects them to `/v1/featuretiles/*`, which returns an empty tile | 🟡 no roads or water drawn |
| Ping (141, not in the `Method` enum) | Keep-alive | Replies true | ✅ |
| Server-pushed events | Responses with no request class, sent unprompted: `AchievementReceived (25) {Achievement}`, `DailyContractCompleted (26) {Contract}`, `LevelUp (31)`, `EndNestMonsterCombat (16) {Loot}`, `EndNestBossCombat (17) {Success, Loot}` | Never sent | 🔴 |
| Analytics / crash reporting | Firebase, GameAnalytics (third party) | Not needed | — |

## 2. Static data (82 tables)

The client looks things up by id and often calls `GetFirst()`, so an empty or missing entry crashes features
lazily. Two examples, both fixed on 2026-10-03:
- bomb 401 missing → the dead_horse fight threw `KeyNotFoundException`;
- empty `senses_potions` → zooming the map out (Witcher Senses view) stuck.

JSON keys are the hidden DataMember `Name=` snake_case strings, not the C# names below. To read one, run
`python tools/ghidra_decomp.py <attribute RVA>`; it shows a C string `UNK_xxx` (Ghidra base +0x100000).
**No original data survives**, so ids and stats have to be reconstructed. Slugs must match the client's assets.

### Filled today (13)

| Table (JSON key) | Served | Client assets available |
|---|---|---|
| `swords` | 6 | 18 sword models |
| `armors` | 6 | 8 armor sets |
| `customization_heads` | 3 | 4 heads |
| `bombs` | 1 (id 401 = `bomb_basic`, id guessed) | 5 bombs |
| `senses_potions` | 1 (`senses_potion_falcon`) | 1 |
| `skills` / `skill_requirements` | 8 / 5 | 49 skills |
| `monsters` / `monster_descriptions` | 8 / 24 | ~130 monster variants, 138 trophies |
| `monster_families` | 11 (complete) | 11 |
| `achievements` | 6 | ≥24 achievement names referenced in code |
| `level_ups` | 10 | curve unknown |
| `difficulties` | 3 | 8 tiers (`tier_1..8`) |

### Empty (69), grouped by feature

| Feature | Tables (C# DTO fields) |
|---|---|
| Consumable items | `potions` (Id, Slug, Priority, AutoEquipPrio), `oils` (… XPMatching), `lures`, `ingredients`, `consumables` / `summoning_scrolls` (… Duration), `pack_types` |
| Effects | `effects` (Id, Name, EffectTypeId), `effect_types`, `effect_apply_types`, `potion_to_effect` / `oil_to_effect` / `sword_to_effect` / `armor_to_effect` / `skill_to_effect` / `player_modifier_to_effect` (ItemId, EffectId, Power, ApplyTime) |
| Damage | `damage_types` (Id, Slug, Power), `bomb_damage_types` (BombId, DamageTypeId, Amount), `monster_vulnerabilities` (MonsterId, DamageTypeId) |
| Player modifiers | `player_modifiers`, `consumables_player_modifiers`, `summoning_scrolls_player_modifiers` |
| Alchemy | `brewers` (Id, Slug, Uses, TimeCoefficient), `recipe_tiers`, `potion/oil/lure/bomb/senses_potion_recipes` (Id, Slug, Output, TierId, CraftingTime, Priority), the 5 matching `*_recipe_ingredients` (RecipeId, IngredientId, Amount), `effect_unlock_potion_recipes` / `effect_unlock_lure_recipes`, `herbs` (Id, Slug, PrefabPath) |
| Quests | `quests` (Id, SeasonId, Name, JournalLog, ActivationCriteria), `quest_edges`, `quest_nodes` (Id, QuestId, Name, ActivationCriteria), `quest_node_edges` (From, To), `quest_node_outputs` (Id, QuestNodeId, Name, EndPoint), `seasons` |
| Contracts | `contracts` (Id, ContractTypeId, Value1-3), `contract_actions` / `contract_crafts` / `contract_combat_usages` / `contract_monsters` / `contract_quests` / `contract_skills`, `daily_quests` (Id, Slug, Reward, ContractId), `weekly_quests_rewards` |
| Shop & IAP | `shop_bundles` (Id, GoldPrice, Discount, Permanent, LayoutPriority, OneTime, Dev, InAppPriceId, Name, Icon, Description, LayoutType, LayoutUnderlay), `shop_bundles_layout_group_name_categories`, `shop_bundle_items`, `shop_potions/bombs/oils/lures/senses_potions/armors/swords` (ItemId, Price), `inapp_prices`, `inapp_price_shops`, `auto_equip` (per-condition attack bonuses), `auto_equip_items_prices` |
| Config & misc | `game_configuration` (ParamName, ParamValue), `player_starting_skills`, `item_hints` |

## 3. API methods (118) by feature

"Req → Resp" gives the shape from `dump.cs`; `{}` means no extra fields.

### Account & profile

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 115 | GetInitialPlayerData | `{}` → 19 sub-responses | ✅ *live* | Keep the batch in sync with every module that reads it |
| 3 | GetPlayerInfo | `{}` → Name, Gold, Exp, Head, TutorialFinished, Gender | 🟡 *live* | Serve a persisted profile (currently "Geralt", 5000 gold, 4500 exp) |
| 29 | SetName | name → IntResponse | 🔴 | Persist the name |
| 46 | SetGender | byte → IntResponse | 🔴 | Persist the gender |
| 28 | SetCustomizationHead | head id → IntResponse | 🟡 echo | Persist the head |
| 30 | SetTutorialFinished | `{}` → IntResponse | 🟡 echo | Persist the flag (currently config `Player:TutorialFinished`) |
| 27 | DistanceTraveled | metres → total | 🟡 constant 15000 | Accumulate (stats, achievements) |
| 38 / 82 | AddGold / AddExp | amount → new total | 🔴 | Probably dev or reward paths; apply and persist |
| 31 | LevelUp | pushed | 🔴 | Push when exp crosses a `level_ups` threshold |

### Inventory & items

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 5 | GetInventory | `{}` → 9 dicts (ingredients, bombs, potions, oils, lures, senses potions, consumables, friend packs, scrolls) + BagSize | 🟡 *live*, empty | Persist inventory |
| 119 | ResolveRewards | int → Success, List<Item> | 🟡 *live*, empty | Deliver pending rewards (polled about every 7 s) |
| 47-51 | DropPotion / DropBomb / DropOil / DropLure / DropSensesPotion | (id, amount) → (id, amount) | 🔴 | Remove from inventory |
| 71, 74, 100, 109, 118 | DropIngredients / DropItem (type, id, amount) / DropConsumable / DropFriendPack / DropSummoningScroll | same pattern | 🔴 | Same |

### Equipment

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 9 | GetEquipment | `{}` → owned swords/armors + equipped | 🟡 batch, hardcoded | Persist the loadout |
| 11 / 55 | EquipArmor / EquipSword | id → id | 🟡 echo | Persist |
| 12 / 13 | EquipSteelSword / EquipSilverSword | no classes in this client build | 🟡 echo | Probably legacy |
| 98 | BuyAutoEquipItems | combat loadout → Boolean | 🔴 | Charge gold, grant items (`auto_equip_items_prices`) |

### Alchemy & crafting

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 6 | GetKnownRecipes | `{}` → Dict<int, HashSet<int>> | 🟡 batch, empty | Persist known recipes |
| 69 | GetBrewers | `{}` → Success, List<Brewer> | 🟡 batch, empty | Serve the player's brewers |
| 4 | CraftItem | BrewerInstanceId, … → ? | 🔴 | Start crafting (consume ingredients) |
| 44 | GetCraftingQueue | `{}` → List<CraftSlot> | 🔴 | Timed crafting queue |
| 45 / 97 | CancelCrafting / FinishCrafting | → Boolean | 🔴 | Queue management, grant outputs |
| 68 | ClaimRecipe | → ? | 🔴 | Unlock a recipe |
| 19 | GatherHerb | → ? | 🔴 | Grant ingredients for a herb placement (see 40) |

### Map & world

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 40 | GetLocationsByCell | S2 cell ids → Success, LocationMap, MonsterPlacements, HerbPlacements, QuestNodeInstancePlacements, NestPlacements | 🟡 *live*, all empty | **Populates the world**: spawn monsters, herbs and nests per S2 cell. Nothing appears on the map until this is done. |
| 88 | LoadCells | S2 cell ids → Boolean | 🟡 *live* | Usually precedes 40 |
| 67 | GetWeather | lat, lng → WeatherCode | 🟡 *live*, always Clear | Real weather (affects day/night/weather-dependent combat via `auto_equip`) |
| 14 / 87 | GetMonsterInstance(s) | → ? | 🔴 | Monster instance details |
| 54 | SpawnMonster | lat, lng, type, level, ttl → Success, InstanceId | 🔴 | Debug or scripted spawns |
| 15 / 116 | GetNestInstance / RespawnNest | → ? / Boolean | 🔴 | Nest lifecycle |
| 2 | GetLocations | no classes in this build | — | Legacy; the client logs "no handler" |

### Combat, monsters & Witcher Senses

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 41 | EncounterMonster | instance id → Boolean | 🔴 | Validate and lock the encounter |
| 10 | PrepareToCombat | loadout → ? | 🔴 | Consume prepared items |
| 8 | CombatEnd | → BaseExp, ComboExp, OilExp, TimeExp, PerfectParryExp, FirstTimeExp, BoostedExp, PackType, Loot | 🔴 | **Exp and loot after every fight**, kill tracking |
| 39 | ThrowBomb | bomb id → count | 🔴 | Consume a bomb |
| 89 | UseOilPotions | → Boolean | 🔴 | Consume oils/potions |
| 7 | GetKilledMonsters | `{}` → kills per monster, claimed knowledge tiers | 🟡 batch, hardcoded | Persist kills (bestiary) |
| 56 | GetKilledMonsterInstances | `{}` → List<long> | 🟡 batch, empty | Hide killed map monsters |
| 65 | ClaimMonsterKnowledgeReward | MonsterId → Success, MonsterId, SkillPoints | 🔴 | Bestiary tier rewards |
| 42 / 43 | UseSenses / GetSensedMonsters | potion id, monsters → Success / List<long> | 🔴 / 🟡 empty | Map-wide monster sensing (separate from the investigation minigame) |

### Nests & summoning

| ID | Method | Req → Resp | Status |
|---|---|---|---|
| 52 | EncounterNest | instance id → NestStateResponse | 🔴 |
| 18 | UseLure | → NestStateResponse | 🔴 |
| 53 | EndNestCombat | Win, InstanceId → Success, Loot, Reward, exp breakdown | 🔴 |
| 16 / 17 | EndNestMonsterCombat / EndNestBossCombat | pushed: Loot / Success, Loot | 🔴 |
| 111 / 112 | SummonLocalMonsters / GetSummonedMonsters | → List<LocalMonstersEntity> | 🔴 |
| 113 / 114 | EncounterSummonedMonster / CombatEndSummonedMonster | instance id → Boolean / exp breakdown | 🔴 |
| 117 | GetLastSummoningSkillUsageTime | → int | 🔴 |

### Quests & story

| ID | Method | Req → Resp | Status | Server needs to |
|---|---|---|---|---|
| 57 | EndBehaviourGraph | (instanceId, output, facts) → Success, Locations, QuestNodeInstances, Exp, Gold, 7 item dicts, Armors, Swords, Expiring | ✅ *live* | Done: facts, step progress and the next node. **Rewards are still zero** (e.g. Thorstein's oil). |
| 58 / 59 / 78 | GetFacts / GetAllFacts / SetFacts | | ✅ *live* | Persisted in `data/facts.json` |
| 60 | GetActiveQuestNodeInstances | `{}` → Locations, QuestNodeInstances, Expiring | ✅ batch | Serves the S00 prolog_01 chain (§4) with a per-step `PoiDisplayMode` (1 Normal, 2 CloseFollow, 3 FarFollow, 4 Hunt, 5 Auto, 6 Hidden, 7 Collecting): CloseFollow for Thorstein and dead_horse, Hunt (search circle) for footprints and tracks, Normal for the griffin; the originals' values are unknown. Steps spawn at the fixed dev coordinates `TutLat/TutLng`, so walk there or fake GPS. |
| 70 | GetFinishedSeasonQuests | `{}` → CurrentSeason, FinishedQuests, TrackedQuestId, ActiveQuestIdList | 🟡 batch: season 0, ids 0..299 active | Real season/quest state |
| 61 / 62 | Get/SetCurrentObjective | string | 🟡 empty / 🔴 | Persist the objective text |
| 72 | TrackQuest | quest id → id | 🟡 echo | Persist the tracked quest |
| 77 | RelocateQuest | instance id → Success, Locations, QuestNodeInstances, Expiring | 🔴 | Move a quest POI near the player; would remove the need to fake GPS |
| 81 / 95 | ClaimDailyQuest / ClaimWeeklyQuest | no classes in this build | — | |

### Contracts (daily / weekly)

| ID | Method | Status |
|---|---|---|
| 20 GetDailyContracts | Success, ?, CanAdd, CanReshuffle, Contracts | 🟡 empty |
| 21 / 22 / 23 Add / Reshuffle / RemoveDailyContract | | 🔴 |
| 26 DailyContractCompleted | pushed {Contract} | 🔴 |
| 86 AddSpecifiedContract | | 🔴 |
| 94 GetWeeklyContractProgress | Success, LastStampAcquiredDate, Stamps | 🟡 empty |
| 96 AddWeeklyStamps | | 🔴 |

### Achievements, skills & levelling

| ID | Method | Req → Resp | Status |
|---|---|---|---|
| 24 | GetAchievements | Success, Dict (count = number of **ints**, not pairs) | 🟡 batch, 2 hardcoded |
| 25 | AchievementReceived | pushed {Achievement} | 🔴 |
| 63 | GetSkills | Skills, SkillPoints | 🟡 batch, hardcoded |
| 64 | AcquireSkill | Skill → Success, Skill | 🟡 echo, not persisted |
| 93 | AddSkillPoints | int → total | 🟡 arithmetic, not persisted |

### Effects, modifiers & consumables

| ID | Method | Status |
|---|---|---|
| 84 / 85 AddExpiringEffect / GetExpiringEffects | | 🔴 / 🟡 empty |
| 90 / 91 / 92 Add / Get / RemovePlayerModifier | | 🔴 / 🟡 empty / 🔴 |
| 99 UseConsumable | id → (id, count) | 🔴 |

### Shop & in-app purchases

| ID | Method | Status |
|---|---|---|
| 79 / 83 GetDailyShopBundles / GetOneTimeShopBundles | Success, List<int> | 🟡 *live*, empty |
| 75 BuyShopBundle | (bundle, ?) → (?, ?) | 🔴 |
| 80 GetTransactionStatus, 101 CheckInApp (`CheckInAppStatusRequest/Response`) | Google Play billing | 🔴; real IAP can't be revived, so make bundles gold-only or free |
| 32-37 Buy{Potion, Bomb, Oil, Lure, Armor, Sword}, 73 BuyItem, 76 BuyInAppBundle | no request/response classes in this build | — |

### Friends & packs

| ID | Method | Status |
|---|---|---|
| 102 GetFriends | CurrentPlayerId, Friends, PlayerStateChanges | 🟡 empty |
| 110 GetFriendsNotifications | invites, accepted, packs, state changes | 🟡 *live*, empty, polled |
| 103 / 104 / 105 / 108 Add / Accept / Reject / DeleteFriend | long → (bool, long) | 🔴 |
| 106 / 107 SendPack / OpenPack | | 🔴 |

### Misc

| ID | Method | Status |
|---|---|---|
| 66 | Log (plus `LogImpressions`/`LogPlayerReports` classes) | 🔴; the Logging channel is ignored too |

## 4. Quest content shipped in the client

151 quest graphs, 97 investigation assets, 446 dialog assets, 209 cutscene assets, 66 POI settings.

**Story order: `s00/tutorial` → `s00/prolog` prolog_01 → prolog_02 → `s01`.** Three independent signals in the
graph data agree:

| Signal | tutorial | prolog_01 | prolog_02 | S01 |
|---|---|---|---|---|
| Tracked quest id (`Set Tracked Quest`; journal step = fact `10000 + id`) | 144 | 145 | 146 | 147-161 (+104) |
| Chapter counter **fact 102**, set at the chapter's end | 1 (`tut_gravehag` / `tut_exit`) | 2 (`griffin`) | 3 (`gargoyle`) | 4 (`s01mq01_scholar_02`) |
| Story flag **fact 107** | — | 1 (`thorstein`), 2 (`griffin`) | 3 (`qi_map_button`), 4 (`obelisk`) | — |

**Fact 3 is the client's "tutorial finished" flag.** `Tutorial.CheckTutorial` (0x1F9A10C) reads it at boot: if it
is non-zero it unlocks the gated features (`ToggleTutorialFeatures`); otherwise it waits for fact updates. Only
the tutorial's end sets it (`tut_gravehag` "exam_end" and `tut_exit` set facts 2=1, 3=1, 102=1). Our server
starts players at Thorstein and seeds fact 2=1 but never sets 3, which is very likely why the bottom menu and
info screens never appear.

| Chapter | Graphs | Status |
|---|---|---|
| `s00/tutorial` (quest 144, "the witcher exam"): `tut_witcher` (instance 1271842437439635223, POI `s00/tutorial/tutorial_witcher_lq`), `tut_ghoul` (1152921521786716388, POI `ghoul_lq`), `tut_gravehag` (1152921521786716389, cutscene `cs_tutorial_witcher`, ends `exam_end`/`exam_fail`), `tut_empty` (2547305230505251704, outputs `devourer`/`empty_end`, POI `devourer_lq`?), `tut_exit` (skip path), plus fight sub-graphs `tut_ui`, `tut_dummy_1..3` | 9 | 🔴 not served (a fresh player starts at Thorstein); exact step order inside the chapter unknown |
| `s00/prolog` prolog_01 (quest 145): `thorstein → footprints_01 → tracks_01 → tracks_02 → dead_horse → tracks_03 → griffin` (+ `tracking`, a re-route helper with outputs `tracking`/`CT_horse`/`CT_gryphon`) | 8 | ✅ served in this order. thorstein and dead_horse are live-verified (dead_horse has 3 endings: `dead_horse`/`1ghoul_left`/`2ghouls_left`); later steps untested. The order comes from journal fact 10145, which each graph sets to 1,1,2,3,4,5,6 along it. |
| `s00/prolog` prolog_02 (quest 146): `qi_map_button` (journal 2, fact 107=3) → `obelisk` (journal 3, 107=4) → `crown` / `heart` / `sword` in any order (facts 97 / 99 / 98) → `gargoyle` (requires all three; sets 102=3, 70=2, clears 10145); `map` is a re-route helper (`CT_obelisk`/`CT_gargoyle`) | 7 | 🔴 not served |
| `s01` (quests 147-161): hq01 sword_in_stone, hq02 nests, hq03 blacksmith, hq04 firefly, hq05 bandit_and_devourer, hq06 trolling, mq01 scholar, mq02 cure, mq03 striga, mq04 cursed_one, mq05 mushroom_hunt, mq06 frightener, plus `quest_item_buttons` and a `s01_chickentest` test graph. Main (hq) and side (mq) quests likely run in parallel; fact 70 is reused across them as a shared state value. | 127 | 🔴 |

Extracted so far: the `s00_story_*` bundles and `s01_story_graphs_assets_all.bundle` (`tools/apk_extracted/bundles/`;
each comes out of the OBB's `assets/aa/Android/`). Read any graph with
`python tools/unity_extract/bundle_explorer.py graph <bundle> <name>`.

## 5. Suggested order of work

1. **Start fresh players in the tutorial** (quest 144) instead of at Thorstein, and stop pre-seeding fact 2. Its end sets fact 3, which unlocks the bottom menu.
2. **Rewards and inventory persistence**: EndBehaviourGraph rewards (Thorstein's oil needs `oils` static data), `CombatEnd` (8), and persisted `GetInventory`/`GetEquipment`/profile. The griffin fight needs these.
3. **Finish S00**: test `tracks_03 → griffin`, then serve prolog_02 in the order in §4 (the crown/heart/sword steps run in parallel, so the server must offer all three at once).
4. **World population**: `GetLocationsByCell` (40) monsters, herbs and nests, plus `EncounterMonster`/`CombatEnd` for free roam.
5. **Static data**: fill tables from the client's slugs; ids and stats are reconstructions.
6. Alchemy, contracts, shop (gold-only), achievements, then friends and summoning.
