namespace WitcherRevival.Server.Net;

/// <summary>
/// Monsters on the world map, one world for every player: the same monsters stand at the same places at the same
/// times for everyone, since nothing of a player goes into their draw. Ordinary world monsters are visible
/// at every player level; each player fights them for themselves: a kill hides the monster for that player only
/// (KilledInstances of their profile). Places come from the playable-locations service
/// per level-14 cell (fixed for a UTC day). Each cell has <see cref="MonstersPerCell"/> original slots with their own
/// share of the day's places (those the cell's herbs and nemeton leave free); policy permits up to two additional
/// monsters in each share, while preserving the original monster. A slot's monsters live
/// <see cref="LifetimeSeconds"/> and is followed at once by the next one on a place drawn from the slot's share.
/// The slots of a cell are evenly spread over a lifetime and cells start at different phases, so small groups come
/// and go instead of the whole map emptying at once. The client asks for the successor itself
/// (GetMonsterInstances 87) when a monster expires; its senses plates last as long as the monster.
///
/// Which monster: the client has no rule of its own (EVIDENCE.md §16), so the server decides, as the original
/// did. The species are the world bestiary (<see cref="WorldBestiary"/>), with the occurrences the client's own
/// bestiary shows (MONSTERS/OCCURANCE/*, INFO_2 of each monster):
///   - place: URBAN ("near human settlements": an urban or cropland place), NON_URBAN ("prefers to avoid human
///     settlements": not urban), FOREST (green areas: forest, shrubland, savanna, grassland), WATER (wetland or
///     water); FOREST and WATER are alternatives; NEUTRAL2 ("common in all natural environment types"): anywhere;
///   - DAY ("most commonly found during the day") and NIGHT ("nocturnally active"): not in the other half of the
///     day; the twilight between them (sun 6° either side of the horizon) suits both;
///   - FULL_MOON_ONLY and FOG_ONLY: only then;
///   - DAWN, DUSK, D_AND_D, NOON, MIDNIGHT, RAIN, FOG, FULL_MOON ("increased activity"): triple weight while they
///     hold, for every rarity.
/// The sun and moon are those over the cell at the monster's mid-life; rain and fog come from WorldWeather.
/// New generations draw rarity first with authored category weights 88/18/3, independently of pool size.
/// Species within that category have equal base weight, with the above environmental boosts. In four of six
/// shares, common draws prefer eligible zero-skull species; rare/legendary draws use the full eligible category.
/// Before a configured activation instant the exact previous per-species lottery and beginner restrictions apply.
/// Player-level gates remain separate in the personal Aura draw. Density is bounded by available safe places.
/// A slot remains empty when its places cannot support a matching species; habitat rules still apply.
/// </summary>
public static class WorldSpawns
{
    public const int LifetimeSeconds = 1800;
    // Keep this partition count fixed: changing it would move existing monsters and reuse their generations.
    public const int MonstersPerCell = 6;
    public const int DefaultMonsterSlotsPerCell = 18;
    // Four partitions prefer easy common draws; legacy generations restrict all their draws to zero skulls.
    public const int BeginnerSlotsPerCell = 4;
    public const int CommonWeight = 88, RareWeight = 18, LegendaryWeight = 3;
    public const int RarityWeightTotal = CommonWeight + RareWeight + LegendaryWeight;

    // Client BiomeType: 1 Forest, 2 Shrubland, 3 Savanna, 4 Grassland, 5 Wetland, 6 Cropland, 7 Urban,
    // 8 SnowIce, 9 Barren, 10 Water.
    public const int Forest = 1, Shrubland = 2, Savanna = 3, Grassland = 4, Wetland = 5, Cropland = 6, Urban = 7,
        Barren = 9, Water = 10;

    /// <summary>Authored eligibility for personal Aura summons, not ordinary world visibility.</summary>
    public static int MinPlayerLevel(WorldBestiary.Species species) =>
        species.Skulls switch { <= 0 => 1, 1 => 3, 2 => 6, _ => 10 };

    public static int Weight(WorldBestiary.Species species) => species.Rarity switch { 1 => 10, 2 => 3, _ => 1 };

    private static bool Has(WorldBestiary.Species species, string tag) => species.Tags.Contains(tag);

