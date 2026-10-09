using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Simple numbers a player can change in the dashboard to suit how they play, saved in the world folder (tuning.json) and read
/// again about once a second, so a change needs no restart. A missing or damaged file means every default; a bad value is
/// refused when it is saved. The placement service (a separate process) reads the same file for the places.* settings
/// (playable_locations.Tuning, with the same keys, defaults and limits).
/// </summary>
public sealed class WorldTuning
{
    /// <param name="Applies">When a change takes effect, in words for the dashboard.</param>
    public sealed record Setting(string Key, string Group, string Label, string Help, string Applies, double Default, double Min,
        double Max, double Step, string Unit);

    public const string ExpPercent = "exp.percent", LootPercent = "loot.percent",
        HerbRespawnMinutes = "herbs.respawnMinutes", HerbsPerCell = "herbs.perCell", RealWeather = "weather.real",
        StartingBag = "inventory.startSize", NestGold = "nests.gold";

    private const string PlacesApply = "Places drawn from now on. Monsters already out stay for up to 30 minutes.";

    private static Setting Share(string ground, string label, string where, double share) => new("places." + ground, "Places",
        label, $"How much of a map cell's places lie {where}. The five shares count against each other, so only their sizes " +
        "matter; a cell without that kind of ground gives its share to the others, and 0 leaves it out.",
        PlacesApply, share, 0, 100, 5, "share");

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
        new(ExpPercent, "Rewards", "Experience from fights",
            "How much experience a won fight gives, as a share of the normal amount: 200 doubles it, 50 halves it.",
            "The next fight.", 100, 10, 1000, 5, "%"),
        new(LootPercent, "Rewards", "Ingredients from fights",
            "How many ingredients a won fight drops, as a share of the normal amount: 200 doubles them, 0 drops none.",
            "The next fight.", 100, 0, 1000, 10, "%"),
        new(NestGold, "Rewards", "Gold for clearing a nest",
            "The orens a cleared nest pays, for the first three clears of a day.",
            "The next nest you open.", WorldNests.BountyGold, 0, 1000, 10, "orens"),
        new(HerbRespawnMinutes, "Herbs", "Herb respawn time",
            "How long a herb you picked stays gone before it grows back.",
            "Herbs picked from now on.", 60, 1, 1440, 1, "minutes"),
        new(HerbsPerCell, "Herbs", "Herbs per map cell",
            "How many herb bushes a map cell can hold (at most a third of its places, so a cell keeps room for monsters).",
            "Map cells the game loads from now on.", 4, 0, 12, 1, "bushes"),
        new(RealWeather, "Weather", "Real weather",
            "1 shows the real weather where you play, from Open-Meteo (only your position rounded to about 11 km is sent); " +
            "0 keeps it always clear. The weather decides which monsters appear and which potions help.",
            "The next weather the game asks for (about every five minutes).", 1, 0, 1, 1, "on/off"),
        new(StartingBag, "Inventory", "Starting bag size",
            "How many items the inventory holds before any bag is bought. The five bags in Thorstein's shop add 50 to 400 " +
            "each, up to 1000 in all. A full bag leaves fight loot behind and refuses herbs and shop items.",
            "The next game start.", 200, 50, 1000, 10, "items"),
    };

    /// <summary>The running server's settings, for code that has no access to the service (the herb rules are static). All defaults
    /// until the server's own is set.</summary>
    public static WorldTuning Current { get; set; } = new(null, null);

    private readonly string? path;
    private readonly ILogger? log;
    private readonly object gate = new();
    private Dictionary<string, double> values = Defaults();
    private long nextCheck;
    private (DateTime Written, long Length) seen, refused;

    public WorldTuning(string? directory, ILogger? log)
    {
        this.log = log;
        if (!string.IsNullOrWhiteSpace(directory)) path = Path.Combine(Path.GetFullPath(directory), "tuning.json");
        Reload(force: true);
    }

    public static Dictionary<string, double> Defaults() => Settings.ToDictionary(s => s.Key, s => s.Default);

    /// <summary>Reads the file now, not at the next check: what the dashboard does after a save, so the new numbers apply at once.</summary>
    public void Refresh() => Reload(force: true);

    /// <summary>The current value of a setting: what the player saved, else its default.</summary>
    public double Get(string key)
    {
        Reload();
        lock (gate) return values[key];
    }

    /// <summary>Every setting with its current value (the saved ones laid over the defaults).</summary>
    public IReadOnlyDictionary<string, double> Effective()
    {
        Reload();
        lock (gate) return new Dictionary<string, double>(values);
    }

    /// <summary>The file's contents for [values]: every setting, so a later default change never moves what a player chose.</summary>
    public static byte[] Serialize(IReadOnlyDictionary<string, double> values) => JsonSerializer.SerializeToUtf8Bytes(
        new { schemaVersion = 1, values = Settings.ToDictionary(s => s.Key, s => values.TryGetValue(s.Key, out double v) ? v : s.Default) },
        new JsonSerializerOptions { WriteIndented = true });

    /// <summary>Reads a document {"schemaVersion":1,"values":{...}}. [strict] refuses a setting this version does not know
    /// (what a save does); reading the saved file ignores one, so a file written by a newer version still loads.</summary>
    public static Dictionary<string, double> Parse(JsonElement document, bool strict)
    {
        if (document.ValueKind != JsonValueKind.Object || !document.TryGetProperty("schemaVersion", out var version) ||
            version.ValueKind != JsonValueKind.Number || version.GetInt32() != 1 ||
            !document.TryGetProperty("values", out var given) || given.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Tuning must be {\"schemaVersion\":1,\"values\":{...}}.");
        var result = Defaults();
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
        return result;
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
                if (!File.Exists(path)) { values = Defaults(); seen = refused = default; return; }
                var info = new FileInfo(path);
                stamp = (info.LastWriteTimeUtc, info.Length);
                if (stamp == seen || stamp == refused) return;
                if (info.Length > 16 * 1024) throw new InvalidDataException("Tuning is too large.");
                using var document = JsonDocument.Parse(File.ReadAllBytes(path));
                values = Parse(document.RootElement, strict: false);
                seen = stamp;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            {
                refused = stamp; // keep the last good values, and say so once per version of the file
                log?.LogWarning("Tuning file refused; keeping the last valid settings ({Reason})", ex.GetType().Name);
            }
        }
    }
}
