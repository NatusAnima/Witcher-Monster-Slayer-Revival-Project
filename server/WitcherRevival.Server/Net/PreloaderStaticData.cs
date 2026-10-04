using System.IO.Compression;
using System.Text;
using System.Text.Json;

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
    // The rows themselves live in StaticData/static_data.json: { "<container array name>": [ { element }, ... ] }, keys in
    // DataMember Name= snake_case and field order; "_notes" keeps the per-table findings. Rows are passed through
    // verbatim (GetRawText keeps key order). tools/data_sources/ rebuilds the wiki-derived tables in that file.
    private static readonly Dictionary<string, string[]> ContentOverrides = LoadContent();

    private static Dictionary<string, string[]> LoadContent()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "StaticData", "static_data.json")));
        var tables = new Dictionary<string, string[]>();
        foreach (var table in doc.RootElement.EnumerateObject())
            if (!table.Name.StartsWith('_'))
                tables[table.Name] = table.Value.EnumerateArray().Select(row => row.GetRawText()).ToArray();
        return tables;
    }

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