    /// <summary>The sky and weather over a cell at a moment.</summary>
    public sealed record Conditions(bool Day, bool Night, bool Dawn, bool Dusk, bool Noon, bool Midnight, bool FullMoon,
        bool Rain, bool Fog);

    /// <summary>Whether a species may stand on a place (its biomes) under the given conditions.</summary>
    public static bool Fits(WorldBestiary.Species species, int[] biomes, Conditions sky)
    {
        if (Has(species, "URBAN") && !biomes.Any(b => b is Urban or Cropland)) return false;
        if (Has(species, "NON_URBAN") && biomes.Contains(Urban)) return false;
        bool forest = Has(species, "FOREST"), water = Has(species, "WATER");
        if ((forest || water) && !((forest && biomes.Any(b => b is Forest or Shrubland or Savanna or Grassland)) ||
                                   (water && biomes.Any(b => b is Wetland or Water))))
            return false;
        if ((Has(species, "DAY") && sky.Night) || (Has(species, "NIGHT") && sky.Day)) return false;
        return !(Has(species, "FULL_MOON_ONLY") && !sky.FullMoon) && !(Has(species, "FOG_ONLY") && !sky.Fog);
    }

    private static readonly (string Tag, Func<Conditions, bool> Holds)[] Boosts =
    {
        ("DAWN", sky => sky.Dawn), ("DUSK", sky => sky.Dusk), ("D_AND_D", sky => sky.Dawn || sky.Dusk),
        ("NOON", sky => sky.Noon), ("MIDNIGHT", sky => sky.Midnight), ("RAIN", sky => sky.Rain),
        ("FOG", sky => sky.Fog), ("FULL_MOON", sky => sky.FullMoon),
    };

    private static bool Boosted(WorldBestiary.Species species, Conditions sky) =>
        Boosts.Any(b => Has(species, b.Tag) && b.Holds(sky));

    public static int WeightUnder(WorldBestiary.Species species, Conditions sky) =>
        Weight(species) * (Boosted(species, sky) ? 3 : 1);

    /// <summary>Authored ordinary-world lottery. The inputs must already satisfy habitat/time eligibility.
    /// Missing rare/legendary mass falls back to enabled common; missing common leaves the attempt empty instead of
    /// redistributing its mass to harder categories. Callers must not retry an empty roll in the same slot.
    /// Legacy WeightUnder remains unchanged for Aura and pre-activation generations.</summary>
    public static WorldBestiary.Species? DrawBalanced(IReadOnlyList<WorldBestiary.Species> eligible,
        Conditions sky, Random rng, bool preferBeginner, WorldBalance.Rules? rules = null)
    {
        rules ??= WorldBalance.DefaultRules;
        int ticket = rng.Next(rules.Total);
        int rarity = ticket < rules.Common ? 1 : ticket < rules.Common + rules.Rare ? 2 : 3;
        var pool = eligible.Where(s => s.Rarity == rarity && rules.Weight(s.MonsterId) > 0).ToList();
        if (pool.Count == 0 && rarity != 1 && rules.Common > 0)
            pool = eligible.Where(s => s.Rarity == 1 && rules.Weight(s.MonsterId) > 0).ToList();
        if (pool.Count == 0) return null;
        if (pool[0].Rarity == 1 && preferBeginner)
        {
            var easy = pool.Where(s => s.Skulls == 0).ToList();
            if (easy.Count > 0) pool = easy;
        }
        int roll = rng.Next(pool.Sum(s => rules.Weight(s.MonsterId) * (Boosted(s, sky) ? 3 : 1)));
        return pool.First(s => (roll -= rules.Weight(s.MonsterId) * (Boosted(s, sky) ? 3 : 1)) < 0);
    }

    public sealed record Spawn(long InstanceId, int MonsterId, int Difficulty, string PlaceId, ulong CellId,
        long SpawnTimeMs, int Ttl);

    public static long PlacesEpoch(long unixSeconds) => unixSeconds / 86_400;

