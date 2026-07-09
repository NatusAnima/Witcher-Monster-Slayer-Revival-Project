 the

# TWMS — Api Methods, Response Wire Formats & Static-Data Content Reference

> Companion to `docs/protocol-boot.md`. Captures the reverse-engineering findings from the
> **content bring-up session (2026-07-04)**: the full Api `Method` enum, decoded `*Response`
> wire formats, the static-data `Container` element DTOs, the tutorial flow, `BehaviourGraphModule`,
> the screen→module map, and the server/client changes made this session.
> All line numbers refer to `dump/arm64_v1043/dump.cs` (IL2CPP v1.0.43, type-only dump — no method
> bodies, so **field/ctor declaration order == big-endian serialize order**, confirmed against the
> already-working boot batch).

---

## 0. The central finding — why the screens were empty

The feature screens (**Equipment, Statistics, Achievements, Skills, Bestiary**) send **NO Api request
when opened**. They inject already-synced models (`PlayerData` / `PlayerInventory` / `IPlayerSkills` /
`BestiaryKnowledge`) that were populated at boot by the `GetInitialPlayerData(115)` batch, plus the
static-data `Container`, and just read them. They stay live via push signals (`AchievementReceivedResponse`,
`AcquireSkillResponse`, `SkillUnlocked`, …), not polling.

**Consequence:** the screens render empty **only** because (a) the 82 `Container` arrays were all emitted
`[]` (no item/monster/skill/achievement *definitions*) and (b) the initial player batch owned almost nothing.
Making the screens show content is therefore **pure data population** — no new request/response plumbing is
needed for *display*. New handlers are only needed for **user actions** (equip, acquire skill, tutorial) and
the periodic `DistanceTraveled(27)` telemetry.

Evidence (screen controllers, all under the already-un-bypassed `GuiModule`):
`CharacterPanelController` (662186, injects `IPlayerInventory`), `CharacterDetailsPanel` (661975),
`CharacterItemsPanel` (662023), `SkillTreePanel` (657386, injects `IIntStorage<Skill>` + `IPlayerSkills`),
`Bestiary` (665374), `BestiaryKnowledge` (665844, `FillInitialData(GetKilledMonstersResponse)` @665884).
There is **no** standalone Achievements or Statistics panel — `AchievementWindow` (650764) is only the
trophy-unlock toast; achievements/stats are sub-views of Character/Bestiary fed from `PlayerData`.

---

## 1. Full Api `Method` enum (dump.cs 595483)

