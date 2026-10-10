namespace WitcherRevival.Server.Net;

/// <summary>
/// Reconstructed 1.1.116 rules for profiles created in "reconstructed" mode (see docs/SERVER-RECONSTRUCTION.md).
/// Every value names its evidence class: Client (1.1.116 code/assets), Donor (1.3.102 assets loaded by LAB),
/// Community (published before update 1.2, with source) or Authored (no evidence; marked lab_ where visible).
/// </summary>
public static class Reconstruction
{
    // ── Levels ──────────────────────────────────────────────────────────────────────────────
    // Community (search summary of the Witcher wiki XP page, unverified): level 1→2 needs 1000 XP and
    // every further level 1000 more than the previous one. Community (DualShockers, 20 Jul 2021):
    // "usually around five" skill points per level-up. The client derives the level from these rows.
    public const int MaxLevel = 40;              // Authored cap; community skill gates reach level 35.
    public const int SkillPointsPerLevel = 5;

    public static int ExpThreshold(int level) => 1000 * (level - 1) * level / 2;

    public static int LevelForExp(int exp)
    {
        int level = 1;
        while (level < MaxLevel && exp >= ExpThreshold(level + 1)) level++;
        return level;
    }

    // ── Skills ──────────────────────────────────────────────────────────────────────────────
    // Client: 49 ScriptableSkill slugs and rank ancestry; original server rows are unavailable.
    // Community policy: pre-1.2 Wiki revision 554271 (27 Jan 2022), verified in
    // docs/CLOCK-SKILLS-EQUIPMENT-20261002.md. Costs and gates apply to future purchases only.
    // IDs 1..63 retain their stored identities; missing ranks append 64..101. ParentId joins
    // ranks of ONE slug; RequiredSkillId is a separate sign prerequisite (retained authored rule).
    public sealed record Skill(int Id, string Slug, int Cost, int RequiredLevel, int? ParentId,
        bool Starting, int Rank = 1, int? RequiredSkillId = null);

    public static readonly IReadOnlyList<Skill> Skills = BuildSkills();

    private static List<Skill> BuildSkills()
    {
        var skills = new List<Skill>();
        void Add(string slug, int level, int[] ids, int[] costs, bool starting = false, int? requiredSkill = null)
        {
            if (ids.Length != costs.Length || ids.Length == 0)
                throw new InvalidOperationException("Skill ranks and costs must have equal nonzero lengths.");
            for (int rank = 0; rank < ids.Length; rank++)
                skills.Add(new Skill(ids[rank], slug, costs[rank], level,
                    rank == 0 ? null : ids[rank - 1], starting, rank + 1, requiredSkill));
        }
        Add("fast_attack", 1, [1], [0], starting: true);
        Add("strong_attack", 1, [2], [0], starting: true);
        Add("parry", 1, [3], [0], starting: true);
        Add("muscle_memory", 1, [4, 9, 10, 11, 12], [1, 3, 5, 9, 15]);
        Add("strength_training", 1, [5, 13, 14, 15, 16], [1, 3, 5, 9, 15]);
        Add("hit_deflection", 15, [6], [9]);
        Add("precise_blows", 10, [7], [6]);
        Add("crushing_blows", 10, [8], [6]);
        Add("resolve", 1, [17, 18, 19], [1, 5, 15]);
        Add("fleet_footed", 10, [20, 64, 65, 66, 67], [1, 3, 5, 9, 15]);
        Add("anatomical_knowledge", 15, [21, 68, 69, 70, 71], [1, 3, 5, 9, 15]);
        Add("lightning_reflexes", 20, [22, 72], [3, 7]);
        Add("cold_blood", 20, [23], [9]);
        Add("counterattack", 25, [24, 73], [1, 3]);
        Add("crippling_strike", 25, [25], [9]);
        Add("razor_focus", 30, [26], [12]);
        Add("battle_trance", 30, [27, 74, 75, 76, 77], [1, 3, 5, 9, 15]);
        Add("undying", 35, [28], [18]);
        Add("witcher_aura", 1, [29], [0], starting: true);
        Add("igni_sign", 1, [30], [0], starting: true);
        Add("pyromaniac", 1, [31, 32, 33, 34, 35], [1, 3, 5, 9, 15], requiredSkill: 30);
        Add("focus", 10, [36, 78, 79, 80, 81], [1, 3, 5, 9, 15]);
        Add("aard_sign", 10, [37], [5]);
        Add("quen_sign", 15, [38], [5]);
        Add("shock_wave", 15, [39, 82, 83, 84, 85], [1, 3, 5, 9, 15], requiredSkill: 37);
        Add("quen_discharge", 20, [40, 86, 87, 88, 89], [1, 3, 5, 9, 15], requiredSkill: 38);
        Add("adrenaline_burst", 25, [41], [9]);
        Add("quen_intensity", 30, [42], [9], requiredSkill: 38);
        Add("igni_intensity", 30, [43], [9], requiredSkill: 30);
        Add("aard_intensity", 30, [44], [9], requiredSkill: 37);
        Add("gorged_on_power", 35, [45], [18]);
        Add("oil_preparation", 1, [46], [0], starting: true);
        Add("brewing", 1, [47], [0], starting: true);
        Add("bomb_creation", 1, [48], [0], starting: true);
        Add("enhanced_oils", 1, [49], [9]);
        Add("tawny_owl", 1, [50], [6]);
        Add("fixative", 10, [51, 90, 91, 92, 93], [1, 3, 5, 9, 15]);
        Add("cat", 10, [52], [6]);
        Add("steady_aim", 10, [53], [6]);
        Add("acquired_tolerance", 15, [54], [9]);
        Add("advanced_steady_aim", 20, [55], [9]);
        Add("squall", 20, [56], [6]);
        Add("protective_coating", 25, [57, 94, 95, 96, 97], [1, 3, 5, 9, 15]);
        Add("fast_metabolism", 25, [58], [9]);
        Add("pyrotechnics", 25, [59, 98, 99, 100, 101], [1, 3, 5, 9, 15]);
        Add("superior_oils", 30, [60], [9]);
        Add("wolverine", 30, [61], [6]);
        Add("advanced_pyrotechnics", 30, [62], [12]);
        Add("elixir_master", 35, [63], [15]);
        return skills;
    }

    // Native HasFulfilledPrerequisities checks every explicit required ID against all owned rows.
    // Keep rank purchase order explicit as well as the ancestry used to draw/select rank chains.
    public static IEnumerable<int> SkillRequirements(Skill skill)
    {
        if (skill.ParentId is int parent) yield return parent;
        if (skill.RequiredSkillId is int required) yield return required;
    }

    public static Skill? SkillById(int id) => Skills.FirstOrDefault(skill => skill.Id == id);

    // ── Effects ─────────────────────────────────────────────────────────────────────────────
    // Client: Effects.GetUtilityEffect ids 42–50 and Effects.GetEffect ids 29–41 (see
    // connection/skill-effects-review/). effect_type_id: 1 Combat, 2 Utility.
    public sealed record EffectRow(int Id, string Name, int Type);
    public sealed record ItemEffect(int ItemId, int EffectId, int Power, int ApplyTime);

    private const int Utility = 2, Combat = 1, OnStart = 1, OnDeflecting = 5, OnLowHealth = 12,
        OnPerfectFinisher = 15, OnSkillUnlock = 18, OnPreStart = 23;

    public static readonly IReadOnlyList<EffectRow> Effects = new EffectRow[]
    {
        new(29, "lab_oil_necrophage", Combat), new(30, "lab_oil_draconid", Combat), new(31, "lab_oil_ogroid", Combat),
        new(32, "lab_oil_hybrid", Combat), new(33, "lab_oil_elemental", Combat), new(34, "lab_oil_relict", Combat),
        new(35, "lab_oil_specter", Combat), new(36, "lab_oil_insectoid", Combat), new(37, "lab_oil_animal", Combat),
        new(38, "lab_oil_vampire", Combat), new(39, "lab_oil_cursed", Combat),
        new(41, "lab_improve_attack_power", Combat), new(67, "lab_heal", Combat), new(76, "lab_heal_over_time", Combat),
        new(16, "lab_bomb_speed", Combat), new(74, "lab_bomb_throw_angle", Combat),
        // Potion, armor and sword effects (see PotionEffects, ArmorEffects, SwordEffects).
        new(1, "lab_improve_fast_attack", Combat), new(6, "lab_improve_finisher", Combat),
        new(58, "lab_deal_fire_damage", Combat),
        new(2, "lab_improve_strong_attack", Combat), new(9, "lab_gain_armor", Combat),
        new(17, "lab_signs_cooldown_reduction", Combat), new(18, "lab_damage_during_night", Combat),
        new(19, "lab_damage_when_raining", Combat), new(20, "lab_damage_on_low_hp", Combat),
        new(21, "lab_low_hp_threshold", Combat), new(26, "lab_improve_signs", Combat),
        new(40, "lab_improve_health", Combat), new(56, "lab_adrenaline_generation", Combat),
        new(59, "lab_minimum_adrenaline", Combat), new(61, "lab_improve_potion_effects", Combat),
        new(65, "lab_increase_experience", Combat), new(ExtraIngredientEffect, "lab_extra_ingredient_chance", Combat),
        new(80, "lab_impair_adrenaline_loss", Combat), new(82, "lab_improve_deflect", Combat),
        // Numeric skill contracts recovered from 1.1.116 native effect classes.
        new(3, "lab_improve_defense", Combat), new(5, "lab_improve_first_attack", Combat),
        new(7, "lab_finisher_slowdown", Combat), new(8, "lab_enemy_attack_delay", Combat),
        new(11, "lab_improve_aard", Combat), new(12, "lab_quen_reflection", Combat),
        new(13, "lab_signs_slowdown", Combat), new(15, "lab_oil_finisher", Combat),
        new(22, "lab_improve_oil", Combat), new(23, "lab_oil_defense", Combat),
        new(24, "lab_improve_bombs", Combat), new(25, "lab_igni_extra_damage_chance", Combat),
        new(4, "lab_generate_adrenaline", Combat), new(10, "lab_final_blow_survival", Combat),
        new(14, "lab_instant_sign_recovery", Combat), new(27, "lab_fast_attack_adrenaline", Combat),
        new(28, "lab_strong_attack_adrenaline", Combat),
        new(42, "lab_unlock_aard", Utility), new(43, "lab_unlock_igni", Utility), new(44, "lab_unlock_quen", Utility),
        new(45, "lab_additional_potion_slot", Utility), new(62, "lab_unlock_potion_recipe", Utility),
        new(46, "lab_craft_bombs", Utility),
        new(47, "lab_unlock_fastswordattack", Utility), new(48, "lab_unlock_strongswordattack", Utility),
        new(49, "lab_unlock_parry", Utility), new(50, "lab_unlock_deflect", Utility),
        new(77, "lab_witcher_aura_interval", Utility), new(78, "lab_witcher_aura_monsters", Utility),
    };

