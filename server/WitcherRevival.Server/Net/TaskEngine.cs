using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>Task progress joins the same profile revision as the action that earned it.</summary>
public sealed class TaskEngine(TaskCatalog catalog, TimeProvider clock, IConfiguration configuration)
{
    public sealed record Entry(TaskCatalog.Definition Definition, int Progress = 0, bool Claimed = false, int[]? Samples = null);
    public sealed record EventState(int Id, List<Entry> Tasks, bool Claimed = false);
    public sealed record Receipt(string Fingerprint, byte[] Response);
    public sealed record State(int Day, List<Entry> Daily, int Issued, List<int> Seen, bool Reshuffled,
        List<int> Stamps, int LastStamp, int HuntClaims, Dictionary<int, EventState> Events,
        Dictionary<int, int> Achievements, Dictionary<string, Receipt> Receipts, long LastTime = 0, long NestsCleared = 0,
        Dictionary<int, Entry>? TrophyProgress = null);
    /// <summary>Only accepted crafting/preparation/combat operations supply extra details. Kills, herbs,
    /// level-ups, skills and story progress are derived from the actual atomic profile transition.</summary>
    public sealed record Action(int Method, int[][]? Combat = null);

    // Explicit, process-wide test clock. Unset on the LAB deployment; never follows the story clock.
    private readonly long? fixedTime = TestTime(configuration);
    public long Now => fixedTime ?? clock.GetUtcNow().ToUnixTimeSeconds();
    private static long? TestTime(IConfiguration cfg)
    {
        long? value = cfg.GetValue<long?>("Tasks:FixedUnixTime");
        if (value is < 0 or > int.MaxValue) throw new InvalidDataException("Tasks:FixedUnixTime must fit signed Unix seconds.");
        return value;
    }
    public TaskCatalog.Catalog? Catalog => catalog.Current;
    public static State Copy(State s) => s with
    {
        Daily = s.Daily.ToList(), Seen = s.Seen.ToList(), Stamps = s.Stamps.ToList(),
        Events = s.Events.ToDictionary(p => p.Key, p => p.Value with { Tasks = p.Value.Tasks.ToList() }),
        Achievements = new(s.Achievements), Receipts = new(s.Receipts),
        TrophyProgress = new(s.TrophyProgress ?? []),
    };

    public State Refresh(LocalProfileStore.PlayerState p, TaskCatalog.Catalog c, long now)
    {
        now = Math.Max(now, p.Tasks?.LastTime ?? 0);
        int day = checked((int)(now / 86400));
        var s = p.Tasks is null ? new State(day, [], 0, [], false, [], -1, 0, [], [], []) : Copy(p.Tasks);
        // A clock correction cannot reopen yesterday's issuance, reroll or hunt reward.
        day = Math.Max(day, s.Day);
        if (day > s.Day)
            s = s with { Day = day, Issued = 0, Seen = s.Daily.Select(e => e.Definition.Id).ToList(), Reshuffled = false };
        if (c.Hunt.Streak && s.LastStamp >= 0 && day > s.LastStamp + 1)
            s.Stamps.Clear();
        foreach (var e in c.Timed.Events.Where(e => now >= e.Start && now <= e.End))
            if (!s.Events.ContainsKey(e.Id)) s.Events[e.Id] = new(e.Id, e.Tasks.Select(d => NewEntry(d, p)).ToList());
        s = s with { Daily = s.Daily.Select(e => RefreshWindow(e, now)).ToList(), TrophyProgress = s.TrophyProgress ?? [] };
        foreach (var e in s.Events.Values.ToArray())
            s.Events[e.Id] = e with { Tasks = e.Tasks.Select(t => RefreshWindow(t, now)).ToList() };
        foreach (var d in c.Trinkets.Trinkets.Where(d => d.WindowSeconds > 0))
            s.TrophyProgress[d.Id] = RefreshWindow(s.TrophyProgress.GetValueOrDefault(d.Id) ?? NewEntry(d, p), now);
        Unlock(s, c, p, now);
        return s with { LastTime = now };
    }