    /// <summary>The cell of a place id "lab-&lt;cell hex&gt;-&lt;epoch&gt;-&lt;n&gt;".</summary>
    public static ulong? CellOf(string placeId)
    {
        var parts = placeId.Split('-');
        return parts.Length == 4 && parts[0] == "lab" && ulong.TryParse(parts[1],
            System.Globalization.NumberStyles.HexNumber, null, out ulong cell) ? cell : null;
    }

    /// <summary>The places epoch of a place id.</summary>
    public static long? EpochOf(string placeId)
    {
        var parts = placeId.Split('-');
        return parts.Length == 4 && parts[0] == "lab" && long.TryParse(parts[2], out long epoch) ? epoch : null;
    }

    /// <summary>The living monsters of one cell at a moment, one per slot, the same for every player and request
    /// (seeded by cell, slot and the slot's generation; weatherAt gives the weather the generation was drawn under).</summary>
    public static List<Spawn> ForCell(PlayableLocations.Cell cell, long nowSeconds, Func<long, int>? weatherAt = null,
        int monsterSlotsPerCell = DefaultMonsterSlotsPerCell, long balanceFromUnixSeconds = 0,
        Func<long, WorldBalance.Rules>? balanceAt = null)
    {
        if (monsterSlotsPerCell is < 6 or > 18) throw new ArgumentOutOfRangeException(nameof(monsterSlotsPerCell));
        if (balanceFromUnixSeconds < 0) throw new ArgumentOutOfRangeException(nameof(balanceFromUnixSeconds));
        long dealSeed = StableHash($"{cell.Id}:places");
        var dealRng = new Random((int)(dealSeed ^ (dealSeed >> 32)));
        var taken = WorldHerbs.ForCell(cell).Select(h => h.PlaceId).ToHashSet();
        if (WorldNests.ForCell(cell, PlacesEpoch(nowSeconds)) is { } nest) taken.Add(nest.PlaceId);
        var dealt = cell.Places.Where(p => !taken.Contains(p.Id)).OrderBy(_ => dealRng.Next()).ToList();
        long phase = (StableHash($"{cell.Id}:phase") & long.MaxValue) % LifetimeSeconds;
        var spawns = new List<Spawn>();
        var extraSpawns = new List<Spawn>();
        for (int slot = 0; slot < MonstersPerCell; slot++)
        {
            long offset = (phase + slot * LifetimeSeconds / MonstersPerCell) % LifetimeSeconds;
            long generation = (long)Math.Floor((nowSeconds - offset) / (double)LifetimeSeconds);
            long start = generation * LifetimeSeconds + offset;
            bool balanced = start >= balanceFromUnixSeconds;
            var rules = balanced ? balanceAt?.Invoke(start) ?? WorldBalance.DefaultRules : null;
            long seed = StableHash($"{cell.Id}:{slot}:{generation}");
            var rng = new Random((int)(seed ^ (seed >> 32)));
            var sky = Sky(cell.Lat, cell.Lng, DateTimeOffset.FromUnixTimeSeconds(start + LifetimeSeconds / 2),
                weatherAt?.Invoke(generation) ?? WorldWeather.Clear);
            var share = dealt.Where((_, n) => n % MonstersPerCell == slot).ToList();
            var used = new HashSet<string>();
            foreach (var place in share.OrderBy(_ => rng.Next()).ToList())
            {
                var options = WorldBestiary.All.Where(s => Fits(s, place.Biomes, sky) &&
                    (balanced || slot >= BeginnerSlotsPerCell || s.Skulls == 0)).ToList();
                if (options.Count == 0) continue;
                WorldBestiary.Species? species;
                if (balanced) species = DrawBalanced(options, sky, rng, slot < BeginnerSlotsPerCell, rules);
                else
                {
                    int roll = rng.Next(options.Sum(s => WeightUnder(s, sky)));
                    species = options.First(s => (roll -= WeightUnder(s, sky)) < 0);
                }
                if (species is null) break;
                // A changed species must never reuse an older cached encounter identity.
                string version = rules?.IdentitySuffix ?? "";
                long id = StableHash($"{cell.Id}:{slot}:{generation}:{place.Id}:{species.MonsterId}{version}") & long.MaxValue;
                spawns.Add(new Spawn(id | 1L << 61, species.MonsterId, species.Difficulty, place.Id, cell.Id,
                    start * 1000L, LifetimeSeconds));
                used.Add(place.Id);
                break;
            }
            // Supplemental slots use the same fixed partition and generation as their original slot.
            // They cannot move, replace or overlap an existing monster, herb or nemeton. Reducing the
            // policy removes later supplemental slots only; already served encounters retain their TTL.
            for (int extra = slot + MonstersPerCell; extra < monsterSlotsPerCell; extra += MonstersPerCell)
            {
                long extraSeed = StableHash($"{cell.Id}:extra:{extra}:{generation}");
                var extraRng = new Random((int)(extraSeed ^ (extraSeed >> 32)));
                foreach (var place in share.Where(p => !used.Contains(p.Id)).OrderBy(_ => extraRng.Next()))
                {
                    var options = WorldBestiary.All.Where(s => Fits(s, place.Biomes, sky) &&
                        (balanced || slot >= BeginnerSlotsPerCell || s.Skulls == 0)).ToList();
                    if (options.Count == 0) continue;
                    WorldBestiary.Species? species;
                    if (balanced) species = DrawBalanced(options, sky, extraRng, slot < BeginnerSlotsPerCell, rules);
                    else
                    {
                        int roll = extraRng.Next(options.Sum(s => WeightUnder(s, sky)));
                        species = options.First(s => (roll -= WeightUnder(s, sky)) < 0);
                    }
                    if (species is null) break;
                    string version = rules?.IdentitySuffix ?? "";
                    long id = StableHash($"{cell.Id}:extra:{extra}:{generation}:{place.Id}:{species.MonsterId}{version}") & long.MaxValue;
                    extraSpawns.Add(new Spawn(id | 1L << 61, species.MonsterId, species.Difficulty, place.Id, cell.Id,
                        start * 1000L, LifetimeSeconds));
                    used.Add(place.Id);
                    break;
                }
            }
        }
        spawns.AddRange(extraSpawns);
        return spawns;
    }

