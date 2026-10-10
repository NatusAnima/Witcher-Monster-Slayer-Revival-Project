using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace WitcherRevival.Server.Net;

/// <summary>Operator-authored task data. An absent Tasks:Directory leaves the legacy fixtures intact.</summary>
public sealed class TaskCatalog : IDisposable
{
    public sealed record Reward(int Type, int Item, int Amount);
    public sealed record Definition(int Id, string Slug, int Type, int Target, int Gold = 0,
        int MinLevel = 1, int Weight = 1, int ItemType = 0, int Fights = 0,
        int[]? Monsters = null, int[]? Items = null, int[]? Actions = null,
        int[]? Quests = null, int[]? Outputs = null, Reward[]? Rewards = null,
        string Evidence = "Authored", int WindowSeconds = 0);
    public sealed record DailyFile(int SchemaVersion, Definition[] Tasks);
    public sealed record HuntFile(int SchemaVersion, int Size, bool Streak, int RewardId, Reward Reward);
    public sealed record Event(int Id, string Name, long Start, long End, int Gold, Definition[] Tasks, Reward[] Rewards);
    public sealed record TimedFile(int SchemaVersion, Event[] Events);
    public sealed record TrinketsFile(int SchemaVersion, Definition[] Trinkets);
    public sealed record Catalog(DailyFile Daily, HuntFile Hunt, TimedFile Timed, TrinketsFile Trinkets)
    {
        [JsonIgnore] public IEnumerable<Definition> AllTasks => Daily.Tasks.Concat(Timed.Events.SelectMany(e => e.Tasks));
        [JsonIgnore] public IEnumerable<Definition> All => AllTasks.Concat(Trinkets.Trinkets);
    }

    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = true,
    };
    private readonly string? directory;
    private readonly ILogger<TaskCatalog> log;
    private readonly object gate = new();
    private Catalog? current;
    private string? lastBytes;
    private string? wireIdentity;
    private DateTime nextCheck;
    private FileStream? manifestLock;
    public bool Enabled => directory is not null;
    public TaskCatalog(IConfiguration cfg, ILogger<TaskCatalog> log)
    {
        this.log = log;
        directory = cfg["Tasks:Directory"];
        if (directory is not null)
        {
            directory = Path.GetFullPath(directory);
            current = Read(); // Invalid initial data fails before profiles/identity storage are opened.
            wireIdentity = WireIdentity(current);
            PreserveCatalogue(cfg["LocalProfile:DataDirectory"] ?? "data/profiles", current);
        }
    }

    private void PreserveCatalogue(string dataDirectory, Catalog candidate)
    {
        string root = LocalProfileStore.PrepareDirectory(dataDirectory);
        string path = Path.Combine(root, "tasks-catalogue.json");
        manifestLock = new FileStream(Path.Combine(root, "tasks-catalogue.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            if (File.Exists(path))
            {
                if (new FileInfo(path).Length > 4 * 1024 * 1024) throw new InvalidDataException("Task catalogue manifest is too large.");
                var previous = JsonSerializer.Deserialize<Catalog>(File.ReadAllBytes(path), Json)
                    ?? throw new InvalidDataException("Empty task catalogue manifest.");
                Validate(previous);
                // Existing IDs describe immutable contracts/rewards. New IDs may be appended after a coordinated
                // restart. This keeps old profile entries, event claims and achievements resolvable indefinitely.
                Definition Stable(Definition d) => d with { Weight = 1, MinLevel = 1 };
                bool Keeps(Definition[] old, Definition[] next) => old.All(d => next.Any(n => n.Id == d.Id &&
                    JsonSerializer.Serialize(Stable(n), Json) == JsonSerializer.Serialize(Stable(d), Json)));
                if (!Keeps(previous.Daily.Tasks, candidate.Daily.Tasks) || !Keeps(previous.Trinkets.Trinkets, candidate.Trinkets.Trinkets) ||
                    previous.Timed.Events.Any(e => !candidate.Timed.Events.Any(n => JsonSerializer.Serialize(n, Json) == JsonSerializer.Serialize(e, Json))) ||
                    JsonSerializer.Serialize(previous.Hunt with { Streak = true }, Json) != JsonSerializer.Serialize(candidate.Hunt with { Streak = true }, Json))
                    throw new InvalidDataException("Task catalogue cannot remove or redefine persisted IDs; use new IDs and retain old records.");
            }
            string pending = path + ".pending";
            try
            {
                using (var file = new FileStream(pending, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(pending, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                    JsonSerializer.Serialize(file, candidate, Json); file.Flush(flushToDisk: true);
                }
                File.Move(pending, path, overwrite: true);
            }
            finally { if (File.Exists(pending)) File.Delete(pending); }
        }
        catch { manifestLock.Dispose(); manifestLock = null; throw; }
    }

    public void Dispose() => manifestLock?.Dispose();

    public Catalog? Current
    {
        get
        {
            if (!Enabled) return null;
            lock (gate)
            {
                if (DateTime.UtcNow < nextCheck) return current;
                nextCheck = DateTime.UtcNow.AddSeconds(1);
                try
                {
                    var candidate = Read();
                    // A running client does not reload its static catalogue. Live edits may change draw weights,
                    // level gates and the missed-day policy, but never its IDs, text, targets, dates or rewards.
                    if (WireIdentity(candidate) != wireIdentity)
                        throw new InvalidDataException("Task static catalogue changes require a server and client restart.");
                    current = candidate;
                }
                catch (Exception ex) when (ex is IOException or JsonException or InvalidDataException or ArgumentException)
                { log.LogWarning("Task catalogue reload refused; keeping last valid version ({Reason})", ex.GetType().Name); }
                return current;
            }
        }
    }

    private Catalog Read()
    {
        string[] names = ["daily.json", "hunt.json", "timed.json", "trinkets.json"];
        var data = names.Select(n =>
        {
            var path = Path.Combine(directory!, n);
            if (new FileInfo(path).Length > 1024 * 1024) throw new InvalidDataException("Task file exceeds 1 MiB.");
            return File.ReadAllText(path);
        }).ToArray();
        string hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\0', data))));
        if (hash == lastBytes && current is not null) return current;
        T Parse<T>(int i) => JsonSerializer.Deserialize<T>(data[i], Json) ?? throw new InvalidDataException("Empty task file.");
        var candidate = new Catalog(Parse<DailyFile>(0), Parse<HuntFile>(1), Parse<TimedFile>(2), Parse<TrinketsFile>(3));
        Validate(candidate);
        lastBytes = hash;
        return candidate;
    }

    private static string WireIdentity(Catalog c) => JsonSerializer.Serialize(c with
    {
        Daily = c.Daily with { Tasks = c.Daily.Tasks.Select(d => d with { Weight = 1, MinLevel = 1 }).ToArray() },
        Hunt = c.Hunt with { Streak = true },
    }, Json);

    public static void Validate(Catalog c)
    {
        if (c.Daily.SchemaVersion != 1 || c.Hunt.SchemaVersion != 1 || c.Timed.SchemaVersion != 1 || c.Trinkets.SchemaVersion != 1 ||
            c.Daily.Tasks is null || c.Timed.Events is null || c.Trinkets.Trinkets is null ||
            c.Daily.Tasks.Length is < 3 or > 256 || c.Timed.Events.Length > 64 || c.Trinkets.Trinkets.Length > 128 ||
            c.Hunt.Size is < 1 or > 31 || c.Hunt.RewardId < 1 || c.Hunt.Reward is not { Type: 16, Item: 2, Amount: 1 })
            throw new InvalidDataException("Invalid task schema or collection bounds.");
        foreach (var e in c.Timed.Events)
        {
            if (e is null || e.Id is < 1 or > 1000000 || string.IsNullOrWhiteSpace(e.Name) || e.Name.Length > 96 || e.Start < 0 || e.End <= e.Start || e.End > int.MaxValue ||
                e.Gold is < 0 or > 100000 || e.Tasks is null || e.Tasks.Length is < 1 or > 32 || e.Rewards is null || e.Rewards.Length > 16)
                throw new InvalidDataException("Invalid timed event.");
            foreach (var r in e.Rewards) ValidateReward(r);
        }
        if (c.Timed.Events.Select(e => e.Id).Distinct().Count() != c.Timed.Events.Length)
            throw new InvalidDataException("Duplicate event IDs.");
        var sorted = c.Timed.Events.OrderBy(e => e.Start).ToArray();
        if (sorted.Zip(sorted.Skip(1)).Any(p => p.First.End >= p.Second.Start))
            throw new InvalidDataException("Overlapping timed events.");
        var all = c.All.ToArray();
        if (all.Any(d => d is null)) throw new InvalidDataException("Null task definition.");
        if (all.Select(d => d.Id).Distinct().Count() != all.Length) throw new InvalidDataException("Duplicate task IDs.");
        foreach (var d in all)
        {
            if (d is null || d.Id is < 10000 or > 1000000 || d.Slug is null || !Regex.IsMatch(d.Slug, "^[a-z0-9_]{1,96}$") ||
                d.Type is not (1 or 2 or 3 or 4 or 6 or 7 or 8 or 9 or 10 or 11 or 12 or 13) ||
                d.Target < 1 || d.Target > (d.Type == 3 ? 2000000 : 10000) || d.Gold is < 0 or > 100000 || d.MinLevel is < 1 or > 40 ||
                d.Weight is < 0 or > 10000 || d.Fights is < 0 or > 128 || d.Evidence is not ("Client" or "Community" or "Authored") ||
                d.WindowSeconds is < 0 or > 86400 || d.WindowSeconds > 0 && (d.Type != 1 || d.Target < 2))
                throw new InvalidDataException("Invalid task definition.");
            foreach (var ids in new[] { d.Monsters, d.Items, d.Actions, d.Quests, d.Outputs })
                if (ids is not null && (ids.Length > 256 || ids.Distinct().Count() != ids.Length || ids.Any(i => i < 1)))
                    throw new InvalidDataException("Invalid task references.");
            if (d.Type == 1 && d.Target > 256 ||
                d.Monsters?.Any(id => WorldBestiary.Of(id) is null) == true ||
                d.Quests?.Any(id => !StoryEngine.Quests.Any(q => q.Id == id) && id != TaskEngine.JointVentureQuest) == true ||
                d.Outputs?.Any(id => !StoryEngine.Outputs.Any(o => o.Id == id)) == true ||
                d.Items?.Any(id => !Reconstruction.KnownItem(d.Type == 12 ? ItemKinds.Ingredients : d.Type == 4 ? ItemKinds.Bombs : Economy.KindOf(d.ItemType) ?? "", id)) == true ||
                d.Actions?.Any(id => id > 12) == true ||
                (d.Type == 11 && d.Actions is not { Length: > 0 }) ||
                (d.Type == 6 && !Economy.Recipes.Any(r => r.ItemType == d.ItemType)) ||
                (d.Type == 10 && d.ItemType is not (3 or 4)) ||
                (d.Type == 13 && d.Outputs is not { Length: > 0 }) ||
                (d.Type == 9 && d.Quests is not { Length: > 0 }) ||
                (d.Type == 2 && d.MinLevel < WorldNests.PlayerMinimalLevel))
                throw new InvalidDataException("Unsupported task condition.");
            foreach (var reward in d.Rewards ?? []) ValidateReward(reward);
            if ((d.Rewards?.Length ?? 0) > 1) throw new InvalidDataException("The timed subtask UI reads one item reward.");
        }
        if (c.Trinkets.Trinkets.Any(d => d.Type is not (1 or 2 or 3 or 7 or 8 or 9 or 13)) ||
            c.Timed.Events.Any(e => e.Tasks.Any(d => d.Type == 13)) ||
            c.Daily.Tasks.Any(d => d.Type == 13 || d.Rewards is { Length: > 0 }) ||
            c.Daily.Tasks.Count(d => d.Weight > 0 && d.MinLevel == 1) < 3)
            throw new InvalidDataException("Daily tasks need three available level-one entries and gold-only rewards.");
    }

    private static void ValidateReward(Reward r)
    {
        if (r is null || r.Amount is < 1 or > 10000 || !(r.Type == 16 && r.Item == 2 ||
            Economy.KindOf(r.Type) is { } kind && (Reconstruction.KnownItem(kind, r.Item) ||
                kind == ItemKinds.Lures && WorldNests.Lures.Any(l => l.Id == r.Item))))
            throw new InvalidDataException("Unknown task reward item.");
    }

    /// <summary>Wire rows use the exact lowercase aliases recovered from the 1.1.116 attribute generators.</summary>
    public static Dictionary<string, string[]> Rows(Catalog c)
    {
        var rows = new Dictionary<string, List<object>>();
        void Add(string name, object row)
        { if (!rows.TryGetValue(name, out var list)) rows[name] = list = []; list.Add(row); }
        foreach (string name in new[] { "contracts", "contract_monsters", "contract_crafts", "contract_combat_usages",
            "contract_actions", "contract_quests", "contract_skills", "contract_ingredients", "contract_bombs",
            "contract_allowed_swords", "daily_quests", "daily_quest_rewards", "daily_quest_contracts", "achievements",
            "events", "event_rewards", "weekly_quests_rewards" }) rows[name] = [];
        foreach (var d in c.All)
        {
            int value1 = d.Type is 6 or 10 ? d.ItemType : d.Type == 11 ? d.Fights : d.Type == 4 ? 0 : d.Target;
            int value2 = d.Type is 4 or 6 or 10 ? d.Target : d.Type == 1 ? d.WindowSeconds : 0;
            // CombatActionQuestProgress treats -1 as any sword; 0 restricts local tracking to steel.
            Add("contracts", new { id = d.Id, contract_type_id = d.Type, value1, value2,
                value3 = d.Type == 11 ? d.Target : 0, value4 = d.Type == 11 ? -1 : 0 });
            foreach (int id in d.Monsters ?? []) Add("contract_monsters", new { contract_id = d.Id, monster_id = id });
            foreach (int id in d.Items ?? [])
                if (d.Type == 4) Add("contract_bombs", new { contract_id = d.Id, bomb_id = id });
                else Add(d.Type == 6 ? "contract_crafts" : d.Type == 10 ? "contract_combat_usages" : "contract_ingredients",
                    new { contract_id = d.Id, item_id = id });
            // Definitions retain their existing CombatDetails zero-based indexes. Native contract
            // ActionType is one-based: fast=9/detail8, strong=8/detail7, parry=3/detail2.
            // Original jump tables 0x36F6330/0x36F63CC; never reinterpret already saved progress.
            foreach (int id in d.Actions ?? []) Add("contract_actions", new { contract_id = d.Id, action_type = id + 1 });
            foreach (int id in d.Quests ?? []) Add("contract_quests", new { contract_id = d.Id, quest_id = id });
        }
        foreach (var d in c.AllTasks)
        {
            Add("daily_quests", new { id = d.Id, slug = d.Slug, reward = d.Gold, contract_id = d.Id,
                daily_quest_type_id = c.Daily.Tasks.Any(t => t.Id == d.Id) ? 1 : 2 });
            foreach (var r in d.Rewards ?? []) Add("daily_quest_rewards", new { id = d.Id, daily_quest_id = d.Id, reward_type_id = r.Type, reward_id = r.Item, amount = r.Amount });
        }
        foreach (var d in c.Trinkets.Trinkets) Add("achievements", new { id = d.Id, slug = d.Slug, contract_id = d.Id });
        foreach (var e in c.Timed.Events)
        {
            Add("events", new { id = e.Id, name = e.Name, order_value = e.Id, tutorial = 0,
                available_since_timestamp = e.Start, available_to_timestamp = e.End, event_type_id = 2, gold = e.Gold });
            int index = 0;
            foreach (var r in e.Rewards) Add("event_rewards", new { id = e.Id * 100 + index++, event_id = e.Id, reward_type_id = r.Type, reward_id = r.Item, amount = r.Amount });
        }
        Add("weekly_quests_rewards", new { id = c.Hunt.RewardId, weekly_quest_tier_id = 0,
            item_type_id = c.Hunt.Reward.Type, amount = c.Hunt.Reward.Amount, gold = 0, item_id = c.Hunt.Reward.Item });
        Add("summoning_scrolls", new { id = 2, slug = "summoning_scroll_basic", priority = 0, duration = 500 });
        Add("summoning_scrolls_player_modifiers", new { summoning_scroll_id = 2, player_modifier_id = 13 });
        // Native LoadSummoningScrolls requires the modifier. ID13 is in the original GUI blacklist;
        // empty effects are accepted by LoadPlayerModifiers and do not invent a combat buff.
        Add("player_modifiers", new { id = 13, slug = "summoning_scroll_basic" });
        Add("game_configuration", new { id = 9301, param_name = "weeklyStampsMaxCount", param_value = c.Hunt.Size.ToString(System.Globalization.CultureInfo.InvariantCulture) });
        return rows.ToDictionary(p => p.Key, p => p.Value.Select(r => JsonSerializer.Serialize(r)).ToArray());
    }
}
