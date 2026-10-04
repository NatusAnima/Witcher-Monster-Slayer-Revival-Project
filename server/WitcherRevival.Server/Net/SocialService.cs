using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using WitcherRevival.Server.Protocol;
namespace WitcherRevival.Server.Net;

/// <summary>Original 1.1.116 friends wire formats with reconstructed limits and rewards.
/// A durable social intent plus a receipt in the one affected profile recovers a debit/grant after a crash.
/// Call outside registry/profile locks. Construction never calls the profile lookup delegate.</summary>
public sealed class SocialService : IDisposable
{
    public const string PackItems = "friend_packs";
    public const int PackId = 1;
    private const long MinimumId = 100_000_000_000, MaximumId = 999_999_999_999;
    private readonly object gate = new();
    private readonly string path;
    private readonly string lockPath;
    private FileStream? processLock;
    private readonly Func<string, LocalProfileStore> openStore;
    private readonly IConfiguration cfg;
    private readonly int limit, amount;
    private State state = new(1, new(), [], new(), new());
    private bool disposed;
    public sealed record Edge(string From, string To, bool Accepted, bool NoticeDelivered = false);
    public sealed record Gift(string Sender, string Receiver, string Receipt, int Day, int Pack, int Amount, bool Claimed);
    public sealed record Completed(string Hash, string Response);
    public sealed record Intent(string Actor, string Other, int Method, long RequestId, string Hash, Gift Gift);
    public sealed record State(int Version, Dictionary<string, long> Players, List<Edge> Edges,
        Dictionary<string, Gift> Gifts, Dictionary<string, Completed> Operations, Intent? Pending = null);