    public LocalProfileStore.PlayerState Transition(LocalProfileStore.Profile before, LocalProfileStore.PlayerState after, Action? action)
    {
        if (Catalog is not { } c || before.Player is not { } prior) return after;
        long now = Math.Max(Now, after.Tasks?.LastTime ?? 0);
        var s = Refresh(after, c, now);
        s = s with { NestsCleared = checked(s.NestsCleared + NestGain(prior, after)) };
        foreach (var d in c.Trinkets.Trinkets.Where(d => d.WindowSeconds > 0))
            s.TrophyProgress![d.Id] = Advance(s.TrophyProgress[d.Id], prior, after, action, now);
        Unlock(s, c, after, now);
        // DailyQuestProgress.IsTrackingEnabled 0x1A02D0C requires fact3 exactly1.
        bool tracking = before.Facts.GetValueOrDefault(3) == 1;
        if (tracking) s = s with { Daily = s.Daily.Select(e => Advance(e, prior, after, action, now)).ToList() };
        foreach (var e in c.Timed.Events.Where(e => tracking && now >= e.Start && now <= e.End))
        {
            var state = s.Events[e.Id];
            s.Events[e.Id] = state with { Tasks = state.Tasks.Select(t => Advance(t, prior, after, action, now)).ToList() };
        }
        // The client increments locally on a won map/nest fight. RPC94 reconciles it after reconnect;
        // sending RPC96 for that same fight would increment it twice (callback ignores its payload).
        if (before.Facts.GetValueOrDefault(3) != 0 && action?.Method is 8 or 53 or 114 &&
            PositiveKills(prior, after).Any() && s.LastStamp < s.Day && s.Stamps.Count < c.Hunt.Size)
        {
            s.Stamps.Add(s.Day);
            s = s with { LastStamp = s.Day };
        }
        return after with { Tasks = s };
    }

    public State Issue(LocalProfileStore.PlayerState p, string profile, TaskCatalog.Catalog c, State s)
    {
        // RPC21 also runs at midnight and after remove. Existing unfinished slots stay on both sides;
        // removal/claim never replenishes today's allowance.
        while (s.Daily.Count < 3 && s.Issued < 3)
        {
            var d = Draw(p, profile, c, s, "issue");
            if (d is null) break;
            s.Daily.Add(NewEntry(d, p)); s.Seen.Add(d.Id); s = s with { Issued = s.Issued + 1 };
        }
        return s;
    }

    public static TaskCatalog.Definition? Draw(LocalProfileStore.PlayerState p, string profile, TaskCatalog.Catalog c, State s, string purpose)
    {
        var pool = c.Daily.Tasks.Where(d => d.Weight > 0 && d.MinLevel <= Reconstruction.LevelForExp(p.Exp) &&
            !s.Seen.Contains(d.Id) && !s.Daily.Any(e => e.Definition.Id == d.Id)).OrderBy(d => d.Id).ToArray();
        if (pool.Length == 0) return null;
        byte[] seed = SHA256.HashData(Encoding.UTF8.GetBytes($"{profile}:{s.Day}:{purpose}:{s.Issued}:{string.Join(',', s.Seen.Order())}"));
        uint pick = System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(seed) % (uint)pool.Sum(d => d.Weight);
        foreach (var d in pool) { if (pick < d.Weight) return d; pick -= (uint)d.Weight; }
        throw new InvalidOperationException("Task draw exhausted its validated pool.");
    }

    public static int Required(TaskCatalog.Definition d) => d.Target;
    public static Entry NewEntry(TaskCatalog.Definition d, LocalProfileStore.PlayerState p) =>
        new(d, d.Type == 7 ? Math.Min(d.Target, Reconstruction.LevelForExp(p.Exp)) : 0);
    public static int[] WireProgress(Entry e) => e.Definition.Type switch
    {
        1 => e.Samples ?? new int[e.Definition.Target],
        11 => e.Samples ?? new int[Math.Max(1, e.Definition.Fights)],
        _ => [e.Progress],
    };
    public static bool Complete(Entry e) => e.Progress >= Required(e.Definition);

