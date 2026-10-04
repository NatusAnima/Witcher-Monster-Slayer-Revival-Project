using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace WitcherRevival.Server.Net;

/// <summary>Durable generation policy. Edits append future versions; living generations retain their lottery.</summary>
public sealed class WorldBalance
{
    public const int MaximumVersions = 128;
    public const long MaximumStart = 253402298999; // Leave room for a full lifetime in DateTimeOffset.
    public sealed record Rules(int Common = 88, int Rare = 18, int Legendary = 3,
        Dictionary<int, int>? SpeciesWeights = null)
    {
        public int Weight(int monster) => SpeciesWeights?.GetValueOrDefault(monster, 1) ?? 1;
        [JsonIgnore] public int Total => Common + Rare + Legendary;
        // Compute once per immutable rules revision, rather than building an identity for every spawn.
        [JsonIgnore] public string IdentitySuffix { get; } = Identity(Common, Rare, Legendary, SpeciesWeights);
        private static string Identity(int common, int rare, int legendary, Dictionary<int, int>? species)
        {
            string overrides = string.Join(',', (species ?? []).Where(p => p.Value != 1).OrderBy(p => p.Key)
                .Select(p => FormattableString.Invariant($"{p.Key}={p.Value}")));
            return common == 88 && rare == 18 && legendary == 3 && overrides.Length == 0 ? ":balance88-18-3" :
                FormattableString.Invariant($":balance:{common}:{rare}:{legendary}:{overrides}");
        }
    }
    public sealed record Version(long FromUnixSeconds, Rules Rules);
    public sealed record Schedule(int SchemaVersion, Version[] Versions)
    {
        public Rules At(long generation)
        {
            for (int i = Versions.Length - 1; i >= 0; i--)
                if (Versions[i].FromUnixSeconds <= generation) return Versions[i].Rules;
            return DefaultRules;
        }
    }
    public static Rules DefaultRules { get; } = new(SpeciesWeights: []);
    public static Schedule Default { get; } = new(1, [new(0, DefaultRules)]);
    private readonly string? path;
    private readonly ILogger log;
    private readonly object gate = new();
    private Schedule current;
    private long nextCheck;
    public WorldBalance(string? directory, ILogger log)
    {
        this.log = log;
        path = string.IsNullOrWhiteSpace(directory) ? null : Path.Combine(Path.GetFullPath(directory), "spawn-balance.json");
        current = Load();
    }
    public static Rules Validate(Rules rules)
    {
        if (rules.Common is < 0 or > 10000 || rules.Rare is < 0 or > 10000 || rules.Legendary is < 0 or > 10000 || rules.Total == 0)
            throw new InvalidDataException("Rarity weights must be from 0 to 10000 with a positive total.");
        var species = rules.SpeciesWeights ?? [];
        if (species.Count > WorldBestiary.All.Count || species.Any(p => WorldBestiary.Of(p.Key) is null || p.Value is < 0 or > 1000) ||
            WorldBestiary.All.All(s => species.GetValueOrDefault(s.MonsterId, 1) == 0))
            throw new InvalidDataException("Species weights must name world monsters, range from 0 to 1000 and leave at least one enabled.");
        return new(rules.Common, rules.Rare, rules.Legendary,
            species.Where(p => p.Value != 1).OrderBy(p => p.Key).ToDictionary());
    }
    private static void Fields(JsonElement value, params string[] names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Expected an object.");
        var actual = value.EnumerateObject().Select(p => p.Name).ToArray();
        if (actual.Length != names.Length || !actual.ToHashSet().SetEquals(names))
            throw new InvalidDataException("Define every policy field exactly once.");
    }
    public static Rules ParseRules(JsonElement value)
    {
        Fields(value, "common", "rare", "legendary", "speciesWeights");
        var species = value.GetProperty("speciesWeights");
        if (species.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Expected species weights.");
        var weights = new Dictionary<int, int>();
        foreach (var pair in species.EnumerateObject())
        {
            if (!int.TryParse(pair.Name, NumberStyles.None, CultureInfo.InvariantCulture, out int id) ||
                pair.Name != id.ToString(CultureInfo.InvariantCulture) || pair.Value.ValueKind != JsonValueKind.Number ||
                !pair.Value.TryGetInt32(out int weight) || !weights.TryAdd(id, weight))
                throw new InvalidDataException("Species weights must be unique integer identifiers and integer values.");
        }
        foreach (string name in new[] { "common", "rare", "legendary" })
            if (value.GetProperty(name).ValueKind != JsonValueKind.Number || !value.GetProperty(name).TryGetInt32(out _))
                throw new InvalidDataException("Category weights must be integers.");
        return Validate(new(value.GetProperty("common").GetInt32(), value.GetProperty("rare").GetInt32(),
            value.GetProperty("legendary").GetInt32(), weights));
    }
    public static Schedule Parse(byte[] bytes)
    {
        if (bytes.Length > 512 * 1024) throw new InvalidDataException("Spawn balance history is too large.");
        using var document = JsonDocument.Parse(bytes);
        var value = document.RootElement;
        Fields(value, "schemaVersion", "versions");
        if (value.GetProperty("schemaVersion").ValueKind != JsonValueKind.Number ||
            !value.GetProperty("schemaVersion").TryGetInt32(out int schema) || schema != 1 ||
            value.GetProperty("versions").ValueKind != JsonValueKind.Array ||
            value.GetProperty("versions").GetArrayLength() is < 1 or > MaximumVersions)
            throw new InvalidDataException("Invalid spawn balance history.");
        long previous = -1;
        var versions = new List<Version>();
        foreach (var version in value.GetProperty("versions").EnumerateArray())
        {
            Fields(version, "fromUnixSeconds", "rules");
            if (version.GetProperty("fromUnixSeconds").ValueKind != JsonValueKind.Number ||
                !version.GetProperty("fromUnixSeconds").TryGetInt64(out long from) || from <= previous || from > MaximumStart)
                throw new InvalidDataException("Spawn balance versions must have increasing nonnegative timestamps.");
            versions.Add(new(from, ParseRules(version.GetProperty("rules"))));
            previous = from;
        }
        return new(1, versions.ToArray());
    }
    public static Schedule Append(Schedule previous, Rules desired, long now, long firstBalancedGeneration)
    {
        desired = Validate(desired);
        if (now < 0 || now >= MaximumStart || firstBalancedGeneration < 0 || firstBalancedGeneration > MaximumStart)
            throw new InvalidDataException("Spawn balance activation is outside the supported timeline.");
        // Keep the predecessor of the oldest living generation and all newer versions.
        long oldest = now - WorldSpawns.LifetimeSeconds;
        var anchor = previous.Versions.LastOrDefault(v => v.FromUnixSeconds <= oldest);
        var retained = previous.Versions.Where(v => v == anchor || v.FromUnixSeconds > oldest).ToList();
        // A version that has not started can be replaced without changing any living generation.
        retained.RemoveAll(v => v.FromUnixSeconds > now);
        retained.Add(new(Math.Max(now + 1, firstBalancedGeneration), desired));
        if (retained.Count > MaximumVersions) throw new InvalidDataException("Too many recent balance changes; wait for earlier generations to expire.");
        return new(1, retained.ToArray());
    }
    private Schedule Load() => path is not null && File.Exists(path) ? Parse(File.ReadAllBytes(path)) : Default;
    public Schedule Read(bool refresh = false)
    {
        lock (gate)
        {
            if (path is null || !refresh && Environment.TickCount64 < nextCheck) return current;
            nextCheck = Environment.TickCount64 + 1000;
            try { current = Load(); }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            { log.LogWarning("Spawn balance reload refused; keeping last valid policy ({Reason})", e.GetType().Name); }
            return current;
        }
    }
}
