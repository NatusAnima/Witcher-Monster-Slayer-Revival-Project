using System.Security.Cryptography;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    private readonly object auraGate = new();
    // Geometry already included in RPC40, bounded by the current 64-cell area and 24 points/cell.
    // The client chooses the final summon position around this validated anchor (0x18FD7EC).
    private readonly Dictionary<ulong, (long Epoch, PlayableLocations.Cell Cell)> auraPlaces = new();
    private const double AuraAnchorRadiusMetres = 250;
    private const double AuraCoordinateScale = 100000; // native constant at 0x36E7AB8

    private static bool IsAuraRequest(ApiProtocol.ApiRequest req) => req.Method == M_SummonLocalMonsters &&
        req.Data.Length >= 4 && System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(req.Data) == 13;

    private void RememberAuraPlaces(IReadOnlyList<PlayableLocations.Cell> cells, long now)
    {
        var area = playable.Area.ToHashSet();
        long epoch = WorldSpawns.PlacesEpoch(now);
        lock (auraGate)
        {
            foreach (ulong id in auraPlaces.Where(p => !area.Contains(p.Key) || p.Value.Epoch != epoch).Select(p => p.Key).ToArray())
                auraPlaces.Remove(id);
            foreach (var cell in cells.Where(c => area.Contains(c.Id)))
                auraPlaces[cell.Id] = (epoch, cell with { Places = cell.Places.Take(24).ToArray() });
        }
    }

    private byte[] GetLastAuraUsage(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 0) throw new InvalidDataException("Aura timestamp request has no fields.");
        return BuildIntResponse(true, profiles.Snapshot().Player?.Aura?.At ?? 0);
    }

    private byte[] SummonWitcherAura(long requestId, int skillId, int longitude, int latitude)
    {
        // SummonLocalMonstersResponse failure has only its Result byte (Factory 0x1E796D8).
        byte[] Refused() => ApiProtocol.Boolean(false);
        byte[] Accepted(SummonedMonsters.Group group)
        { var b = new ByteBuffer(); b.WriteByte(1); b.WriteInt(1); WriteSummonedGroup(b, group); return b.ToArray(); }
        if (skillId != 29 || Math.Abs((long)longitude) > 180 * AuraCoordinateScale ||
            Math.Abs((long)latitude) > 90 * AuraCoordinateScale) return Refused();
        lock (auraGate)
        {
            int now = UnixSeconds();
            var p = profiles.Snapshot().Player;
            if (p is null || !p.Skills.Contains(29)) return Refused();
            if (p.Aura is { } prior)
            {
                if (prior.RequestId == requestId)
                {
                    if (prior.Longitude != longitude || prior.Latitude != latitude) return Refused();
                    var saved = summons.Active(now).FirstOrDefault(g => g.ItemType == 13 && g.ItemId == 29);
                    return saved is null ? Refused() : Accepted(saved);
                }
                if ((long)now - prior.At <= skillBalance.WitcherAuraIntervalSeconds) return Refused();
            }
            double lat = latitude / AuraCoordinateScale, lng = longitude / AuraCoordinateScale;
            var area = playable.Area.ToHashSet();
            var anchor = auraPlaces.Where(c => area.Contains(c.Key) && c.Value.Epoch == WorldSpawns.PlacesEpoch(now))
                .SelectMany(c => c.Value.Cell.Places.Select(place => (Cell: c.Value.Cell, Place: place)))
                .Where(p => double.IsFinite(p.Place.Lat) && double.IsFinite(p.Place.Lng) &&
                    Math.Abs(p.Place.Lat) <= 90 && Math.Abs(p.Place.Lng) <= 180)
                .Select(p => (p.Cell, p.Place, Distance: PlayableLocations.Distance(lat, lng, p.Place.Lat, p.Place.Lng)))
                .Where(p => p.Distance <= AuraAnchorRadiusMetres)
                .OrderBy(p => p.Distance).ThenBy(p => p.Place.Id, StringComparer.Ordinal).FirstOrDefault();
            if (anchor.Place is null) return Refused();
            int level = Reconstruction.LevelForExp(p.Exp);
            var sky = WorldSpawns.Sky(anchor.Place.Lat, anchor.Place.Lng, DateTimeOffset.FromUnixTimeSeconds(now),
                weather.ForGeneration(anchor.Cell.Id, anchor.Cell.Lat, anchor.Cell.Lng, now / WorldSpawns.LifetimeSeconds));
            var choices = WorldBestiary.All.Where(s => WorldSpawns.MinPlayerLevel(s) <= level &&
                WorldSpawns.Fits(s, anchor.Place.Biomes, sky)).ToArray();
            if (choices.Length == 0) return Refused();
            int roll = RandomNumberGenerator.GetInt32(choices.Sum(s => WorldSpawns.WeightUnder(s, sky)));
            var species = choices.First(s => (roll -= WorldSpawns.WeightUnder(s, sky)) < 0);
            var group = summons.TrySummonAura(now, skillBalance.WitcherAuraLifetimeSeconds,
                checked((int)Math.Round(anchor.Place.Lng * AuraCoordinateScale)),
                checked((int)Math.Round(anchor.Place.Lat * AuraCoordinateScale)),
                (species.MonsterId, species.Difficulty), (created, groups) =>
                {
                    bool accepted = false;
                    profiles.UpdatePlayer(new Dictionary<int, int>(), null, current =>
                    {
                        if (!current.Skills.Contains(29) || current.Aura is { } previous &&
                            (previous.RequestId == requestId || (long)now - previous.At <= skillBalance.WitcherAuraIntervalSeconds))
                            return null;
                        accepted = true;
                        return current with { Summons = groups.ToList(), Aura = new(now, requestId, longitude, latitude) };
                    });
                    return accepted;
                });
            return group is null ? Refused() : Accepted(group);
        }
    }
}
