namespace WitcherRevival.Server.Net;

/// <summary>
/// Nemeta (monster nests) on the world map and their baits, for reconstructed profiles.
///
/// Client: GetLocationsByCell (40) carries nests as Placement&lt;Nest&gt; ([byte Type][string PlaceId][long InstanceId]
/// [int BossType][int NestState], Nest.Deserialize 0x19349BC; NestInstance.ToString prints "nest - boss:{0},
/// state:{1}, ..."). NestOnMapController shows a nest as active only from GameConfigData.NestPlayerMinimalLevel on
/// and in the Default or Lured state. Tapping it sends EncounterNest (52); NestWindow (LoadData 0x17D98FC) then
/// shows the monsters to fight (Default, Lured), the bait panel (DefaultClear, LuredClear, the latter locked) or
/// the level lock (NotAllowed). A fight runs the standardnestmechanic graph (common_story_assets_all): three fights
/// against Monster_1..3 with no server call in between, then EndNestCombat (53). After a win the client itself
/// turns Default into DefaultClear and Lured into LuredClear (GetNestRewardsNode.OnEndNestCombatResponse). The
/// bait panel counts down to ISyncedTimeSource.TimeToNewDay for new monsters (NestLureController.Update), and the
/// bonus panel shows "Daily limit: won/NestDailyLimit" and "New bonus in" the same countdown
/// (NestMonstersPanel.SetupMonsters). GameConfigData defaults (ctor 0x1950694): NestXP 500, NestDailyLimit 3,
/// NestPlayerMinimalLevel 10. Baits: lures table (id, slug, priority), ITEMS/NAMES/LURES/LURE_* and
/// icon_lure_* (alchemy_atlas); one bait per clearing ("a specific monster group can only be lured once").
///
/// Community: level 10 (Gamepressure; DualShockers 20 Jul 2021; TheGamer 4 Aug 2021; Digital Trends 5 Aug 2021),
/// three monsters in a row, two easy ones and a medium one (Digital Trends: two Endrega Workers and an Endrega
/// Drone in an insectoid nemeton), 50 gold for each of the first three clears of a day (TheGamer, Digital Trends),
/// "close to 600" XP (DualShockers) or 500 to 700+ XP (Digital Trends), each nemeton once a day unless baited
/// (DualShockers), a bait costs 200 gold (Digital Trends).
///
/// Authored: at most one nemeton per level-14 cell, selected by the placement service with neighbor spacing;
/// older services without placement metadata retain the independent per-cell draw. The monster classes and their make-up from
/// the monsters this server has rows for, the rarity experience (so that a plain clear gives 575 XP), the loot.
/// </summary>
public static class WorldNests
{
    // NestState (Client WitcherWorld.WebstuffClient.Core.Socket.Api.Response.Map.NestState).
    public const int Default = 1, DefaultClear = 2, Lured = 3, LuredClear = 4, NotAllowed = 5;

    // Client GameConfigData defaults; sent as game_configuration rows too.
    public const int PlayerMinimalLevel = 10, DailyLimit = 3, ClearingExp = 500;

    // Community: 50 gold per clear, the first three clears of a day.
    public const int BountyGold = 50;

    // Authored: experience for each monster by rarity; three common monsters and the clearing give 575.
    public static int RarityExp(int rarity) => rarity switch { <= 1 => 25, 2 => 50, _ => 100 };

    public const int ItemTypeLure = 5;   // Client Lure.GetItemType.

    /// <summary>A monster the nests use: id, difficulty and rarity as in the monsters table.</summary>
    public sealed record Species(int MonsterId, int Difficulty, int Rarity);

    /// <summary>A monster class a nemeton can hold: its family (monster_families id), the easy monsters for the
    /// first two fights and the boss for the third, and the weight among nests without bait.</summary>
    public sealed record NestClass(int Family, string Slug, Species[] Easy, Species Boss, int Weight);

    private static readonly Species Ghoul = new(1, 1, 1), Alghoul = new(2, 2, 1), Drowner = new(3, 1, 1),
        Nekker = new(4, 1, 1), NekkerWarrior = new(5, 2, 1), SmallDraconid = new(7, 2, 1), Devourer = new(10, 1, 1),
        Wraith = new(11, 2, 1), WraithLvl2 = new(12, 2, 1);

