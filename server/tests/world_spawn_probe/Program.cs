using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using WitcherRevival.Server.Net;

// Pure synthetic contract tests. No host, profile, geometry provider or network is started.
int checks = 0;
void Check(bool ok, string name) { if (!ok) throw new InvalidOperationException(name); checks++; }
WorldBestiary.Species Species(int id, int rarity, int skulls = 0, params string[] tags) =>
    new(id, "synthetic-" + id, "Synthetic", 1, rarity, skulls, 1, tags);
var clear = new WorldSpawns.Conditions(true, false, false, false, false, false, false, false, false);
var common = Species(1, 1);
var rare = Species(2, 2, 1);
var legend = Species(3, 3, 2);
var pools = new[] {
    new[] { common, rare, legend },
    Enumerable.Range(0, 50).Select(i => Species(100+i, 2, 2)).Concat(new[] {common, legend}).ToArray(),
    Enumerable.Range(0, 70).Select(i => Species(200+i, 3, 3)).Concat(new[] {common, rare}).ToArray(),
};
foreach (var pool in pools) foreach (bool beginner in new[] {false, true})
{
    var counts = new int[4];
    for (int ticket = 0; ticket < 109; ticket++)
        counts[WorldSpawns.DrawBalanced(pool, clear, new Tickets(ticket, 0), beginner)!.Rarity]++;
    Check(counts.SequenceEqual(new[] {0, 88, 18, 3}), "category mass independent of species count/beginner flag");
}
foreach (var pool in new[] {new[] {common}, new[] {rare, legend}, new[] {legend}, Array.Empty<WorldBestiary.Species>()})
{
    var counts = new int[4];
    for (int ticket = 0; ticket < 109; ticket++)
        counts[WorldSpawns.DrawBalanced(pool, clear, new Tickets(ticket, 0), true)?.Rarity ?? 0]++;
    var expected = pool.Length == 0 ? new[] {109, 0, 0, 0} : pool[0] == common ? new[] {0, 109, 0, 0}
        : pool[0] == rare ? new[] {88, 0, 18, 3} : new[] {106, 0, 0, 3};
    Check(counts.SequenceEqual(expected), "missing categories never inflate legendary mass");
}
var hardCommon = Species(4, 1, 2);
Check(WorldSpawns.DrawBalanced(new[] {hardCommon, common, rare, legend}, clear, new Tickets(0, 0), true) == common,
    "common beginner preference");
Check(WorldSpawns.DrawBalanced(new[] {hardCommon}, clear, new Tickets(0, 0), true) == hardCommon,
    "no unnecessary empty slot when no beginner fits");
Check(WorldSpawns.DrawBalanced(new[] {rare}, clear, new Tickets(88, 0), true) == rare,
    "beginner preference does not suppress rare draws");
var rainy = clear with { Rain = true };
var rainRare = Species(5, 2, 2, "RAIN");
int boosted = Enumerable.Range(0, 4).Count(ticket =>
    WorldSpawns.DrawBalanced(new[] {rare, rainRare}, rainy, new Tickets(88, ticket), false) == rainRare);
Check(boosted == 3, "environment multiplier applies within category");
Check(WorldSpawns.WeightUnder(common, clear) == 10 && WorldSpawns.WeightUnder(rare, clear) == 3 &&
      WorldSpawns.WeightUnder(legend, clear) == 1, "legacy and Aura lottery untouched");

PlayableLocations.Cell Cell(int biome, int count, long at, ulong id = 0x4704440000000000UL) =>
    new(id, 10, 20, Enumerable.Range(0, count).Select(i => new PlayableLocations.Place(
        $"lab-{id:x16}-{at/86400}-{i}", 10+i/10000.0, 20, new[] {biome}, "synthetic")).ToArray());
var historical = new List<object>();
foreach (int biome in new[] {1, 5, 7, 10}) foreach (int count in new[] {0, 4, 24})
    foreach (long at in new[] {1790899199L, 1790899200L, 1790940000L}) foreach (int slots in new[] {6, 12, 18})
        historical.Add(WorldSpawns.ForCell(Cell(biome, count, at), at, _ => WorldWeather.Clear, slots, long.MaxValue));