    private static Entry RefreshWindow(Entry e, long now)
    {
        if (e.Definition.WindowSeconds <= 0 || Complete(e) || e.Claimed) return e;
        // Native UpdateProgress keeps timestamps even when their visible contribution expires.
        // A final kill exactly one limit after the oldest may still complete (max-min <= limit).
        var times = (e.Samples ?? []).Where(t => t > 0).TakeLast(e.Definition.Target).ToArray();
        int current = times.Count(t => now < (long)t + e.Definition.WindowSeconds);
        bool completed = times.Length == e.Definition.Target &&
            (long)times.Max() - times.Min() <= e.Definition.WindowSeconds;
        var values = new int[e.Definition.Target]; times.CopyTo(values, 0);
        return e with { Progress = completed ? e.Definition.Target : current, Samples = values };
    }

    private static Entry Advance(Entry e, LocalProfileStore.PlayerState a, LocalProfileStore.PlayerState b, Action? action, long now)
    {
        if (e.Claimed || Complete(e)) return e; // The client latches completion before later fights.
        e = RefreshWindow(e, now);
        var d = e.Definition;
        if (d.Type == 7) return e with { Progress = Math.Min(d.Target, Reconstruction.LevelForExp(b.Exp)) };
        if (d.Type == 11)
        {
            var values = WireProgress(e).ToArray();
            foreach (var details in action?.Combat ?? [])
            {
                int amount = (int)Math.Min(d.Target, (d.Actions ?? []).Sum(i => (i < details.Length ? (long)details[i] : 0) +
                    (action?.Method == 53 && i == 2 && details.Length > 11 ? details[11] : 0)));
                if (d.Fights > 0)
                { Array.Copy(values, 1, values, 0, values.Length - 1); values[^1] = amount; }
                else values[0] = (int)Math.Min(d.Target, (long)values[0] + amount);
                if (values.Sum(i => (long)i) >= d.Target) break;
            }
            return e with { Samples = values, Progress = (int)Math.Min(d.Target, values.Sum(i => (long)i)) };
        }
        int gain = Delta(d, a, b, action);
        int progress = (int)Math.Min(d.Target, (long)e.Progress + gain);
        if (d.Type == 1 && gain > 0)
        {
            if (d.WindowSeconds > 0)
            {
                var history = WireProgress(e).Where(t => t > 0)
                    .Concat(Enumerable.Repeat(checked((int)now), Math.Min(gain, d.Target))).TakeLast(d.Target).ToArray();
                var ring = new int[d.Target]; history.CopyTo(ring, 0);
                return RefreshWindow(e with { Samples = ring }, now);
            }
            var values = WireProgress(e).ToArray();
            for (int i = e.Progress; i < progress; i++) values[i] = checked((int)now);
            return e with { Samples = values, Progress = progress };
        }
        return e with { Progress = progress };
    }