    public SocialService(IConfiguration cfg, string directory, Func<string, LocalProfileStore> openStore)
    {
        this.cfg = cfg; this.openStore = openStore;
        limit = cfg.GetValue("Social:FriendLimit", 100); amount = cfg.GetValue("Social:GiftIngredientAmount", 5);
        if (limit is < 1 or > 1000 || amount is < 1 or > 50 ||
            cfg.GetValue("Social:GiftEveryWins", 5) is < 0 or > 10000)
            throw new InvalidOperationException("Social limits or reward configuration is outside its supported range.");
        directory = LocalProfileStore.PrepareDirectory(directory);
        path = Path.Combine(directory, "social.json");
        lockPath = Path.Combine(directory, "social.lock");
    }
    // Idle servers can share the identity directory for existing synthetic profile-lock checks.
    // Once social state is used, exactly one process holds its lock until disposal.
    private void EnsureLoaded()
    {
        if (processLock is not null) return;
        var candidate = new FileStream(lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            var loaded = File.Exists(path) ? JsonSerializer.Deserialize<State>(File.ReadAllBytes(path))
                ?? throw new InvalidDataException("Empty social state.") : new(1, new(), [], new(), new());
            Validate(loaded); state = loaded; processLock = candidate;
        }
        catch { candidate.Dispose(); throw; }
    }
    private static void Validate(State s)
    {
        if (s.Version != 1 || s.Players is null || s.Edges is null || s.Gifts is null || s.Operations is null ||
            s.Players.Values.Any(id => id < MinimumId || id > MaximumId) || s.Players.Values.Distinct().Count() != s.Players.Count)
            throw new InvalidDataException("Invalid social state.");
        foreach (var id in s.Players.Keys) LocalProfileStore.CheckProfileId(id);
        bool Known(string id) => s.Players.ContainsKey(id);
        bool ValidGift(Gift g) => Known(g.Sender) && Known(g.Receiver) && g.Sender != g.Receiver &&
            g.Pack == PackId && g.Amount is >= 1 and <= 50 && g.Day >= 0 &&
            g.Receipt is { Length: > 0 and <= 128 } && !g.Receipt.Any(char.IsControl);
        if (s.Edges.Any(e => e.From == e.To || !Known(e.From) || !Known(e.To)) ||
            s.Edges.GroupBy(e => string.CompareOrdinal(e.From, e.To) < 0 ? Direction(e.From, e.To) : Direction(e.To, e.From)).Any(g => g.Count() > 1) ||
            s.Gifts.Any(kv => kv.Key != Direction(kv.Value.Sender, kv.Value.Receiver) || !ValidGift(kv.Value)) ||
            s.Pending is { } p && (!Known(p.Actor) || !Known(p.Other) || p.Method is not (106 or 107) ||
                !ValidGift(p.Gift) || p.Gift.Claimed || p.Actor != (p.Method == 106 ? p.Gift.Sender : p.Gift.Receiver) ||
                p.Other != (p.Method == 106 ? p.Gift.Receiver : p.Gift.Sender)))
            throw new InvalidDataException("Invalid social relations or journal.");
    }
    private State Copy() => JsonSerializer.Deserialize<State>(JsonSerializer.SerializeToUtf8Bytes(state))!;
    /// <summary>Operator counts only: never registers a player, acknowledges a notification or recovers a gift.</summary>
    public object OperatorSummary(string profile)
    {
        lock (gate)
        {
            try
            {
                var observed = state;
                if (processLock is null && File.Exists(path))
                {
                    using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
                    if (file.Length > 8 * 1024 * 1024) throw new InvalidDataException();
                    observed = JsonSerializer.Deserialize<State>(file) ?? throw new InvalidDataException();
                    Validate(observed);
                }
                var edges = observed.Edges.Where(e => e.From == profile || e.To == profile).ToArray();
                return new { status = "available", registered = observed.Players.ContainsKey(profile),
                    friends = edges.Count(e => e.Accepted), invitationsReceived = edges.Count(e => !e.Accepted && e.To == profile),
                    invitationsSent = edges.Count(e => !e.Accepted && e.From == profile),
                    unopenedGifts = observed.Gifts.Values.Count(g => g.Receiver == profile && !g.Claimed),
                    sentUnopenedGifts = observed.Gifts.Values.Count(g => g.Sender == profile && !g.Claimed),
                    recoveryPending = observed.Pending is { } p && (p.Actor == profile || p.Other == profile), friendLimit = limit };
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            { return new { status = "unavailable", reason = "Social state could not be inspected safely; no reconciliation was attempted." }; }
        }
    }
    private void Save(State next)
    {
        string temp = path + ".pending";
        try
        {
            using (var file = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temp, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                JsonSerializer.Serialize(file, next); file.Flush(true);
            }
            File.Move(temp, path, true); state = next;
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
    private int Day => checked((int)((cfg.GetValue<long?>("Social:FixedUnixTime") ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds()) / 86400));
    private static string Direction(string from, string to) => from + ":" + to;
    private static string OperationKey(string profile, long request) => profile + ":" + request;
    private static bool Between(Edge e, string a, string b) => e.From == a && e.To == b || e.From == b && e.To == a;
    private LocalProfileStore.PlayerState? Player(string id) => openStore(id).Snapshot().Player;
    private long Ensure(string profile)
    {
        if (state.Players.TryGetValue(profile, out long id)) return id;
        LocalProfileStore.CheckProfileId(profile);
        // Materialize a new authenticated reconstructed profile before publishing its public friend id.
        var own = openStore(profile);
        if (own.Snapshot() is { Revision: 0, Player: not null })
            own.UpdatePlayer(new Dictionary<int, int>(), null, p => p);
        // Only authenticated callers register. An arbitrary public id never creates a profile.
        long candidate;
        do { candidate = MinimumId + (long)(BitConverter.ToUInt64(RandomNumberGenerator.GetBytes(8)) % (ulong)(MaximumId - MinimumId + 1)); }
        while (state.Players.ContainsValue(candidate));
        var next = Copy(); next.Players.Add(profile, candidate); Save(next); return candidate;
    }
    public byte[] Friends(string profile)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            Recover(); long self = Ensure(profile);
            var edges = state.Edges.Where(e => e.From == profile || e.To == profile).ToList();
            var b = new ByteBuffer(); b.WriteLong(self); b.WriteInt(edges.Count);
            foreach (var edge in edges)
            {
                string other = edge.From == profile ? edge.To : edge.From; var p = Player(other);
                b.WriteLong(state.Players[other]); b.WriteInt(edge.Accepted ? 0 : edge.From == profile ? 1 : 2);
                b.WriteString(p?.Name ?? "Unnamed"); b.WriteByte(p?.Gender ?? 0); b.WriteInt(1);
                b.WriteInt(Reconstruction.LevelForExp(p?.Exp ?? 0));
                WriteGift(b, state.Gifts.GetValueOrDefault(Direction(profile, other)));
                WriteGift(b, state.Gifts.GetValueOrDefault(Direction(other, profile)));
            }
            b.WriteInt(0);
            // A full friend snapshot already tells the inviter which invitation was accepted.
            if (edges.Any(e => e.Accepted && e.From == profile && !e.NoticeDelivered))
            {
                var next = Copy();
                Save(next with { Edges = next.Edges.Select(e => e.Accepted && e.From == profile ? e with { NoticeDelivered = true } : e).ToList() });
            }
            return b.ToArray(); // No unsolicited inventory deltas.
        }
    }
    private static void WriteGift(ByteBuffer b, Gift? gift)
    { b.WriteInt(gift?.Day ?? 0); b.WriteInt(gift?.Pack ?? 0); b.WriteByte(gift is null || gift.Claimed ? (byte)1 : (byte)0); }
    public byte[] Notifications(string profile)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            Recover(); Ensure(profile); var b = new ByteBuffer(); b.WriteByte(1);
            WriteIds(b, state.Edges.Where(e => !e.Accepted && e.To == profile).Select(e => state.Players[e.From]));
            // The original callback shows a popup for every accepted id, so acknowledge this cosmetic notice once.
            var accepted = state.Edges.Where(e => e.Accepted && e.From == profile && !e.NoticeDelivered).ToList();
            WriteIds(b, accepted.Select(e => state.Players[e.To]));
            WriteIds(b, state.Gifts.Values.Where(g => g.Receiver == profile && !g.Claimed).Select(g => state.Players[g.Sender]));
            b.WriteInt(0);
            if (accepted.Count > 0)
            {
                var next = Copy();
                Save(next with { Edges = next.Edges.Select(e => accepted.Contains(e) ? e with { NoticeDelivered = true } : e).ToList() });
            }
            return b.ToArray();
        }
    }
    private static void WriteIds(ByteBuffer b, IEnumerable<long> values)
    { var ids = values.Distinct().Order().ToList(); b.WriteInt(ids.Count); foreach (long id in ids) b.WriteLong(id); }
    public byte[] Action(string profile, ApiProtocol.ApiRequest req)
    {
        if (req.Method is < 103 or > 108) throw new InvalidDataException("Unknown social action.");
        var r = new ByteBuffer(req.Data); int pack = req.Method == 106 ? r.ReadInt() : 0; long target = r.ReadLong();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Invalid social payload.");
        byte[] Refuse() => Reply(req.Method, false, target, pack);
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            Recover(); long self = Ensure(profile);
            string hash = Convert.ToHexString(SHA256.HashData(req.Data.Prepend((byte)req.Method).ToArray()));
            string key = OperationKey(profile, req.Id);
            if (state.Operations.TryGetValue(key, out var done))
                return done.Hash == hash ? Convert.FromBase64String(done.Response) : Refuse();
            string? other = state.Players.FirstOrDefault(pair => pair.Value == target).Key;
            if (target == self || other is null || Player(profile) is null || Player(other) is null) return Refuse();
            var edge = state.Edges.FirstOrDefault(e => Between(e, profile, other)); var next = Copy(); bool ok = false;
            switch (req.Method)
            {
                case 103:
                    if (edge is null && state.Edges.Count(e => e.From == profile || e.To == profile) < limit &&
                        state.Edges.Count(e => e.From == other || e.To == other) < limit)
                    { next.Edges.Add(new(profile, other, false)); ok = true; }
                    else if (edge is { Accepted: false }) ok = true; // Mutual request still needs explicit acceptance.
                    break;
                case 104:
                    if (edge is { Accepted: false } && edge.To == profile)
                    { next.Edges.Remove(edge); next.Edges.Add(edge with { Accepted = true }); ok = true; }
                    break;
                case 105:
                    if (edge is { Accepted: false } && edge.To == profile) { next.Edges.Remove(edge); ok = true; }
                    break;
                case 108:
                    if (edge is not null && !state.Gifts.Values.Any(g => !g.Claimed && Between(new(g.Sender, g.Receiver, true), profile, other)))
                    { next.Edges.Remove(edge); ok = true; }
                    break;
                case 106:
                    var previous = state.Gifts.GetValueOrDefault(Direction(profile, other));
                    if (edge is not { Accepted: true } || pack != PackId || previous is not null && (!previous.Claimed || previous.Day >= Day) ||
                        Player(profile)!.Items.GetValueOrDefault(PackItems)?.GetValueOrDefault(pack) is not > 0) return Refuse();
                    var gift = new Gift(profile, other, Guid.NewGuid().ToString("N"), Day, pack, amount, false);
                    Save(next with { Pending = new(profile, other, req.Method, req.Id, hash, gift) });
                    Recover(); return Convert.FromBase64String(state.Operations[key].Response);
                case 107:
                    var incoming = state.Gifts.GetValueOrDefault(Direction(other, profile));
                    if (edge is not { Accepted: true } || incoming is null || incoming.Claimed) return Refuse();
                    Save(next with { Pending = new(profile, other, req.Method, req.Id, hash, incoming) });
                    Recover(); return Convert.FromBase64String(state.Operations[key].Response);
            }
            if (!ok) return Refuse();
            byte[] response = Reply(req.Method, true, target, pack);
            next.Operations[key] = new(hash, Convert.ToBase64String(response)); Save(next); return response;
        }
    }
    /// <summary>Profile receipt and economy change share one atomic write; completed request ids are retained.</summary>
    private void Recover()
    {
        EnsureLoaded();
        if (state.Pending is not { } intent) return;
        string receipt = "social:" + intent.Method + ":" + intent.Gift.Receipt; bool ok = false;
        var store = openStore(intent.Actor);
        if (store.Snapshot().Player is not null)
            store.UpdatePlayer(new Dictionary<int, int>(), null, p =>
            {
                if (p.Granted.Contains(receipt)) { ok = true; return null; }
                string kind = intent.Method == 106 ? PackItems : ItemKinds.Ingredients;
                int id = intent.Method == 106 ? intent.Gift.Pack : 101;
                var items = p.Items.GetValueOrDefault(kind) ?? new Dictionary<int, int>(); int before = items.GetValueOrDefault(id);
                if (intent.Method == 106 && before < 1 || intent.Method == 107 &&
                    (before > int.MaxValue - intent.Gift.Amount || SocialPolicy.Occupied(p) + intent.Gift.Amount > SocialPolicy.BagCapacity)) return null;
                int after = intent.Method == 106 ? before - 1 : before + intent.Gift.Amount; p.Items[kind] = items;
                if (after == 0) items.Remove(id); else items[id] = after;
                p.Granted.Add(receipt); ok = true; return p;
            });
        var next = Copy() with { Pending = null };
        if (ok) next.Gifts[Direction(intent.Gift.Sender, intent.Gift.Receiver)] = intent.Gift with { Claimed = intent.Method == 107 };
        byte[] response = Reply(intent.Method, ok, state.Players[intent.Other], intent.Gift.Pack, intent.Gift.Amount);
        next.Operations[OperationKey(intent.Actor, intent.RequestId)] = new(intent.Hash, Convert.ToBase64String(response)); Save(next);
    }
    public static byte[] Refusal(ApiProtocol.ApiRequest req)
    {
        if (req.Method is < 103 or > 108) throw new ArgumentOutOfRangeException(nameof(req));
        int offset = req.Method == 106 ? 4 : 0;
        int pack = offset == 4 && req.Data.Length >= 4 ? BinaryPrimitives.ReadInt32BigEndian(req.Data) : 0;
        long target = req.Data.Length >= offset + 8 ? BinaryPrimitives.ReadInt64BigEndian(req.Data.AsSpan(offset)) : 0;
        return Reply(req.Method, false, target, pack);
    }

    private static byte[] Reply(int method, bool ok, long other, int pack, int reward = 0)
    {
        var b = new ByteBuffer(); b.WriteByte(ok ? (byte)1 : (byte)0); if (method == 106) b.WriteInt(pack); b.WriteLong(other);
        if (method == 107) { b.WriteInt(ok ? 1 : 0); b.WriteInt(ok ? 101 : 0); b.WriteInt(ok ? reward : 0); } return b.ToArray();
    }
    /// <summary>Administrative callers enter here BEFORE the registry lock. Complete any prepared gift first;
    /// then existing revision checks detect that change before reset/copy/restore. Keeps lock order uniform.</summary>
    public T WithProfileAdministration<T>(Func<T> change)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            Recover();
            return change();
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            processLock?.Dispose();
        }
    }
}