string legacyHash = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(historical))).ToLowerInvariant();
// Generated independently from the previous deployed DLL c84fc151... on these 108 synthetic inputs.
Check(legacyHash == "04827d7b2e31b61e30c188bb4661a84573380b6b475003d0336df7fa18ab6020", "pre-activation byte-for-byte legacy compatibility");
const long activation = 1790940000;
foreach (int count in new[] {0, 4, 24}) foreach (long at in new[] {activation-1, activation, activation+900, activation+1800})
{
    var cell = Cell(1, count, at);
    var old = WorldSpawns.ForCell(cell, at, _ => WorldWeather.Clear, 18, long.MaxValue);
    var modern = WorldSpawns.ForCell(cell, at, _ => WorldWeather.Clear, 18, 0);
    var actual = WorldSpawns.ForCell(cell, at, _ => WorldWeather.Clear, 18, activation);
    var expected = old.Where(s => s.SpawnTimeMs/1000 < activation)
        .Concat(modern.Where(s => s.SpawnTimeMs/1000 >= activation)).OrderBy(s => s.InstanceId);
    Check(actual.OrderBy(s => s.InstanceId).SequenceEqual(expected), "generation transition preserves old records through TTL");
    Check(actual.All(s => s.Ttl == 1800) && actual.Select(s => s.PlaceId).Distinct().Count() == actual.Count,
        "unique places and stable TTL");
    Check(!actual.Select(s => s.PlaceId).Intersect(WorldHerbs.ForCell(cell).Select(h => h.PlaceId)).Any(), "no herb overlap");
}

// Lock the currently deployed default lottery and identities, independently captured from its DLL.
var balancedReference = new List<object>();
foreach (int biome in new[] {1, 5, 7, 10}) foreach (int count in new[] {0, 4, 24})
    foreach (long at in new[] {1790899199L, 1790899200L, 1790940000L}) foreach (int slots in new[] {6, 12, 18})
        balancedReference.Add(WorldSpawns.ForCell(Cell(biome, count, at), at, _ => WorldWeather.Clear, slots, 0,
            WorldBalance.Default.At));
string balancedHash = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(balancedReference))).ToLowerInvariant();
Check(balancedHash == "bd31267020386e8443c3e105cda2121b571fdb7b652e864db8edb53bb44a6424",
    "default policy preserves currently deployed 88:18:3 algorithm and IDs");
var categoryRules = new WorldBalance.Rules(2, 3, 1, []);
var categoryCounts = new int[4];
for (int ticket = 0; ticket < 6; ticket++)
    categoryCounts[WorldSpawns.DrawBalanced(pools[0], clear, new Tickets(ticket, 0), true, categoryRules)!.Rarity]++;
Check(categoryCounts.SequenceEqual(new[] {0, 2, 3, 1}), "operator category weights control exact ticket mass");
Check(WorldSpawns.DrawBalanced(new[] {common}, clear, new Tickets(0), true, new(0, 1, 0, [])) is null,
    "zero common category cannot reappear through fallback");
Check(WorldSpawns.DrawBalanced(new[] {common, hardCommon}, clear, new Tickets(0, 0), true,
    new(1, 0, 0, new() {[common.MonsterId] = 0})) == hardCommon, "disabled beginner does not hide enabled hard common");
Check(WorldSpawns.DrawBalanced(new[] {common}, clear, new Tickets(0), true,
    new(1, 0, 0, new() {[common.MonsterId] = 0})) is null, "disabled species never drawn");
var boostedRules = new WorldBalance.Rules(0, 1, 0, new() {[rare.MonsterId] = 2, [rainRare.MonsterId] = 4});
int multiplierHits = Enumerable.Range(0, 14).Count(ticket =>
    WorldSpawns.DrawBalanced(new[] {rare, rainRare}, rainy, new Tickets(0, ticket), false, boostedRules) == rainRare);
Check(multiplierHits == 12, "species multipliers combine with environmental boosts");
Check(new WorldBalance.Rules(SpeciesWeights: new() {[31] = 1}).IdentitySuffix == ":balance88-18-3",
    "explicit defaults preserve canonical identities");

var changedRules = new WorldBalance.Rules(100, 0, 0, new() {[31] = 0});
var timeline = WorldBalance.Append(WorldBalance.Default, changedRules, activation, 0);
Check(timeline.Versions[^1].FromUnixSeconds == activation+1, "edits start in a strictly future second");
var futureGate = WorldBalance.Append(WorldBalance.Default, changedRules, activation, activation+10000);
Check(futureGate.Versions[^1].FromUnixSeconds == activation+10000, "original immutable activation remains respected");
var restarted = WorldBalance.Parse(JsonSerializer.SerializeToUtf8Bytes(timeline, WorldPolicy.Json));
foreach (long at in new[] {activation, activation+1, activation+900, activation+1800, activation+1801})
{
    var cell = Cell(1, 24, at);
    var before = WorldSpawns.ForCell(cell, at);
    var after = WorldSpawns.ForCell(cell, at, balanceAt: _ => changedRules);
    var actual = WorldSpawns.ForCell(cell, at, balanceAt: timeline.At);
    var expected = before.Where(s => s.SpawnTimeMs/1000 <= activation)
        .Concat(after.Where(s => s.SpawnTimeMs/1000 > activation)).OrderBy(s => s.InstanceId);
    Check(actual.OrderBy(s => s.InstanceId).SequenceEqual(expected), "operator edit preserves old generations and draws new policy");
    Check(actual.SequenceEqual(WorldSpawns.ForCell(cell, at, balanceAt: restarted.At)), "serialized restart preserves all living IDs");
    Check(WorldSpawns.ForCell(cell, at, balanceFromUnixSeconds: activation+10000, balanceAt: timeline.At)
        .SequenceEqual(WorldSpawns.ForCell(cell, at, balanceFromUnixSeconds: activation+10000)), "timeline cannot override legacy activation gate");
}
var restored = WorldBalance.Append(timeline, WorldBalance.DefaultRules, activation+900, 0);
Check(restored.At(activation+1).IdentitySuffix == changedRules.IdentitySuffix &&
    restored.At(activation+901).IdentitySuffix == WorldBalance.DefaultRules.IdentitySuffix,
    "restoring previous rules is a new revision, not a rewritten timeline");