| id | name                   | id | name                        | id | name                        | id  | name                           |
| -- | ---------------------- | -- | --------------------------- | -- | --------------------------- | --- | ------------------------------ |
| 2  | GetLocations           | 33 | BuyBomb                     | 64 | AcquireSkill                | 95  | ClaimWeeklyQuest               |
| 3  | GetPlayerInfo          | 34 | BuyOil                      | 65 | ClaimMonsterKnowledgeReward | 96  | AddWeeklyStamps                |
| 4  | CraftItem              | 35 | BuyLure                     | 66 | Log                         | 97  | FinishCrafting                 |
| 5  | GetInventory           | 36 | BuyArmor                    | 67 | GetWeather                  | 98  | BuyAutoEquipItems              |
| 6  | GetKnownRecipes        | 37 | BuySword                    | 68 | ClaimRecipe                 | 99  | UseConsumable                  |
| 7  | GetKilledMonsters      | 38 | AddGold                     | 69 | GetBrewers                  | 100 | DropConsumable                 |
| 8  | CombatEnd              | 39 | ThrowBomb                   | 70 | GetFinishedSeasonQuests     | 101 | CheckInApp                     |
| 9  | GetEquipment           | 40 | GetLocationsByCell          | 71 | DropIngredients             | 102 | GetFriends                     |
| 10 | PrepareToCombat        | 41 | EncounterMonster            | 72 | TrackQuest                  | 103 | AddFriend                      |
| 11 | EquipArmor             | 42 | UseSenses                   | 73 | BuyItem                     | 104 | AcceptFriendInvitation         |
| 12 | EquipSteelSword        | 43 | GetSensedMonsters           | 74 | DropItem                    | 105 | RejectFriendInvitation         |
| 13 | EquipSilverSword       | 44 | GetCraftingQueue            | 75 | BuyShopBundle               | 106 | SendPack                       |
| 14 | GetMonsterInstance     | 45 | CancelCrafting              | 76 | BuyInAppBundle              | 107 | OpenPack                       |
| 15 | GetNestInstance        | 46 | SetGender                   | 77 | RelocateQuest               | 108 | DeleteFriend                   |
| 16 | EndNestMonsterCombat   | 47 | DropPotion                  | 78 | SetFacts                    | 109 | DropFriendPack                 |
| 17 | EndNestBossCombat      | 48 | DropBomb                    | 79 | GetDailyShopBundles         | 110 | GetFriendsNotifications        |
| 18 | UseLure                | 49 | DropOil                     | 80 | GetTransactionStatus        | 111 | SummonLocalMonsters            |
| 19 | GatherHerb             | 50 | DropLure                    | 81 | ClaimDailyQuest             | 112 | GetSummonedMonsters            |
| 20 | GetDailyContracts      | 51 | DropSensesPotion            | 82 | AddExp                      | 113 | EncounterSummonedMonster       |
| 21 | AddDailyContract       | 52 | EncounterNest               | 83 | GetOneTimeShopBundles       | 114 | CombatEndSummonedMonster       |
| 22 | ReshuffleDailyContract | 53 | EndNestCombat               | 84 | AddExpiringEffect           | 115 | GetInitialPlayerData           |
| 23 | RemoveDailyContract    | 54 | SpawnMonster                | 85 | GetExpiringEffects          | 116 | RespawnNest                    |
| 24 | GetAchievements        | 55 | EquipSword                  | 86 | AddSpecifiedContract        | 117 | GetLastSummoningSkillUsageTime |
| 25 | AchievementReceived    | 56 | GetKilledMonsterInstances   | 87 | GetMonsterInstances         | 118 | DropSummoningScroll            |
| 26 | DailyContractCompleted | 57 | EndBehaviourGraph           | 88 | LoadCells                   | 119 | ResolveRewards                 |
| 27 | DistanceTraveled       | 58 | GetFacts                    | 89 | UseOilPotions               |     |                                |
| 28 | SetCustomizationHead   | 59 | GetAllFacts                 | 90 | AddPlayerModifier           |     |                                |
| 29 | SetName                | 60 | GetActiveQuestNodeInstances | 91 | GetPlayerModifiers          |     |                                |
| 30 | SetTutorialFinished    | 61 | GetCurrentObjective         | 92 | RemovePlayerModifier        |     |                                |
| 31 | LevelUp                | 62 | SetCurrentObjective         | 93 | AddSkillPoints              |     |                                |
| 32 | BuyPotion              | 63 | GetSkills                   | 94 | GetWeeklyContractProgress   |     |                                |

**`Ping` is NOT in this enum** — it is a distinct message type, not an Api Method. The server's old
`M_Ping=141` constant is a no-op that the catch-all covers.

---

## 2. Response wire formats (decoded)

Codec (matches `Protocol/ByteBuffer.cs`, all big-endian): `bool`=1B, `byte`=1B, `int`=4B, `long`=8B,
`string`=`[int len][utf8]`, `List<T>`=`[int count][elem×count]`, `Dictionary<K,V>`=`[int count][(K,V)×count]`.

Three shared base response classes: `IntIntResponse` (596139), `IntLongResponse` (596182),
`IntResponse` (596225). **`IntResponse` = `[byte Result][int Param]`.**