    public static IEnumerable<ItemEffect> SkillEffects(SkillBalancePolicy? policy = null)
    {
        policy ??= SkillBalancePolicy.Default;
        var bySlug = new Dictionary<string, int>
        {
            ["fast_attack"] = 47, ["strong_attack"] = 48, ["parry"] = 49, ["hit_deflection"] = 50,
            ["aard_sign"] = 42, ["igni_sign"] = 43, ["quen_sign"] = 44, ["bomb_creation"] = 46,
        };
        foreach (var skill in Skills)
        {
            // Community powers: pinned pre-1.2 table; Client IDs/units/triggers: native mapping.
            // Combat selects the highest owned rank, so these are full values, not increments.
            // Irrecoverable gains/chances use the explicit authored SkillBalancePolicy below.
            (int Effect, int Power, int Time)? bonus = skill.Slug switch
            {
                "muscle_memory" => (1, 4 * skill.Rank, OnStart),
                "strength_training" => (2, 4 * skill.Rank, OnStart),
                "fleet_footed" => (3, 2 * skill.Rank, OnStart),
                "anatomical_knowledge" => (6, 2 * skill.Rank, OnStart),
                "lightning_reflexes" => (7, 5 * skill.Rank, OnStart),
                "counterattack" => (5, 5 * skill.Rank, OnDeflecting),
                // Effect 8 uses milliseconds; 1000 is displayed and applied as one second.
                "crippling_strike" => (8, 1000, OnPerfectFinisher),
                "battle_trance" => (9, 4 * skill.Rank, OnStart),
                "pyromaniac" => (25, 5 * skill.Rank, OnStart),
                "focus" => (13, 15 * skill.Rank, OnStart),
                "shock_wave" => (11, 2 * skill.Rank, OnStart),
                "quen_discharge" => (12, 5 + 5 * skill.Rank, OnStart),
                "enhanced_oils" => (22, 5, OnStart),
                "fixative" => (15, 2 * skill.Rank, OnStart),
                "protective_coating" => (23, 2 * skill.Rank, OnStart),
                "pyrotechnics" => (24, 2 * skill.Rank, OnStart),
                "superior_oils" => (22, 10, OnStart),
                // Authored associations and powers, applied through verified native consumers.
                // Resolve uses a minimum floor, avoiding effect80's unsafe sum with Ursine armor.
                "resolve" => (59, policy.ResolveFloorPercentPerRank * skill.Rank, OnStart),
                "precise_blows" => (27, policy.AttackAdrenalineBonus, OnStart),
                "crushing_blows" => (28, policy.AttackAdrenalineBonus, OnStart),
                "cold_blood" => (4, policy.EventAdrenalineGain, 4), // OnParrying
                "razor_focus" => (4, policy.InitialAdrenalineGain, OnStart),
                "undying" => (10, policy.FinalBlowSurvivalChancePercent, OnStart),
                "adrenaline_burst" => (4, policy.EventAdrenalineGain, 11), // OnCastSign
                // Native event9 fires when the Quen shield ends, despite its OnQuenCast enum name.
                "quen_intensity" => (4, policy.EventAdrenalineGain, 9),
                "igni_intensity" => (4, policy.EventAdrenalineGain, 8),
                "aard_intensity" => (4, policy.EventAdrenalineGain, 7),
                "gorged_on_power" => (14, policy.InstantSignRecoveryChancePercent, OnStart),
                // Two independent angle increments: base45 gives elevations30 then15 at defaults.
                // The ballistic speed factor stays1 so the trajectory still reaches its target.
                "steady_aim" or "advanced_steady_aim" => (74, policy.BombAngleReductionDegrees, OnStart),
                "advanced_pyrotechnics" => (4, policy.EventAdrenalineGain, 10), // OnBombExplode
                _ => null,
            };
            if (bonus is { } numeric)
                yield return new ItemEffect(skill.Id, numeric.Effect, numeric.Power, numeric.Time);
            if (bySlug.TryGetValue(skill.Slug, out int effect))
                yield return new ItemEffect(skill.Id, effect, 1, OnSkillUnlock);
            if (skill.Id is 54 or 58)
                yield return new ItemEffect(skill.Id, 45, 1, OnSkillUnlock);
            // GetEffectsData (0x1A2A0C0) identifies the aura skill only when BOTH utility effects exist.
            if (skill.Id == 29)
            {
                yield return new ItemEffect(skill.Id, 77, policy.WitcherAuraIntervalSeconds, OnSkillUnlock);
                yield return new ItemEffect(skill.Id, 78, 1, OnSkillUnlock);
            }
            foreach (var recipe in Economy.Recipes.Where(recipe => recipe.RequiredSkill == skill.Id))
                yield return new ItemEffect(skill.Id, 62, recipe.Id, OnSkillUnlock);
            // Client: BombModule<T> creates its BombSpeed and BombAngle modifiers at 0, and BombAction.OnExit
            // throws at elevation 90° − BombAngle with the ballistic speed d·√(g·BombSpeed/cosθ)/√(2d·sinθ − 2h·cosθ).
            // With both at 0 a tapped bomb falls in place. Only ImproveBombSpeed (16, Percent) and
            // DecreaseBombThrowAngle (74, Point) raise them, so the starting bomb skill carries the base:
            // speed factor 1.0 (an exact ballistic hit) and a 45° throw. Values are Authored from the formula.
            if (skill.Slug == "bomb_creation")
            {
                yield return new ItemEffect(skill.Id, 16, 100, OnStart);
                yield return new ItemEffect(skill.Id, 74, 45, OnStart);
            }
        }
    }

    // ── Items ───────────────────────────────────────────────────────────────────────────────
    // Slugs are Client localisation keys (ITEMS/NAMES/OILS|POTIONS|BOMBS/<SLUG>). Oil bonuses are
    // Community (Gamepressure oils page, 21 Jul 2021): basic +33 %, family oils +100 %.
    // Client: DataManager.LoadOils casts every oil effect to OilCombatEffect, whose only subclass is
    // TryToImproveAttacksAgainstFamily (ids 29–39, families 1–11); any other effect id breaks loading.
    // The basic oil therefore carries the family effect for every family (EffectId 0 = all).
    // Item ids share one client storage across kinds, so each kind has its own hundred. Donor graphs fix
    // three ids: the exam (tut_gravehag) offers oil 301, bomb 402 and potion 205; the Alghul fight uses
    // bomb 401. Which slug each id carries is Authored: oils and bombs follow the Gamepressure list order
    // (basic first), 205 is Swallow and the other potions follow the client localisation order.
    public sealed record Oil(int Id, string Slug, int EffectId, int Power, bool FamilyOil);

    public static readonly IReadOnlyList<Oil> Oils = new Oil[]
    {
        new(301, "oil_basic", 0, 33, false),
        new(302, "oil_necrophage", 29, 100, true), new(303, "oil_ogroid", 31, 100, true),
        new(304, "oil_cursed", 39, 100, true), new(305, "oil_relict", 34, 100, true),
        new(306, "oil_hybrid", 32, 100, true), new(307, "oil_insectoid", 36, 100, true),
        new(308, "oil_draconid", 30, 100, true), new(309, "oil_specter", 35, 100, true),
        new(310, "oil_elemental", 33, 100, true), new(311, "oil_vampire", 38, 100, true),
    };

    public static IEnumerable<ItemEffect> OilEffects() => Oils.SelectMany(oil => oil.EffectId == 0
        ? Enumerable.Range(29, 11).Select(effect => new ItemEffect(oil.Id, effect, oil.Power, OnStart))
        : new[] { new ItemEffect(oil.Id, oil.EffectId, oil.Power, OnStart) });

    // Item effects. Client: DataManager.LoadPotions/LoadEquipment put each item's effects, in row order, into
    // its description (LocalizationHelper.ReplaceEffects: tag #n = effect n's GetPower(), formatted "0.##"),
    // so an item without rows shows a raw "#0%". Effects.GetEffect maps the ids to classes; GetPower is the
    // power for Percent and Point classes and power / 10 for Permille (HealOverTime). Values are Community
    // (Gamepressure potions and armors, 21 Jul 2021; TheGamer potions, 27 Jul 2021, and equipment, 6 Aug 2021)
    // unless marked Authored; apply times are Authored.
    public static IEnumerable<ItemEffect> PotionEffects() => new[]
    {
        // Swallow: HealOverTime (Client) subscribes to the character's OnUpdate for the rest of the fight and
        // heals GetMultipliedPower (power / 1000) × dt / 3 s of the maximum vitality; its description shows
        // power / 10. The guides quote the in-game "1 %" (#0), so power is 10, from the moment it is drunk.
        new ItemEffect(205, 76, 10, OnStart),
        new ItemEffect(201, 41, 33, OnStart),   // Thunderbolt: +33 % melee damage (ImproveAttackPower).
        new ItemEffect(202, 40, 50, OnStart),   // Swift: +50 % maximum vitality (ImproveHealth).
        new ItemEffect(203, 59, 25, OnStart),   // Blizzard: partly filled critical hit meter; 25 % is Authored.
        new ItemEffect(204, 17, 30, OnStart),   // Tawny Owl: sign cooldown -30 %.
        new ItemEffect(206, 18, 75, OnStart),   // Cat: +75 % damage at night.
        new ItemEffect(207, 19, 75, OnStart),   // Squall: +75 % damage during precipitation.
        // Wolverine: "+#1 % damage when vitality reaches #0 %": the low-health threshold (LowerLowHPProc) first,
        // then +100 % damage applied on low health.
        new ItemEffect(208, 21, 50, OnStart), new ItemEffect(208, 20, 100, OnLowHealth),
        new ItemEffect(209, 26, 100, OnStart),  // Petri's Philter (potion_mariborforest): +100 % sign intensity.
    };

    // ── Equipment ───────────────────────────────────────────────────────────────────────────
    // Client (1.1.116): 19 sword and 8 armour prefabs (appearance/sword|armor/<slug>), ITEMS/NAMES and
    // ITEMS/DESCRIPTIONS/SWORDS|ARMORS/<SLUG> naming each effect ("#0%" is the effect's power); a sword row's
    // sword_type 0 makes steel damage and 1 silver (SwordModule.Init); swords have no damage stat. Shop: ShopTab
    // Equipment, GroupType Armors, Steel_Swords, Silver_Swords (ItemTypeIds ARMORS 8, SWORDS 9). Community: effects
    // and prices from TheGamer "All Equipment" (6 Aug 2021) and Gamepressure (21 Jul 2021); Dawnbringer +10 % damage
    // at night (Game Rant, 27 Nov 2021; the Sword in the Stone reward, Witcher Wiki); Hermit's Armor is the reward
    // for lifting the striga's curse in "The Sins of Our Fathers" (Witcher Wiki). Authored: ids 7+, the Hermit's
    // Armor power, the gold price of the Witcher's silver sword (a real-money bundle in 2021), and the Kaer Morhen
    // steel sword as a starting gift (a launch-week reward). Experience (65) and extra ingredients are Dummy
    // classes in the client: the server applies them (PlayerService, the kill's reward).
    public sealed record Gear(int Id, string Slug, int SwordType, int? Price, (int Effect, int Power)[] Effects);