    private static IEnumerable<(int Id, int Count)> PositiveKills(LocalProfileStore.PlayerState a, LocalProfileStore.PlayerState b) =>
        (b.Kills ?? []).Select(p => (p.Key, p.Value - (a.Kills?.GetValueOrDefault(p.Key) ?? 0))).Where(p => p.Item2 > 0);
    private static bool Matches(int[]? ids, int id) => ids is not { Length: > 0 } || ids.Contains(id);
    private static int NestGain(LocalProfileStore.PlayerState a, LocalProfileStore.PlayerState b) =>
        Math.Max(0, (b.Nests?.Wins ?? 0) - (a.Nests?.Day == b.Nests?.Day ? a.Nests?.Wins ?? 0 : 0));
    private static void Unlock(State s, TaskCatalog.Catalog c, LocalProfileStore.PlayerState p, long now)
    {
        foreach (var d in c.Trinkets.Trinkets)
            if (!s.Achievements.ContainsKey(d.Id) &&
                (d.WindowSeconds > 0 ? s.TrophyProgress?.GetValueOrDefault(d.Id)?.Progress ?? 0 :
                 d.Type == 2 ? s.NestsCleared : LifetimeProgress(d, p)) >= Required(d))
                s.Achievements[d.Id] = checked((int)now);
    }
    private static int LifetimeProgress(TaskCatalog.Definition d, LocalProfileStore.PlayerState p) => d.Type switch
    {
        1 => (p.Kills ?? []).Where(k => Matches(d.Monsters, k.Key)).Sum(k => k.Value),
        3 => p.Distance?.Metres ?? 0,
        7 => Reconstruction.LevelForExp(p.Exp),
        8 => p.Skills.Count,
        9 => (p.Story?.Finished ?? []).Count(id => Matches(d.Quests, id)),
        13 => (p.Story?.Outputs ?? []).Count(id => Matches(d.Outputs, id)),
        _ => 0,
    };

    private static int Delta(TaskCatalog.Definition d, LocalProfileStore.PlayerState a, LocalProfileStore.PlayerState b, Action? action)
    {
        switch (d.Type)
        {
            case 1: return PositiveKills(a, b).Where(k => Matches(d.Monsters, k.Id)).Sum(k => k.Count);
            case 2: return NestGain(a, b);
            case 3: return Math.Max(0, (b.Distance?.Metres ?? 0) - (a.Distance?.Metres ?? 0));
            case 4: return action?.Method is 39 or 53 ? ItemGain(b, a, ItemKinds.Bombs, d.Items) : 0;
            case 6:
                if (action?.Method != 68) return 0;
                return ItemGain(a, b, Economy.KindOf(d.ItemType)!, d.Items);
            case 7: return Math.Max(0, Reconstruction.LevelForExp(b.Exp) - Reconstruction.LevelForExp(a.Exp));
            case 8: return b.Skills.Except(a.Skills).Count();
            case 9: return (b.Story?.Finished ?? []).Except(a.Story?.Finished ?? []).Count(id => Matches(d.Quests, id));
            case 10:
                if (action?.Method is not (10 or 89)) return 0;
                return ItemGain(b, a, Economy.KindOf(d.ItemType)!, d.Items);
            case 11:
                return (action?.Combat ?? []).Sum(details =>
                {
                    int actions = (d.Actions ?? []).Sum(i => i < details.Length ? details[i] : 0);
                    return d.Fights > 0 ? actions >= d.Target ? 1 : 0 : actions;
                });
            case 12:
                return action?.Method == 19 ? ItemGain(a, b, ItemKinds.Ingredients, d.Items) : 0;
            default: return 0;
        }
    }

    private static int ItemGain(LocalProfileStore.PlayerState a, LocalProfileStore.PlayerState b, string kind, int[]? ids) =>
        (b.Items.GetValueOrDefault(kind) ?? []).Where(p => Matches(ids, p.Key))
            .Sum(p => Math.Max(0, p.Value - (a.Items.GetValueOrDefault(kind)?.GetValueOrDefault(p.Key) ?? 0)));

    public static LocalProfileStore.PlayerState Reward(LocalProfileStore.PlayerState p, int gold, IEnumerable<TaskCatalog.Reward> rewards)
    {
        p = p with { Gold = checked(p.Gold + gold) };
        foreach (var r in rewards)
        {
            string kind = r.Type == 16 ? "summoning_scrolls" : Economy.KindOf(r.Type)!;
            if (!p.Items.TryGetValue(kind, out var items)) p.Items[kind] = items = [];
            items[r.Item] = checked(items.GetValueOrDefault(r.Item) + r.Amount);
        }
        return p;
    }
}
