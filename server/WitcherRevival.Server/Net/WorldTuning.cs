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
        ExpByRarity = "xp.baseByRarity", VanillaCurve = "xp.vanillaCurve", QuestSoftCap = "quests.softCap",
        QuestHardCap = "quests.hardCap", TrinketBuffs = "trinkets.buffs", ShopScrolls = "shop.scrolls",
        ShopWeatherItems = "shop.weatherItems";

    /// <summary>Bestiary knowledge thresholds by rarity (common, rare, legendary): the cumulative kills of tiers 1-3.</summary>
    public static string Bestiary(string rarity, int tier) => $"bestiary.{rarity}{tier}";
    public static readonly string[] BestiaryRarities = ["common", "rare", "legendary"];

    private const string PlacesApply = "Places drawn from now on. Monsters already out stay for up to 30 minutes.";
    private const string SpawnApply = "Monsters drawn from now on. Monsters already out stay for up to 30 minutes.";
    private const string StaticApply = "The next server start and game start.";
    private const string Switch = "on/off";

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
            "stand on them is the World page's monsters per cell.", PlacesApply, 24, 4, 48, 1, "places"),
        new("places.spacing", "Places", "Distance between places",
            "The least distance between two places. Smaller lets a cell hold more of them.", PlacesApply, 50, 30, 200, 5, "m"),
        Share("paths", "On paths", "on footpaths and tracks away from houses", 40),
        Share("parks", "In parks", "in parks and on their paths", 25),
        Share("woods", "In woods", "in woods and forests", 15),
        Share("water", "By water", "within 60 m of a river, lake or the sea", 10),
        Share("urban", "Near houses", "within 60 m of a building: the streets and footpaths of a town", 40),
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
            "1 keeps world monsters within your level: no skulls from level 1, one skull from 3, two from 6, legendaries from 10. " +
            "0 lets any monster appear at any level.", SpawnApply, 1, 0, 1, 1, Switch),
        new(ExpByRarity, "Experience", "Experience by rarity",
            "1 gives 100 experience for a common monster, 250 for a rare and 600 for a legendary, as the original game did; 0 " +
            "goes by the skulls shown (100, 175, 250, 600).", "The next fight.", 1, 0, 1, 1, Switch),
        new(VanillaCurve, "Experience", "Original level table",
            "1 uses the original game's experience table (level 10 at 27,000, level 40 at 3,877,000); 0 this project's (level 10 at " +
            "45,000, level 40 at 780,000). Your level stays as it is when you switch; only the experience to the next level changes.",
            StaticApply, 0, 0, 1, 1, Switch, 1),
        new(ExpPercent, "Experience", "Experience from fights",
            "How much experience a won fight gives, as a share of the normal amount: 200 doubles it, 50 halves it.",
            "The next fight.", 100, 10, 1000, 5, "%"),
        new(LootPercent, "Rewards", "Ingredients from fights",
            "How many ingredients a won fight drops, as a share of the normal amount: 200 doubles them, 0 drops none.",
            "The next fight.", 100, 0, 1000, 10, "%"),
        new(NestGold, "Rewards", "Gold for clearing a nest",
            "The orens a cleared nest pays, for the first three clears of a day.",
            "The next nest you open.", 100, 0, 1000, 10, "orens", WorldNests.BountyGold),
        new(NestExpPercent, "Rewards", "Experience from nests",
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
        BestiarySetting("common", 1, 3, 3), BestiarySetting("common", 2, 25, 50), BestiarySetting("common", 3, 100, 150),
        BestiarySetting("rare", 1, 2, 2), BestiarySetting("rare", 2, 10, 10), BestiarySetting("rare", 3, 20, 30),
        BestiarySetting("legendary", 1, 1, 1), BestiarySetting("legendary", 2, 2, 2), BestiarySetting("legendary", 3, 4, 6),
        new(QuestSoftCap, "Quests", "Quest places: preferred distance",
            "Quest places are chosen within this distance of you when the map has room; 5000 leaves the quests' own distances.",
            "Quest places chosen from now on.", 800, 100, 5000, 50, "m", 5000),
        new(QuestHardCap, "Quests", "Quest places: farthest distance",
            "No quest place is ever farther from you than this (a farther one moves closer at the next map load).",
            "Quest places chosen from now on.", 1000, 100, 5000, 50, "m", 5000),
        new(TrollDefeats, "Story", "Monster Slayer: troll defeats",
            "After Good Money, a player who has beaten a rock troll must lose this many fights to rock trolls before the troll " +
            "talks and offers Monster Slayer. The game shows the quest from its next start.",
            "The next lost fight.", 3, 1, 10, 1, "fights"),
        new(TrinketBuffs, "Trinkets", "Trinket bonuses",
            "1 gives each trinket a bonus (more herbs, experience, attack against a family, bag slots…), shown in its description; " +
            "0 keeps trinkets as keepsakes only.", "At once; the descriptions at the next game start.", 1, 0, 1, 1, Switch, 0),
        new(ShopScrolls, "Shop", "Summoning scrolls in the shop",
            "1 sells the summoning scrolls (by family and rarity) for orens.", StaticApply, 1, 0, 1, 1, Switch, 0),
        new(ShopWeatherItems, "Shop", "Weather items in the shop",
            "1 sells the weather items (rain, fog, clear skies for an hour) for orens. Items already owned can always be used.",
            StaticApply, 1, 0, 1, 1, Switch, 0),
    };

    /// <summary>The running server's settings, for code that has no access to the service (the herb rules are static). Revival
    /// until the server's own is set.</summary>
    public static WorldTuning Current { get; set; } = new(null, null);

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