    public const int SteelSword = 0, SilverSword = 1, NotSword = -1;

    // The client names effect 66 ExtraIngredientChance (EffectBehaviourType), but Effects.GetEffect (0x194E178) builds a Dummy with
    // power 0 for it, and for 0, 42-55, 60, 62, 63, 68, 73, 77-79 and 81: Wolven armor's description read "Grants a 0% chance of
    // defeated monsters dropping extra alchemy ingredients". Only 70 and 71 build a Dummy that keeps the row's power (the
    // description's #0), and nothing in the client reads them, so the effect rides on 71 (IncreaseIngredientsGathering).
    public const int ExtraIngredientEffect = 71;

    public static readonly IReadOnlyList<Gear> Armors = new Gear[]
    {
        new(1, "armor_ursine", NotSword, 3400, new[] { (80, 80) }),   // critical meter loss on damage -80 %
        new(2, "armor_griffin", NotSword, 6800, new[] { (82, 10) }),  // a parried hit reflects 10 % (ImproveDeflect)
        new(3, "armor_wolven", NotSword, 6800, new[] { (ExtraIngredientEffect, 50) }), // 50 % chance of extra alchemy ingredients
        new(4, "armor_feline", NotSword, 3400, new[] { (9, 15) }),    // unparried hits -15 % (GainArmor)
        new(5, "armor_manticore", NotSword, 6800, new[] { (61, 100) }), // White Gull: potion effects +100 %
        new(6, "armor_kaer_morhen", NotSword, 12000, new[] { (65, 25) }), // +25 % experience from monsters
        new(7, "armor_adepts", NotSword, null, Array.Empty<(int, int)>()), // starting armour
        new(8, "armor_hermits", NotSword, null, new[] { (80, 50) }),  // quest reward; critical meter loss -50 % (Authored)
    };

    public static readonly IReadOnlyList<Gear> Swords = new Gear[]
    {
        new(1, "sword_steel_griffin", SteelSword, 3200, new[] { (26, 30) }),   // sign intensity +30 %
        new(2, "sword_silver_griffin", SilverSword, 3600, new[] { (26, 30) }),
        new(3, "sword_steel_wolven", SteelSword, 3200, new[] { (56, 10) }),    // critical meter charge +10 (Point)
        new(4, "sword_silver_wolven", SilverSword, 3600, new[] { (56, 10) }),
        new(5, "sword_steel_ursine", SteelSword, 1600, new[] { (2, 15) }),     // strong attacks +15 %
        new(6, "sword_silver_ursine", SilverSword, 1800, new[] { (2, 15) }),
        new(7, "sword_steel_witchers", SteelSword, null, Array.Empty<(int, int)>()),   // starting sword
        new(8, "sword_silver_witchers", SilverSword, 800, Array.Empty<(int, int)>()),  // Authored price
        new(9, "sword_steel_feline", SteelSword, 1600, new[] { (1, 15) }),     // fast attacks +15 %
        new(10, "sword_silver_feline", SilverSword, 1800, new[] { (1, 15) }),
        new(11, "sword_steel_manticore", SteelSword, 3200, new[] { (17, 30) }), // sign cooldown -30 %
        new(12, "sword_silver_manticore", SilverSword, 3600, new[] { (17, 30) }),
        new(13, "sword_steel_kaer_morhen", SteelSword, null, new[] { (65, 10) }), // experience +10 %; starting gift
        new(14, "sword_steel_caerme", SteelSword, 6400, new[] { (6, 50) }),     // critical hit (finisher) damage +50 %
        new(15, "sword_silver_melltith", SilverSword, 7200, new[] { (58, 15) }), // 15 % chance of extra fire damage
        new(16, "sword_silver_legendary", SilverSword, 12000, new[] { (65, 25) }), // A'báeth: experience +25 %
        new(17, "sword_silver_dawnbringer", SteelSword, null, new[] { (18, 10) }), // quest reward; +10 % at night
    };

    /// <summary>A new profile's equipment: the Witcher's steel sword, the Kaer Morhen steel sword and Adept's Armor.</summary>
    public static readonly (int[] Swords, int[] Armors, int Sword, int Armor) StartingGear = (new[] { 7, 13 }, new[] { 7 }, 7, 7);

    public static Gear? ArmorById(int id) => Armors.FirstOrDefault(a => a.Id == id);
    public static Gear? SwordById(int id) => Swords.FirstOrDefault(s => s.Id == id);

    public static IEnumerable<ItemEffect> ArmorEffects() =>
        Armors.SelectMany(a => a.Effects.Select(e => new ItemEffect(a.Id, e.Effect, e.Power, e.Effect == 61 ? OnPreStart : OnStart)));

    public static IEnumerable<ItemEffect> SwordEffects() =>
        Swords.SelectMany(s => s.Effects.Select(e => new ItemEffect(s.Id, e.Effect, e.Power, OnStart)));

    /// <summary>Experience bonus in percent (effect 65, IncreaseExperience) of the given equipment.</summary>
    public static int ExperienceBonus(IEnumerable<Gear?> gear) =>
        gear.OfType<Gear>().SelectMany(g => g.Effects).Where(e => e.Effect == 65).Sum(e => e.Power);

    /// <summary>Chance in percent of extra alchemy ingredients (<see cref="ExtraIngredientEffect"/>) of the given equipment.</summary>
    public static int ExtraIngredientChance(IEnumerable<Gear?> gear) =>
        gear.OfType<Gear>().SelectMany(g => g.Effects).Where(e => e.Effect == ExtraIngredientEffect).Sum(e => e.Power);

    public static readonly IReadOnlyList<(int Id, string Slug)> Potions = new[]
    {
        (201, "potion_thunderbolt"), (202, "potion_swift"), (203, "potion_blizzard"), (204, "potion_tawnyowl"),
        (205, "potion_swallow"), (206, "potion_cat"), (207, "potion_squall"), (208, "potion_wolverine"),
        (209, "potion_mariborforest"),
    };

    // Damage types: ids are the client Vulnerability.Type values. Bomb damage is Community (Gamepressure
    // bomb screens: basic kinetic 525; grapeshot steel 525 + kinetic 800; moon dust silver 525 + kinetic 800;
    // dancing star fire 525 + kinetic 800; dimeritium kinetic 525); snowball, radius and style are Authored.
    // Client: LoadBombs replaces description tag #n with the bomb's n-th damage row, and the texts put the
    // kinetic damage at #0 and the element at #1 (dimeritium: #1 kinetic), so rows keep that order.
    // Client: LoadDamageTypes names each type SKILLS/NAMES/ELEMENT/<SLUG> and its icon is icon_<slug> in the GUI
    // atlas (icon_damage_fire … icon_damage_slow for strong attacks), so the slugs are damage_<kind>.
    public static readonly IReadOnlyList<(int Id, string Slug)> DamageTypes = new[]
    {
        (1, "damage_fire"), (2, "damage_silver"), (3, "damage_steel"), (4, "damage_kinetic"), (5, "damage_fast"),
        (6, "damage_slow"), (7, "damage_dimeritium"),
    };

    // Dimeritium type 7 enables its native vulnerability debuff; damage is the kinetic row only.
    public static readonly IReadOnlyList<(int BombId, int DamageType, int Amount)> BombDamage = new[]
    {
        (401, 4, 525), (402, 4, 800), (402, 3, 525), (403, 4, 800), (403, 2, 525),
        (404, 4, 800), (404, 1, 525), (405, 7, 0), (405, 4, 525), (406, 4, 525),
    };

    public const int BombRadius = 3;

    // Bomb 401 keeps the inherited slug; all bombs get damage rows and an impact explosion.
    public static readonly IReadOnlyList<(int Id, string Slug)> ExtraBombs = new[]
    {
        (402, "bomb_grapeshot"), (403, "bomb_moondust"), (404, "bomb_dancingstar"), (405, "bomb_dimeritium"),
        (406, "bomb_snowball"),
    };

    // ── Auto-equip ──────────────────────────────────────────────────────────────────────────
    // Client: DataManager.LoadAutoEquip groups `auto_equip` rows by item_type_id (ItemTypeIds: bombs 2,
    // potions 3, oils 4, swords 9) and AutoEquipController.CalculatePriority indexes every owned item, so
    // each item needs a row. CalculatePriority keeps only items whose summed priority is at least 1, so
    // every row has an Authored base of 10 in the time-of-day, weather and difficulty columns; matching
    // family oils add 100 (basic oil 33 everywhere), swords and bombs add weight by vulnerability.
    public static readonly string[] AutoEquipColumns =
    {
        "attack_strong", "attack_steel", "attack_silver", "attack_fire", "attack_kinetic", "attack_fast",
        "attack_dimeritium", "day", "night", "weather_normal", "weather_rain", "weather_fog",
        "family_draconide", "family_ogroid", "family_hybrid", "family_elemental", "family_relict",
        "family_specter", "family_insectoid", "family_vampire", "family_cursed", "family_necrophage",
        "difficulty1", "difficulty2", "difficulty3", "difficulty4", "difficulty5", "difficulty6",
        "difficulty7", "difficulty8",
    };

    private static readonly Dictionary<int, string> FamilyColumnByEffect = new()
    {
        [29] = "family_necrophage", [30] = "family_draconide", [31] = "family_ogroid", [32] = "family_hybrid",
        [33] = "family_elemental", [34] = "family_relict", [35] = "family_specter", [36] = "family_insectoid",
        [38] = "family_vampire", [39] = "family_cursed",
    };

    private static readonly string[] AutoEquipBaseColumns = AutoEquipColumns
        .Where(column => column is "day" or "night" || column.StartsWith("weather_") || column.StartsWith("difficulty"))
        .ToArray();

    public static IEnumerable<(int ItemType, int ItemId, Dictionary<string, int> Weights)> AutoEquipRows() =>
        SpecificAutoEquipRows().Select(row =>
        {
            var weights = AutoEquipBaseColumns.ToDictionary(column => column, _ => 10);
            foreach (var (column, weight) in row.Weights) weights[column] = weight;
            return (row.ItemType, row.ItemId, weights);
        });