    /// <summary>The conditions over a place: Day above 6° of sun elevation, Night below −6°, Dawn and Dusk in
    /// between (rising or falling), Noon and Midnight within an hour of the solar noon and midnight, the full moon
    /// within 1.5 days of the synodic middle, and rain or fog from the weather code.</summary>
    public static Conditions Sky(double lat, double lng, DateTimeOffset time, int weatherCode)
    {
        var (elevation, hourAngle) = Sun(lat, lng, time);
        var (after, _) = Sun(lat, lng, time.AddMinutes(10));
        bool rising = after > elevation;
        bool day = elevation > 6, night = elevation < -6;
        double moonAge = ((time - new DateTimeOffset(2000, 1, 6, 18, 14, 0, TimeSpan.Zero)).TotalDays % 29.530588853
                          + 29.530588853) % 29.530588853;
        return new Conditions(day, night, !day && !night && rising, !day && !night && !rising,
            Math.Abs(hourAngle) <= 15, Math.Abs(hourAngle) >= 165, Math.Abs(moonAge - 14.765) <= 1.5,
            WorldWeather.IsRaining(weatherCode), WorldWeather.IsFoggy(weatherCode));
    }

    /// <summary>True when the sun is more than 6° below the horizon.</summary>
    public static bool IsNight(double lat, double lng, DateTimeOffset time) => Sun(lat, lng, time).Elevation < -6;

    /// <summary>Sun elevation and hour angle in degrees (NOAA approximation; minutes of error do not matter here).</summary>
    public static (double Elevation, double HourAngle) Sun(double lat, double lng, DateTimeOffset time)
    {
        double day = time.UtcDateTime.DayOfYear, hours = time.UtcDateTime.TimeOfDay.TotalHours;
        double gamma = 2 * Math.PI / 365 * (day - 1 + (hours - 12) / 24);
        double eqTime = 229.18 * (0.000075 + 0.001868 * Math.Cos(gamma) - 0.032077 * Math.Sin(gamma)
                                  - 0.014615 * Math.Cos(2 * gamma) - 0.040849 * Math.Sin(2 * gamma));
        double decl = 0.006918 - 0.399912 * Math.Cos(gamma) + 0.070257 * Math.Sin(gamma) - 0.006758 * Math.Cos(2 * gamma)
                      + 0.000907 * Math.Sin(2 * gamma) - 0.002697 * Math.Cos(3 * gamma) + 0.00148 * Math.Sin(3 * gamma);
        double solarMinutes = hours * 60 + eqTime + 4 * lng;
        double hourAngle = (solarMinutes / 4 - 180) * Math.PI / 180;
        double phi = lat * Math.PI / 180;
        double cosZenith = Math.Sin(phi) * Math.Sin(decl) + Math.Cos(phi) * Math.Cos(decl) * Math.Cos(hourAngle);
        double elevation = 90 - Math.Acos(Math.Clamp(cosZenith, -1, 1)) * 180 / Math.PI;
        double hourDegrees = ((solarMinutes / 4 - 180) % 360 + 540) % 360 - 180;
        return (elevation, hourDegrees);
    }

