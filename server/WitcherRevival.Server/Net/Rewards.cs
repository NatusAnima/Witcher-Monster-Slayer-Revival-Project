using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The reward tables a Tuning preset carries (the dashboard's Rewards page): what each quest ending pays, the items a
/// daily task adds to its gold, and the level-up rewards. Revival and Vanilla are built in; a player's own preset keeps a
/// copy in world/presets. Vanilla is the original game as the wiki records it (v1.1 quest infoboxes, the pre-1.2 level
/// table); Revival is this project's rebalance for casual play.
/// </summary>
public sealed record RewardTables(Dictionary<string, RewardTables.Quest> Quests, int DailyItems, RewardTables.PoolItem[] DailyPool,
    Dictionary<int, RewardTables.Level> Levels)
{
    public sealed record Item(string Kind, int Id, int Amount);

    /// <summary>[Slots] are extra inventory slots, counted while the ending is reached (Economy.BagSize).</summary>
    public sealed record Quest(int Exp, int Gold, Item[] Items, int Slots = 0)
    {
        public Reconstruction.Reward ToReward() => new(Exp, Gold, Items.GroupBy(i => i.Kind)
            .ToDictionary(kind => kind.Key, kind => kind.GroupBy(i => i.Id).ToDictionary(item => item.Key, item => item.Sum(i => i.Amount))));
    }

    public sealed record PoolItem(string Kind, int Id, int Weight, int MinLevel = 1);

    public sealed record Level(int Gold, Item[] Items);

    /// <summary>The page's rows: endings that share a reward are edited together.</summary>
    public sealed record Group(string Quest, string Label, string[] Keys);

    public const string PrologueKey = "prologue.";

    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    public static readonly IReadOnlyList<Group> Groups = new Group[]
    {
        new("Final Exam", "The exam kit", ["prologue.exam"]),
        new("Final Exam", "Quest end", ["prologue.exam_end"]),
        new("Prologue", "Thorstein's horse", ["prologue.horse"]),
        new("Winged Bandit", "Quest end", ["prologue.griffin"]),
        new("A Joint Venture", "Quest end", ["prologue.joint_venture"]),
        new("Good Money", "Quest end", ["s01mq01_margit_2.scholar_02"]),
        new("Evil Never Sleeps", "Reward taken", ["s01mq04_bedwyr_end.final"]),
        new("Evil Never Sleeps", "Reward declined", ["s01mq04_bedwyr_end.no_reward"]),
        new("To The Rescue", "Kienan freed, escaped, or the treasure",
            ["s01hq05_pit.actor_free", "s01hq05_pit.actor_escape", "s01hq05_treasure.treasure"]),
        new("To The Rescue", "Kienan dead", ["s01hq05_pit.actor_dead"]),
        new("To The Rescue", "Kienan again", ["s01hq05_kienan_again.end"]),
        new("Pride Ain't Cheap", "Quest end", ["s01mq02_vesemir.vesemir"]),
        new("What Lurks in the Nemeta", "Quest end", ["s01hq02_well.scholar"]),
        new("The Dark Side of the Full Moon", "Every ending",
            ["s01hq03_farewell.blacksmith", "s01hq03_farewell.blacksmith_map", "s01hq03_new_smith.new_blacksmith"]),
        new("Sword in the Stone", "Quest end", ["s01hq01_stone.sword"]),
        new("Monster Slayer", "The troll beaten", ["s01hq06_troll.won", "s01hq06_cave.won"]),
        new("Monster Slayer", "The troll fight lost", ["s01hq06_troll.lost", "s01hq06_cave.lost"]),
        new("Monster Slayer", "The fleder beaten", ["s01hq06_fleder.won"]),
        new("Monster Slayer", "The grey rocks", ["s01hq06_fleder.grey_rocks"]),
        new("Monster Slayer", "Refused", ["s01hq06_troll.refuse"]),
        new("Will O' The Wisp", "Quest end", ["s01hq04_treasure.treasure"]),
        new("The Great Mushrooming", "Every placing", ["s01mq05_final.first_place", "s01mq05_final.second_place",
            "s01mq05_final.third_place", "s01mq05_final.peleton", "s01mq05_final.last_place"]),
        new("The Sins of Our Fathers", "Striga killed", ["s01mq03_lair.striga_killed"]),
        new("The Sins of Our Fathers", "Striga killed, knowing", ["s01mq03_lair.striga_killed_knew"]),
        new("The Sins of Our Fathers", "Curse lifted", ["s01mq03_armor.armor"]),
        new("Intruder", "Every ending", ["s01mq06_vogt_end.full_reward", "s01mq06_vogt_end.reward",
            "s01mq06_vogt_end.bad_reward", "s01mq06_vogt_end.bonus_reward", "s01mq06_vogt_end.full_reward_dhl",
            "s01mq06_vogt_end.reward_dhl", "s01mq06_vogt_end.bad_reward_dhl", "s01mq06_vogt_end.bonus_reward_dhl"]),
    };

    public static readonly IReadOnlySet<string> Keys = Groups.SelectMany(g => g.Keys).ToHashSet();

    /// <summary>The key of a season 1 output ("node.output"), or null when the output is not an ending on the page.</summary>
    public static string? KeyOf(StoryEngine.Output output) =>
        StoryEngine.NodeById(output.Node) is { } node && Keys.Contains($"{node.Key}.{output.Name}") ? $"{node.Key}.{output.Name}" : null;

    public Quest? For(string? key) => key is not null && Quests.TryGetValue(key, out var quest) ? quest : null;

    // ── Built-in tables ─────────────────────────────────────────────────────────────────────────

    private static Item I(string kind, int id, int amount = 1) => new(kind, id, amount);

    /// <summary>The original amounts: the season 1 story's own outputs (they match the wiki's v1.1 quest infoboxes) and
    /// the prologue's Reconstruction.RewardFor.</summary>
    public static RewardTables Vanilla { get; } = BuildVanilla();

    public static RewardTables Revival { get; } = BuildRevival();

    private static RewardTables BuildVanilla()
    {
        var quests = new Dictionary<string, Quest>();
        foreach (string key in Keys)
        {
            if (key.StartsWith(PrologueKey))
            {
                string reward = key[PrologueKey.Length..];
                string output = reward switch { "horse" => "dead_horse", "griffin" => "griffin_1", "joint_venture" => "success", _ => reward };
                var r = Reconstruction.RewardFor(output);
                quests[key] = new Quest(r?.Exp ?? 0, r?.Gold ?? 0, ItemsOf(r?.Items));
                continue;
            }
            var o = StoryEngine.Outputs.First(o => KeyOf(o) == key);
            quests[key] = new Quest(o.Exp, o.Gold, ItemsOf(o.Items));
        }
        return new RewardTables(quests, 0, RevivalPool, VanillaLevels());
    }

    private static Item[] ItemsOf(Dictionary<string, Dictionary<int, int>>? items) =>
        (items ?? new()).SelectMany(kind => kind.Value.Select(item => new Item(kind.Key, item.Key, item.Value))).ToArray();

    // Revival (2026-10-11 maintainer review): about twice the experience, two to four times the orens, and items that suit
    // the quest's monsters. Items the quest-completed window shows (potions, bombs, oils, lures, gear) appear there;
    // scrolls, consumables and slots arrive silently.
    private static RewardTables BuildRevival()
    {
        var q = new Dictionary<string, Quest>(Vanilla.Quests);
        void Set(Quest quest, params string[] keys) { foreach (string key in keys) q[key] = quest; }
        Item[] Same(string key, params Item[] more) => [.. Vanilla.Quests[key].Items, .. more];
        Set(new(500, 100, [I(ItemKinds.Potions, Reconstruction.SwallowPotionId, 2)]), "prologue.griffin");
        Set(new(600, 150, [I(ItemKinds.SummoningScrolls, SummonScrolls.Basic)]), "prologue.joint_venture");
        Set(new(600, 150, [I(ItemKinds.Oils, 307), I(ItemKinds.Potions, Reconstruction.SwallowPotionId, 2)]), "s01mq01_margit_2.scholar_02");
        Set(new(600, 150, [I(ItemKinds.Oils, 305), I(ItemKinds.Bombs, 402, 2)]), "s01mq04_bedwyr_end.final");
        Set(new(600, 0, []), "s01mq04_bedwyr_end.no_reward");
        Set(new(500, 120, [I(ItemKinds.Oils, 302)]), "s01hq05_pit.actor_free", "s01hq05_pit.actor_escape", "s01hq05_treasure.treasure");
        Set(new(750, 120, [I(ItemKinds.Oils, 302)]), "s01hq05_pit.actor_dead");
        Set(new(600, 150, Same("s01mq02_vesemir.vesemir", I(ItemKinds.Potions, 204))), "s01mq02_vesemir.vesemir");
        Set(new(600, 250, [I(ItemKinds.Lures, 501, 2)]), "s01hq02_well.scholar");
        Set(new(800, 200, [I(ItemKinds.Oils, 304), I(ItemKinds.Bombs, 403, 2)]),
            "s01hq03_farewell.blacksmith", "s01hq03_farewell.blacksmith_map", "s01hq03_new_smith.new_blacksmith");
        Set(new(500, 100, Same("s01hq01_stone.sword")), "s01hq01_stone.sword");
        Item[] slayer = [I(ItemKinds.Oils, 303), I(ItemKinds.SummoningScrolls, SummonScrolls.OgroidFive)];
        Set(new(1050, 200, slayer), "s01hq06_troll.won", "s01hq06_cave.won");   // 800 + the troll fight's 250
        Set(new(800, 200, slayer), "s01hq06_troll.lost", "s01hq06_cave.lost", "s01hq06_fleder.won", "s01hq06_fleder.grey_rocks");
        Set(new(600, 250, [I(ItemKinds.Consumables, Consumables.ExperienceScroll)]), "s01hq04_treasure.treasure");
        Set(new(1500, 300, [I(ItemKinds.Consumables, Consumables.IngredientsScroll, 2)], Slots: 400),
            "s01mq05_final.first_place", "s01mq05_final.second_place", "s01mq05_final.third_place", "s01mq05_final.peleton",
            "s01mq05_final.last_place");
        Set(new(1200, 250, []), "s01mq03_lair.striga_killed");
        Set(new(1500, 250, []), "s01mq03_lair.striga_killed_knew");
        Set(new(1500, 250, Same("s01mq03_armor.armor")), "s01mq03_armor.armor");
        Set(new(3000, 500, [I(ItemKinds.SummoningScrolls, SummonScrolls.Legendary)]),
            Groups.Single(g => g.Quest == "Intruder").Keys);
        return new RewardTables(q, 1, RevivalPool, RevivalLevels());
    }

    // The daily pool: shares potions/oils/bombs 50, summoning scrolls 20, boosters 20, nest baits 10 (nemeta open at 10).
    private static PoolItem[] RevivalPool =>
    [
        new(ItemKinds.Potions, 201, 6), new(ItemKinds.Potions, 205, 6), new(ItemKinds.Potions, 204, 3), new(ItemKinds.Potions, 202, 3),
        new(ItemKinds.Oils, 301, 8), new(ItemKinds.Oils, 302, 2), new(ItemKinds.Oils, 303, 2), new(ItemKinds.Oils, 304, 2),
        new(ItemKinds.Oils, 305, 2), new(ItemKinds.Oils, 307, 2),
        new(ItemKinds.Bombs, 401, 6), new(ItemKinds.Bombs, 402, 3), new(ItemKinds.Bombs, 403, 3), new(ItemKinds.Bombs, 404, 2),
        new(ItemKinds.SummoningScrolls, SummonScrolls.Lesser, 10), new(ItemKinds.SummoningScrolls, SummonScrolls.Basic, 6),
        new(ItemKinds.SummoningScrolls, 6, 1), new(ItemKinds.SummoningScrolls, 5, 1), new(ItemKinds.SummoningScrolls, 8, 1),
        new(ItemKinds.SummoningScrolls, 13, 1),
        new(ItemKinds.Consumables, Consumables.ExperienceScroll, 10), new(ItemKinds.Consumables, Consumables.IngredientsScroll, 10),
        new(ItemKinds.Lures, 501, 6, 10), new(ItemKinds.Lures, 503, 1, 10), new(ItemKinds.Lures, 507, 1, 10),
        new(ItemKinds.Lures, 508, 1, 10), new(ItemKinds.Lures, 510, 1, 10),
    ];

    /// <summary>Wiki (XP page, pre-1.2): from level 3 Thunderbolt ×5, basic oil ×3 and basic bomb ×2 a level, Falcon ×3 at
    /// level 3, oil and bomb ×5 at 10/20/25/30/40, a monster bait at 10/15/20/25/30/40, an Experience Scroll at
    /// 8/13/18/23/28/33. The rows the wiki marks unknown get the standard set, and so does level 2, which lists nothing:
    /// the game's level-up window needs an item (Reconstruction.LevelRewards).</summary>
    private static Dictionary<int, Level> VanillaLevels()
    {
        var levels = new Dictionary<int, Level>();
        for (int level = 2; level <= Reconstruction.MaxLevel; level++)
        {
            bool big = level is 10 or 20 or 25 or 30 or 40;
            var items = new List<Item> { I(ItemKinds.Potions, 201, 5), I(ItemKinds.Oils, Reconstruction.BasicOilId, big ? 5 : 3),
                I(ItemKinds.Bombs, Reconstruction.BasicBombId, big ? 5 : 2) };
            if (level == 3) items.Add(I(ItemKinds.SensesPotions, Economy.Falcon, 3));
            if (level is 10 or 15 or 20 or 25 or 30 or 40) items.Add(I(ItemKinds.Lures, 501));
            if (level is 8 or 13 or 18 or 23 or 28 or 33) items.Add(I(ItemKinds.Consumables, Consumables.ExperienceScroll));
            levels[level] = new Level(0, items.ToArray());
        }
        return levels;
    }

    /// <summary>Revival: the vanilla rewards, 100 orens a level (250 every fifth) and a summoning scroll every fifth level.</summary>
    private static Dictionary<int, Level> RevivalLevels() => VanillaLevels().ToDictionary(p => p.Key, p => p.Key % 5 == 0
        ? new Level(250, [.. p.Value.Items, I(ItemKinds.SummoningScrolls, SummonScrolls.Basic)])
        : new Level(100, p.Value.Items));

    // ── Checks and draws ────────────────────────────────────────────────────────────────────────

    public static bool KnownItem(string kind, int id) => kind switch
    {
        ItemKinds.Lures => WorldNests.Lures.Any(l => l.Id == id),
        ItemKinds.Swords => Reconstruction.SwordById(id) is not null,
        ItemKinds.Armors => Reconstruction.ArmorById(id) is not null,
        ItemKinds.SummoningScrolls => SummonScrolls.ById(id) is not null,
        ItemKinds.Consumables => Consumables.ById(id) is not null,
        _ => Reconstruction.KnownItem(kind, id),
    };

    /// <summary>Refuses a table the server cannot pay, with the reason for the dashboard.</summary>
    public static void Validate(RewardTables t)
    {
        static void Items(Item[]? items, string where)
        {
            if (items is null || items.Length > 16) throw new InvalidDataException($"{where}: at most 16 items.");
            foreach (var item in items)
                if (item is null || !KnownItem(item.Kind, item.Id) || item.Amount is < 1 or > 1000)
                    throw new InvalidDataException($"{where}: {item?.Kind} {item?.Id} is not an item the game knows, or its amount is not 1-1000.");
        }
        if (t.Quests is null || t.DailyPool is null || t.Levels is null) throw new InvalidDataException("The reward tables are incomplete.");
        foreach (var (key, quest) in t.Quests)
        {
            if (!Keys.Contains(key) || quest is null) throw new InvalidDataException($"Unknown quest ending {key}.");
            if (quest.Exp is < 0 or > 100_000 || quest.Gold is < 0 or > 100_000 || quest.Slots is < 0 or > 1000)
                throw new InvalidDataException($"{key}: experience and orens must be 0-100000, slots 0-1000.");
            Items(quest.Items, key);
        }
        if (t.DailyItems is < 0 or > 5) throw new InvalidDataException("A daily task gives 0-5 items.");
        if (t.DailyPool.Length > 128) throw new InvalidDataException("The daily pool holds at most 128 items.");
        foreach (var row in t.DailyPool)
        {
            if (row is null || !KnownItem(row.Kind, row.Id) || row.Weight is < 0 or > 10_000 || row.MinLevel is < 1 or > Reconstruction.MaxLevel)
                throw new InvalidDataException($"Daily pool: {row?.Kind} {row?.Id} is unknown, or its weight (0-10000) or level (1-40) is wrong.");
        }
        foreach (var (level, reward) in t.Levels)
        {
            if (level is < 2 or > Reconstruction.MaxLevel || reward is null || reward.Gold is < 0 or > 100_000)
                throw new InvalidDataException($"Level {level}: levels are 2-40 and orens 0-100000.");
            Items(reward.Items, $"Level {level}");
            if (reward.Items.Length == 0)
                throw new InvalidDataException($"Level {level}: give at least one item (the game's level-up window waits for one).");
        }
    }

    /// <summary>[DailyItems] draws from the pool rows the player's level allows, weighted (repeats possible).</summary>
    public List<Item> DrawDaily(int level, Random random)
    {
        var rows = DailyPool.Where(r => r.Weight > 0 && r.MinLevel <= level && KnownItem(r.Kind, r.Id)).ToList();
        var drawn = new List<Item>();
        long total = rows.Sum(r => (long)r.Weight);
        for (int n = 0; n < DailyItems && total > 0; n++)
        {
            long ticket = random.NextInt64(total);
            foreach (var row in rows)
                if ((ticket -= row.Weight) < 0) { drawn.Add(new Item(row.Kind, row.Id, 1)); break; }
        }
        return drawn;
    }

    public static RewardTables Parse(JsonElement element) =>
        element.Deserialize<RewardTables>(Json) ?? throw new InvalidDataException("The reward tables are empty.");
}