    private static IEnumerable<(int ItemType, int ItemId, Dictionary<string, int> Weights)> SpecificAutoEquipRows()
    {
        foreach (var oil in Oils)
            yield return (4, oil.Id, oil.FamilyOil
                ? new Dictionary<string, int> { [FamilyColumnByEffect[oil.EffectId]] = 100 }
                : FamilyColumnByEffect.Values.ToDictionary(column => column, _ => 33));
        foreach (var (id, _) in Potions) yield return (3, id, new Dictionary<string, int>());
        var bombWeights = new Dictionary<int, string[]>
        {
            [401] = new[] { "attack_kinetic" }, [402] = new[] { "attack_steel", "attack_kinetic" },
            [403] = new[] { "attack_silver", "attack_kinetic" }, [404] = new[] { "attack_fire", "attack_kinetic" },
            [405] = new[] { "attack_dimeritium", "attack_kinetic" }, [406] = new[] { "attack_kinetic" },
        };
        foreach (var (id, columns) in bombWeights) yield return (2, id, columns.ToDictionary(column => column, _ => 50));
        foreach (var sword in Swords)   // steel or silver damage by sword_type
            yield return (9, sword.Id, new Dictionary<string, int> { [sword.SwordType == SteelSword ? "attack_steel" : "attack_silver"] = 100 });
    }

    public const int BasicBombId = 401, ExamBombId = 402;
    public const int BasicOilId = 301, HybridOilId = 306, SwallowPotionId = 205;

    public static bool KnownItem(string kind, int id) => kind switch
    {
        ItemKinds.Oils => Oils.Any(oil => oil.Id == id),
        ItemKinds.Potions => Potions.Any(potion => potion.Id == id),
        ItemKinds.Bombs => id == BasicBombId || ExtraBombs.Any(bomb => bomb.Id == id),
        ItemKinds.Ingredients => Economy.Ingredients.Any(ingredient => ingredient.Id == id),
        ItemKinds.SensesPotions => id == Economy.Falcon,
        _ => false,
    };

    // ── Story ───────────────────────────────────────────────────────────────────────────────
    // Tutorial quest 144 ("Final Exam"): graph identities, outputs and POI settings are Donor/Client
    // (tut_* graphs, poi_settings/s00/tutorial). Node ids: 228 is the tut_ghoul graph's QuestNodeId;
    // 229 is Authored. Stage order follows the graphs and the Gamepressure "Final Exam" walkthrough.
    public sealed record QuestNode(string Stage, long InstanceId, int NodeId, int QuestId, string PoiSettings, string Graph);

    public const string TutorialGhoul = "tutorial_ghoul", TutorialWitcher = "tutorial_witcher",
        TutorialExam = "tutorial_exam", Prologue = "thorstein";

    public static readonly IReadOnlyList<QuestNode> TutorialNodes = new QuestNode[]
    {
        new(TutorialGhoul, 512475750302797027L, 228, 144, "assets/_bundledassets/story/poi_settings/s00/tutorial/ghoul_lq.asset", "s00/tutorial/tut_ghoul"),
        new(TutorialWitcher, 1271842437439635223L, 230, 144, "assets/_bundledassets/story/poi_settings/s00/tutorial/tutorial_witcher_lq.asset", "s00/tutorial/tut_witcher"),
        new(TutorialExam, 1152921521786716389L, 229, 144, "assets/_bundledassets/story/poi_settings/s00/tutorial/devourer_lq.asset", "s00/tutorial/tut_gravehag"),
    };

    public static QuestNode? TutorialNode(string? stage) => TutorialNodes.FirstOrDefault(node => node.Stage == stage);

    /// <summary>Stage after a graph output; null keeps the current stage.</summary>
    public static string? NextStage(string? stage, string output) => (stage, output) switch
    {
        (TutorialGhoul, "tutorial_end") => TutorialWitcher,
        (TutorialGhoul or TutorialWitcher, "exam") => TutorialExam,
        (TutorialExam, "exam_end") => Prologue,
        // Donor prolog_01_dead_horse: "dead_horse" (both fights won), "1ghoul_left" and "2ghouls_left"
        // (a fight lost) all set fact 10145 = 4 and play the same Thorstein dialog (prolog_02); each one
        // leads on to the griffin. Only "2ghouls_left" was known before, so a won fight kept the horse.
        (LocalProfileStore.DeadHorseStage, "dead_horse" or "1ghoul_left" or "2ghouls_left") => LocalProfileStore.GriffinStage,
        // Donor prolog_01_griffin: both endings close "Winged Bandit" and queue quest node 287. Its graph,
        // prolog_02_map, starts "A Joint Venture" (fact 10146 = 1, tracked quest, journal notice) and ends
        // with "empty"; the rest of that quest is not reconstructed yet, so no story node follows.
        (LocalProfileStore.GriffinStage, "griffin_1" or "griffin_2") => LocalProfileStore.PrologueDoneStage,
        // A griffin beaten before the closing stage existed leaves the profile at the griffin stage.
        (LocalProfileStore.PrologueDoneStage or LocalProfileStore.GriffinStage, "empty") => LocalProfileStore.JointVentureStage,
        // "A Joint Venture" (see JointVentureNodes): the map dialog leads to the obelisk, the obelisk to the
        // gifts and the gargoyle, and the gargoyle's closing cutscene ends the quest.
        (LocalProfileStore.JointVentureStage, "map") => LocalProfileStore.JvObeliskStage,
        (LocalProfileStore.JvObeliskStage, "obelisk") => LocalProfileStore.JvGiftsStage,
        (LocalProfileStore.JvGiftsStage, "success" or "success_heart") => LocalProfileStore.JvDoneStage,
        _ => null,
    };

    // Story placement. Guides (GamerJournalist, Gamepressure, 2021): the horse lies about 1 km from where
    // Thorstein is met and is marked on the map; the griffin is found inside a yellow circle that shrinks as
    // the player gets closer. Client: PoiDisplayMode 1 Normal, 2 CloseFollow (shown beside the player),
    // 3 FarFollow, 4 Hunt. The distance bands are Authored and fit the 3×3 level-14 cells the client loads
    // around the player (about ±850 m from the centre).
    public const int DisplayNormal = 1, DisplayCloseFollow = 2, DisplayHunt = 4;

    public static (double Min, double Max)? StoryDistance(string? stage) => stage switch
    {
        LocalProfileStore.DeadHorseStage => (500, 1000),
        LocalProfileStore.GriffinStage => (250, 700),
        _ => null,
    };

    public static int StoryDisplayMode(string? stage) =>
        stage == LocalProfileStore.GriffinStage ? DisplayHunt : DisplayNormal;

    // Quest node 287 (queued by prolog_01_griffin). Client: BehaviourGraphModule.FireQueuedGraph starts the
    // graph of the nearest quest POI with that QuestNodeId when the griffin graph ends, so the node is served
    // beside the player (CloseFollow). Instance id and the Thorstein POI settings are Authored.
    public static readonly QuestNode JointVentureStart = new(LocalProfileStore.PrologueDoneStage,
        5124758224582476011L, 287, 146, "assets/_bundledassets/story/poi_settings/_common/thorstein_lq.asset",
        "s00/prolog/prolog_02_map");

    // "A Joint Venture" (quest 146). Client (1.1.116 catalog and log_prolog_02) and Donor (1.3.102 graphs):
    // the journal's treasure map has an "Examine" button that runs qi_map_button as quest node 236 (Thorstein's
    // dialog, output "map", fact 107 = 3, "The map has been updated!"). The elven obelisk's investigation (rune
    // puzzle) sets facts 97/98/99 = 1 and ends with "obelisk"; then the stone crown and the stone heart are each
    // guarded by a wraith (outputs crown/heart, *_again after a lost try, *_fail), the stone sword is an
    // investigation ("sword"), and the gargoyle king takes one gift: the heart leads to the gargoyle fight
    // ("gargoyle", "gargoyle_again", "gargoyle_fail"), a wrong or missing gift to a wraith ("wraith_won",
    // "wraith_fail"); the figurine cutscene and Thorstein's dialog end the quest with "success" or
    // "success_heart". Community (Gamepressure "A Joint Venture"): after the monolith three places appear on
    // the map (crown, heart, sword); one artifact is enough and the heart is the right one. Graph instance ids
    // and POI settings are Client/Donor; node ids other than 236 and the placement are Authored
    // (in the 9000s, because season 1 graphs use 289, 291 and 292 for other nodes).
    public sealed record StoryNode(string Key, long InstanceId, int NodeId, string PoiSettings, string Graph,
        double MinDistance, double MaxDistance, string? Near = null);

    private const string PrologPoi = "assets/_bundledassets/story/poi_settings/s00/prolog/";
    public const int MapButtonNodeId = 236;
    public static readonly StoryNode Obelisk = new("obelisk", 5124758224582476016L, 9288, PrologPoi + "elven_obelisk.asset",
        "s00/prolog/prolog_02_obelisk", 300, 800);
    public static readonly StoryNode StoneCrown = new("crown", 5124758224582476014L, 9289, PrologPoi + "stone_crown.asset",
        "s00/prolog/prolog_02_crown", 150, 600);
    public static readonly StoryNode StoneSword = new("sword", 5124758224582476015L, 9290, PrologPoi + "stone_sword.asset",
        "s00/prolog/prolog_02_sword", 150, 600);
    public static readonly StoryNode StoneHeart = new("heart", 5124758224582476013L, 9291, PrologPoi + "stone_heart.asset",
        "s00/prolog/prolog_02_heart", 150, 600);
    // The gargoyle king guards the treasure the obelisk points to, so it stands near the obelisk.
    public static readonly StoryNode GargoyleKing = new("gargoyle", 5124756678394249457L, 9292, PrologPoi + "gargoyle_king_lq.asset",
        "s00/prolog/prolog_02_gargoyle", 0, 200, Near: "obelisk");
    public static readonly IReadOnlyList<StoryNode> JointVentureGifts = new[] { StoneCrown, StoneSword, StoneHeart };
    public static readonly IReadOnlyList<StoryNode> JointVentureAll = new[] { Obelisk, StoneCrown, StoneSword, StoneHeart, GargoyleKing };

    /// <summary>The story nodes shown on the map at a stage of "A Joint Venture", or null for other stages.
    /// A gift stays until its goal is reached (a lost wraith fight keeps it for another try); the gargoyle
    /// appears once a gift has been visited and stays until the quest ends.</summary>
    public static IReadOnlyList<StoryNode>? JointVentureNodes(string? stage, IReadOnlyCollection<string>? done)
    {
        done ??= Array.Empty<string>();
        return stage switch
        {
            LocalProfileStore.JvObeliskStage => new[] { Obelisk },
            LocalProfileStore.JvGiftsStage => JointVentureGifts.Where(gift => !done.Contains(gift.Key))
                .Concat(JointVentureGifts.Any(gift => done.Contains(gift.Key)) ? new[] { GargoyleKing } : Array.Empty<StoryNode>())
                .ToList(),
            _ => null,
        };
    }