var replaced = WorldBalance.Append(timeline, categoryRules, activation, 0);
Check(replaced.Versions.Length == 2 && replaced.At(activation).IdentitySuffix == WorldBalance.DefaultRules.IdentitySuffix,
    "pending same-second edit can be replaced without touching living policy");
var many = WorldBalance.Default;
for (int i = 0; i < 127; i++) many = WorldBalance.Append(many, changedRules, activation+i, 0);
Check(many.Versions.Length == 128, "bounded history reaches documented capacity");
bool refused = false;
try { WorldBalance.Append(many, changedRules, activation+127, 0); } catch (InvalidDataException) { refused = true; }
Check(refused, "history limit refuses without dropping living revisions");
var pruned = WorldBalance.Append(many, WorldBalance.DefaultRules, activation+3600, 0);
Check(pruned.Versions.Length == 2 && pruned.At(activation+3600).IdentitySuffix == changedRules.IdentitySuffix,
    "pruning retains the predecessor needed by the oldest living generation");
bool parseRefused = false;
try { WorldBalance.Parse(JsonSerializer.SerializeToUtf8Bytes(new WorldBalance.Schedule(1,
    [new(100, changedRules), new(100, WorldBalance.DefaultRules)]), WorldPolicy.Json)); }
catch (InvalidDataException) { parseRefused = true; }
Check(parseRefused, "persisted duplicate generation boundaries are refused");

// Exercise the production selector at scale; observations are not original-publisher probabilities.
var rng = new Random(20261002);
var sampleCounts = new int[3];
const int draws = 1_000_000;
for (int i = 0; i < draws; i++) sampleCounts[WorldSpawns.DrawBalanced(pools[0], clear, rng, false)!.Rarity-1]++;
foreach (int i in Enumerable.Range(0, 3))
{
    double p = new[] {88, 18, 3}[i] / 109.0;
    Check(Math.Abs(sampleCounts[i]-draws*p) < 6*Math.Sqrt(draws*p*(1-p)), "million production draws within six sigma");
}
var contexts = new List<object>();
foreach (int biome in new[] {1, 5, 7})
{
    var counts = new int[3]; int zero = 0;
    for (int hour = 0; hour < 24; hour++) for (int k = 0; k < 32; k++)
    {
        long at = 1790899200 + hour*3600;
        foreach (var spawn in WorldSpawns.ForCell(Cell(biome, 24, at, 0x4704440000000000UL + ((ulong)k<<40)), at))
        {
            var s = WorldBestiary.Of(spawn.MonsterId)!; counts[s.Rarity-1]++; if (s.Skulls == 0) zero++;
        }
    }
    contexts.Add(new {biome, total = counts.Sum(), counts, percent = counts.Select(n => 100.0*n/counts.Sum()), zeroSkullPercent = 100.0*zero/counts.Sum()});
}
// Warm steady-state cell cost; no sidecar/network latency is included.
var benchmarkCell = Cell(1, 24, activation);
for (int i = 0; i < 100; i++) WorldSpawns.ForCell(benchmarkCell, activation);
long allocated = GC.GetAllocatedBytesForCurrentThread(); var timer = Stopwatch.StartNew();
for (int i = 0; i < 5000; i++) WorldSpawns.ForCell(benchmarkCell, activation+i);
timer.Stop(); allocated = GC.GetAllocatedBytesForCurrentThread()-allocated;
Console.WriteLine(JsonSerializer.Serialize(new {status="PASS", checks, legacyHash, balancedHash, draws, sampleCounts, contexts,
    benchmark = new {cells=5000, milliseconds=timer.Elapsed.TotalMilliseconds, bytes=allocated,
        scope="single-process warmed synthetic generation; excludes transport, geometry and client rendering"}}));

sealed class Tickets(params int[] values) : Random
{
    private int index;
    public override int Next(int maxValue)
    {
        int value = values[index++];
        if (value < 0 || value >= maxValue) throw new InvalidOperationException("invalid synthetic ticket");
        return value;
    }
}
