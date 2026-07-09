using System.IO.Compression;
using System.Text;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Builds the response for <c>OnetimeWebstuffPreloader</c> (the synchronous boot-time static-data
/// fetch, decoded from arm64 v1.0.43 — see docs/protocol-boot.md §9b).
///
/// Request the client sends (17 bytes, big-endian ByteBuffer):
///   [BE32 0x9043284A magic][byte 0x04][BE32 8][BE32 1][BE32 0]
/// Response the client reads (GetMessageSize + ReceiveStaticGameDataJson):
///   [byte 0x04][BE32 size][8 filler bytes (ignored)][gzip(json)]   where size = 8 + gzip.Length
/// The gzip payload is GZipStream(Decompress) -> DataContractJsonSerializer(Container).
/// </summary>
public static class PreloaderStaticData
{
    /// The 4-byte magic that identifies a preloader connection (SECRET_BYTES = -1874646966).
    public static readonly byte[] Magic = { 0x90, 0x43, 0x28, 0x4A };
    public const byte MessageType = 0x04;

    // Container's 82 top-level arrays, keyed by their actual [DataMember(Name=...)] snake_case values
    // extracted from libil2cpp.so DataMemberAttribute generator stubs (RVAs in dump.cs 692936-693099).
    // Il2CppDumper hides the Name= arg — every field has a DIFFERENT snake_case name from the C# field.
    // IL2CPP DCJS matches JSON keys against these Name= values; sending PascalCase field names → all null.
    // Order = field-declaration order (struct offsets 0x10..0x298); DCJS reader is forward-only.
    private static readonly string[] ContainerArrays =
    {
        // offset → C# field              → DataMember Name=
        "achievements",                   // 0x10  Achievements
        "auto_equip",                     // 0x18  AutoEquips
        "bombs",                          // 0x20  Bombs
        "bomb_damage_types",              // 0x28  BombDamageTypes
        "brewers",                        // 0x30  Brewers
        "contracts",                      // 0x38  Contracts
        "contract_actions",               // 0x40  ContractActions
        "contract_crafts",                // 0x48  ContractCrafts
        "contract_combat_usages",         // 0x50  ContractCombatPreparationItems
        "contract_monsters",              // 0x58  ContractMonsters
        "contract_quests",                // 0x60  ContractQuests
        "contract_skills",                // 0x68  ContractSkills
        "daily_quests",                   // 0x70  DailyContracts
        "difficulties",                   // 0x78  Difficulties
        "effects",                        // 0x80  Effects
        "effect_unlock_potion_recipes",   // 0x88  PotionEffectRecipes
        "effect_unlock_lure_recipes",     // 0x90  LureEffectRecipes
        "player_starting_skills",         // 0x98  StartingSkills
        "game_configuration",             // 0xA0  GameConfigurations
        "herbs",                          // 0xA8  Herbs
        "inapp_prices",                   // 0xB0  InAppPrices
        "inapp_price_shops",              // 0xB8  InAppPricePerShops
        "potion_to_effect",               // 0xC0  PotionEffects
        "oil_to_effect",                  // 0xC8  OilEffects
        "skill_to_effect",                // 0xD0  SkillEffects
        "sword_to_effect",                // 0xD8  SwordEffects
        "armor_to_effect",                // 0xE0  ArmorEffects
        "level_ups",                      // 0xE8  LevelUps
        "monsters",                       // 0xF0  Monsters
        "monster_descriptions",           // 0xF8  MonsterDescriptions
        "monster_families",               // 0x100 MonsterFamilies
        "monster_vulnerabilities",        // 0x108 MonsterVulnerabilities
        "effect_types",                   // 0x110 EffectTypes
        "effect_apply_types",             // 0x118 EffectApplyTypes
        "oils",                           // 0x120 Oils
        "potions",                        // 0x128 Potions
        "lures",                          // 0x130 Lures
        "ingredients",                    // 0x138 Ingredients
        "quests",                         // 0x140 Quests
        "quest_edges",                    // 0x148 QuestEdges
        "quest_nodes",                    // 0x150 QuestNodes
        "quest_node_edges",               // 0x158 QuestNodeEdges
        "quest_node_outputs",             // 0x160 QuestNodeOutputs
        "oil_recipes",                    // 0x168 OilRecipes
        "lure_recipes",                   // 0x170 LureRecipes
        "potion_recipes",                 // 0x178 PotionRecipes
        "bomb_recipes",                   // 0x180 BombRecipes
        "senses_potion_recipes",          // 0x188 SensesPotionRecipes
        "oil_recipe_ingredients",         // 0x190 OilRecipeIngredients
        "lure_recipe_ingredients",        // 0x198 LureRecipeIngredients
        "potion_recipe_ingredients",      // 0x1A0 PotionRecipeIngredients
        "bomb_recipe_ingredients",        // 0x1A8 BombRecipeIngredients
        "senses_potion_recipe_ingredients", // 0x1B0 SensesPotionRecipeIngredients
        "recipe_tiers",                   // 0x1B8 RecipeTiers
        "seasons",                        // 0x1C0 Seasons
        "senses_potions",                 // 0x1C8 SensesPotions
        "shop_bundles",                   // 0x1D0 ShopBundles
        "shop_bundles_layout_group_name_categories", // 0x1D8 ShopBundleLayoutGroupNameCategories
        "shop_bundle_items",              // 0x1E0 ShopBundleItems
        "shop_potions",                   // 0x1E8 ShopPotions
        "shop_bombs",                     // 0x1F0 ShopBombs
        "shop_oils",                      // 0x1F8 ShopOils
        "shop_lures",                     // 0x200 ShopLures
        "shop_senses_potions",            // 0x208 ShopSensesPotions
        "shop_armors",                    // 0x210 ShopArmors
        "shop_swords",                    // 0x218 ShopSwords
        "skills",                         // 0x220 Skills
        "skill_requirements",             // 0x228 SkillRequirements
        "damage_types",                   // 0x230 DamageTypes
        "armors",                         // 0x238 Armors
        "customization_heads",            // 0x240 CustomizationHeads
        "swords",                         // 0x248 Swords
        "player_modifiers",               // 0x250 PlayerModifiers
        "player_modifier_to_effect",      // 0x258 PlayerModifierEffects
        "weekly_quests_rewards",          // 0x260 WeeklyQuestRewards
        "item_hints",                     // 0x268 ItemHints
        "auto_equip_items_prices",        // 0x270 AutoEquipItemsPrices
        "consumables",                    // 0x278 Consumables
        "summoning_scrolls",              // 0x280 SummoningScrolls
        "consumables_player_modifiers",   // 0x288 ConsumablesPlayerModifiers
        "summoning_scrolls_player_modifiers", // 0x290 SummoningScrollsPlayerModifiers
        "packs_types",                    // 0x298 PackTypes
    };

    // Static-data content for the info screens (Equipment, Bestiary, Skills, Achievements, Statistics)
    // plus the minimal loadout so PlayerAvatar.Initialize resolves a NON-NULL Sword/Armor/Head
    // (with these arrays empty, LqPlayerAssetsDistributor.GetPrefabAddress(null, gender) throws NRE —
    // verified via disasm: cbz appearance -> throw).
    //
    // Element keys are the nested-DTO [DataMember(Name=)] snake_case values extracted from libil2cpp.so
    // (dump.cs v1.0.43 TypeDefIndex 14568-14630):
    //   achievements  (Container.Achievement):      id, slug, contract_id
    //   difficulties  (Container.Difficulty):       id, slug, player_attack_count, enemy_attack_count
    //   level_ups     (Container.LevelUp):          id, exp_threshold, skill_points
    //   monsters      (Container.Monster):          id, family_id, encounter_distance, attack_animation_time,
    //                                               rarity, difficulty, name, model, image, trophy, slug
    //   monster_descriptions (MonsterDescription):  id, monster_id, level, threshold, content
    //   monster_families (Container.MonsterFamily): id, name, big_image, small_image, small_light_image
    //   skills        (Container.Skill):            id, slug, cost, required_level, parent_id (nullable —
    //                                               key omitted for root skills)
    //   skill_requirements (SkillRequirement):      skill_id, required_skill_id
    //   heads         (StandardPrefabItem):         id, slug, prefab_path
    //   armors        (PrioritizedPrefabItem):      id, slug, priority, prefab_path
    //   swords        (Container.Sword):            id, slug, priority, sword_type, prefab_path,
    //                                               auto_equip_priority  (SwordType: 0=Steel 1=Silver)
    //
    // All slugs / asset paths are REAL keys mined from assets/aa/catalog.json; localized name/content
    // strings are the game's real I2.Loc terms mined from dump/arm64_v1043/stringliteral.json
    // (missing terms fail soft to raw text, they never crash):
    //   monster name    = MONSTERS/BESTIARY/<SLUG_UPPER>
    //   monster descr   = MONSTERS/DESCRIPTIONS/<SLUG_UPPER>/INFO_<n>
    //   family name     = MONSTERS/FAMILIES/<FAMILY_UPPER>
    //   sword/armor/skill/achievement display names are built BY THE CLIENT from the slug
    //   ("ITEMS/NAMES/SWORDS/" + slug etc.), so those DTOs only need the exact catalog slug.
    //
    // The client derives monster prefab/settings addresses from `slug` (AssetsPaths.GetMonsterPrefabPath_LQ/
    // GetMonsterSettingsPath), skill icon/layout from `slug` (game_data/skills/<slug>.asset) and difficulty
    // tuning from `slug` (characters/difficulty/<slug>.asset) — so slugs MUST match catalog keys exactly.
    // model/image/trophy are emitted as real catalog keys too, though this client resolves via slug.
    //
    // Family ids are FIXED engine constants (Family.NECROPHAGE_ID=1, DRACONIDE=2, OGROID=3, HYBRID=4,
    // ELEMENTAL=5, RELICT=6, SPECTER=7, INSECTOID=8, ANIMAL=9, VAMPIRE=10, CURSED=11). Runtime Family
    // keeps only (id, name) — the *_image fields are dropped, so they are emitted empty.
    //
    // prefab_path (equipment) = full addressable path WITH ".prefab" and WITHOUT the gender/quality suffix;
    // the distributor does PrefabPath.Insert(IndexOf('.'), genderSuffix + "_lq") -> matches catalog.json.
    // ids MUST match the ID CONTRACT shared with GameSocketService (player-owned ids ⊂ static ids):
    // swords 1..6 (equipped 1), armors 1..6 (equipped 1), heads 1..3 (head 1), skills 1..8 (owned 1..3),
    // monsters 1..8 (kills on 1..3), achievements 1..6 (earned 1..2), level_ups 1..10, difficulties 1..3.
    //
    // Each entry is one JSON object per element; BuildContainerJson joins them into a compact
    // single-line JSON array (same wire shape the client already accepted for the loadout arrays).
    private static readonly Dictionary<string, string[]> ContentOverrides = new()
    {
        ["swords"] = new[]
        {
            """{"id":1,"slug":"sword_steel_griffin","priority":0,"sword_type":0,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_steel_griffin/prefab_sword_steel_griffin.prefab","auto_equip_priority":0}""",
            """{"id":2,"slug":"sword_silver_griffin","priority":1,"sword_type":1,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_silver_griffin/prefab_sword_silver_griffin.prefab","auto_equip_priority":1}""",
            """{"id":3,"slug":"sword_steel_wolven","priority":2,"sword_type":0,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_steel_wolven/prefab_sword_steel_wolven.prefab","auto_equip_priority":2}""",
            """{"id":4,"slug":"sword_silver_wolven","priority":3,"sword_type":1,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_silver_wolven/prefab_sword_silver_wolven.prefab","auto_equip_priority":3}""",
            """{"id":5,"slug":"sword_steel_ursine","priority":4,"sword_type":0,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_steel_ursine/prefab_sword_steel_ursine.prefab","auto_equip_priority":4}""",
            """{"id":6,"slug":"sword_silver_ursine","priority":5,"sword_type":1,"prefab_path":"Assets/_bundledassets/appearance/sword/sword_silver_ursine/prefab_sword_silver_ursine.prefab","auto_equip_priority":5}""",
        },
        ["armors"] = new[]
        {
            """{"id":1,"slug":"armor_ursine","priority":0,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_ursine/prefab_armor_ursine.prefab"}""",
            """{"id":2,"slug":"armor_griffin","priority":1,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_griffin/prefab_armor_griffin.prefab"}""",
            """{"id":3,"slug":"armor_wolven","priority":2,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_wolven/prefab_armor_wolven.prefab"}""",
            """{"id":4,"slug":"armor_feline","priority":3,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_feline/prefab_armor_feline.prefab"}""",
            """{"id":5,"slug":"armor_manticore","priority":4,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_manticore/prefab_armor_manticore.prefab"}""",
            """{"id":6,"slug":"armor_kaer_morhen","priority":5,"prefab_path":"Assets/_bundledassets/appearance/armor/armor_kaer_morhen/prefab_armor_kaer_morhen.prefab"}""",
        },
        ["customization_heads"] = new[]
        {
            """{"id":1,"slug":"head_caucasian_1","prefab_path":"Assets/_bundledassets/appearance/head/head_caucasian_1/prefab_head_caucasian_1.prefab"}""",
            """{"id":2,"slug":"head_asian_1","prefab_path":"Assets/_bundledassets/appearance/head/head_asian_1/prefab_head_asian_1.prefab"}""",
            """{"id":3,"slug":"head_african_1","prefab_path":"Assets/_bundledassets/appearance/head/head_african_1/prefab_head_african_1.prefab"}""",
        },
        // Combat-tab skill tree (all slugs are real game_data/skills/<slug>.asset keys; row/column/icon/tab
        // come from that scriptable, so the tree renders at its designed position). Roots: 1,2,3 (player-owned).
        ["skills"] = new[]
        {
            """{"id":1,"slug":"fast_attack","cost":1,"required_level":1}""",
            """{"id":2,"slug":"strong_attack","cost":1,"required_level":1}""",
            """{"id":3,"slug":"parry","cost":1,"required_level":2}""",
            """{"id":4,"slug":"muscle_memory","cost":1,"required_level":3,"parent_id":1}""",
            """{"id":5,"slug":"strength_training","cost":1,"required_level":3,"parent_id":2}""",
            """{"id":6,"slug":"hit_deflection","cost":2,"required_level":4,"parent_id":3}""",
            """{"id":7,"slug":"precise_blows","cost":2,"required_level":5,"parent_id":4}""",
            """{"id":8,"slug":"crushing_blows","cost":2,"required_level":5,"parent_id":5}""",
        },
        // Prerequisite edges mirror the parent_id tree (Skill.HasFulfilledPrerequisities checks these).
        ["skill_requirements"] = new[]
        {
            """{"skill_id":4,"required_skill_id":1}""",
            """{"skill_id":5,"required_skill_id":2}""",
            """{"skill_id":6,"required_skill_id":3}""",
            """{"skill_id":7,"required_skill_id":4}""",
            """{"skill_id":8,"required_skill_id":5}""",
        },
        // All 8 have <slug>_lq + <slug>_hq(+_presentation) prefabs, <slug>_settings.asset and a trophy png
        // in catalog.json. difficulty references difficulties ids 1..3 below (IIntStorage<Difficulty> lookup
        // — a dangling id would fail). rarity indexes MonsterRaritySettings (common/rare/legendary).
        ["monsters"] = new[]
        {
            """{"id":1,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/GHOUL","model":"Assets/_bundledassets/characters/monsters/s00/ghoul/ghoul_lq/ghoul_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/ghoul/ghoul_hq/ghoul_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_ghoul.png","slug":"ghoul"}""",
            """{"id":2,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/ALGHOUL","model":"Assets/_bundledassets/characters/monsters/s00/alghoul/alghoul_lq/alghoul_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/alghoul/alghoul_hq/alghoul_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_alghoul.png","slug":"alghoul"}""",
            """{"id":3,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/DROWNER","model":"Assets/_bundledassets/characters/monsters/s00/drowner/drowner_lq/drowner_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/drowner/drowner_hq/drowner_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_drowner.png","slug":"drowner"}""",
            """{"id":4,"family_id":3,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/NEKKER","model":"Assets/_bundledassets/characters/monsters/s00/nekker/nekker_lq/nekker_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/nekker/nekker_hq/nekker_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_nekker.png","slug":"nekker"}""",
            """{"id":5,"family_id":3,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/NEKKERWARRIOR","model":"Assets/_bundledassets/characters/monsters/s00/nekkerwarrior/nekkerwarrior_lq/nekkerwarrior_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/nekkerwarrior/nekkerwarrior_hq/nekkerwarrior_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_nekker_warrior.png","slug":"nekkerwarrior"}""",
            """{"id":6,"family_id":11,"encounter_distance":50,"attack_animation_time":2000,"rarity":2,"difficulty":3,"name":"MONSTERS/BESTIARY/WEREWOLF","model":"Assets/_bundledassets/characters/monsters/s00/werewolf/werewolf_lq/werewolf_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/werewolf/werewolf_hq/werewolf_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_werewolf.png","slug":"werewolf"}""",
            """{"id":7,"family_id":2,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/SMALLDRACONID","model":"Assets/_bundledassets/characters/monsters/s00/smalldraconid/smalldraconid_lq/smalldraconid_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/smalldraconid/smalldraconid_hq/smalldraconid_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_smalldraconid.png","slug":"smalldraconid"}""",
            """{"id":8,"family_id":7,"encounter_distance":50,"attack_animation_time":2000,"rarity":2,"difficulty":3,"name":"MONSTERS/BESTIARY/BANSHEE","model":"Assets/_bundledassets/characters/monsters/s00/banshee/banshee_lq/banshee_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/banshee/banshee_hq/banshee_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_banshee.png","slug":"banshee"}""",
        },
        // 3 knowledge tiers per monster (level 1/2/3 at 1/5/10 kills). All INFO_1..3 terms verified present
        // in stringliteral.json. Player kills {1:5,2:2,3:1} => ghoul reaches tier 2 out of the box.
        ["monster_descriptions"] = new[]
        {
            """{"id":1,"monster_id":1,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/GHOUL/INFO_1"}""",
            """{"id":2,"monster_id":1,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/GHOUL/INFO_2"}""",
            """{"id":3,"monster_id":1,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/GHOUL/INFO_3"}""",
            """{"id":4,"monster_id":2,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/ALGHOUL/INFO_1"}""",
            """{"id":5,"monster_id":2,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/ALGHOUL/INFO_2"}""",
            """{"id":6,"monster_id":2,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/ALGHOUL/INFO_3"}""",
            """{"id":7,"monster_id":3,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/DROWNER/INFO_1"}""",
            """{"id":8,"monster_id":3,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/DROWNER/INFO_2"}""",
            """{"id":9,"monster_id":3,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/DROWNER/INFO_3"}""",
            """{"id":10,"monster_id":4,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/NEKKER/INFO_1"}""",
            """{"id":11,"monster_id":4,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/NEKKER/INFO_2"}""",
            """{"id":12,"monster_id":4,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/NEKKER/INFO_3"}""",
            """{"id":13,"monster_id":5,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/NEKKERWARRIOR/INFO_1"}""",
            """{"id":14,"monster_id":5,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/NEKKERWARRIOR/INFO_2"}""",
            """{"id":15,"monster_id":5,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/NEKKERWARRIOR/INFO_3"}""",
            """{"id":16,"monster_id":6,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/WEREWOLF/INFO_1"}""",
            """{"id":17,"monster_id":6,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/WEREWOLF/INFO_2"}""",
            """{"id":18,"monster_id":6,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/WEREWOLF/INFO_3"}""",
            """{"id":19,"monster_id":7,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/SMALLDRACONID/INFO_1"}""",
            """{"id":20,"monster_id":7,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/SMALLDRACONID/INFO_2"}""",
            """{"id":21,"monster_id":7,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/SMALLDRACONID/INFO_3"}""",
            """{"id":22,"monster_id":8,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/BANSHEE/INFO_1"}""",
            """{"id":23,"monster_id":8,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/BANSHEE/INFO_2"}""",
            """{"id":24,"monster_id":8,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/BANSHEE/INFO_3"}""",
        },
        // Full canonical family set (ids are engine constants, see header comment). Image fields are
        // dropped by the client (Family.Factory<int,string>), hence empty. ANIMAL(9) has no I2 term in
        // stringliteral.json — it fails soft to the raw string if any UI ever shows it.
        ["monster_families"] = new[]
        {
            """{"id":1,"name":"MONSTERS/FAMILIES/NECROPHAGE","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":2,"name":"MONSTERS/FAMILIES/DRACONIDE","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":3,"name":"MONSTERS/FAMILIES/OGROID","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":4,"name":"MONSTERS/FAMILIES/HYBRID","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":5,"name":"MONSTERS/FAMILIES/ELEMENTAL","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":6,"name":"MONSTERS/FAMILIES/RELICT","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":7,"name":"MONSTERS/FAMILIES/SPECTER","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":8,"name":"MONSTERS/FAMILIES/INSECTOID","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":9,"name":"MONSTERS/FAMILIES/ANIMAL","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":10,"name":"MONSTERS/FAMILIES/VAMPIRE","big_image":"","small_image":"","small_light_image":""}""",
            """{"id":11,"name":"MONSTERS/FAMILIES/CURSED","big_image":"","small_image":"","small_light_image":""}""",
        },
        // Real trophy-achievement slugs from stringliteral.json (client builds ACHIEVEMENTS/NAMES/<SLUG_UPPER>
        // and .../DESCRIPTIONS/... terms from the slug). contract_id=0: the contracts array is empty this
        // round, and no contract with id 0 exists to dangle.
        ["achievements"] = new[]
        {
            """{"id":1,"slug":"trophy_from_vizima_to_beauclair","contract_id":0}""",
            """{"id":2,"slug":"trophy_legendary_monster_slayer","contract_id":0}""",
            """{"id":3,"slug":"trophy_in_forest_dark","contract_id":0}""",
            """{"id":4,"slug":"trophy_lizard_slayer","contract_id":0}""",
            """{"id":5,"slug":"trophy_disturbed_the_water","contract_id":0}""",
            """{"id":6,"slug":"trophy_fear_no_more","contract_id":0}""",
        },
        // Rising thresholds; GameSocketService serves Exp = the level-5 threshold (1000).
        ["level_ups"] = new[]
        {
            """{"id":1,"exp_threshold":0,"skill_points":1}""",
            """{"id":2,"exp_threshold":100,"skill_points":1}""",
            """{"id":3,"exp_threshold":300,"skill_points":1}""",
            """{"id":4,"exp_threshold":600,"skill_points":1}""",
            """{"id":5,"exp_threshold":1000,"skill_points":1}""",
            """{"id":6,"exp_threshold":1500,"skill_points":1}""",
            """{"id":7,"exp_threshold":2100,"skill_points":1}""",
            """{"id":8,"exp_threshold":2800,"skill_points":1}""",
            """{"id":9,"exp_threshold":3600,"skill_points":1}""",
            """{"id":10,"exp_threshold":4500,"skill_points":1}""",
        },
        // Slugs are real catalog keys: assets/_bundledassets/characters/difficulty/tier_<n>.asset
        // (AssetsPaths.GetPathForDifficulty builds the address from the slug).
        ["difficulties"] = new[]
        {
            """{"id":1,"slug":"tier_1","player_attack_count":3,"enemy_attack_count":1}""",
            """{"id":2,"slug":"tier_2","player_attack_count":3,"enemy_attack_count":2}""",
            """{"id":3,"slug":"tier_3","player_attack_count":3,"enemy_attack_count":3}""",
        },
    };

    /// <summary>The DataContract JSON the client will deserialize into a Container.</summary>
    public static string BuildContainerJson(bool emptyObject = false)
    {
        if (emptyObject) return "{}";
        // Emit all 82 arrays. The keys are the actual DataMember Name= snake_case values
        // extracted from libil2cpp.so — IL2CPP DCJS matches on Name=, not the C# field names.
        // Arrays present in ContentOverrides get their element objects joined into a JSON array;
        // every other array stays [].
        var sb = new StringBuilder("{");
        for (int i = 0; i < ContainerArrays.Length; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append('"').Append(ContainerArrays[i]).Append("\":");
            if (ContentOverrides.TryGetValue(ContainerArrays[i], out var entries))
            {
                sb.Append('[');
                for (int j = 0; j < entries.Length; j++)
                {
                    if (j > 0) sb.Append(',');
                    sb.Append(entries[j]);
                }
                sb.Append(']');
            }
            else sb.Append("[]");
        }
        sb.Append('}');
        return sb.ToString();
    }

    /// <summary>Full framed response bytes for the preloader (header + filler + gzip(json)).</summary>
    public static byte[] BuildResponse(string json)
    {
        byte[] gzip = Gzip(Encoding.UTF8.GetBytes(json));
        int size = 8 + gzip.Length;                 // 8 filler bytes + gzip payload
        var buf = new byte[5 + size];
        buf[0] = MessageType;                        // 0x04
        buf[1] = (byte)(size >> 24);
        buf[2] = (byte)(size >> 16);
        buf[3] = (byte)(size >> 8);
        buf[4] = (byte)size;                         // BE32 size
        // buf[5..13] = 8 filler bytes, left as zero (client discards them)
        Array.Copy(gzip, 0, buf, 13, gzip.Length);
        return buf;
    }

    /// <summary>gzip(Container JSON) — the raw body the CdnPreloader downloads from the static-data URL
    /// and feeds to GZipStream(Decompress) -> DataContractJsonSerializer(Container).</summary>
    public static byte[] GzipContainer(bool emptyObject = false)
        => Gzip(Encoding.UTF8.GetBytes(BuildContainerJson(emptyObject)));

    private static byte[] Gzip(byte[] data)
    {
        using var ms = new MemoryStream();
        using (var gz = new GZipStream(ms, CompressionLevel.Optimal, leaveOpen: true))
            gz.Write(data, 0, data.Length);
        return ms.ToArray();
    }
}