    /// <summary>The later "A Joint Venture" stage the saved facts show the player has reached when the output
    /// that moves the stage was missed (sent to a server that did not know it yet), or null. Donor graphs:
    /// the map dialog sets fact 107 = 3, the obelisk 107 = 4, the figurine cutscene 100 = 4 or 5.</summary>
    public static string? StageFromFacts(string? stage, IReadOnlyDictionary<int, int> facts)
    {
        int map = facts.GetValueOrDefault(107), treasure = facts.GetValueOrDefault(100);
        string? reached = treasure >= 4 ? LocalProfileStore.JvDoneStage
            : map >= 4 ? LocalProfileStore.JvGiftsStage
            : map >= 3 ? LocalProfileStore.JvObeliskStage : null;
        bool inQuest = stage is LocalProfileStore.JointVentureStage or LocalProfileStore.JvObeliskStage or LocalProfileStore.JvGiftsStage;
        return inQuest && reached is not null && reached != stage && JointVentureOrder(reached) > JointVentureOrder(stage) ? reached : null;
    }

    private static int JointVentureOrder(string? stage) => stage switch
    {
        LocalProfileStore.JointVentureStage => 1,
        LocalProfileStore.JvObeliskStage => 2,
        LocalProfileStore.JvGiftsStage => 3,
        LocalProfileStore.JvDoneStage => 4,
        _ => 0,
    };

    /// <summary>The story node whose goal a graph output reaches, if any.</summary>
    public static string? CompletedStoryNode(string output) => output switch
    {
        "crown" or "crown_again" => StoneCrown.Key,
        "heart" or "heart_again" => StoneHeart.Key,
        "sword" => StoneSword.Key,
        _ => null,
    };

    public sealed record Reward(int Exp, int Gold, Dictionary<string, Dictionary<int, int>> Items);

    // Bestiary knowledge. Client: DataManager.LoadMonsterKnowledge keeps, per monster, level -> threshold (the
    // last row of a level wins) and inserts each description line at index level - 1. MonsterKnowledge.
    // CalculateData walks the levels in order and spends each level's threshold from the kills, so the
    // thresholds are increments; MaxLevel is the highest level and a monster is done after three claims
    // (MAX_LEVEL = 3). CanClaim = LastClaimedTier < Level, a claim takes LastClaimedTier + 1, and
    // PlayerSkills.OnClaimMonsterKnowledgeRewardResponse adds the response's SkillPoints. Client (I2Languages):
    // every monster has five MONSTERS/DESCRIPTIONS/<X>/INFO_n lines (family, habitat, length, weight, trivia).
    // Community pre-1.2 sources: pinned wiki bestiary revision554267 plus TouchTapPlay1Aug2021:
    // cumulative common3/50/150, rare2/10/30, legendary1/2/6. The client consumes incremental thresholds.
    // The wiki's legendary "another" wording is ambiguous; the contemporary guide supplies explicit totals.
    public static IReadOnlyList<int> KnowledgeThresholds(int monsterId) => WorldBestiary.Of(monsterId)?.Rarity switch
    {
        2 => new[] { 2, 8, 20 },
        3 => new[] { 1, 1, 4 },
        _ => new[] { 3, 47, 100 },
    };
    public const int KnowledgeTierSkillPoints = 1;
    public static int KnowledgeTier(int monsterId, int kills)
    {
        int tier = 0, needed = 0;
        foreach (int threshold in KnowledgeThresholds(monsterId))
        {
            needed += threshold;
            if (kills < needed) break;
            tier++;
        }
        return tier;
    }

    /// <summary>Description rows of one monster as (level, INFO line): lines 1 and 2 at levels 1 and 2, lines 3-5
    /// at level 3 in reverse order, since the client inserts each line at index level - 1.</summary>
    public static IEnumerable<(int Level, int Line)> DescriptionRows() =>
        new[] { (1, 1), (2, 2), (3, 5), (3, 4), (3, 3) };

    // Player modifiers. Client: story graphs add and remove them (AddExpiringEffect / RemoveExpiringEffect,
    // AddPlayerModifier 90 / RemovePlayerModifier 92), and PlayerModifiersModule.GetActiveEffects looks every
    // active one up in the player_modifiers table. The season 1 graphs use ids 2-7 with durations of 600 s to
    // 24 h (-1 until removed). Rows (id, slug) come with the season 1 story (StoryEngine.Modifiers): Authored ids
    // for the client's eight s01_* slugs (NOTIFICATIONS/EFFECT/<SLUG>), matched to the graphs by duration and use.
    // Other ids are refused, so the client never holds a modifier it cannot look up.
    public static readonly IReadOnlyList<(int Id, string Slug)> PlayerModifiers =
        StoryEngine.Modifiers.Select(m => (m.Id, m.Slug)).ToArray();

    // Vulnerabilities: Community (M01, the community Monster Slayer sheet, "Vulnerabilities" columns Strong, Fast,
    // Steel, Silver, Fire, Kinetic, Dime), as damage_types ids (see DamageTypes). The client shows them in the
    // bestiary; a monster without any shows the untranslated UI/PANELS/BESTIARY/NOT_VULNERABLE.
    public static readonly IReadOnlyDictionary<string, int[]> Vulnerabilities = new Dictionary<string, int[]>
    {
        ["ghoul"] = new[] { 5, 2 }, ["alghoul"] = new[] { 6, 2 }, ["drowner"] = new[] { 6, 3, 1 },
        ["nekker"] = new[] { 5, 2, 4 }, ["nekkerwarrior"] = new[] { 6, 2 }, ["werewolf"] = new[] { 5, 2, 1 },
        ["smalldraconid"] = new[] { 6, 3 }, ["banshee"] = new[] { 5, 2 }, ["gryphon"] = new[] { 5, 3, 1, 4 },
        ["devourer"] = new[] { 6, 2, 4 }, ["wraith"] = new[] { 5, 2 }, ["wraith_lvl2"] = new[] { 5, 2 },
        ["gargoyle"] = new[] { 6, 3, 7 },
        ["endriagaworker"] = new[] { 5, 3, 1 }, ["endriagatailed"] = new[] { 6, 3, 1 }, ["endriagaspikey"] = new[] { 6, 3, 1 },
    }.Concat(StoryEngine.Vulnerabilities).Concat(WorldBestiary.Vulnerabilities).ToDictionary(pair => pair.Key, pair => pair.Value);

    /// <summary>One-time rewards per graph output.</summary>
    public static Reward? RewardFor(string output) => output switch
    {
        // Exam kit: tut_gravehag requires an oil, a bomb and a potion and offers exactly oil 301, bomb 402
        // and potion 205 (Donor). Quantities are Authored; two bombs mirror the two training throws.
        "exam" => new Reward(0, 0, Items((ItemKinds.Oils, BasicOilId, 1), (ItemKinds.Bombs, ExamBombId, 2),
            (ItemKinds.Potions, SwallowPotionId, 1))),
        // Maintainer (reward list, 10 Oct 2026): no reward (Gamepressure said 1500 XP and 300 gold). Recorded once for the
        // devourer's bestiary entry (OutputKills).
        "exam_end" => new Reward(0, 0, Items()),
        // Nothing to hand over: recorded once so the tutorial ghoul's bestiary entry goes out once (OutputKills).
        "tutorial_end" => new Reward(0, 0, Items()),
        // Client (1.1.116 I2Languages) and Donor (prolog_02 dialog): Thorstein hands over the Hybrid Oil after the
        // horse fights ("[Take it]. Hybrid oil? …"), in the dialog that closes all three horse endings; his first
        // dialog (prolog_01) gives nothing. GamerJournalist's "on accepting" skips the horse part entirely.
        "dead_horse" or "1ghoul_left" or "2ghouls_left" => new Reward(0, 0, Items((ItemKinds.Oils, HybridOilId, 1))),
        // "Winged Bandit". Maintainer: 250 XP and 45 orens (Gamepressure said 1000 XP and 100 gold).
        "griffin_1" or "griffin_2" => new Reward(250, 45, Items()),
        // "A Joint Venture". Authored: a won wraith fight gives the difficulty-2 fight experience and the
        // gargoyle king the difficulty-3 one (BaseExp). Maintainer: 275 XP for the quest (Gamepressure said 60 gold).
        "crown" or "crown_again" or "heart" or "heart_again" or "wraith_won" => new Reward(BaseExp(2), 0, Items()),
        "gargoyle" or "gargoyle_again" => new Reward(BaseExp(3), 0, Items()),
        "success" or "success_heart" => new Reward(275, 0, Items()),
        _ => null,
    };

    /// <summary>Monsters beaten in a story graph fight, by reward key: the fight's result reaches the server as
    /// a graph output, not CombatEnd, so these count once per story fight (Donor graphs: tut_gravehag's
    /// devourer before "exam_end", the griffin before either griffin ending, the wraiths guarding the crown and
    /// the heart or taking a wrong gift, the gargoyle king). Client: QuestEndRequestNode adds the
    /// EndBehaviourGraph response's BestiaryEntries to the bestiary (BestiaryKnowledge.AddKnowledge).</summary>
    public static IReadOnlyDictionary<int, int>? StoryKills(string rewardKey) => rewardKey switch
    {
        "exam_end" => new Dictionary<int, int> { [10] = 1 },
        "griffin" => new Dictionary<int, int> { [9] = 1 },
        "crown" or "heart" or "wraith_won" => new Dictionary<int, int> { [11] = 1 },
        "gargoyle" => new Dictionary<int, int> { [13] = 1 },
        _ => null,
    };

    public const int GhoulId = 1, AlghoulId = 2;

    /// <summary>Story fights whose graph keeps the result in a fact, counted from the profile's facts, so profiles
    /// that won them before this was known count them too. Donor graphs, and no other graph sets these facts:
    /// tut_ghoul sets fact 91 = 1 on its ghoul fight's "End By Win", before "tutorial_end";
    /// prolog_01_dead_horse keeps its two alghoul fights in fact 94: -1 after the first win, -2 after the second,
    /// -3 when "dead_horse" closes, 1 when the second is lost ("1ghoul_left") and 2 when the first is
    /// ("2ghouls_left").</summary>
    public static Dictionary<int, int> FactKills(IReadOnlyDictionary<int, int> facts)
    {
        var kills = new Dictionary<int, int>();
        if (facts.GetValueOrDefault(91) == 1) kills[GhoulId] = 1;
        int alghouls = facts.GetValueOrDefault(94) switch { -1 or 1 => 1, -2 or -3 => 2, _ => 0 };
        if (alghouls > 0) kills[AlghoulId] = alghouls;
        return kills;
    }

    /// <summary>The EndBehaviourGraph (57) response's BestiaryEntries when the output's reward is granted: the
    /// fact-kept fights from the facts sent with the output, the others by reward key.</summary>
    public static IReadOnlyDictionary<int, int>? OutputKills(string output, IReadOnlyDictionary<int, int> facts)
    {
        int? monster = output switch
        {
            "tutorial_end" => GhoulId,
            "dead_horse" or "1ghoul_left" or "2ghouls_left" => AlghoulId,
            _ => null,
        };
        if (monster is null) return StoryKills(RewardKey(output));
        int count = FactKills(facts).GetValueOrDefault(monster.Value);
        return count > 0 ? new Dictionary<int, int> { [monster.Value] = count } : null;
    }