| Response (Method)                 | dump   | Wire layout (declaration order)                                                                                                                                                                                                                                                                                                                                                                                           |
| --------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GetPlayerInfoResponse (3)         | 599255 | `[byte Success][string Name][int Gold][int Exp][int Head][byte TutorialFinished][byte Gender]`                                                                                                                                                                                                                                                                                                                          |
| GetInventoryResponse (5)          | 598945 | 9`Dictionary<int,int>` in order: Ingredient, Bomb, Potion, Oil, Lure, SensesPotion, Consumables, FriendsPacks, SummoningScrolls; then `[int BagSize]`                                                                                                                                                                                                                                                                 |
| GetKnownRecipesResponse (6)       | 599…  | `[int outerCount]` then per entry `[int key][int innerCount][int×inner]`                                                                                                                                                                                                                                                                                                                                             |
| GetKilledMonstersResponse (7)     | 599096 | `[int count][(int monsterId,int count)…]` then `[int ClaimedTiers count][(int,int)…]`                                                                                                                                                                                                                                                                                                                               |
| GetEquipmentResponse (9)          | 598596 | `[int SwordsCount][int×swords][int ArmorsCount][int×armors][int EquippedArmor][int EquippedSword]`                                                                                                                                                                                                                                                                                                                    |
| EquipArmorResponse (11)           | 598075 | IntResponse`[byte Result][int Param=armorId]`                                                                                                                                                                                                                                                                                                                                                                           |
| GetAchievementsResponse (24)      | 598218 | `[byte Success][int count][(int achievementId,int value)…]`                                                                                                                                                                                                                                                                                                                                                            |
| DistanceTraveledResponse (27)     | 597366 | IntResponse`[byte Result][int Param=distance]`                                                                                                                                                                                                                                                                                                                                                                          |
| SetCustomizationHeadResponse (28) | 600160 | IntResponse`[byte Result][int Param=headId]`                                                                                                                                                                                                                                                                                                                                                                            |
| SetTutorialFinishedResponse (30)  | 600268 | IntResponse`[byte Result][int Param]`                                                                                                                                                                                                                                                                                                                                                                                   |
| EndBehaviourGraphResponse (57)    | 597848 | `[byte Success]` + 7×`Dict<int,int>` + `List<int>` Armors + `List<int>` Swords + `[int Exp][int Gold]` + `List<Location>` + `List<QuestNodeInstance>` + `Dict<long,int>` — **read order unproven** (Factory.Deserialize @0x31DE4BC not disassembled); an all-zero reply is byte-identical under both plausible orders, so it's safe as a stub but must be byte-verified before granting real loot |
| GetSkillsResponse (63)            | 599424 | `[int count][int×skillIds][int SkillPoints]` — Skills is `List<int>` of ids, **no DTO**                                                                                                                                                                                                                                                                                                                       |
| AcquireSkillResponse (64)         | 596425 | `[byte Success][int Skill]`                                                                                                                                                                                                                                                                                                                                                                                             |
| EquipSwordResponse (55)           | 598102 | IntResponse`[byte Result][int Param=swordId]`                                                                                                                                                                                                                                                                                                                                                                           |
| AddSkillPointsResponse (93)       | 596686 | IntResponse`[byte Result][int Param=newTotal]`                                                                                                                                                                                                                                                                                                                                                                          |

**No nested DTO** appears in any response above (all lists are `List<int>`, all dicts `Dictionary<int,int>`).
For contrast, responses that *do* carry DTOs (not needed this round): `GetPlayerModifiersResponse` →
`List<ExpiringPlayerModifier>`, `GetSummonedMonstersResponse` → `List<LocalMonstersEntity>`.

**Request layouts** (needed to echo ids in action handlers): `IntRequest` payload = `[int Param]`
(single int; body not in dump but only plausible shape). `SetTutorialFinishedRequest` (602627) has **no
fields**. `AcquireSkillRequest` (601302) = `[int Skill]`. `EquipSteelSword(12)`/`EquipSilverSword(13)`
have **no `*Request` class** in the dump — treated as IntRequest-shaped with a fallback id.

---

## 3. Static-data `Container` element DTOs

