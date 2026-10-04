using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

/// <summary>Bounded, in-memory views of maps actually sent to clients. Reading these never generates a world,
/// reveals monsters or reads the player's GPS. Coordinates belong to the delivered places, not the device.</summary>
public static class MapObservation
{
    public const int StaleAfterSeconds = 120, RetentionSeconds = 3600, MaximumProfiles = 32;
    public sealed record Cell(string Id, double? Lat, double? Lng, int Places);
    public sealed record Point(string Id, string Kind, double Lat, double Lng, string PlaceId, string Name,
        int? MonsterId = null, int? Rarity = null, int? Skulls = null, DateTimeOffset? ExpiresAt = null);
    public sealed record Snapshot(DateTimeOffset ObservedAt, Cell[] Cells, Point[] Points,
        int Places, int Monsters, int Herbs, int Nests, int Quests, bool Truncated);
    private static readonly object Gate = new();
    private static readonly Dictionary<string, Snapshot> Latest = new();

    public static Snapshot Create(IReadOnlyList<PlayableLocations.Cell> cells, IReadOnlyList<WorldSpawns.Spawn> monsters,
        IReadOnlyList<WorldHerbs.Herb> herbs, IReadOnlyList<WorldNests.Nest> nests, IEnumerable<Point> quests)
    {
        var places = cells.SelectMany(c => c.Places).DistinctBy(p => p.Id).ToDictionary(p => p.Id);
        var points = new List<Point>();
        foreach (var monster in monsters)
            if (places.TryGetValue(monster.PlaceId, out var p))
            {
                var species = WorldBestiary.Of(monster.MonsterId);
                points.Add(new(monster.InstanceId.ToString(), "monster", (float)p.Lat, (float)p.Lng, p.Id,
                    species?.Name ?? $"Monster {monster.MonsterId}", monster.MonsterId, species?.Rarity, species?.Skulls,
                    DateTimeOffset.FromUnixTimeMilliseconds(monster.SpawnTimeMs).AddSeconds(monster.Ttl)));
            }
        foreach (var herb in herbs)
            if (places.TryGetValue(herb.PlaceId, out var p))
                points.Add(new(herb.InstanceId.ToString(), "herb", (float)p.Lat, (float)p.Lng, p.Id, $"Herb {herb.Type}"));
        foreach (var nest in nests)
            if (places.TryGetValue(nest.PlaceId, out var p))
                points.Add(new(nest.InstanceId.ToString(), "nest", (float)p.Lat, (float)p.Lng, p.Id, "Nemeton"));
        var questPoints = quests.ToArray(); points.AddRange(questPoints);
        return new(DateTimeOffset.UtcNow, cells.Take(64).Select(c =>
            new Cell(c.Id.ToString(), c.Lat, c.Lng, c.Places.Count)).ToArray(), points.Take(4096).ToArray(),
            places.Count, monsters.Count, herbs.Count, nests.Count, questPoints.Length, cells.Count > 64 || points.Count > 4096);
    }

    public static void Record(string profile, Snapshot snapshot)
    {
        if (snapshot.Cells.Length == 0) return; // RPC40 is a delta; empty deltas must not erase a useful observation.
        lock (Gate)
        {
            Prune();
            if (!Latest.ContainsKey(profile) && Latest.Count >= MaximumProfiles)
                Latest.Remove(Latest.MinBy(p => p.Value.ObservedAt).Key);
            Latest[profile] = snapshot with { ObservedAt = DateTimeOffset.UtcNow };
        }
    }

    private static void Prune()
    {
        var oldest = DateTimeOffset.UtcNow.AddSeconds(-RetentionSeconds);
        foreach (var profile in Latest.Where(p => p.Value.ObservedAt < oldest).Select(p => p.Key).ToArray()) Latest.Remove(profile);
    }

    public static void Forget(string profile) { lock (Gate) Latest.Remove(profile); }

    public static string[] CellIds(string profile)
    {
        lock (Gate)
        {
            Prune();
            return Latest.TryGetValue(profile, out var value) ? value.Cells.Select(c => c.Id).ToArray() : [];
        }
    }

    public static object Read(string profile)
    {
        lock (Gate)
        {
            bool expired = Latest.TryGetValue(profile, out var previous) &&
                previous.ObservedAt < DateTimeOffset.UtcNow.AddSeconds(-RetentionSeconds);
            Prune(); Latest.TryGetValue(profile, out var value);
            double? age = value is null ? null : Math.Max(0, (DateTimeOffset.UtcNow - value.ObservedAt).TotalSeconds);
            return new { scope = "last-client-map-response", profile, source = "RPC 40", observedAt = value?.ObservedAt,
                ageSeconds = age, staleAfterSeconds = StaleAfterSeconds, retentionSeconds = RetentionSeconds,
                status = value is null ? "empty" : age > StaleAfterSeconds ? "stale" : "ready",
                emptyReason = value is null ? expired ? "expired" : "not-retained" : null,
                coverage = "Last non-empty cell response sent to this profile, not its complete loaded map or current visible screen.",
                cells = value?.Cells ?? [], points = value?.Points ?? [],
                truncated = value?.Truncated ?? false,
                counts = new { cells = value?.Cells.Length ?? 0, places = value?.Places ?? 0, monsters = value?.Monsters ?? 0,
                    herbs = value?.Herbs ?? 0, nests = value?.Nests ?? 0, quests = value?.Quests ?? 0 },
                warnings = new[] { "May include encounters subsequently defeated or expired. RPC 87 successors and personal summons are not included.",
                    "Only the latest response is retained for at most one hour and 32 profiles; restart clears observations. An empty observation is not proof of an empty world." } };
        }
    }
}