    /// <summary>Won fights per monster: world and summoned fights, the story fights of granted rewards and the
    /// fact-kept story fights.</summary>
    public static Dictionary<int, int> AllKills(LocalProfileStore.PlayerState player, IReadOnlyDictionary<int, int> facts)
    {
        var kills = new Dictionary<int, int>(player.Kills ?? new Dictionary<int, int>());
        var story = player.Granted.Distinct().Select(key => StoryKills(key) ?? new Dictionary<int, int>())
            .Append(FactKills(facts));
        foreach (var fights in story)
            foreach (var (monster, count) in fights)
                kills[monster] = kills.GetValueOrDefault(monster) + count;
        return kills;
    }

    /// <summary>Outputs that share one reward (either griffin ending, or any horse ending, grants it once).</summary>
    public static string RewardKey(string output) => output switch
    {
        "griffin_1" or "griffin_2" => "griffin",
        "dead_horse" or "1ghoul_left" or "2ghouls_left" => "horse",
        "crown" or "crown_again" => "crown",
        "heart" or "heart_again" => "heart",
        "gargoyle" or "gargoyle_again" => "gargoyle",
        "success" or "success_heart" => "joint_venture",
        _ => output,
    };

    private static Dictionary<string, Dictionary<int, int>> Items(params (string Kind, int Id, int Count)[] items)
    {
        var result = new Dictionary<string, Dictionary<int, int>>();
        foreach (var (kind, id, count) in items)
        {
            if (!result.TryGetValue(kind, out var map)) result[kind] = map = new Dictionary<int, int>();
            map[id] = map.GetValueOrDefault(id) + count;
        }
        return result;
    }

    /// <summary>The items a level-up grants, as (kind, id, count). Client: LevelUpWindow.LoadData (0x17D4B38) counts
    /// repeated ids as amounts and, with no item at all, never calls the base LoadData, so the window waits forever
    /// on a dimmed map; every level therefore grants something. Community (DualShockers, 20 Jul 2021; TouchTapPlay,
    /// 29 Jul 2021): a level-up brings rewards and about five skill points, without a published list. The items are
    /// Authored: alchemy basics every level and a bomb every fifth level.</summary>
    public static IReadOnlyList<(string Kind, int Id, int Count)> LevelRewards(int level)
    {
        var items = new List<(string, int, int)>
        {
            (ItemKinds.Ingredients, 103, 3), (ItemKinds.Ingredients, 101, 2), (ItemKinds.Potions, SwallowPotionId, 1),
        };
        if (level % 5 == 0) items.Add((ItemKinds.Bombs, BasicBombId, 1));
        return items;
    }

    /// <summary>Adds experience and gold; every level gained adds its skill points.</summary>
    public static LocalProfileStore.PlayerState WithExp(LocalProfileStore.PlayerState player, int exp, int gold = 0)
    {
        int total = player.Exp + exp;
        int levelsGained = LevelForExp(total) - LevelForExp(player.Exp);
        return player with
        {
            Exp = total,
            Gold = player.Gold + gold,
            SkillPoints = player.SkillPoints + levelsGained * SkillPointsPerLevel,
        };
    }

    // ── Summoned monsters ───────────────────────────────────────────────────────────────────
    // Client: Tutorial.EndTutorial calls PoiModule.UseTutorialSummoningScroll, which sends SummonLocalMonsters
    // (111) for item type 16 and GameConfigData.TutorialSummoningScrollId (default 1; game_configuration has
    // no row). ItemHelper.GetSummonSourceByItemType maps that pair to InitSpawnAfterTutorial. The client
    // places the returned monsters around the returned point and shows them while
    // StartTime < LinuxSeconds < StartTime + (DespawnTime - StartTime).
    public const int SummoningScrollItemType = 16, TutorialSummoningScrollId = 1;

    // Authored: the monsters of the post-tutorial summon are not published. Three difficulty-1 monsters
    // of the prologue region (ghoul, drowner, nekker), as in the monsters table.
    public static readonly IReadOnlyList<(int MonsterId, int Difficulty)> TutorialSummonMonsters = new[] { (1, 1), (3, 1), (4, 1) };

    // Client default for scroll monsters is 500 s (GameConfigData.SummoningScrollMonstersDespawnTime).
    // Authored: the post-tutorial summon lasts an hour while world spawns are not reconstructed.
    public const int TutorialSummonTtlSeconds = 3600;

    // Community (Gamepressure, July 2021): 100/250/600 XP per fight by difficulty, +15 for each perfect
    // parry and each critical hit, +100 for the first fight with a monster; DualShockers (2021): +50 for the
    // proper oil. Client: the combat-end panel shows critical hits (UI/PANELS/COMBAT_END/PERFORMED_CRITICAL_HIT)
    // from ComboExp. The 1.1.116 client never increments CriticalHits (Details[9]); its critical hit is the proper
    // finisher, counted in PerfectAttacks (Details[1], FinisherProperHit.OnHit). UsedProperOil (Details[10]) is 1
    // when an applied oil matches the enemy's family and has exp_matching (SwordModule.GrantOilXP).
    // See server/connection/combat-system-review/EVIDENCE.md §3b and §5.
    public static int BaseExp(int difficulty) => difficulty switch { <= 1 => 100, 2 => 250, _ => 600 };

    // Difficulty tiers (difficulties rows; the slug names the client's characters/difficulty/tier_<n>.asset).
    // Client: when a fight graph leaves EnemyMaxHp and EnemyDamage unset, as the map template fightgraph does,
    // PrepareFightNode.PrepareMechanic (0x17F3EA0) gives the enemy PlayerAttackCount × SwordBasicDamage (75) HP and
    // PlayerSettings.hp (2400) ÷ EnemyAttackCount damage per hit. The original rows are not recovered. Values
    // are calibrated on the client's own story fights, which set HP and damage explicitly (s00 and s01 graphs:
    // wraiths, nekkers and endrega workers 2977 / 290; alghoul, drowner, werewolf 4175 / 350; griffin, gargoyle,
    // cave troll 5545 / 410; endrega warrior 7934 / 964; devourer, nekker warrior 11020 / 875; likho 14547 / 1000;
    // golem 16879 / 1000; frightener up to 24518 / 1000), rounded to whole attack counts. The original tier assets
    // display 0/1/2/3 skulls at tiers 1/4/6/8. World monster rows select those tiers below; the counts remain
    // authored reconstruction tuning, not recovered historical balance. See connection/combat-system-review/EVIDENCE.md §6b.
    public sealed record DifficultyTier(int Id, int PlayerAttackCount, int EnemyAttackCount);

    public static readonly IReadOnlyList<DifficultyTier> Difficulties = new DifficultyTier[]
    {
        new(1, 40, 8),    // 3000 HP, 300 per hit (story 2977 / 290)
        new(2, 74, 6),    // 5550 HP, 400 per hit (story 5545 / 410)
        new(3, 147, 3),   // 11025 HP, 800 per hit (story 11020 / 875)
        new(4, 106, 3),   // 7950 HP, 800 per hit (story 7934 / 964)
        new(5, 147, 3),   // 11025 HP, 800 per hit
        new(6, 194, 2),   // 14550 HP, 1200 per hit (story 14547 / 1000)
        new(7, 225, 2),   // 16875 HP, 1200 per hit (story 16879 / 1000)
        new(8, 327, 2),   // 24525 HP, 1200 per hit (story 24518 / 1000)
    };
    public const int PerfectParryExp = 15, CriticalHitExp = 15, FirstKillExp = 100, ProperOilExp = 50;

    // Client: CombatDetails.Index.
    public const int DetailPerfectAttacks = 1, DetailCriticalHits = 9, DetailUsedProperOil = 10, DetailPerfectParries = 11,
        DetailBombsUsed = 12, RequiredDetailsCount = 13;

    public static LocalProfileStore.PlayerState StartState() => new(
        Exp: 0, Gold: 0, SkillPoints: 0,
        Skills: Skills.Where(skill => skill.Starting).Select(skill => skill.Id).ToList(),
        Items: new Dictionary<string, Dictionary<int, int>>(),
        Granted: new List<string>());
}

/// <summary>Static-data rows derived from <see cref="Reconstruction"/>; keys are verified DataMember names.</summary>
public static class ReconstructionRows
{
    private static string J(object value) => System.Text.Json.JsonSerializer.Serialize(value);

    // Story monsters after the inherited eight and the Griffin (see Build: named by MONSTERS/NAMES/<X>, with
    // five description tiers each). Devourer assets, trophy and texts are Client; id 10 and the necrophage family
    // are Authored.
    private static readonly string[] AppendedMonsters = new[]
    {
        """{"id":10,"family_id":1,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/DEVOURER","model":"Assets/_bundledassets/characters/monsters/s00/devourer/devourer_lq/devourer_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/devourer/devourer_hq/devourer_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_devourer.png","slug":"devourer"}""",
        // Story fight monsters of "A Joint Venture". Client: PrepareFightNode.LoadMechanic throws "Monster wraith
        // is not listed as map monster" unless the graph's monster slug has a monsters row (the fight then never
        // loads). Names, models, presentations, trophies and *_settings assets are in the 1.1.116 catalog and
        // I2Languages; families follow the bestiary (wraiths are specters, gargoyles elementa); difficulty,
        // rarity and distances are Authored (the graphs set the fights' HP and damage).
        """{"id":11,"family_id":7,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/WRAITH","model":"Assets/_bundledassets/characters/monsters/s00/wraith/wraith_lq/wraith_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/wraith/wraith_hq/wraith_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_wraith.png","slug":"wraith"}""",
        """{"id":12,"family_id":7,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":2,"name":"MONSTERS/BESTIARY/WRAITH_LVL2","model":"Assets/_bundledassets/characters/monsters/s00/wraith_lvl2/wraith_lvl2_lq/wraith_lvl2_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/wraith_lvl2/wraith_lvl2_hq/wraith_lvl2_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_wraith_lvl2.png","slug":"wraith_lvl2"}""",
        """{"id":13,"family_id":5,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":3,"name":"MONSTERS/BESTIARY/GARGOYLE","model":"Assets/_bundledassets/characters/monsters/s00/gargoyle/gargoyle_lq/gargoyle_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/gargoyle/gargoyle_hq/gargoyle_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_gargoyle.png","slug":"gargoyle"}""",
        // Endregas of "Good Money" (insectoids, family 8). Client: names MONSTERS/NAMES/ENDRIAGA* (worker, warrior =
        // "tailed", drone = "spikey"), lq models, presentations and trophies in the 1.1.116 catalog. Community (M01):
        // worker and drone common with no skull, warrior rare with one skull; skulls become difficulty 1 and 2 as
        // for the other rows.
        """{"id":14,"family_id":8,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/ENDRIAGAWORKER","model":"Assets/_bundledassets/characters/monsters/s00/endriagaworker/endriagaworker_lq/endriagaworker_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/endriagaworker/endriagaworker_hq/endriagaworker_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_endriagaworker.png","slug":"endriagaworker"}""",
        """{"id":15,"family_id":8,"encounter_distance":50,"attack_animation_time":2000,"rarity":2,"difficulty":2,"name":"MONSTERS/BESTIARY/ENDRIAGATAILED","model":"Assets/_bundledassets/characters/monsters/s00/endriagatailed/endriagatailed_lq/endriagatailed_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/endriagatailed/endriagatailed_hq/endriagatailed_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_endriagatailed.png","slug":"endriagatailed"}""",
        """{"id":16,"family_id":8,"encounter_distance":50,"attack_animation_time":2000,"rarity":1,"difficulty":1,"name":"MONSTERS/BESTIARY/ENDRIAGASPIKEY","model":"Assets/_bundledassets/characters/monsters/s00/endriagaspikey/endriagaspikey_lq/endriagaspikey_lq.prefab","image":"Assets/_bundledassets/characters/monsters/s00/endriagaspikey/endriagaspikey_hq/endriagaspikey_hq_presentation.prefab","trophy":"Assets/_bundledassets/ui/monster_trophies/trophy_endriagaspikey.png","slug":"endriagaspikey"}""",
    };

