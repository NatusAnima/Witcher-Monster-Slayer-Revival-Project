using System.Text.Json;
using System.Text.RegularExpressions;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Simple numbers a player can change in the dashboard to suit how they play, grouped in presets: Revival (this project's
/// balance) and Vanilla (the original game) are built in and read-only; a player's own presets live in world/presets and
/// can be created, renamed and deleted. Every behaviour that differs from the original game is a setting, and each setting
/// names its Vanilla value. A preset also carries the reward tables (RewardTables, the Rewards page).
///
/// world/tuning.json holds the active preset's id and its resolved values; it is read again about once a second, so a change
/// needs no restart. A missing or damaged file means Revival; a bad value is refused when it is saved. The placement service
/// (a separate process) reads the places.* values from the same file (playable_locations.Tuning, the same keys and limits).
/// </summary>
public sealed class WorldTuning
{
    /// <param name="Applies">When a change takes effect, in words for the dashboard.</param>
    /// <param name="VanillaValue">The original game's value, when it differs from the Revival default.</param>
    public sealed record Setting(string Key, string Group, string Label, string Help, string Applies, double Default, double Min,
        double Max, double Step, string Unit, double? VanillaValue = null)
    {
        public double Vanilla => VanillaValue ?? Default;
    }

    public sealed record Preset(string Id, string Name, bool BuiltIn, Dictionary<string, double> Values, RewardTables Rewards);

    public const string RevivalId = "revival", VanillaId = "vanilla";

    public const string ExpPercent = "exp.percent", LootPercent = "loot.percent",
        HerbRespawnMinutes = "herbs.respawnMinutes", HerbsPerCell = "herbs.perCell", RealWeather = "weather.real",
        StartingBag = "inventory.startSize", MaxBag = "inventory.maxSize", NestGold = "nests.gold", NestExpPercent = "nests.expPercent",
        TrollDefeats = "story.trollDefeats", TaskGoldPercent = "tasks.goldPercent", TaskExp = "tasks.exp",
        WikiOccurrences = "spawns.wikiOccurrences", NaturalAwayFromBuildings = "spawns.naturalAwayFromBuildings",
        Boost = "spawns.boost", StrongBoost = "spawns.strongBoost", RainRoaming = "spawns.rainRoaming", LevelGate = "spawns.levelGate",
        OneSkullLevel = "spawns.oneSkullLevel", TwoSkullsLevel = "spawns.twoSkullsLevel",
        ThreeSkullsLevel = "spawns.threeSkullsLevel", QuenAbsorb = "skills.quenAbsorb",
        ExpByRarity = "xp.baseByRarity", VanillaCurve = "xp.vanillaCurve", QuestSoftCap = "quests.softCap",
        QuestWalkingCap = "quests.walkingCap",
        QuestHardCap = "quests.hardCap", TrinketBuffs = "trinkets.buffs", ShopScrolls = "shop.scrolls",
        ShopWeatherItems = "shop.weatherItems", ShopOrenPacks = "shop.orenPacks", OpenPacks = "inventory.openPacks",
        SelfFriend = "friends.self", ShopDailyDiscount = "shop.dailyDiscount", DeflectsAsParries = "xp.deflectsAsParries",
        OilsMultiply = "combat.oilsMultiply", CollectingDistance = "quests.collectingDistance",
        CollectingUntracked = "quests.collectingUntracked", IntruderAllEndings = "quests.intruderAllEndings",
        NestMinLevel = "nests.minLevel", NestsPerDay = "nests.perDay", ParryExp = "xp.perfectParry", AttackExp = "xp.perfectAttack",
        FirstKillExp = "xp.firstKill", OilExp = "xp.properOil", SkillPointsPerLevel = "skills.pointsPerLevel",
        TierSkillPoints = "bestiary.tierSkillPoints", BrewTimePercent = "alchemy.brewTimePercent", PackEveryWins = "rewards.packEveryWins",
        ExtraPotionChance = "skills.extraPotionChance", SquallRemains = "skills.squallRemains", ResolveFloor = "skills.resolveFloor",
        AttackAdrenaline = "skills.attackAdrenaline", EventAdrenaline = "skills.eventAdrenaline",
        InitialAdrenaline = "skills.initialAdrenaline", SurvivalChance = "skills.survivalChance",
        SignRecoveryChance = "skills.signRecoveryChance", BombAngle = "skills.bombAngle", AuraInterval = "skills.auraIntervalMinutes",
        AuraLifetime = "skills.auraLifetimeMinutes", SkillsReset = "skills.reset", LastingMinutes = "combat.lastingMinutes",
        BlacksmithDamage = "combat.blacksmithDamage", InteractionRange = "map.interactionRange",
        QuenPerfectParry = "combat.quenPerfectParry", PerfectParriesAsParries = "tasks.perfectParriesAsParries",
        FightGoldCommonMin = "rewards.fightGoldCommonMin", FightGoldCommonMax = "rewards.fightGoldCommonMax",
        FightGoldRareMin = "rewards.fightGoldRareMin", FightGoldRareMax = "rewards.fightGoldRareMax",
        FightGoldLegendaryMin = "rewards.fightGoldLegendaryMin", FightGoldLegendaryMax = "rewards.fightGoldLegendaryMax",
        FightGoldPerTier = "rewards.fightGoldPerTier";

    /// <summary>The settings hook.js applies in the game (ClientTexts sends them with the texts at the game's start).</summary>
    public static readonly string[] GameSettings = [OilsMultiply, CollectingDistance, CollectingUntracked, IntruderAllEndings,
        SkillsReset, DeflectsAsParries, QuenPerfectParry, PerfectParriesAsParries];

    /// <summary>Bestiary knowledge thresholds by rarity (common, rare, legendary): the cumulative kills of tiers 1-3.</summary>
    public static string Bestiary(string rarity, int tier) => $"bestiary.{rarity}{tier}";
    public static readonly string[] BestiaryRarities = ["common", "rare", "legendary"];

    private const string PlacesApply = "Places drawn from now on. Monsters already out stay for up to 30 minutes.";
    private const string SpawnApply = "Monsters drawn from now on. Monsters already out stay for up to 30 minutes.";
    private const string StaticApply = "The next server start and game start.";
    private const string GameApply = "The next game start.";
    private const string Switch = "on/off";
    private const string Unknown = " The original game's value is not known; this is the reconstruction's.";

    // A skill's number, which the game reads from its static data at its start.
    private static Setting SkillSetting(string key, string label, string help, double value, double max, string unit) =>
        new(key, "Skills", label, help + Unknown, StaticApply, value, 0, max, 1, unit);

    private static Setting Share(string ground, string label, string where, double share) => new("places." + ground, "Places",
        label, $"How much of a map cell's places lie {where}. The five shares count against each other, so only their sizes " +
        "matter; a cell without that kind of ground gives its share to the others, and 0 leaves it out.",
        PlacesApply, share, 0, 100, 5, "share");

    private static Setting BestiarySetting(string rarity, int tier, double revival, double vanilla) => new(Bestiary(rarity, tier),
        "Bestiary", $"{char.ToUpper(rarity[0])}{rarity[1..]} monsters: kills for tier {tier}",
        $"How many {rarity} monsters of one kind you must beat, in all, for the bestiary's tier {tier} (each tier gives a skill " +
        "point). A tier never needs fewer kills than the one before it.", StaticApply, revival, 1, 1000, 1, "kills", vanilla);

    public static readonly IReadOnlyList<Setting> Settings = new Setting[]
    {
        new("places.perCell", "Places", "Places per map cell",
            "How many spots a map cell (about half a kilometre across) offers for monsters, herbs, nests and quests. How many monsters " +
            "stand on them is the World page's monsters per cell.", PlacesApply, 32, 4, 48, 1, "places"),
        new("places.spacing", "Places", "Distance between places",
            "The least distance between two places. Smaller lets a cell hold more of them.", PlacesApply, 50, 30, 200, 5, "m"),
        Share("paths", "On paths", "on footpaths and tracks away from houses", 40),
        Share("parks", "In parks", "in parks and on their paths", 25),
        Share("woods", "In woods", "in woods and forests", 15),
        Share("water", "By water", "within 60 m of a river, lake or the sea", 10),
        Share("urban", "Near houses", "within 60 m of a building: the streets and footpaths of a town", 40),
        new(InteractionRange, "Places", "Reach on the map",
            "How far from you monsters, herbs, nemeta and quest places can be tapped (the game's basicInteractionRange: 67.5 m " +
            "in the original).", StaticApply, 100, 30, 300, 0.5, "m", 67.5),
        new("places.offPath", "Places", "Distance beside paths",
            "How far a place stands beside a footpath or track (every other one half as far again), in a park or wood if there " +
            "is one, else on any ground clear of roads, buildings and water; beside a street, a third of it farther out. " +
            "0 leaves places on the paths. Field round 2026-10-31: monsters and herbs stood on the paths and streets.",
            PlacesApply, 12, 0, 30, 1, "m"),
        new("places.streetClearance", "Places", "Distance from streets",
            "How far places keep from the middle of ordinary streets (main roads always keep 30 m). Below 13 m, places line " +
            "both sides of the streets (bigger streets only among houses), so towns get monsters on their streets and not " +
            "only in their parks; 13 m or more keeps them to footpaths, parks and woods.",
            PlacesApply, 12, 10, 30, 1, "m"),
        new(WikiOccurrences, "Monsters", "Where and when monsters appear: the wiki",
            "1 follows the Witcher wiki's Monster Slayer bestiary (where and when each monster appears, its rarity), and the " +
            "game's bestiary shows the same; 0 uses the game's own 1.1.116 texts.", SpawnApply, 1, 0, 1, 1, Switch),
        new(NaturalAwayFromBuildings, "Monsters", "Natural monsters stay off streets",
            "1 keeps the monsters 'common in all natural environment types' to woods, water, parks and paths (also inside towns), " +
            "never on streets among houses; 0 lets them stand anywhere.", SpawnApply, 1, 0, 1, 1, Switch),
        new(Boost, "Monsters", "Increased activity",
            "How much likelier a monster is while its 'increased activity' holds (dawn, dusk, fog, a full moon).",
            SpawnApply, 3, 1, 10, 1, "times"),
        new(StrongBoost, "Monsters", "Significantly increased activity",
            "How much likelier a monster is while its 'significantly increased activity' holds (noon, midnight, rain).",
            SpawnApply, 6, 1, 20, 1, "times"),
        new(RainRoaming, "Monsters", "Rain brings water monsters inland",
            "1 lets water monsters that like rain appear away from water while it rains ('Drowners spawn near water or during " +
            "rain'); 0 keeps them by water.", SpawnApply, 1, 0, 1, 1, Switch),
        new(LevelGate, "Monsters", "Monsters suit your level",
            "1 keeps world monsters within your level: no skulls from level 1, then one skull, two skulls and three (the " +
            "legendaries) from the levels below. 0 lets any monster appear at any level.", SpawnApply, 1, 0, 1, 1, Switch),
        new(OneSkullLevel, "Monsters", "One-skull monsters from level",
            "With Monsters suit your level: the level from which one-skull monsters appear.", SpawnApply, 5, 1, 40, 1, "level"),
        new(TwoSkullsLevel, "Monsters", "Two-skull monsters from level",
            "The same for two-skull monsters.", SpawnApply, 10, 1, 40, 1, "level"),
        new(ThreeSkullsLevel, "Monsters", "Three-skull monsters (legendaries) from level",
            "The same for three-skull monsters: every legendary has three.", SpawnApply, 15, 1, 40, 1, "level"),
        new(ExpByRarity, "Experience", "Experience by rarity",
            "1 gives 100 experience for a common monster, 250 for a rare and 600 for a legendary, as the original game did; 0 " +
            "goes by the skulls shown (100, 175, 250, 600).", "The next fight.", 1, 0, 1, 1, Switch),
        new(VanillaCurve, "Experience", "Original level table",
            "1 uses the original game's experience table (level 10 at 27,000, level 40 at 3,877,000); 0 this project's (level 10 at " +
            "45,000, level 40 at 780,000). Your level stays as it is when you switch; only the experience to the next level changes.",
            StaticApply, 0, 0, 1, 1, Switch, 1),
        new(DeflectsAsParries, "Experience", "Deflected blows count as perfect parries",
            "1 pays the perfect-parry experience for blows deflected with Hit Reflection: once it is learnt, the game counts every " +
            "perfect parry as a deflect, so it never paid for one. The hook also counts each deflect as a parry, so the parry " +
            "tasks (Swordmaster, On your guard) still move. 0 keeps the original game's count.", "The next fight.",
            1, 0, 1, 1, Switch, 0),
        new(PerfectParriesAsParries, "Experience", "Perfect parries count for parry tasks",
            "1 lets the hook count each perfect parry as a parry too, so Swordmaster and On your guard move with them (the game " +
            "counts them apart, so a fight of perfect parries left those tasks where they were). Parries pay no experience, so " +
            "nothing is paid twice. 0 keeps the original game's count.", "The next game start.",
            1, 0, 1, 1, Switch, 0),
        new(ExpPercent, "Experience", "Experience from fights",
            "How much experience a won fight gives, as a share of the normal amount: 200 doubles it, 50 halves it.",
            "The next fight.", 100, 10, 1000, 5, "%"),
        new(ParryExp, "Experience", "Experience for a perfect parry",
            "Experience each perfect parry adds to a won fight or nemeton (before Experience from fights).",
            "The next fight.", 15, 0, 500, 1, "experience"),
        new(AttackExp, "Experience", "Experience for a perfect attack",
            "Experience each perfect attack (the fight summary's combo) adds to a won fight or nemeton.",
            "The next fight.", 15, 0, 500, 1, "experience"),
        new(FirstKillExp, "Experience", "Experience for a new monster",
            "Experience the first win over a kind of monster adds (its new bestiary entry).", "The next fight.", 100, 0, 5000, 10, "experience"),
        new(OilExp, "Experience", "Experience for the right oil",
            "Experience a won fight adds when the oil on the sword suits the monster.", "The next fight.", 50, 0, 1000, 5, "experience"),
        new(LootPercent, "Rewards", "Ingredients from fights",
            "How many ingredients a won fight drops, as a share of the normal amount: 200 doubles them, 0 drops none.",
            "The next fight.", 100, 0, 1000, 10, "%"),
        new(FightGoldCommonMin, "Rewards", "Orens from a common monster, at least",
            "A won fight against a common monster pays a random amount from this to the most (a nemeton's monsters too, beside " +
            "its own gold), more for a harder one (Orens for each harder tier). The fight's summary shows it in the line the " +
            "game kept for the fight's duration. The original game paid none.", "The next fight.", 3, 0, 1000, 1, "orens", 0),
        new(FightGoldCommonMax, "Rewards", "Orens from a common monster, at most",
            "The most a common monster pays; below the least, it pays the least.", "The next fight.", 7, 0, 1000, 1, "orens", 0),
        new(FightGoldRareMin, "Rewards", "Orens from a rare monster, at least",
            "The same for a rare monster.", "The next fight.", 10, 0, 1000, 1, "orens", 0),
        new(FightGoldRareMax, "Rewards", "Orens from a rare monster, at most",
            "The same for a rare monster.", "The next fight.", 15, 0, 1000, 1, "orens", 0),
        new(FightGoldLegendaryMin, "Rewards", "Orens from a legendary monster, at least",
            "The same for a legendary monster.", "The next fight.", 20, 0, 5000, 1, "orens", 0),
        new(FightGoldLegendaryMax, "Rewards", "Orens from a legendary monster, at most",
            "The same for a legendary monster.", "The next fight.", 25, 0, 5000, 1, "orens", 0),
        new(FightGoldPerTier, "Rewards", "Orens for each harder tier",
            "How much more a monster pays for each difficulty tier above the first (its skulls in the bestiary, 1 to 3): 25 " +
            "pays a tier-3 monster 50 % more.", "The next fight.", 25, 0, 200, 5, "%"),
        new(PackEveryWins, "Rewards", "A herbalist's pack every",
            "Every this many won fights bring a herbalist's pack (when the bag has room). 0 brings none." + Unknown,
            "The next won fight.", 5, 0, 100, 1, "won fights"),
        new(NestMinLevel, "Nemeta", "Nemeta from level",
            "The level from which nemeta can be fought; below it the game shows them closed. At most 10, the original game's.",
            StaticApply, 10, 1, 10, 1, "level"),
        new(NestsPerDay, "Nemeta", "Nemeta per day",
            "How many nemeton clears a day pay its gold (the nemeton window shows the count). More clears still pay " +
            "experience, and their monsters' orens.",
            StaticApply, 3, 1, 20, 1, "clears"),
        new(NestGold, "Nemeta", "Gold for clearing a nest",
            "The orens a cleared nest pays, for the first clears of a day (Nemeta per day).",
            "The next nest you open.", 100, 0, 1000, 10, "orens", WorldNests.BountyGold),
        new(NestExpPercent, "Nemeta", "Experience from nests",
            "How much experience a nest gives (its monsters, and 250 for clearing it), as a share of the original amount.",
            "The next nest you open.", 200, 10, 1000, 5, "%", 100),
        new(TaskGoldPercent, "Rewards", "Gold from daily tasks",
            "How many orens a daily task pays, as a share of its own amount (50 to 100).", StaticApply, 200, 0, 1000, 10, "%", 100),
        new(TaskExp, "Rewards", "Experience from daily tasks",
            "Experience a claimed daily task adds to its gold (the original game gave none). The task's items are on the Rewards page.",
            "The next claimed task.", 200, 0, 5000, 10, "experience", 0),
        new(HerbRespawnMinutes, "Herbs", "Herb respawn time",
            "How long a herb you picked stays gone before it grows back.",
            "Herbs picked from now on.", 60, 1, 1440, 1, "minutes"),
        new(HerbsPerCell, "Herbs", "Herbs per map cell",
            "How many herb bushes a map cell can hold (at most a third of its places, so a cell keeps room for monsters).",
            "Map cells the game loads from now on.", 4, 0, 12, 1, "bushes"),
        new(RealWeather, "Weather", "Real weather",
            "1 shows the real weather where you play, from Open-Meteo (only your position rounded to about 11 km is sent); " +
            "0 keeps it always clear. The weather decides which monsters appear and which potions help.",
            "The next weather the game asks for (about every five minutes).", 1, 0, 1, 1, Switch),
        new(StartingBag, "Inventory", "Starting bag size",
            "How many items the inventory holds before any bag is bought. The five bags in Thorstein's shop add 50 to 400 " +
            "each, and some quests add more. A full bag leaves fight loot behind and refuses herbs and shop items.",
            "The next game start.", 400, 50, 1000, 10, "items", 200),
        new(MaxBag, "Inventory", "Largest bag",
            "The most items the inventory can ever hold, with every bag and quest reward.", "The next game start.",
            2000, 1000, 4000, 50, "items", 1000),
        new(OpenPacks, "Inventory", "Open packs from the inventory",
            "1 lets a player open their own herbalist's packs (what they hold is on the Rewards page): the inventory's Remove " +
            "button for a pack reads Open. 0 keeps the original game's packs, which are only sent to friends (Remove throws them away).",
            "At once; the button's name at the next game start.", 1, 0, 1, 1, Switch, 0),
        new(SelfFriend, "Inventory", "Yourself in the friends list",
            "1 lists every player first among their own friends, so a pack can be sent to yourself and opened there (a backup to " +
            "Open in the inventory; one at a time, any day). 0 keeps the original game's list.",
            "At once; the game shows it when its friends list refreshes.", 1, 0, 1, 1, Switch, 0),
        BestiarySetting("common", 1, 3, 3), BestiarySetting("common", 2, 25, 50), BestiarySetting("common", 3, 100, 150),
        BestiarySetting("rare", 1, 2, 2), BestiarySetting("rare", 2, 10, 10), BestiarySetting("rare", 3, 20, 30),
        BestiarySetting("legendary", 1, 1, 1), BestiarySetting("legendary", 2, 2, 2), BestiarySetting("legendary", 3, 4, 6),
        new(TierSkillPoints, "Bestiary", "Skill points per bestiary tier",
            "The skill points each bestiary tier gives when its reward is claimed.", StaticApply, 1, 0, 10, 1, "points"),
        new(SkillPointsPerLevel, "Skills", "Skill points per level",
            "The skill points each new level gives. Levels already reached keep what they gave.", StaticApply, 5, 0, 20, 1, "points"),
        new(SkillsReset, "Skills", "Reset skills in the skill tree",
            "1 lets a player give back every learned skill for the points it cost (the starting skills stay): in the skill " +
            "tree, open a fully learned skill and tap its button twice. 0 keeps the original game's skills for good.",
            GameApply, 1, 0, 1, 1, Switch, 0),
        SkillSetting(ExtraPotionChance, "Elixir Master: a second potion",
            "The chance that a potion brewed with Elixir Master comes out twice.", 10, 100, "%"),
        new(SquallRemains, "Skills", "Squall: elemental remains",
            "How many elemental remains the Squall potion's recipe needs." + Unknown, StaticApply, 1, 1, 100, 1, "remains"),
        SkillSetting(ResolveFloor, "Resolve: adrenaline floor",
            "The adrenaline Resolve keeps at least, per rank.", 10, 30, "% per rank"),
        SkillSetting(AttackAdrenaline, "Precise and Crushing Blows",
            "The extra adrenaline each fast (Precise Blows) or strong (Crushing Blows) attack gives.", 1, 20, "points"),
        SkillSetting(EventAdrenaline, "Adrenaline from parries, signs and bombs",
            "The adrenaline Cold Blood (a parry), Adrenaline Burst (a sign), the three Intensity skills (Quen, Igni, Aard) and " +
            "Advanced Pyrotechnics (a bomb) give each time.", 1, 10, "points"),
        SkillSetting(InitialAdrenaline, "Razor Focus: adrenaline at the start",
            "The adrenaline Razor Focus gives when a fight starts.", 3, 10, "points"),
        SkillSetting(SurvivalChance, "Undying: survive the final blow",
            "The chance that Undying lets you survive a blow that would end the fight.", 10, 100, "%"),
        SkillSetting(SignRecoveryChance, "Gorged on Power: instant sign",
            "The chance that Gorged on Power makes a sign ready again at once.", 10, 100, "%"),
        SkillSetting(BombAngle, "Steady Aim: flatter throws",
            "How many degrees Steady Aim, and again Advanced Steady Aim, take off a bomb's throwing angle (45 without them).",
            15, 20, "degrees"),
        new(AuraInterval, "Skills", "Witcher Aura: how often",
            "How long after a Witcher Aura monster the skill can summon the next." + Unknown, StaticApply, 60, 5, 1440, 5, "minutes"),
        new(AuraLifetime, "Skills", "Witcher Aura: how long the monster stays",
            "How long a Witcher Aura monster waits on the map. At most Witcher Aura: how often." + Unknown,
            StaticApply, 60, 5, 1440, 5, "minutes"),
        new(QuenAbsorb, "Skills", "Quen: share of a blow it absorbs",
            "How much of the blow that breaks the Quen shield it takes. The game starts the shield at nothing and the Quen skill " +
            "carries the share (ImproveQuenAbsorb), so without it Quen let every blow through. 100 blocks the blow; the community " +
            "remembers the original game's 70.", StaticApply, 100, 0, 100, 5, "%", 70),
        new(BrewTimePercent, "Alchemy", "Brewing time",
            "How long brewing takes, as a share of each recipe's own time (faster stations still halve it): 50 brews twice as fast.",
            StaticApply, 100, 10, 200, 5, "%"),
        new(QuestSoftCap, "Quests", "Quest places: preferred distance",
            "Quest places are chosen within this distance of you when the map has room; 5000 leaves the quests' own distances.",
            "Quest places chosen from now on.", 800, 100, 5000, 50, "m", 5000),
        new(QuestHardCap, "Quests", "Quest places: farthest distance",
            "No quest place is ever farther from you than this (a farther one moves closer at the next map load).",
            "Quest places chosen from now on.", 1000, 100, 5000, 50, "m", 5000),
        new(QuestWalkingCap, "Quests", "Quest places: farthest walk",
            "No new quest place is farther than this to walk, along the map's roads and paths: a place across a river or " +
            "round a fence can be two or three times farther on foot than it looks. 0 measures in a straight line only.",
            "Quest places chosen from now on.", 1500, 0, 5000, 50, "m", 0),
        new(TrollDefeats, "Story", "Monster Slayer: troll defeats",
            "After Good Money, a player who has beaten a rock troll must lose this many fights to rock trolls before the troll " +
            "talks and offers Monster Slayer. The game shows the quest from its next start.",
            "The next lost fight.", 3, 1, 10, 1, "fights"),
        new(CollectingDistance, "Story", "Walking between quest finds",
            "How far you walk before the next find of a collecting quest appears beside you (the Great Mushrooming's mushrooms). " +
            "The game counts walking in steps of 100 m, and only while it is open.", GameApply, 100, 100, 200, 100, "m", 200),
        new(CollectingUntracked, "Story", "Quest finds without tracking the quest",
            "1 shows a started collecting quest's finds (the Great Mushrooming's mushrooms) even while another quest is tracked; " +
            "0 shows them only while that quest is the tracked one, as the original game did.", GameApply, 1, 0, 1, 1, Switch, 0),
        new(IntruderAllEndings, "Story", "Intruder: every ending can be reached",
            "1 lets the Intruder's full and bonus endings happen when you did not wait out the sorcerer's 24 hours: in the game's " +
            "own data they need a choice that is never offered, so four of its eight endings can never be reached. 0 keeps the " +
            "original data.", GameApply, 1, 0, 1, 1, Switch, 0),
        new(OilsMultiply, "Combat", "Oils multiply the blow",
            "1 makes an oil's bonus (33 % for the basic oil) multiply the whole blow, after weaknesses, potions and skills. 0 keeps " +
            "the original game's sum: the oil adds its share of the sword's base damage, so on a blow already doubled by a " +
            "weakness it shows as about 14 % more, and the oils' descriptions say so.", GameApply, 1, 0, 1, 1, Switch, 0),
        new(LastingMinutes, "Combat", "Potions and oils last",
            "How long a potion or oil taken before a fight keeps working: every fight in that time has it, and the map's " +
            "effects panel shows the time left. As many potions as your potion slots (a new one replaces the one taken first) " +
            "and one oil (a new one replaces it); the same one again starts its time again. 0 keeps them to the one fight, as " +
            "the original game did.", "The next potion or oil taken; the names in the effects panel at the next game start.",
            30, 0, 1440, 5, "minutes", 0),
        new(QuenPerfectParry, "Combat", "Perfect parries under Quen",
            "1 lets a perfect parry count while the Quen shield is up: the blow is parried and the shield stays (the game takes " +
            "the shield first, so a parry under Quen always broke it). 0 keeps the original game's order.", "The next game start.",
            1, 0, 1, 1, Switch, 0),
        new(BlacksmithDamage, "Combat", "The blacksmith's sharpening",
            "How much more melee damage a sword the blacksmith sharpened deals, for the hour it lasts (the effects panel: " +
            "Increased damage). The game sends the hour; the amount was the original servers'." + Unknown,
            StaticApply, 10, 0, 100, 5, "%"),
        new(TrinketBuffs, "Trinkets", "Trinket bonuses",
            "1 gives each trinket a bonus (more herbs, experience, attack against a family, bag slots…), shown in its description; " +
            "0 keeps trinkets as keepsakes only.", "At once; the descriptions at the next game start.", 1, 0, 1, 1, Switch, 0),
        new(ShopScrolls, "Shop", "Summoning scrolls in the shop",
            "1 sells the summoning scrolls (by family and rarity) for orens.", StaticApply, 1, 0, 1, 1, Switch, 0),
        new(ShopWeatherItems, "Shop", "Weather items in the shop",
            "1 sells the weather items (rain, fog, clear skies for an hour) for orens. Items already owned can always be used.",
            StaticApply, 1, 0, 1, 1, Switch, 0),
        new(ShopOrenPacks, "Shop", "Gold coin packs in the shop",
            "1 keeps the original game's packs of orens (bought for real money there, free here). The game never offers them " +
            "when a purchase costs more than the wallet holds.", StaticApply, 0, 0, 1, 1, Switch, 1),
        new(ShopDailyDiscount, "Shop", "Daily deals discount",
            "How much cheaper the shop's three daily deals (potions, oils and bombs) are. The prices themselves are on the " +
            "Rewards page.", StaticApply, 40, 0, 90, 5, "%", 25),
    };

    /// <summary>The running server's settings, for code that has no access to the service (the herb rules are static). Revival
    /// until the server's own is set.</summary>
    public static WorldTuning Current { get; set; } = new(null, null);

    /// <summary>The values at this server's start, for the settings the game also reads from its static data at its start (the
    /// nemeta limits, skill points, the skills' numbers, brewing time): the server keeps to them until its next start, as the
    /// game does. WorldPolicy sets them; Revival's before that.</summary>
    public static IReadOnlyDictionary<string, double> Started { get; set; } = Defaults();

    private readonly string? path, presetDirectory;
    private readonly ILogger? log;
    private readonly object gate = new();
    private Dictionary<string, double> values = Defaults();
    private string active = RevivalId;
    private RewardTables rewards = RewardTables.Revival;
    private long nextCheck;
    private (DateTime Written, long Length) seen, refused, presetSeen;

    public WorldTuning(string? directory, ILogger? log)
    {
        this.log = log;
        if (!string.IsNullOrWhiteSpace(directory))
        {
            path = Path.Combine(Path.GetFullPath(directory), "tuning.json");
            presetDirectory = Path.Combine(Path.GetFullPath(directory), "presets");
            Migrate();
        }
        Reload(force: true);
    }

    public static Dictionary<string, double> Defaults() => Settings.ToDictionary(s => s.Key, s => s.Default);
    public static Dictionary<string, double> VanillaValues() => Settings.ToDictionary(s => s.Key, s => s.Vanilla);

    public static Preset RevivalPreset() => new(RevivalId, "Revival", true, Defaults(), RewardTables.Revival);
    public static Preset VanillaPreset() => new(VanillaId, "Vanilla", true, VanillaValues(), RewardTables.Vanilla);

    /// <summary>Reads the file now, not at the next check: what the dashboard does after a save, so the new numbers apply at once.</summary>
    public void Refresh() => Reload(force: true);

    /// <summary>The current value of a setting in the active preset.</summary>
    public double Get(string key)
    {
        Reload();
        lock (gate) return values[key];
    }

    public bool On(string key) => Get(key) != 0;

    /// <summary>Every setting with its current value.</summary>
    public IReadOnlyDictionary<string, double> Effective()
    {
        Reload();
        lock (gate) return new Dictionary<string, double>(values);
    }

    /// <summary>The active preset's reward tables.</summary>
    public RewardTables Rewards
    {
        get { Reload(); lock (gate) return rewards; }
    }

    public string ActivePreset
    {
        get { Reload(); lock (gate) return active; }
    }

    // ── Documents ───────────────────────────────────────────────────────────────────────────────

    /// <summary>tuning.json: the active preset and its resolved values (every setting, so the placement service reads them all).</summary>
    public static byte[] Serialize(string preset, IReadOnlyDictionary<string, double> values) => JsonSerializer.SerializeToUtf8Bytes(
        new { schemaVersion = 2, preset, values = Settings.ToDictionary(s => s.Key, s => values.TryGetValue(s.Key, out double v) ? v : s.Default) },
        new JsonSerializerOptions { WriteIndented = true });

    public static byte[] SerializePreset(Preset preset) => JsonSerializer.SerializeToUtf8Bytes(new
    {
        schemaVersion = 1, name = preset.Name,
        values = Settings.ToDictionary(s => s.Key, s => preset.Values.TryGetValue(s.Key, out double v) ? v : s.Default),
        rewards = preset.Rewards,
    }, RewardTables.Json);

    /// <summary>Reads the values of a document {"schemaVersion":1|2,"values":{...}} (a preset file has the same values block).
    /// [strict] refuses a setting this version does not know (what a save does); reading a saved file ignores one, so a file
    /// written by a newer version still loads. Settings missing from the document take [fill]'s values (Revival by default).</summary>
    public static Dictionary<string, double> Parse(JsonElement document, bool strict, IReadOnlyDictionary<string, double>? fill = null)
    {
        if (document.ValueKind != JsonValueKind.Object || !document.TryGetProperty("values", out var given) ||
            given.ValueKind != JsonValueKind.Object ||
            document.TryGetProperty("schemaVersion", out var version) && (version.ValueKind != JsonValueKind.Number || version.GetInt32() is not (1 or 2)))
            throw new InvalidDataException("Tuning must be {\"schemaVersion\":2,\"values\":{...}}.");
        var result = new Dictionary<string, double>(fill ?? Defaults());
        foreach (var property in given.EnumerateObject())
        {
            var setting = Settings.FirstOrDefault(s => s.Key == property.Name);
            if (setting is null)
            {
                if (strict) throw new InvalidDataException($"Unknown setting {property.Name}.");
                continue;
            }
            if (property.Value.ValueKind != JsonValueKind.Number || !property.Value.TryGetDouble(out double value) ||
                !double.IsFinite(value) || value < setting.Min || value > setting.Max ||
                setting.Step >= 1 && value != Math.Round(value))
                throw new InvalidDataException($"{setting.Label} must be {(setting.Step >= 1 ? "a whole number" : "a number")} from " +
                    $"{setting.Min} to {setting.Max}.");
            result[setting.Key] = value;
        }
        foreach (string rarity in BestiaryRarities)
            for (int tier = 2; tier <= 3; tier++)
                if (result[Bestiary(rarity, tier)] < result[Bestiary(rarity, tier - 1)])
                    throw new InvalidDataException($"The bestiary's {rarity} tier {tier} cannot need fewer kills than tier {tier - 1}.");
        if (result[AuraLifetime] > result[AuraInterval])
            throw new InvalidDataException("A Witcher Aura monster cannot stay longer than the time between two of them.");
        return result;
    }

    // ── Presets ─────────────────────────────────────────────────────────────────────────────────

    private static readonly Regex PresetId = new("^custom(-[0-9]{1,4})?$");

    /// <summary>Revival, Vanilla and the player's own presets (by name).</summary>
    public IReadOnlyList<Preset> Presets()
    {
        var list = new List<Preset> { RevivalPreset(), VanillaPreset() };
        if (presetDirectory is not null && Directory.Exists(presetDirectory))
            foreach (string file in Directory.GetFiles(presetDirectory, "*.json").OrderBy(f => f, StringComparer.Ordinal))
                if (PresetId.IsMatch(Path.GetFileNameWithoutExtension(file)) && ReadPreset(Path.GetFileNameWithoutExtension(file)) is { } preset)
                    list.Add(preset);
        return list;
    }

    public Preset? FindPreset(string id) => id switch
    {
        RevivalId => RevivalPreset(),
        VanillaId => VanillaPreset(),
        _ => PresetId.IsMatch(id) ? ReadPreset(id) : null,
    };

    public string? PresetPath(string id) => presetDirectory is null || !PresetId.IsMatch(id) ? null : Path.Combine(presetDirectory, id + ".json");

    /// <summary>A free id for a new preset of the player's.</summary>
    public string NewPresetId()
    {
        for (int n = 1; ; n++)
        {
            string id = n == 1 ? "custom" : $"custom-{n}";
            if (!File.Exists(PresetPath(id))) return id;
        }
    }

    /// <summary>A name the dashboard accepts: 1-40 characters, no line breaks.</summary>
    public static string CheckName(string? name) => name?.Trim() is { Length: > 0 and <= 40 } trimmed && !trimmed.Any(char.IsControl)
        ? trimmed : throw new InvalidDataException("A preset name has 1 to 40 characters.");

    private Preset? ReadPreset(string id)
    {
        string? file = PresetPath(id);
        if (file is null || !File.Exists(file)) return null;
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(file));
            var root = document.RootElement;
            var tables = root.TryGetProperty("rewards", out var r) ? RewardTables.Parse(r) : RewardTables.Revival;
            return new Preset(id, CheckName(root.GetProperty("name").GetString()), false, Parse(root, strict: false), tables);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException or KeyNotFoundException)
        {
            log?.LogWarning("Preset {Id} cannot be read ({Reason})", id, ex.GetType().Name);
            return null;
        }
    }

    // A tuning.json from before presets (schemaVersion 1, the player's own numbers) becomes the player's preset "Custom" and
    // stays active, so nothing they chose resets.
    private void Migrate()
    {
        if (path is null || !File.Exists(path)) return;
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(path));
            if (!document.RootElement.TryGetProperty("schemaVersion", out var version) || version.GetInt32() != 1) return;
            var old = Parse(document.RootElement, strict: false);
            string id = NewPresetId();
            Directory.CreateDirectory(presetDirectory!);
            WriteAtomic(PresetPath(id)!, SerializePreset(new Preset(id, "Custom", false, old, RewardTables.Revival)));
            WriteAtomic(path, Serialize(id, old));
            log?.LogInformation("Tuning: the saved settings became the preset \"Custom\" ({Id})", id);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
        {
            log?.LogWarning("Tuning: the old settings file could not become a preset ({Reason})", ex.GetType().Name);
        }
    }

    public static void WriteAtomic(string file, byte[] bytes)
    {
        string temporary = file + ".tmp";
        File.WriteAllBytes(temporary, bytes);
        File.Move(temporary, file, overwrite: true);
    }

    private void Reload(bool force = false)
    {
        if (path is null) return;
        lock (gate)
        {
            if (!force && Environment.TickCount64 < nextCheck) return;
            nextCheck = Environment.TickCount64 + 1000;
            (DateTime, long) stamp = default;
            try
            {
                if (!File.Exists(path)) { values = Defaults(); active = RevivalId; rewards = RewardTables.Revival; seen = refused = presetSeen = default; return; }
                var info = new FileInfo(path);
                stamp = (info.LastWriteTimeUtc, info.Length);
                string? presetFile = PresetPath(active);
                var presetStamp = presetFile is not null && File.Exists(presetFile)
                    ? (new FileInfo(presetFile).LastWriteTimeUtc, new FileInfo(presetFile).Length) : default;
                if ((stamp == seen && presetStamp == presetSeen) || stamp == refused) return;
                if (info.Length > 16 * 1024) throw new InvalidDataException("Tuning is too large.");
                using var document = JsonDocument.Parse(File.ReadAllBytes(path));
                string id = document.RootElement.TryGetProperty("preset", out var p) && p.ValueKind == JsonValueKind.String
                    ? p.GetString()! : RevivalId;
                var preset = FindPreset(id);
                values = Parse(document.RootElement, strict: false, (preset ?? RevivalPreset()).Values);
                active = preset?.Id ?? RevivalId;
                rewards = preset?.Rewards ?? RewardTables.Revival;
                seen = stamp;
                presetFile = PresetPath(active);
                presetSeen = presetFile is not null && File.Exists(presetFile)
                    ? (new FileInfo(presetFile).LastWriteTimeUtc, new FileInfo(presetFile).Length) : default;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            {
                refused = stamp; // keep the last good values, and say so once per version of the file
                log?.LogWarning("Tuning file refused; keeping the last valid settings ({Reason})", ex.GetType().Name);
            }
        }
    }
}
