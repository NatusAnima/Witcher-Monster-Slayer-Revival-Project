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
        // Consumables: every potion/oil/bomb the client has localisation for. No original data survives, so the ids
        // are a reconstruction: alphabetical within each category, potions 2xx, oils 3xx, bombs 4xx. That fits all
        // three ids the story graphs use: tutorial exam Potions=205 (Swallow, the healing potion), Oils=301 (basic),
        // Bombs=401 (basic, also prolog_01_dead_horse's FightEquipment — an empty bombs array made that lookup throw
        // KeyNotFoundException in BaseGraph.InitializeNodes). Slugs follow the ITEMS/NAMES/<CATEGORY>/<SLUG_UPPER>
        // terms. Keys: PrioritizedItem (id, slug, priority) + each DTO's DataMember names read from libil2cpp.so;
        // stats are guesses (explode_style 0 = OnImpact).
        ["bombs"] = new[]
        {
            """{"id":401,"slug":"bomb_basic","priority":0,"delay":0,"duration":0,"value":150,"radius":1,"explode_style":0,"prefab_path":"Assets/_bundledassets/appearance/bomb/bomb_basic/prefab_bomb_basic.prefab"}""",
            """{"id":402,"slug":"bomb_dancingstar","priority":1,"delay":0,"duration":0,"value":150,"radius":1,"explode_style":0,"prefab_path":"Assets/_bundledassets/appearance/bomb/bomb_dancingstar/prefab_bomb_dancingstar.prefab"}""",
            """{"id":403,"slug":"bomb_dimeritium","priority":2,"delay":0,"duration":0,"value":150,"radius":1,"explode_style":0,"prefab_path":"Assets/_bundledassets/appearance/bomb/bomb_dimeritium/prefab_bomb_dimeritium.prefab"}""",
            """{"id":404,"slug":"bomb_grapeshot","priority":3,"delay":0,"duration":0,"value":150,"radius":1,"explode_style":0,"prefab_path":"Assets/_bundledassets/appearance/bomb/bomb_grapeshot/prefab_bomb_grapeshot.prefab"}""",
            """{"id":405,"slug":"bomb_moondust","priority":4,"delay":0,"duration":0,"value":150,"radius":1,"explode_style":0,"prefab_path":"Assets/_bundledassets/appearance/bomb/bomb_moondust/prefab_bomb_moondust.prefab"}""",
        },
        ["potions"] = new[]
        {
            """{"id":201,"slug":"potion_blizzard","priority":0,"auto_equip_priority":0}""",
            """{"id":202,"slug":"potion_cat","priority":1,"auto_equip_priority":0}""",
            """{"id":203,"slug":"potion_mariborforest","priority":2,"auto_equip_priority":0}""",
            """{"id":204,"slug":"potion_squall","priority":3,"auto_equip_priority":0}""",
            """{"id":205,"slug":"potion_swallow","priority":4,"auto_equip_priority":0}""",
            """{"id":206,"slug":"potion_swift","priority":5,"auto_equip_priority":0}""",
            """{"id":207,"slug":"potion_tawnyowl","priority":6,"auto_equip_priority":0}""",
            """{"id":208,"slug":"potion_thunderbolt","priority":7,"auto_equip_priority":0}""",
            """{"id":209,"slug":"potion_wolverine","priority":8,"auto_equip_priority":0}""",
        },
        ["oils"] = new[]
        {
            """{"id":301,"slug":"oil_basic","priority":0,"exp_matching":0}""",
            """{"id":302,"slug":"oil_cursed","priority":1,"exp_matching":0}""",
            """{"id":303,"slug":"oil_draconid","priority":2,"exp_matching":0}""",
            """{"id":304,"slug":"oil_elemental","priority":3,"exp_matching":0}""",
            """{"id":305,"slug":"oil_hybrid","priority":4,"exp_matching":0}""",
            """{"id":306,"slug":"oil_insectoid","priority":5,"exp_matching":0}""",
            """{"id":307,"slug":"oil_necrophage","priority":6,"exp_matching":0}""",
            """{"id":308,"slug":"oil_ogroid","priority":7,"exp_matching":0}""",
            """{"id":309,"slug":"oil_relict","priority":8,"exp_matching":0}""",
            """{"id":310,"slug":"oil_specter","priority":9,"exp_matching":0}""",
            """{"id":311,"slug":"oil_vampire","priority":10,"exp_matching":0}""",
        },
        // Consumable effects (all values reconstructed — none of the original data survives). Effects.GetEffect
        // (0x1871810) switches on ItemEffect.effect_id, whose values are the client's EffectBehaviourType enum, and
        // passes power + effect_apply_type_id (= the ApplyTime enum) to the CombatEffect it builds; the effects /
        // effect_apply_types tables just name every enum value so lookups by id can't miss. Swallow (205, the tutorial
        // exam potion) heals on low health; family oils buff attacks against their family; bombs deal typed damage
        // (damage_types ids = the Vulnerability.Type enum: Fire, Silver, Steel, Kinetic, Fast, Strong, Dimeritium).
        ["effects"] = new[]
        {
            """{"id":1,"name":"ImproveFastAttack","effect_type_id":1}""",
            """{"id":2,"name":"ImproveStrongAttack","effect_type_id":1}""",
            """{"id":3,"name":"ImproveDefense","effect_type_id":1}""",
            """{"id":4,"name":"GenerateAdrenaline","effect_type_id":1}""",
            """{"id":5,"name":"ImproveNextAttackAfterDeflect","effect_type_id":1}""",
            """{"id":6,"name":"ImproveFinisher","effect_type_id":1}""",
            """{"id":7,"name":"ImproveFinisherSlowMo","effect_type_id":1}""",
            """{"id":8,"name":"AddEnemyCooldown","effect_type_id":1}""",
            """{"id":9,"name":"ImproveArmor","effect_type_id":1}""",
            """{"id":10,"name":"ImproveFinalBlowSurvival","effect_type_id":1}""",
            """{"id":11,"name":"ImproveAard","effect_type_id":1}""",
            """{"id":12,"name":"ImproveQuen","effect_type_id":1}""",
            """{"id":13,"name":"ImproveSignsSlowMo","effect_type_id":1}""",
            """{"id":14,"name":"ImproveInstantSignRecoveryChance","effect_type_id":1}""",
            """{"id":15,"name":"ImproveOilFinisher","effect_type_id":1}""",
            """{"id":16,"name":"ImproveBombSpeed","effect_type_id":1}""",
            """{"id":17,"name":"ImproveSignsCooldownReduction","effect_type_id":1}""",
            """{"id":18,"name":"ImproveDamageDuringNight","effect_type_id":1}""",
            """{"id":19,"name":"ImproveDamageWhenRaining","effect_type_id":1}""",
            """{"id":20,"name":"ImproveDamageOnLowHP","effect_type_id":1}""",
            """{"id":21,"name":"LowerLowHPProc","effect_type_id":1}""",
            """{"id":22,"name":"ImproveOil","effect_type_id":1}""",
            """{"id":23,"name":"ImproveOilArmor","effect_type_id":1}""",
            """{"id":24,"name":"ImproveBomb","effect_type_id":1}""",
            """{"id":25,"name":"ImproveIgniAdditionalDamageChange","effect_type_id":1}""",
            """{"id":26,"name":"ImproveSigns","effect_type_id":1}""",
            """{"id":27,"name":"ImproveFastAttackAdrenalineGeneration","effect_type_id":1}""",
            """{"id":28,"name":"ImproveStrongAttackAdrenalineGeneration","effect_type_id":1}""",
            """{"id":29,"name":"ImproveAttacksAgainstNecrophages","effect_type_id":1}""",
            """{"id":30,"name":"ImproveAttacksAgainstDraconides","effect_type_id":1}""",
            """{"id":31,"name":"ImproveAttacksAgainstOgroids","effect_type_id":1}""",
            """{"id":32,"name":"ImproveAttacksAgainstHybrids","effect_type_id":1}""",
            """{"id":33,"name":"ImproveAttacksAgainstElementals","effect_type_id":1}""",
            """{"id":34,"name":"ImproveAttacksAgainstRelicts","effect_type_id":1}""",
            """{"id":35,"name":"ImproveAttacksAgainstSpecters","effect_type_id":1}""",
            """{"id":36,"name":"ImproveAttacksAgainstInsectoids","effect_type_id":1}""",
            """{"id":37,"name":"ImproveAttacksAgainstAnimals","effect_type_id":1}""",
            """{"id":38,"name":"ImproveAttacksAgainstVampires","effect_type_id":1}""",
            """{"id":39,"name":"ImproveAttacksAgainstCursed","effect_type_id":1}""",
            """{"id":40,"name":"ImproveHealth","effect_type_id":1}""",
            """{"id":41,"name":"ImproveAttackPower","effect_type_id":1}""",
            """{"id":42,"name":"UnlockAard","effect_type_id":1}""",
            """{"id":43,"name":"UnlockIgni","effect_type_id":1}""",
            """{"id":44,"name":"UnlockQuen","effect_type_id":1}""",
            """{"id":45,"name":"GrantAdditionalPotion","effect_type_id":1}""",
            """{"id":46,"name":"CraftBombs","effect_type_id":1}""",
            """{"id":47,"name":"UnlockFastAttack","effect_type_id":1}""",
            """{"id":48,"name":"UnlockStrongAttack","effect_type_id":1}""",
            """{"id":49,"name":"UnlockParry","effect_type_id":1}""",
            """{"id":50,"name":"UnlockDeflect","effect_type_id":1}""",
            """{"id":51,"name":"UnlockPotionTawnyOwl","effect_type_id":1}""",
            """{"id":52,"name":"UnlockPotionCat","effect_type_id":1}""",
            """{"id":53,"name":"UnlockPotionSquall","effect_type_id":1}""",
            """{"id":54,"name":"UnlockPotionWolverine","effect_type_id":1}""",
            """{"id":55,"name":"UnlockBaits","effect_type_id":1}""",
            """{"id":56,"name":"ImproveAdrenalineGeneration","effect_type_id":1}""",
            """{"id":57,"name":"DealPercentageDamage","effect_type_id":1}""",
            """{"id":58,"name":"TryDealFireDamage","effect_type_id":1}""",
            """{"id":59,"name":"ImproveMinimumAdrenaline","effect_type_id":1}""",
            """{"id":60,"name":"EquipPotion","effect_type_id":1}""",
            """{"id":61,"name":"ImprovePotionEffects","effect_type_id":1}""",
            """{"id":62,"name":"UnlockPotionRecipe","effect_type_id":1}""",
            """{"id":63,"name":"UnlockBaitRecipe","effect_type_id":1}""",
            """{"id":64,"name":"IncreaseSignDrawTime","effect_type_id":1}""",
            """{"id":65,"name":"IncreaseExperience","effect_type_id":1}""",
            """{"id":66,"name":"ExtraIngredientChance","effect_type_id":1}""",
            """{"id":67,"name":"Heal","effect_type_id":1}""",
            """{"id":68,"name":"Mushrooming","effect_type_id":1}""",
            """{"id":69,"name":"ImproveQuenAbsorb","effect_type_id":1}""",
            """{"id":70,"name":"ShortenCraftingTime","effect_type_id":1}""",
            """{"id":71,"name":"IncreaseIngredientsGathering","effect_type_id":1}""",
            """{"id":72,"name":"IncreaseInteractionDistance","effect_type_id":1}""",
            """{"id":73,"name":"FakeEffect","effect_type_id":1}""",
            """{"id":74,"name":"DecreaseBombThrowAngle","effect_type_id":1}""",
            """{"id":75,"name":"DelayedHeal","effect_type_id":1}""",
            """{"id":76,"name":"HealOverTime","effect_type_id":1}""",
            """{"id":77,"name":"WitcherAuraInterval","effect_type_id":1}""",
            """{"id":78,"name":"WitcherAuraMonsters","effect_type_id":1}""",
            """{"id":79,"name":"ExtraCraftingItem","effect_type_id":1}""",
            """{"id":80,"name":"ImpairAdrenalineLoss","effect_type_id":1}""",
            """{"id":81,"name":"IncreaseMonsterDefeatedExperience","effect_type_id":1}""",
            """{"id":82,"name":"ImproveDeflect","effect_type_id":1}""",
        },
        ["effect_types"] = new[]
        {
            """{"id":1,"name":"Combat"}""",
        },
        ["effect_apply_types"] = new[]
        {
            """{"id":1,"name":"OnStart"}""",
            """{"id":2,"name":"OnAttack"}""",
            """{"id":3,"name":"OnReceiveDamage"}""",
            """{"id":4,"name":"OnParrying"}""",
            """{"id":5,"name":"OnDeflecting"}""",
            """{"id":6,"name":"OnThrowBomb"}""",
            """{"id":7,"name":"OnAardCast"}""",
            """{"id":8,"name":"OnIgniCast"}""",
            """{"id":9,"name":"OnQuenCast"}""",
            """{"id":10,"name":"OnBombExplode"}""",
            """{"id":11,"name":"OnCastSign"}""",
            """{"id":12,"name":"OnLowHealth"}""",
            """{"id":13,"name":"OnDeath"}""",
            """{"id":14,"name":"OnSurrender"}""",
            """{"id":15,"name":"OnPerfectFinisher"}""",
            """{"id":16,"name":"OnFastAttack"}""",
            """{"id":17,"name":"OnStrongAttack"}""",
            """{"id":18,"name":"OnSkillUnlock"}""",
            """{"id":19,"name":"OnStartOptional"}""",
            """{"id":20,"name":"OnReceivingUnblockedDamage"}""",
            """{"id":21,"name":"OnCombatPrepEnter"}""",
            """{"id":22,"name":"OnTargetSet"}""",
            """{"id":23,"name":"OnPreStart"}""",
            """{"id":24,"name":"OnUpdate"}""",
        },
        ["potion_to_effect"] = new[]
        {
            """{"item_id":201,"effect_id":1,"power":15,"effect_apply_type_id":1}""",
            """{"item_id":202,"effect_id":18,"power":15,"effect_apply_type_id":1}""",
            """{"item_id":203,"effect_id":4,"power":10,"effect_apply_type_id":1}""",
            """{"item_id":204,"effect_id":2,"power":15,"effect_apply_type_id":1}""",
            """{"item_id":205,"effect_id":67,"power":300,"effect_apply_type_id":12}""",
            """{"item_id":206,"effect_id":3,"power":10,"effect_apply_type_id":1}""",
            """{"item_id":207,"effect_id":17,"power":20,"effect_apply_type_id":1}""",
            """{"item_id":208,"effect_id":41,"power":15,"effect_apply_type_id":1}""",
            """{"item_id":209,"effect_id":20,"power":25,"effect_apply_type_id":1}""",
        },
        ["oil_to_effect"] = new[]
        {
            """{"item_id":301,"effect_id":41,"power":10,"effect_apply_type_id":1}""",
            """{"item_id":302,"effect_id":39,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":303,"effect_id":30,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":304,"effect_id":33,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":305,"effect_id":32,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":306,"effect_id":36,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":307,"effect_id":29,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":308,"effect_id":31,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":309,"effect_id":34,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":310,"effect_id":35,"power":25,"effect_apply_type_id":1}""",
            """{"item_id":311,"effect_id":38,"power":25,"effect_apply_type_id":1}""",
        },
        ["damage_types"] = new[]
        {
            """{"id":1,"slug":"fire","power":1}""",
            """{"id":2,"slug":"silver","power":1}""",
            """{"id":3,"slug":"steel","power":1}""",
            """{"id":4,"slug":"kinetic","power":1}""",
            """{"id":5,"slug":"fast","power":1}""",
            """{"id":6,"slug":"strong","power":1}""",
            """{"id":7,"slug":"dimeritium","power":1}""",
        },
        ["bomb_damage_types"] = new[]
        {
            """{"bomb_id":401,"damage_type_id":1,"amount":150}""",
            """{"bomb_id":402,"damage_type_id":1,"amount":250}""",
            """{"bomb_id":403,"damage_type_id":7,"amount":200}""",
            """{"bomb_id":404,"damage_type_id":4,"amount":250}""",
            """{"bomb_id":405,"damage_type_id":2,"amount":200}""",
        },
        // Zooming the map out opens the Witcher Senses view; WitcherSensesGUI.Show takes GetFirst() of
        // IIntStorage<SensesPotion>, which threw "Sequence contains no elements" on an empty array and left
        // the view stuck (couldn't zoom back in). Keys: PrioritizedItem + effect_id (read from libil2cpp.so).
        // senses_potion_falcon is the only senses potion in the client's assets; id and effect_id are guesses.
        ["senses_potions"] = new[]
        {
            """{"id":1,"slug":"senses_potion_falcon","priority":0,"effect_id":0}""",
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
            // Tutorial (s00/tutorial): exam monster devourer (+ gravehag, same chapter), and the training dummies
            // the tut_* graphs look up by MonsterSlug. Dummies have no presentation prefab or trophy; their
            // family (9 ANIMAL) is a placeholder.
            """{"id":9,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/DEVOURER","model":"Assets/_bundledassets/characters/monsters/s00/devourer/devourer_lq/devourer_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/devourer/devourer_hq/devourer_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_devourer.png","slug":"devourer"}""",
            """{"id":10,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":2,"difficulty":3,"name":"MONSTERS/BESTIARY/GRAVEHAG","model":"Assets/_bundledassets/characters/monsters/s00/gravehag/gravehag_lq/gravehag_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/gravehag/gravehag_hq/gravehag_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_gravehag.png","slug":"gravehag"}""",
            """{"id":11,"family_id":9,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/DUMMY_LVL1","model":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl1/dummy_lvl1_lq/dummy_lvl1_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl1/dummy_lvl1_hq/dummy_lvl1_hq.prefab","trophy":"","slug":"dummy_lvl1"}""",
            """{"id":12,"family_id":9,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/DUMMY_LVL2","model":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl2/dummy_lvl2_lq/dummy_lvl2_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl2/dummy_lvl2_hq/dummy_lvl2_hq.prefab","trophy":"","slug":"dummy_lvl2"}""",
            """{"id":13,"family_id":9,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/DUMMY_LVL3","model":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl3/dummy_lvl3_lq/dummy_lvl3_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/dummy_lvl3/dummy_lvl3_hq/dummy_lvl3_hq.prefab","trophy":"","slug":"dummy_lvl3"}""",
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
            // Every monster needs its 3 tiers: DataManager.LoadMonsters indexes the per-monster description and
            // threshold dictionaries by monster id, so a monster without entries throws KeyNotFoundException and
            // stops boot at "Синхронизация данных" (58%). Dummy terms don't exist; they fail soft to raw text.
            """{"id":25,"monster_id":9,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/DEVOURER/INFO_1"}""",
            """{"id":26,"monster_id":9,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/DEVOURER/INFO_2"}""",
            """{"id":27,"monster_id":9,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/DEVOURER/INFO_3"}""",
            """{"id":28,"monster_id":10,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/GRAVEHAG/INFO_1"}""",
            """{"id":29,"monster_id":10,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/GRAVEHAG/INFO_2"}""",
            """{"id":30,"monster_id":10,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/GRAVEHAG/INFO_3"}""",
            """{"id":31,"monster_id":11,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL1/INFO_1"}""",
            """{"id":32,"monster_id":11,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL1/INFO_2"}""",
            """{"id":33,"monster_id":11,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL1/INFO_3"}""",
            """{"id":34,"monster_id":12,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL2/INFO_1"}""",
            """{"id":35,"monster_id":12,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL2/INFO_2"}""",
            """{"id":36,"monster_id":12,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL2/INFO_3"}""",
            """{"id":37,"monster_id":13,"level":1,"threshold":1,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL3/INFO_1"}""",
            """{"id":38,"monster_id":13,"level":2,"threshold":5,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL3/INFO_2"}""",
            """{"id":39,"monster_id":13,"level":3,"threshold":10,"content":"MONSTERS/DESCRIPTIONS/DUMMY_LVL3/INFO_3"}""",
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