`Container` @ **692933**. JSON keys are the `[DataMember(Name=…)]` snake_case values (DCJS matches on
these, **not** the C# field names — Il2CppDumper hides the `Name=` arg). The 82 top-level array keys are
already listed in `server/…/PreloaderStaticData.cs`. Element DTOs below — **every field is a scalar
`int` / `string` / `Nullable<int>`; no nested objects or arrays**; relationships are flat FK ints.

| DTO (array)                                                   | dump   | Fields → JSON key                                                                                                                                         |
| ------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Achievement** (`achievements`)                      | 693109 | `id`, `slug`, `contract_id`                                                                                                                          |
| **Monster** (`monsters`)                              | 693760 | `id`, `family_id`, `encounter_distance`, `attack_animation_time`, `rarity`, `difficulty`, `name`, `model`, `image`, `trophy`, `slug` |
| **MonsterDescription** (`monster_descriptions`)       | 693794 | `id`, `monster_id`, `level`, `threshold`, `content`                                                                                              |
| **MonsterFamily** (`monster_families`)                | 693816 | `id`, `name`, `big_image`, `small_image`, `small_light_image`                                                                                    |
| **Skill** (`skills`)                                  | 694202 | `id`, `slug`, `cost`, `required_level`, `parent_id` (nullable — null/omit for root)                                                             |
| **SkillRequirement** (`skill_requirements`)           | 694234 | `skill_id`, `required_skill_id`                                                                                                                        |
| **Sword** (`swords`)                                  | 694280 | `id`, `slug`, `priority`, `prefab_path`, `sword_type`, **`auto_equip_priority`** (non-naive key)                                         |
| **Armor** = PrioritizedPrefabItem (`armors`)          | 694296 | `id`, `slug`, `priority`, `prefab_path`                                                                                                            |
| **Head** = StandardPrefabItem (`customization_heads`) | 694266 | `id`, `slug`, `prefab_path`                                                                                                                          |
| **LevelUp** (`level_ups`)                             | 693708 | `id`, `exp_threshold`, `skill_points`                                                                                                                |
| **Difficulty** (`difficulties`)                       | 693560 | `id`, `slug`, `player_attack_count`, `enemy_attack_count`                                                                                          |

Base classes: `StandardItem` (694250: id, slug), `PrioritizedItem` (693916: +priority),
`StandardPrefabItem` (694266: +prefab_path), `PrioritizedPrefabItem` (694296: +prefab_path).
Appearance prefab paths live under `Assets/_bundledassets/appearance/{sword,armor,head}/<slug>/prefab_<slug>.prefab`;
the asset distributor inserts a `_<gender>_lq` suffix at the `.`. The APK addressable catalog
(`com.spokko.witchermonsterslayer/assets/aa/catalog.json`, 5.3 MB) is the source of valid slugs/paths —
32+ real appearance prefab sets confirmed present. Localized `name`/`content` are localization keys;
missing keys fail soft (raw text), not a crash. Missing 3D-model addressables **can** crash on load — so
equipment/monster model keys must be real.

---

## 4. Tutorial flow (dump.cs 593371)

The driver is a Zenject helper class named **`Tutorial`** (not a Module; there is no `TutorialController`).
`CheckTutorial` = RVA `0x1F9A10C` (593403). Injects `IFactDatabaseModule`, `PoiModule`,
**`BehaviourGraphModule`**, `StoryModule`, plus a `string _endTutGraph` behaviour-graph asset path.

- **Gate:** `IsTutorialFinished` (backing field 0x18) is seeded from the **server flag**
  `GetPlayerInfoResponse.TutorialFinished` (Method 3). Finished → no-op; not-finished → `ToggleTutorialFeatures`
  (hides the normal HUD — `BottomMenu._tutorialBlocker` @664885) then starts the tutorial.
- **Progression is Fact-driven:** `TutorialFactListener` subscribes to `FactDatabaseUpdatedSignal`
  (`ServerFactDatabaseModule`); story objective facts use `StoryModule.OBJECTIVE_FACT_PREFIX = 10000`.
  Completion fires `EndTutorial` → sends **`SetTutorialFinished` (Method 30)** and plays `_endTutGraph`
  through BehaviourGraphModule.
- **Content is DATA-DRIVEN** — the S00 story chapter: cutscenes `CUTSCENES/S00/CS_TUTORIAL_WITCHER_1/2`,
  dialogs `DIALOGS_S00_TUTORIAL_*`, quest objectives `QUESTS_S00_TUTORIAL_OBJECTIVES`. Runs through
  StoryModule (story graph) + BehaviourGraphModule (behaviour graph), gated by Facts.
- Support classes: `TutorialSettings : ScriptableObject` (610560 — Torstein/Gryphon/Nekker prefabs, BombId),
  `TutorialNpc` (610399), `TutorialPoi`(+Factory) (610448), `TutorialHints` (679196 — parry/attack/finisher),
  `TutorialFinisher(WithTutorial) : SwordAction` (679687/679708), `TutorialPatch`/`TutorialSignsPatch : BrainPatch`
  (681729/681800), `TutorialCharacterPanelController` (663015). Signals `TutorialFinishedSignal` (612535),
  `ForceTutorialFinishedSignal` (612486).

**To enable:** server `TutorialFinished` 1→0 + implement `SetTutorialFinished(30)`; **un-bypass
BehaviourGraphModule**; StoryModule/ServerFactDatabaseModule/PoiModule already live; S00 addressables must be
present in the APK. Getting the tutorial to visibly **start** is achievable now; a full **playthrough** needs
sequenced objective Facts + working combat → follow-up milestone.

---

## 5. BehaviourGraphModule (dump.cs 634932)

The combat-AI + scripted-sequence engine. Executes `BehaviourGraph` assets for fights (`StartFightGraph`
635033, `StartNestGraph`, …), presentations/cutscenes (`StartPresentation` 635042), and quest/story scripting
(`StartQuestGraph` 635045, `OnQueueStoryGraph` 635102). Node types incl. `FightNode`, `FightEquipmentNode`
(635687). Graphs load as **addressables** via `UnifiedLinkFactory`.

- RVAs: `InitializeModule` `0x31972F8` (635021), `get_Initialized` `0x319726C` (635008),
  `get_MainEventTracker` `0x31972F0` (635018). `<Initialized>` bool @ **0xE8**.
- **`BehaviurGraphSettings _settings` @ offset 0x18** (note the game's misspelling; SO @ 635147). It has
  **no scalar fields** — all 8 fields (0x18..0x50) are object refs (BehaviourGraph / InjectGraphsStorage),
  so a hand-built fake can only be a zeroed typed block, not real graphs. It **is** DI-bound
  (`BindInstance<BehaviurGraphSettings>` @449889 via `BehaviourGraphInstaller.settings @0x20`), so the plain
  un-bypass may already resolve `_settings` correctly.
- **Why it was bypassed:** `InitializeModule` builds `_mainEventTracker` and subscribes to combat/story
  SignalBus messages incl. server responses `EndBehaviourGraphResponse` (57) and `EndNestCombatResponse` —
  which arrive with null `.Data` because the server never sent them → historically NRE'd the clean boot.
  The existing `SignalBus.Fire` null-Data guard (RVA `0x1C5C6DC` in hook.js) now swallows those, so init is
  probably safe; init needs its settings (like PoiModule needed PoiSettings) but **not** server data —
  only combat/tutorial *completion* needs the server to answer 57 / EndNestCombat.

---

## 6. Screen → backing module → status

Menu backbone: `BottomMenu` (664858) + `MenuButton` (665003), panels keyed by `enum GUIPanelIdentifier`
(640934): `None,Map,Bestiary,Journal,Alchemy,Character,Quests,Shop,Skills,Nest`. All GuiPanels sit under
`GuiModule` (un-bypassed ✅). No dedicated Achievements/Statistics panel — sub-views of Character/Bestiary.

| Screen             | Backing data                                        | Module status                                                         |
| ------------------ | --------------------------------------------------- | --------------------------------------------------------------------- |
| Equipment          | `IPlayerInventory` OwnedSwords/Armors/Equipped*   | PlayerData/PlayerModule ✅ (needs GetEquipment/GetInventory batch)    |
| Achievements       | PlayerData trophies +`GetAchievements(24)`        | ✅ (needs GetAchievements response)                                   |
| Statistics         | monster kills (Bestiary) + skills/stats             | ✅ (needs GetKilledMonsters/GetSkills)                                |
| Skills             | `IIntStorage<Skill>` (static) + `IPlayerSkills` | ✅ (needs static skills + GetSkills)                                  |
| Bestiary           | `BestiaryKnowledge` ← GetKilledMonsters          | ✅                                                                    |
| **Tutorial** | `Tutorial` + BehaviourGraphModule + StoryModule   | **❌ was blocked on BehaviourGraphModule** (fixed this session) |

**Only the Tutorial** was blocked by a still-bypassed module; the rest only needed their PlayerData
sub-responses populated.

---

## 7. Changes made this session

Three parallel tracks, one file each (id contract fixed by orchestrator so static ids and player-owned ids
line up):

### Track B — `server/…/Net/GameSocketService.cs`

- **`BuildInitialPlayerData()` enriched** (18-response batch count unchanged; `Player:SendInitialData` gate intact):
  PlayerInfo Gold=5000, Exp=4500, Head=1, **TutorialFinished=0**, Gender=0; Equipment owns swords {1,2,3}
  armors {1,2} equipped 1/1; KilledMonsters {1:5, 2:2, 3:1}; Achievements {1:1, 2:1}; Skills {1,2,3} +
  SkillPoints 10; DistanceTraveled Param=15000.
- **Catch-all replaced** with explicit handlers: **27** DistanceTraveled `[byte1][int15000]` (fixes a byte
  under-run the catch-all caused), **11/55/12/13** Equip* IntResponse echoing the id from `[int Param]`
  (fallback 1), **28** SetCustomizationHead IntResponse, **30** SetTutorialFinished `[byte1][int1]`, **64**
  AcquireSkill `[byte1][int Skill]`, **93** AddSkillPoints IntResponse, **57** EndBehaviourGraph minimal
  all-zero reply (57 bytes). New `M_*` consts added.

### Track C — `tools/patch/hook.js`

- **BehaviourGraphModule un-bypassed:** `0x31972F8` + `0x319726C` added to `UNBYPASS_RVAS` (both loops skip
  them → module runs normally).
- Expanded the `InitializeModule` diagnostic to dump `_settings @0x18` (null vs non-null) at ENTER.
- Added a **disabled-by-default** settings-injection fallback (zeroed typed `BehaviurGraphSettings` at 0x18),
  modeled on the PoiSettings block — enable only if the device boot NREs on null settings.
- `CheckTutorial` left un-bypassed; `SignalBus.Fire` null-Data guard intact.

### Track A — `server/…/Net/PreloaderStaticData.cs`  *(in progress at time of writing)*

- Populating `Container` arrays from catalog.json per the id contract: swords 1..6, armors 1..6, heads 1..3,
  monsters 1..8 (+ families + descriptions), skills 1..8 (tree via parent_id + requirements), achievements
  1..6, level_ups 1..10, difficulties 1..3. **id/slug tables to be appended here on completion.**

---

## 8. Open items / on-device verification checklist

1. **Fable A id/slug tables** — append when Track A completes; confirm Exp=4500 (Track B) lands near
   level 5 on Track A's `level_ups` curve.
2. **BehaviourGraphModule init** — boot and read the `_settings @0x18` diagnostic. If non-null → done;
   if null + NRE → enable the injection block. A later `StartFightGraph`/`StartQuestGraph` NRE (null graph
   fields) is expected and is the follow-up combat milestone, not this round.
3. **EndBehaviourGraphResponse(57) field order** — unproven; all-zero stub is safe, byte-verify before real loot.
4. **Equip 12/13 & IntRequest shape** — first on-device Equip/AcquireSkill log line confirms `[int Param]`.
5. **Doc nit** (pre-existing, untouched): `BuildInitialPlayerData` header comment still says "12-response batch"
   though it has been 18.

## 9. Key RVAs discovered this session (arm64 v1.0.43)

| RVA                           | Symbol                                                  |
| ----------------------------- | ------------------------------------------------------- |
| `0x31972F8` / `0x319726C` | BehaviourGraphModule InitializeModule / get_Initialized |
| `0x31972F0`                 | BehaviourGraphModule.get_MainEventTracker               |
| `0x1F9A10C`                 | Tutorial.CheckTutorial                                  |
| `0x1F9A530` / `0x1F9A69C` | Tutorial.ForceTutorialFinished / EndTutorial            |
| `0x1C5C6DC`                 | SignalBus.Fire(object) — null-Data guard site          |

---

## 10. S00 prolog quest chain (decoded via Unity AssetBundle extraction, 2026-07-10)

`dump.cs` only has IL2CPP class/method **shapes** — it never contains serialized asset **data** (quest
chains, node graphs, fact IDs). Getting past the tutorial's first cutscene required reading the actual
`BehaviourGraph` assets out of the OBB. Tooling: `pip install UnityPy`, then
`tools/unity_extract/bundle_explorer.py` (list/search/graph subcommands). Bundles are inside the OBB
(itself a plain zip) at `assets/aa/Android/*.bundle`; extract with `unzip`. Relevant bundles:
`s00_story_graphs_assets_all.bundle` (BehaviourGraph node data for all S00 prolog quest nodes),
`s00_story_investigations_assets_all.bundle` (Investigation-mechanic scene data),
`s00_story_poi_settings_assets_all.bundle` (POI marker settings assets).

**`GetActiveQuestNodeInstances (60)` `QuestNodeInstance.InstanceId` must be the graph's real, baked-in
`QuestNodeInstanceId` field** — not an arbitrary value. Sending a fabricated one (tried `InstanceId=2` for
dead_horse) throws `"key was not present in the dictionary"` the moment the client's `StartQuestGraph`
runs, because `DataConsumer`/`DataProvider` node types inside the graph look up cross-graph state keyed by
this ID. `QuestNodeId` itself is baked as `0` in every graph asset — it's purely server-assigned bookkeeping,
not read by the client (matches the pre-existing code comment "spawn is independent of QuestNodeId; click
needs StoryGraph").

| Graph (`BehaviourGraphName` under `s00/prolog/`) | Real `QuestNodeInstanceId` | Node type / notes |
| --- | --- | --- |
| `prolog_01_thorstein` | `5124757777905877225` | Dialoggraph-driven, 30 nodes. First tutorial step. |
| `prolog_01_dead_horse` | `5124756197357912298` | **Investigation** node (`_investigationSlug: 's00/prolog_dead_horse/prolog_dead_horse'`), 102 nodes, includes `Fightgraph` sub-branches (an ambush — see investigations bundle GameObjects `prolog_dead_horse_bush`/`prolog_dead_horse_alghouls`). |
| `prolog_01_griffin` | `5124757777905877227` | 49 nodes. Not yet server-wired. |
| `prolog_01_footprints_01`, `prolog_01_tracks_01/02/03`, `prolog_01_tracking` | `0` (unset in asset) | Small stub graphs (4-13 nodes). Real instance id unconfirmed — check via `bundle_explorer.py graph` before wiring. |

**dead_horse's node flow** (via `bundle_explorer.py graph ... prolog_01_dead_horse`): `Start Graph` →
`Branching` → `Load Enviro` (`_forceAR: 0`) → **`Investigation`** (`_investigationSlug` set) →
`Set Fact`/`Fadeoutblacktransition`. This is the WitcherSenses AR clue-tracking mechanic, not a dialogue —
after the POI is clicked and `StartQuestGraph` fires cleanly (live-verified, no exception), nothing further
renders on screen yet. The Investigation mechanic itself (what client-side trigger or server API — `UseSenses
(42)`, `GetSensedMonsters (43)` — makes it visibly progress) is **not yet reverse-engineered**; its own
43-node local scene graph lives in `s00_story_investigations_assets_all.bundle` under the same name
(`prolog_dead_horse`).