    // Classes with a weaker and a stronger monster in the table, and the draconids, whose story nemeton
    // (s01mq05_nest) fights three small draconids. Cursed, elemental and hybrid have a single strong monster;
    // insectoids, relicts and vampires have no row yet.
    public static readonly IReadOnlyList<NestClass> Classes = new NestClass[]
    {
        new(1, "necrophage", new[] { Ghoul, Drowner, Devourer }, Alghoul, 3),
        new(3, "ogroid", new[] { Nekker }, NekkerWarrior, 3),
        new(7, "specter", new[] { Wraith }, WraithLvl2, 2),
        new(2, "draconid", new[] { SmallDraconid }, SmallDraconid, 2),
    };

    public static NestClass? ClassOf(int family) => Classes.FirstOrDefault(c => c.Family == family);

    public static Species? SpeciesOf(int monsterId) => Classes.SelectMany(c => c.Easy.Append(c.Boss))
        .FirstOrDefault(s => s.MonsterId == monsterId);

    /// <summary>A bait: lures row id and slug, the class it lures (null: a random one) and whether the shop sells
    /// it. Ids Authored (item type 5, the five hundreds); slugs from the client names and icons.</summary>
    public sealed record Lure(int Id, string Slug, int? Family, bool Sold);

    public static readonly IReadOnlyList<Lure> Lures = new Lure[]
    {
        new(501, "lure_basic", null, true), new(502, "lure_cursed", 11, false), new(503, "lure_draconid", 2, true),
        new(504, "lure_elemental", 5, false), new(505, "lure_hybrid", 4, false), new(506, "lure_insectoid", 8, false),
        new(507, "lure_necrophage", 1, true), new(508, "lure_ogroid", 3, true), new(509, "lure_relict", 6, false),
        new(510, "lure_specter", 7, true), new(511, "lure_vampire", 10, false),
    };

    public const int BaitPrice = 200;   // Community (Digital Trends): a bait costs 200 gold.

    public static Lure? LureById(int id) => Lures.FirstOrDefault(l => l.Id == id);

    /// <summary>A nemeton of the day: instance id, place, cell, class and its three monsters (boss last).</summary>
    public sealed record Nest(long InstanceId, string PlaceId, ulong CellId, int Family, int[] Monsters)
    {
        public int Boss => Monsters[^1];
    }

    /// <summary>The cell's nemeton for the day's places, the same for every player and request (each player's
    /// fights and clears are theirs, NestDay of their profile). New sidecars designate an anchor or explicitly
    /// suppress the cell; herbs reserve that anchor. Legacy responses retain their original selection.</summary>
    public static Nest? ForCell(PlayableLocations.Cell cell, long epoch)
    {
        var herbs = WorldHerbs.ForCell(cell).Select(h => h.PlaceId).ToHashSet();
        long seed = WorldSpawns.StableHash($"{cell.Id}:{epoch}:nest");
        var rng = new Random((int)(seed ^ (seed >> 32)));
        var places = cell.Places.OrderBy(_ => rng.Next()).ToList();
        var place = cell.HasNestPlacement ? places.FirstOrDefault(p => p.Id == cell.NestPlaceId)
            : places.FirstOrDefault(p => !herbs.Contains(p.Id)) ?? places.FirstOrDefault();
        if (place is null) return null;
        int roll = rng.Next(Classes.Sum(c => c.Weight));
        var nestClass = Classes.First(c => (roll -= c.Weight) < 0);
        long id = WorldSpawns.StableHash($"{cell.Id}:{epoch}:nest:{place.Id}") & long.MaxValue;
        return new Nest(id | 1L << 59, place.Id, cell.Id, nestClass.Family, Monsters(nestClass, seed));
    }

    /// <summary>Two easy monsters of the class and its boss.</summary>
    public static int[] Monsters(NestClass nestClass, long seed)
    {
        var rng = new Random((int)(seed ^ (seed >> 32)) ^ nestClass.Family);
        return new[]
        {
            nestClass.Easy[rng.Next(nestClass.Easy.Length)].MonsterId,
            nestClass.Easy[rng.Next(nestClass.Easy.Length)].MonsterId,
            nestClass.Boss.MonsterId,
        };
    }

    /// <summary>The class a bait brings to a nest: its own, or for the basic bait one of the others at random.</summary>
    public static NestClass? LuredClass(Lure lure, int currentFamily, long seed)
    {
        if (lure.Family is int family) return ClassOf(family);
        var others = Classes.Where(c => c.Family != currentFamily).ToList();
        var rng = new Random((int)(seed ^ (seed >> 32)));
        return others[rng.Next(others.Count)];
    }

    /// <summary>The UTC day of a Unix time; nests, their bonus count and the client's countdown turn with it.</summary>
    public static long Day(long unixSeconds) => unixSeconds / 86_400;
}
