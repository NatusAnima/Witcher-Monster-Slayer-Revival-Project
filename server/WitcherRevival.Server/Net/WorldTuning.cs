using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Simple numbers a player can change in the dashboard to suit how they play, saved in the world folder (tuning.json) and read
/// again about once a second, so a change needs no restart. A missing or damaged file means every default; a bad value is
/// refused when it is saved. The placement service (a separate process) reads the same file for the woods limit.
/// </summary>
public sealed class WorldTuning
{
    /// <param name="Applies">When a change takes effect, in words for the dashboard.</param>
    public sealed record Setting(string Key, string Group, string Label, string Help, string Applies, double Default, double Min,
        double Max, double Step, string Unit);

    public const string WoodsPlaces = "woods.maxPlaces", ExpPercent = "exp.percent", LootPercent = "loot.percent",
        HerbRespawnMinutes = "herbs.respawnMinutes", HerbsPerCell = "herbs.perCell";

    public static readonly IReadOnlyList<Setting> Settings = new Setting[]
    {
        new(WoodsPlaces, "Monsters", "Woods limit per map cell",
            "The most places woodland can hold in one map cell (a cell holds 24 in all). Lower it to see fewer monsters in forests and more " +
            "on paths and in parks. A cell of nothing but woods keeps this many.",
            "Places drawn from now on. Monsters already out stay for up to 30 minutes.", 12, 0, 24, 1, "places"),
        new(ExpPercent, "Rewards", "Experience from fights",
            "How much experience a won fight gives, as a share of the normal amount: 200 doubles it, 50 halves it.",
            "The next fight.", 100, 10, 1000, 5, "%"),
        new(LootPercent, "Rewards", "Ingredients from fights",
            "How many ingredients a won fight drops, as a share of the normal amount: 200 doubles them, 0 drops none.",
            "The next fight.", 100, 0, 1000, 10, "%"),
        new(HerbRespawnMinutes, "Herbs", "Herb respawn time",
            "How long a herb you picked stays gone before it grows back.",
            "Herbs picked from now on.", 60, 1, 1440, 1, "minutes"),
        new(HerbsPerCell, "Herbs", "Herbs per map cell",
            "How many herb bushes a map cell can hold (at most a third of its places, so a small cell keeps room for monsters).",
            "Map cells the game loads from now on.", 4, 0, 12, 1, "bushes"),
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