    /// <summary>Replaces or extends the inherited sample tables. Quest tables keep the prologue rows first.</summary>
    public static readonly IReadOnlyDictionary<string, string[]> Tables = Build();

    public static Dictionary<string, string[]> Build(SkillBalancePolicy? policy = null)
    {
        var rows = new Dictionary<string, string[]>();
        rows["skills"] = Reconstruction.Skills.Select(skill => skill.ParentId is int parent
            ? J(new Dictionary<string, object> { ["id"] = skill.Id, ["slug"] = skill.Slug, ["cost"] = skill.Cost,
                ["required_level"] = skill.RequiredLevel, ["parent_id"] = parent })
            : J(new Dictionary<string, object> { ["id"] = skill.Id, ["slug"] = skill.Slug, ["cost"] = skill.Cost,
                ["required_level"] = skill.RequiredLevel })).ToArray();
        rows["skill_requirements"] = Reconstruction.Skills
            .SelectMany(skill => Reconstruction.SkillRequirements(skill).Select(required =>
                J(new Dictionary<string, object> { ["skill_id"] = skill.Id, ["required_skill_id"] = required }))).ToArray();
        rows["player_starting_skills"] = Reconstruction.Skills.Where(skill => skill.Starting)
            .Select(skill => J(new Dictionary<string, object> { ["id"] = skill.Id })).ToArray();
        rows["level_ups"] = Enumerable.Range(1, Reconstruction.MaxLevel).Select(level => J(new Dictionary<string, object>
            { ["id"] = level, ["exp_threshold"] = Reconstruction.ExpThreshold(level),
              ["skill_points"] = level == 1 ? 0 : Reconstruction.SkillPointsPerLevel })).ToArray();
        rows["effects"] = Reconstruction.Effects.Select(effect => J(new Dictionary<string, object>
            { ["id"] = effect.Id, ["name"] = effect.Name, ["effect_type_id"] = effect.Type })).ToArray();
        rows["skill_to_effect"] = Reconstruction.SkillEffects(policy).Select(ItemEffectRow).ToArray();
        // The inherited prologue quest with its log (catalog key, see AppendedRows), so the journal lists the
        // finished prologue.
        rows["quests"] = new[] { """{"id":145,"season_id":0,"name":"LAB prologue","journal_log":"assets/_bundledassets/story/journal/s00/prolog/log_prolog_01.asset","activation_criteria":""}""" };
        rows["oil_to_effect"] = Reconstruction.OilEffects().Select(ItemEffectRow).ToArray();
        rows["oils"] = Reconstruction.Oils.Select(oil => J(new Dictionary<string, object>
            { ["id"] = oil.Id, ["slug"] = oil.Slug, ["priority"] = oil.Id, ["exp_matching"] = oil.FamilyOil ? 1 : 0 })).ToArray();
        rows["potions"] = Reconstruction.Potions.Select(potion => J(new Dictionary<string, object>
            { ["id"] = potion.Id, ["slug"] = potion.Slug, ["priority"] = potion.Id, ["auto_equip_priority"] = potion.Id })).ToArray();
        rows["auto_equip"] = Reconstruction.AutoEquipRows().Select(row =>
        {
            var json = new Dictionary<string, object> { ["item_id"] = row.ItemId, ["item_type_id"] = row.ItemType };
            foreach (string column in Reconstruction.AutoEquipColumns) json[column] = row.Weights.GetValueOrDefault(column);
            return J(json);
        }).ToArray();
        rows["bombs"] = new[] { (401, "bomb_basic") }.Concat(Reconstruction.ExtraBombs)
            .Select(bomb => J(new Dictionary<string, object>
            {
                ["id"] = bomb.Item1, ["slug"] = bomb.Item2, ["priority"] = bomb.Item1 - 401, ["delay"] = 0, ["duration"] = 0,
                ["value"] = 0, ["radius"] = Reconstruction.BombRadius, ["explode_style"] = 0,
                ["prefab_path"] = $"assets/_bundledassets/appearance/bomb/{bomb.Item2}/prefab_{bomb.Item2}.prefab",
            })).ToArray();
        rows["damage_types"] = Reconstruction.DamageTypes.Select(type => J(new Dictionary<string, object>
            { ["id"] = type.Id, ["slug"] = type.Slug, ["power"] = 100 })).ToArray();
        rows["bomb_damage_types"] = Reconstruction.BombDamage.Select(row => J(new Dictionary<string, object>
            { ["bomb_id"] = row.BombId, ["damage_type_id"] = row.DamageType, ["amount"] = row.Amount })).ToArray();
        rows["potion_to_effect"] = Reconstruction.PotionEffects().Select(ItemEffectRow).ToArray();
        rows["armor_to_effect"] = Reconstruction.ArmorEffects().Select(ItemEffectRow).ToArray();
        rows["sword_to_effect"] = Reconstruction.SwordEffects().Select(ItemEffectRow).ToArray();
        // Monster names and bestiary tiers. The inherited rows name each monster by its MONSTERS/BESTIARY/<X> term,
        // which is the bestiary's trivia text (INFO_5 quotes it), so the fight preparation showed the trivia as the
        // name; the name is MONSTERS/NAMES/<X> (Client I2Languages). Every monster gets its five description tiers.
        // Season 1 story monsters follow (StoryEngine: Client model, image and trophy paths; Community M01 rarity,
        // skulls and vulnerabilities).
        var monsters = PreloaderStaticData.ContentOverrides["monsters"].Concat(AppendedMonsters).Concat(StoryEngine.MonsterRows)
            .Concat(WorldBestiary.MonsterRows)
            .Select(row =>
            {
                var monster = System.Text.Json.Nodes.JsonNode.Parse(row)!.AsObject();
                monster["name"] = monster["name"]!.GetValue<string>().Replace("MONSTERS/BESTIARY/", "MONSTERS/NAMES/");
                // Native MonsterFactory and MonsterInfo read this static difficulty, not placement.Level.
                // Original tier_1..3 are all EASY/no icon; tier_4/6/8 show one/two/three skulls. Selecting
                // these existing tiers also selects their authored HP/damage and auto-equip settings.
                // Species.Difficulty remains the legacy input for spawn rewards; story graph HP/damage
                // overrides and the eight difficulty rows are retained.
                if (WorldBestiary.Of(monster["id"]!.GetValue<int>()) is { } species)
                {
                    monster["rarity"] = species.Rarity;
                    monster["difficulty"] = species.Skulls switch
                    {
                        0 => 1, 1 => 4, 2 => 6, 3 => 8,
                        _ => throw new InvalidDataException($"Unsupported skull count for monster {species.MonsterId}."),
                    };
                }
                return monster.ToJsonString();
            }).ToArray();
        rows["monsters"] = monsters;
        var parsed = monsters.Select(row =>
        {
            using var monster = System.Text.Json.JsonDocument.Parse(row);
            return (Id: monster.RootElement.GetProperty("id").GetInt32(), Slug: monster.RootElement.GetProperty("slug").GetString()!,
                Key: monster.RootElement.GetProperty("name").GetString()!["MONSTERS/NAMES/".Length..]);
        }).ToList();
        var lines = Reconstruction.DescriptionRows().ToList();
        rows["monster_descriptions"] = parsed.SelectMany(monster => lines.Select((line, n) => J(new Dictionary<string, object>
        {
            ["id"] = (monster.Id - 1) * lines.Count + n + 1, ["monster_id"] = monster.Id, ["level"] = line.Level,
            ["threshold"] = Reconstruction.KnowledgeThresholds(monster.Id)[line.Level - 1],
            ["content"] = $"MONSTERS/DESCRIPTIONS/{monster.Key}/INFO_{line.Line}",
        }))).ToArray();
        rows["monster_vulnerabilities"] = parsed.SelectMany(monster => Reconstruction.Vulnerabilities[monster.Slug]
            .Select(type => J(new Dictionary<string, object> { ["monster_id"] = monster.Id, ["damage_type_id"] = type })))
            .ToArray();
        rows["herbs"] = WorldHerbs.Types.Select(herb => J(new Dictionary<string, object>
        {
            ["id"] = herb.Id, ["slug"] = herb.Slug,
            ["prefab_path"] = $"Assets/_bundledassets/map/collectables/herbs/{herb.Slug}/prefab_{herb.Slug}.prefab",
        })).ToArray();
        // Nemeta and baits (WorldNests): the lures rows (icons icon_<slug>), the shop's bait prices, and the
        // client's own GameConfigData defaults for nests as game_configuration rows (GameConfigData.Load keys).
        rows["lures"] = WorldNests.Lures.Select((lure, n) => J(new Dictionary<string, object>
            { ["id"] = lure.Id, ["slug"] = lure.Slug, ["priority"] = n })).ToArray();
        rows["shop_lures"] = WorldNests.Lures.Where(lure => lure.Sold).Select(lure => J(new Dictionary<string, object>
            { ["item_id"] = lure.Id, ["price"] = WorldNests.BaitPrice })).ToArray();
        rows["game_configuration"] = new (string Name, int Value)[]
        {
            ("nestClearingExp", WorldNests.ClearingExp), ("nestDailyLimit", WorldNests.DailyLimit),
            ("nestPlayerMinimalLevel", WorldNests.PlayerMinimalLevel),
            // the shop's amount for every bag (ShopItemDataSource.GetQuantityForItem); each bag's own text gives its size
            ("inventoryIncrement", Economy.Bags[0].Slots),
        }.Select((row, n) => J(new Dictionary<string, object>
            { ["id"] = n + 1, ["param_name"] = row.Name, ["param_value"] = row.Value.ToString() })).ToArray();
        // Equipment rows in the inherited format (rows 1-6 unchanged); the client builds prefab paths from the slug.
        rows["swords"] = Reconstruction.Swords.Select(sword => J(new Dictionary<string, object>
        {
            ["id"] = sword.Id, ["slug"] = sword.Slug, ["priority"] = sword.Id - 1, ["sword_type"] = sword.SwordType,
            ["prefab_path"] = $"Assets/_bundledassets/appearance/sword/{sword.Slug}/prefab_{sword.Slug}.prefab",
            ["auto_equip_priority"] = sword.Id - 1,
        })).ToArray();
        rows["armors"] = Reconstruction.Armors.Select(armor => J(new Dictionary<string, object>
        {
            ["id"] = armor.Id, ["slug"] = armor.Slug, ["priority"] = armor.Id - 1,
            ["prefab_path"] = $"Assets/_bundledassets/appearance/armor/{armor.Slug}/prefab_{armor.Slug}.prefab",
        })).ToArray();
        rows["difficulties"] = Reconstruction.Difficulties.Select(tier => J(new Dictionary<string, object>
        {
            ["id"] = tier.Id, ["slug"] = $"tier_{tier.Id}", ["player_attack_count"] = tier.PlayerAttackCount,
            ["enemy_attack_count"] = tier.EnemyAttackCount,
        })).ToArray();
        // Player modifiers of the season 1 graphs (PlayerModifier: id, slug; see Reconstruction.PlayerModifiers), and the
        // dashboard's debug modifiers with their effects (PlayerService.DebugModifiers; gameplay never grants them).
        rows["player_modifiers"] = [.. StoryEngine.ModifierRows(), .. PlayerService.DebugModifiers.Select(m =>
            J(new Dictionary<string, object> { ["id"] = m.Id, ["slug"] = m.Slug }))];
        rows["player_modifier_to_effect"] = PlayerService.DebugModifiers.Select(m =>
            ItemEffectRow(new Reconstruction.ItemEffect(m.Id, m.Effect, PlayerService.DebugModifierPower, 1))).ToArray();
        // Native pack type and slug; numeric id and rewards are explicit LAB policy.
        rows["packs_types"] = [J(new Dictionary<string, object>
        { ["id"] = SocialService.PackId, ["slug"] = "pack_herbalist", ["priority"] = 1 })];
        Economy.AddRows(rows, policy);
        return rows;
    }