    public static long StableHash(string text)
    {
        ulong hash = 14695981039346656037UL;
        foreach (char c in text) { hash ^= c; hash *= 1099511628211UL; }
        return (long)hash;
    }
}

/// <summary>
/// Herbs on the world map for reconstructed profiles. Client: GetLocationsByCell (40) carries them as
/// Placement&lt;Herb&gt; ([byte Type][string PlaceId][long InstanceId][int Type = herbs row id][int SpawnTime],
/// Herb.Deserialize 0x19342D8); HerbInstance.ShouldBeInstantiated shows a herb only once its SpawnTime (Unix
/// seconds) has passed. Clicking one sends GatherHerb (19). The five herb types and their prefabs are Client
/// (catalog: map/collectables/herbs/herb_*). Community (TouchTapPlay, 30 Jul 2021): green bushes on the map give
/// bundles of herbs and roots. The number of herbs per cell, their places, loot and respawn time are Authored:
/// <see cref="HerbsPerCell"/>, but at most a third of the cell's places, so that a cell with few places keeps most
/// of them for monsters.
/// </summary>
public static class WorldHerbs
{
    public const int HerbsPerCell = 4, RespawnSeconds = 3600;
    public const int HerbaId = 101, RadixId = 102;

    public static readonly IReadOnlyList<(int Id, string Slug)> Types = new[]
    {
        (1, "herb_blue"), (2, "herb_red"), (3, "herb_violet"), (4, "herb_white"), (5, "herb_yellow"),
    };

    public sealed record Herb(long InstanceId, int Type, string PlaceId, ulong CellId);

    // Plants grow in the open: woods, grass, wetland and fields first (Client BiomeType 1, 4, 5, 6).
    private static readonly int[] PlantBiomes = { 1, 4, 5, 6 };

    /// <summary>The herbs of one cell for the day's places, the same for every player and request; each player
    /// gathers them for themselves (HerbRespawns of their profile).</summary>
    public static List<Herb> ForCell(PlayableLocations.Cell cell)
    {
        long seed = WorldSpawns.StableHash($"{cell.Id}:herbs");
        var rng = new Random((int)(seed ^ (seed >> 32)));
        var places = cell.Places.Where(p => !cell.HasNestPlacement || p.Id != cell.NestPlaceId)
            .OrderBy(_ => rng.Next()).ToList();
        var green = places.Where(p => p.Biomes.Intersect(PlantBiomes).Any()).ToList();
        int count = Math.Min(HerbsPerCell, (places.Count + 2) / 3);
        return (green.Count >= count ? green : places).Take(count).Select(place =>
        {
            long id = WorldSpawns.StableHash($"{cell.Id}:herb:{place.Id}") & long.MaxValue;
            return new Herb(id | 1L << 60, Types[rng.Next(Types.Count)].Id, place.Id, cell.Id);
        }).ToList();
    }

    /// <summary>What one gathering yields, as ingredient ids (one per unit): two bundles of herbs and, one time
    /// in three, a root.</summary>
    public static List<int> Loot(long instanceId, long respawnWindow)
    {
        long seed = WorldSpawns.StableHash($"{instanceId}:{respawnWindow}:loot");
        var loot = new List<int> { HerbaId, HerbaId };
        if ((seed & long.MaxValue) % 3 == 0) loot.Add(RadixId);
        return loot;
    }
}
