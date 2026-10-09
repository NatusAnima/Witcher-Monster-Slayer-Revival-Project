using System.Text.Json;
using System.Text.Json.Serialization;

namespace WitcherRevival.Server.Net;

/// <summary>Authored density policy; hot reload changes future map responses, never saved progress.</summary>
public sealed class WorldPolicy
{
    public sealed record Settings(int SchemaVersion = 1, int MonsterSlotsPerCell = WorldSpawns.DefaultMonsterSlotsPerCell);
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = true,
    };
    private readonly string? path;
    private readonly ILogger<WorldPolicy> log;
    private readonly object gate = new();
    private Settings current = new();
    private long nextCheck;
    // Immutable for the process and pinned in deployment configuration across restarts.
    // Zero enables the new lottery for a fresh installation; a future instant stages an upgrade.
    public long SpawnBalanceFromUnixSeconds { get; }
    public WorldBalance Balance { get; }
    public DistancePolicy Distance { get; }
    /// <summary>The numbers a player tunes in the dashboard.</summary>
    public WorldTuning Tuning { get; }

    public WorldPolicy(IConfiguration cfg, ILogger<WorldPolicy> log)
    {
        this.log = log;
        SpawnBalanceFromUnixSeconds = cfg.GetValue<long>("World:SpawnBalanceFromUnixSeconds", 0);
        if (SpawnBalanceFromUnixSeconds < 0)
            throw new InvalidDataException("World spawn balance activation must be a nonnegative Unix timestamp.");
        string? directory = cfg["World:Directory"];
        Balance = new WorldBalance(directory, log);
        Distance = new DistancePolicy(directory, log);
        Tuning = WorldTuning.Current = new WorldTuning(directory, log);
        Distance.Read(refresh: true);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            path = Path.Combine(Path.GetFullPath(directory), "world.json");
            // An explicitly configured directory must contain a valid initial policy.
            current = Load();
        }
    }

    public static void Validate(Settings settings)
    {
        if (settings.SchemaVersion != 1 || settings.MonsterSlotsPerCell is < WorldSpawns.MonstersPerCell or > WorldSpawns.MaxMonsterSlotsPerCell)
            throw new InvalidDataException($"World policy requires schemaVersion 1 and monsterSlotsPerCell from " +
                $"{WorldSpawns.MonstersPerCell} to {WorldSpawns.MaxMonsterSlotsPerCell}.");
    }

    private Settings Load()
    {
        using var stream = new FileStream(path!, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
        if (stream.Length > 4096) throw new InvalidDataException("World policy is too large.");
        using var document = JsonDocument.Parse(stream);
        if (document.RootElement.ValueKind != JsonValueKind.Object ||
            document.RootElement.EnumerateObject().Count() != 2 ||
            !document.RootElement.TryGetProperty("schemaVersion", out _) ||
            !document.RootElement.TryGetProperty("monsterSlotsPerCell", out _))
            throw new InvalidDataException("World policy must define both settings exactly once.");
        var settings = document.Deserialize<Settings>(Json) ?? throw new InvalidDataException("Empty world policy.");
        Validate(settings);
        return settings;
    }

    public Settings Read()
    {
        if (path is null) return current;
        lock (gate)
        {
            if (Environment.TickCount64 < nextCheck) return current;
            nextCheck = Environment.TickCount64 + 1000;
            try { current = Load(); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            { log.LogWarning("World policy reload refused; keeping last valid settings ({Reason})", ex.GetType().Name); }
            return current;
        }
    }
}