    private static string ItemEffectRow(Reconstruction.ItemEffect effect) => J(new Dictionary<string, object>
    {
        ["item_id"] = effect.ItemId, ["effect_id"] = effect.EffectId, ["power"] = effect.Power,
        ["effect_apply_type_id"] = effect.ApplyTime,
    });

    // Rows appended after the inherited sample rows: tutorial quest 144 (output ids 3.. are Authored) and the
    // quest rows of "A Joint Venture". Story monsters are in AppendedMonsters (CombatPreparationController.Show
    // looks the fight's monster up in the monster storage, so every story monster needs a row).
    private static readonly IReadOnlyDictionary<string, string[]> PrologueRows = new Dictionary<string, string[]>
    {
        ["quests"] = new[]
        {
            // journal_log is the Addressables key of the quest's log, exactly as in the client catalog: JournalUI
            // loads it as given (AssetsPaths.GetJournalLogPath has no caller in 1.1.116), and a key that is not in
            // the catalog never finishes loading, so the journal keeps its input blocker and the game shows
            // "waiting for server response" forever. The log lists the quest items, e.g. the treasure map of
            // "A Joint Venture" (Client catalog).
            """{"id":144,"season_id":0,"name":"LAB tutorial","journal_log":"assets/_bundledassets/story/journal/s00/tutorial/log_tutorial.asset","activation_criteria":""}""",
            // "A Joint Venture": prolog_02_map tracks quest 146 (Donor); only its first node is served so far.
            """{"id":146,"season_id":0,"name":"LAB joint venture","journal_log":"assets/_bundledassets/story/journal/s00/prolog/log_prolog_02.asset","activation_criteria":""}""",
        },
        ["quest_nodes"] = new[]
        {
            """{"id":228,"quest_id":144,"name":"LAB tutorial ghoul","activation_criteria":""}""",
            """{"id":230,"quest_id":144,"name":"LAB tutorial witcher","activation_criteria":""}""",
            """{"id":229,"quest_id":144,"name":"LAB tutorial exam","activation_criteria":""}""",
            """{"id":287,"quest_id":146,"name":"LAB joint venture map","activation_criteria":""}""",
            // 236 is the map's "Examine" button (log_prolog_02); the others follow Reconstruction's story nodes.
            """{"id":236,"quest_id":146,"name":"LAB joint venture map button","activation_criteria":""}""",
            """{"id":9288,"quest_id":146,"name":"LAB joint venture obelisk","activation_criteria":""}""",
            """{"id":9289,"quest_id":146,"name":"LAB joint venture crown","activation_criteria":""}""",
            """{"id":9290,"quest_id":146,"name":"LAB joint venture sword","activation_criteria":""}""",
            """{"id":9291,"quest_id":146,"name":"LAB joint venture heart","activation_criteria":""}""",
            """{"id":9292,"quest_id":146,"name":"LAB joint venture gargoyle","activation_criteria":""}""",
        },
        ["quest_node_outputs"] = new[]
        {
            """{"id":3,"quest_node_id":228,"name":"tutorial_end","endpoint":0}""",
            """{"id":4,"quest_node_id":228,"name":"exam","endpoint":0}""",
            """{"id":5,"quest_node_id":230,"name":"tutorial_end","endpoint":0}""",
            """{"id":6,"quest_node_id":230,"name":"exam","endpoint":0}""",
            """{"id":7,"quest_node_id":229,"name":"exam_end","endpoint":0}""",
            """{"id":8,"quest_node_id":229,"name":"exam_fail","endpoint":0}""",
            // The other two endings of prolog_01_dead_horse (node 2); "2ghouls_left" is the inherited id 2.
            """{"id":9,"quest_node_id":2,"name":"dead_horse","endpoint":0}""",
            """{"id":10,"quest_node_id":2,"name":"1ghoul_left","endpoint":0}""",
            """{"id":11,"quest_node_id":287,"name":"empty","endpoint":0}""",
            // Outputs of "A Joint Venture" (Donor graphs); "success" and "success_heart" end the quest.
            """{"id":12,"quest_node_id":236,"name":"map","endpoint":0}""",
            """{"id":13,"quest_node_id":9288,"name":"obelisk","endpoint":0}""",
            """{"id":14,"quest_node_id":9289,"name":"crown","endpoint":0}""",
            """{"id":15,"quest_node_id":9289,"name":"crown_again","endpoint":0}""",
            """{"id":16,"quest_node_id":9289,"name":"crown_fail","endpoint":0}""",
            """{"id":17,"quest_node_id":9290,"name":"sword","endpoint":0}""",
            """{"id":18,"quest_node_id":9291,"name":"heart","endpoint":0}""",
            """{"id":19,"quest_node_id":9291,"name":"heart_again","endpoint":0}""",
            """{"id":20,"quest_node_id":9291,"name":"heart_fail","endpoint":0}""",
            """{"id":21,"quest_node_id":9292,"name":"gargoyle","endpoint":0}""",
            """{"id":22,"quest_node_id":9292,"name":"gargoyle_again","endpoint":0}""",
            """{"id":23,"quest_node_id":9292,"name":"gargoyle_fail","endpoint":0}""",
            """{"id":24,"quest_node_id":9292,"name":"wraith_won","endpoint":0}""",
            """{"id":25,"quest_node_id":9292,"name":"wraith_fail","endpoint":0}""",
            """{"id":26,"quest_node_id":9292,"name":"success","endpoint":1}""",
            """{"id":27,"quest_node_id":9292,"name":"success_heart","endpoint":1}""",
            """{"id":28,"quest_node_id":287,"name":"CT_obelisk","endpoint":0}""",
            """{"id":29,"quest_node_id":287,"name":"CT_gargoyle","endpoint":0}""",
        },
        // Client: StoryGraph.BuildSeasonGraphs takes the top ancestor of a season's quests (quest_edges run
        // from parent to child) as the season root; GetJournalLog looks only at the root's children, so without
        // edges the journal lists no quest. FillAvailableNodes evaluates the root's activation criteria unless
        // the root is finished, so the root must be a quest with a node: the tutorial (Authored hierarchy).
        ["quest_edges"] = new[]
        {
            """{"from_quest_id":144,"to_quest_id":145}""",
            """{"from_quest_id":144,"to_quest_id":146}""",
        },
        ["quest_node_edges"] = new[]
        {
            """{"from_quest_node_output_id":3,"to_quest_node_id":230}""",
            """{"from_quest_node_output_id":4,"to_quest_node_id":229}""",
            """{"from_quest_node_output_id":6,"to_quest_node_id":229}""",
            """{"from_quest_node_output_id":9,"to_quest_node_id":3}""",
            """{"from_quest_node_output_id":10,"to_quest_node_id":3}""",
            // "A Joint Venture": map → button → obelisk → the three gifts → gargoyle (see JointVentureNodes).
            """{"from_quest_node_output_id":11,"to_quest_node_id":236}""",
            """{"from_quest_node_output_id":12,"to_quest_node_id":9288}""",
            """{"from_quest_node_output_id":13,"to_quest_node_id":9289}""",
            """{"from_quest_node_output_id":13,"to_quest_node_id":9290}""",
            """{"from_quest_node_output_id":13,"to_quest_node_id":9291}""",
            """{"from_quest_node_output_id":14,"to_quest_node_id":9292}""",
            """{"from_quest_node_output_id":15,"to_quest_node_id":9292}""",
            """{"from_quest_node_output_id":17,"to_quest_node_id":9292}""",
            """{"from_quest_node_output_id":18,"to_quest_node_id":9292}""",
            """{"from_quest_node_output_id":19,"to_quest_node_id":9292}""",
            """{"from_quest_node_output_id":28,"to_quest_node_id":9288}""",
            """{"from_quest_node_output_id":29,"to_quest_node_id":9292}""",
        },
    };

    /// <summary>The prologue rows, then the season 1 rows of the story engine (children of the tutorial root).</summary>
    public static readonly IReadOnlyDictionary<string, string[]> AppendedRows = new Dictionary<string, string[]>
    {
        ["quests"] = [.. PrologueRows["quests"], .. StoryEngine.QuestRows()],
        ["quest_nodes"] = [.. PrologueRows["quest_nodes"], .. StoryEngine.NodeRows()],
        ["quest_node_outputs"] = [.. PrologueRows["quest_node_outputs"], .. StoryEngine.OutputRows()],
        ["quest_edges"] = [.. PrologueRows["quest_edges"], .. StoryEngine.QuestEdgeRows()],
        ["quest_node_edges"] = [.. PrologueRows["quest_node_edges"], .. StoryEngine.NodeEdgeRows()],
    };
}

public static class ItemKinds
{
    public const string Potions = "potions", Bombs = "bombs", Oils = "oils", Ingredients = "ingredients",
        SensesPotions = "senses_potions", Lures = "lures";
}
