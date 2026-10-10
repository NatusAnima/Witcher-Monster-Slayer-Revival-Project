using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The dashboard's debug tools for one player (Admin:DebugTools, on the Players tab): set orens, level and skill points, learn
/// every skill, give or take items, switch invincibility and one-hit kills, bring the quests next to the player, set the time
/// of day and moon the quests see, and run the quests step by step (QuestRunner.cs). Changes are saved by
/// LocalProfileStore.DebugUpdate, which no task or trinket counts (a quest step goes through the game's own handler instead,
/// so it counts as play).
///
/// A running game learns of them through server pushes of replies it already reads: the client turns every message into a
/// MethodMessage signal, and the subscribers of GetPlayerInfo (3: experience, so the level, and orens), GetInventory (5),
/// GetKnownRecipes (6), GetEquipment (9), GetSkills (63), GetBrewers (69) and GetPlayerModifiers (91) replace their state.
/// Pushes wait in a queue until a session of the player has finished booting (ResolveRewards 119, the post-sync gate) and
/// go out after its next reply; a boot (GetInitialPlayerData 115) reads everything afresh, so it drops them. Quest places
/// reach the game when it next loads its map (a restart): the client keeps the places it has.
/// </summary>
public sealed partial class PlayerService
{
    // Debug player modifiers (Reconstruction's player_modifiers and player_modifier_to_effect rows). Gameplay can never add
    // them: AddPlayerModifier (90) takes only the story's ids. ImproveHealth (40) and ImproveAttackPower (41) at OnStart (1)
    // multiply health and attack by 1 + power/100 when a fight starts (HealthModule.IncreaseHealth), and the client applies
    // player modifiers to world, story and nest fights (PlayerModifiersModule.GetActiveEffects). The slugs are two of the
    // client's own modifier names that nothing else uses, so its effects panel has a name and an icon for them.
    public const int InvincibleModifier = 901, OneHitModifier = 902;

    public static readonly IReadOnlyList<(int Id, string Slug, int Effect)> DebugModifiers =
        [(InvincibleModifier, "modifier_maidens_skin", 40), (OneHitModifier, "modifier_dead_honey", 41)];

    public const int DebugModifierPower = 100_000;

    // Time for quests: one bit per AstroConditionNode.condition (+0x44: full moon 0, sunrise 1, sunset 2, day 3) the game's
    // quests see as true, or -1 for the phone's own sky. Kept until the server restarts; sent with the weather (hook.js).
    private int sky = -1;
    private static readonly string[] SkyParts = ["a full moon", "dawn", "dusk", "daylight"];

    /// <summary>The time for quests the debug tools set (-1: the phone's own sky).</summary>
    public int Sky => Volatile.Read(ref sky);

    private static string SkyName(int mask) => mask < 0 ? "the phone's own sky"
        : string.Join(" and ", SkyParts.Where((_, bit) => (mask >> bit & 1) == 1)) is { Length: > 0 } parts ? parts : "night";

    public sealed record DebugRequest(string Action, int? Value = null, string? Kind = null, int? Item = null, int? Amount = null,
        bool? On = null);

    /// <summary>What a debug action did: the saved revision, the pushes queued and whether a running game takes them now.</summary>
    public sealed record DebugOutcome(long Revision, int[] Pushes, bool Live, string Effect);

    /// <summary>A debug action the player's state cannot take; the dashboard shows the message.</summary>
    public sealed class DebugRefusal(string message) : Exception(message);

    private readonly object pushGate = new();
    private readonly SortedSet<int> pendingPushes = [];
    private readonly HashSet<Guid> bootedSessions = [];

    /// <summary>Applies one debug action (see the class summary); <paramref name="backup"/> receives the profile before it.
    /// Throws ArgumentException for a malformed request and DebugRefusal for one the player's state cannot take.</summary>
    public DebugOutcome Debug(DebugRequest r, Action<LocalProfileStore.Profile> backup)
    {
        if (profiles.Snapshot().Player is null) throw new DebugRefusal("This profile uses the legacy format, which the debug tools cannot change.");
        int now = UnixSeconds();
        Func<LocalProfileStore.PlayerState, LocalProfileStore.PlayerState?> change;
        int[] pushes;
        string effect;
        switch (r.Action)
        {
            case "gold":
                int gold = Within(r.Value, 0, 100_000_000, "Orens");
                (change, pushes, effect) = (p => p with { Gold = gold }, [M_GetPlayerInfo], $"Orens set to {gold}.");
                break;
            case "level":
                int level = Within(r.Value, 1, Reconstruction.MaxLevel, "Level");
                // Five skill points per level up or down; no LevelUp push or level rewards for levels set here.
                change = p => p with
                {
                    Exp = Reconstruction.ExpThreshold(level), LevelAnnounced = level,
                    SkillPoints = Math.Max(0, p.SkillPoints + (level - Reconstruction.LevelForExp(p.Exp)) * Reconstruction.SkillPointsPerLevel),
                };
                (pushes, effect) = ([M_GetPlayerInfo, 63], $"Level set to {level}, with skill points to match.");
                break;
            case "skillPoints":
                int points = Within(r.Value, 0, 100_000, "Skill points");
                (change, pushes, effect) = (p => p with { SkillPoints = points }, [63], $"Skill points set to {points}.");
                break;
            case "allSkills":
                (change, pushes, effect) = (p => p with { Skills = p.Skills.Union(Reconstruction.Skills.Select(s => s.Id)).ToList() },
                    [63, 6], "Every skill learned.");
                break;
            case "item":
                (change, pushes, effect) = ItemChange(r);
                break;
            case "invincible" or "oneHit":
                int id = r.Action == "invincible" ? InvincibleModifier : OneHitModifier;
                bool on = r.On ?? throw new ArgumentException("Say on or off.");
                change = p =>
                {
                    var kept = LiveModifiers(p, now).Where(m => m.Id != id).ToList();
                    if (on) kept.Add(new LocalProfileStore.ModifierState(id, now, 0));
                    return p with { Modifiers = kept };
                };
                (pushes, effect) = ([M_GetPlayerModifiers],
                    $"{(r.Action == "invincible" ? "Invincibility" : "One-hit kills")} {(on ? "on" : "off")} from the next fight.");
                break;
            case "questsHere":
                (change, effect) = QuestsHere();
                pushes = [];
                break;
            case "questStep":   // the quest runner (QuestRunner.cs)
                return CompleteQuestStep(r.Value ?? throw new ArgumentException("Choose a quest."), backup);
            case "sky":
                int mask = Within(r.Value, -1, 15, "Time for quests");
                var marked = profiles.DebugUpdate(p => p, backup);
                Volatile.Write(ref sky, mask);
                log.LogInformation("Debug action=sky mask={Mask}", mask);
                return new DebugOutcome(marked.Revision, [], Live, $"Quests see {SkyName(mask)} from the game's next weather " +
                    "update (about every 5 minutes) or its next start, until the server restarts. The game needs this version's hook.");
            default:
                throw new ArgumentException("Unknown debug action.");
        }
        var saved = profiles.DebugUpdate(change, backup);
        lock (pushGate) pendingPushes.UnionWith(pushes);
        log.LogInformation("Debug action={Action} revision={Revision} pushes={Pushes}", r.Action, saved.Revision, pushes.Length);
        return new DebugOutcome(saved.Revision, pushes, Live, effect);
    }

    /// <summary>Whether a session of this player has finished booting, so queued pushes reach the game after its next reply.</summary>
    public bool Live { get { lock (pushGate) return bootedSessions.Count > 0; } }

    private static int Within(int? value, int low, int high, string what) =>
        value is int v && v >= low && v <= high ? v : throw new ArgumentException($"{what} must be a whole number from {low} to {high}.");

    // Give (amount > 0) or take an item: stacks by kind, swords and armours (owned once; one taken off is replaced by the
    // starting one), and crafting stations (each a new instance; the unlimited basic one stays).
    private (Func<LocalProfileStore.PlayerState, LocalProfileStore.PlayerState?>, int[], string) ItemChange(DebugRequest r)
    {
        int amount = Within(r.Amount, -100_000, 100_000, "Amount");
        if (amount == 0) throw new ArgumentException("Amount must not be 0.");
        int id = r.Item ?? throw new ArgumentException("Choose an item.");
        string kind = r.Kind ?? throw new ArgumentException("Choose a kind of item.");
        string verb = amount > 0 ? "Gave" : "Took";
        switch (kind)
        {
            case "swords" or "armors":
                bool sword = kind == "swords";
                if ((sword ? Reconstruction.SwordById(id) : Reconstruction.ArmorById(id)) is null) throw new ArgumentException("Unknown item.");
                int starting = sword ? Reconstruction.StartingGear.Sword : Reconstruction.StartingGear.Armor;
                if (amount < 0 && id == starting) throw new DebugRefusal("The starting sword and armour stay.");
                return (p =>
                {
                    var gear = EquipmentOf(p);
                    var owned = (sword ? gear.Swords : gear.Armors).Where(x => x != id).ToList();
                    if (amount > 0) owned.Add(id);
                    gear = sword ? gear with { Swords = owned, Sword = owned.Contains(gear.Sword) ? gear.Sword : starting }
                        : gear with { Armors = owned, Armor = owned.Contains(gear.Armor) ? gear.Armor : starting };
                    return p with { Equipment = gear };
                }, [M_GetEquipment], $"{verb} {(sword ? "sword" : "armour")} {id}.");
            case "brewers":
                if (Economy.Brewers.FirstOrDefault(b => b.Id == id && b != Economy.BasicBrewer) is not { } station)
                    throw new ArgumentException("Choose station 2 or 3.");
                return (p =>
                {
                    var brewers = EnsureBrewers(p);
                    for (int n = 0; n < amount; n++)
                        brewers.Add(new LocalProfileStore.BrewerState(brewers.Max(b => b.InstanceId) + 1, station.Id, station.Uses, Idle, 0));
                    // idle stations go first when taking
                    foreach (var gone in brewers.Where(b => b.Type == station.Id).OrderBy(b => b.WorkingRecipe != Idle).Take(-amount).ToList())
                        brewers.Remove(gone);
                    return p with { Brewers = brewers };
                }, [69], $"{verb} {Math.Abs(amount)} of station {id}.");
            default:
                bool known = kind switch
                {
                    ItemKinds.Lures => WorldNests.Lures.Any(l => l.Id == id),
                    SocialService.PackItems => id == SocialService.PackId,
                    "summoning_scrolls" => id == 2 && TasksEnabled,
                    _ => Reconstruction.KnownItem(kind, id),
                };
                if (!known) throw new ArgumentException("Unknown item.");
                return (p =>
                {
                    if (!p.Items.TryGetValue(kind, out var owned)) p.Items[kind] = owned = new Dictionary<int, int>();
                    int count = (int)Math.Clamp((long)owned.GetValueOrDefault(id) + amount, 0, int.MaxValue);
                    if (count == 0) owned.Remove(id); else owned[id] = count;
                    return p;
                }, [M_GetInventory], $"{verb} {Math.Abs(amount)} × {kind} {id}.");
        }
    }

    // New places for the quests in progress and the givers of the quests on offer: the playable places nearest the player's GPS
    // fix (else the loaded area's centre), each place once while there are enough, with new ids so the game's map takes them.
    private (Func<LocalProfileStore.PlayerState, LocalProfileStore.PlayerState?>, string) QuestsHere()
    {
        var snapshot = profiles.Snapshot();
        var keys = new List<string>();
        if (SeasonOne(snapshot) is { } story)
        {
            foreach (var node in StoryEngine.Active(story, snapshot.Facts, StoryNow(story)).Where(n => !n.BesidePlayer))
                for (int copy = 0; copy < Math.Max(1, node.Copies); copy++)
                    keys.Add(node.PlaceOf ?? StoryPlaceKey(node, copy));
            keys.AddRange(StoryEngine.Available(story, snapshot.Facts).Select(q => StoryEngine.RootOf(q.Id)?.Key).OfType<string>());
        }
        else if (Reconstruction.JointVentureNodes(snapshot.QuestStage, snapshot.Player!.StoryDone) is { } nodes)
            keys.AddRange(nodes.Select(n => n.Key));
        else if (snapshot.QuestStage is { } stage && Reconstruction.StoryDistance(stage) is not null)
            keys.Add(stage);
        keys = keys.Distinct().ToList();
        if (keys.Count == 0) throw new DebugRefusal("No quest in progress or on offer has a place on the map (the tutorial's stay beside the player).");
        var area = playable.Area;
        var cells = area.Count == 0 ? null : playable.Cells(area, 0);
        if (cells is not { Count: > 0 }) throw new DebugRefusal("Open the game first: the server needs the map around the player.");
        var position = PlayerPositionIn(cells);
        double lat = position?.Lat ?? cells.Average(c => c.Lat), lng = position?.Lng ?? cells.Average(c => c.Lng);
        var nearest = cells.SelectMany(c => c.Places.Select(p => (Cell: c.Id, Place: p)))
            .OrderBy(x => PlayableLocations.Distance(lat, lng, x.Place.Lat, x.Place.Lng)).Take(keys.Count).ToList();
        if (nearest.Count == 0) throw new DebugRefusal("The map around the player has no playable places.");
        var places = keys.Select((key, n) => (Key: key, Spot: nearest[n % nearest.Count])).ToDictionary(x => x.Key, x =>
            new LocalProfileStore.StoryPlace($"lab-story-{x.Key}-{Guid.NewGuid():N}", x.Spot.Place.Lat, x.Spot.Place.Lng,
                x.Spot.Place.Biomes, x.Spot.Cell));
        int farthest = (int)nearest.Max(x => PlayableLocations.Distance(lat, lng, x.Place.Lat, x.Place.Lng));
        return (p =>
            {
                var all = new Dictionary<string, LocalProfileStore.StoryPlace>(p.StoryPlaces ?? new());
                foreach (var (key, place) in places) all[key] = place;
                return p with { StoryPlaces = all };
            },
            $"Moved {keys.Count} quest place(s) within {farthest} m of {(position is null ? "the map's centre" : "you")}. " +
            "Restart the game to see them.");
    }

    // After each reply: a boot drops queued pushes, the post-sync gate marks the session booted, and a booted session gets them.
    private async Task DrainPushesAsync(Stream stream, int method, Guid session, CancellationToken ct)
    {
        int[] methods;
        lock (pushGate)
        {
            if (method == M_GetInitialPlayerData) { pendingPushes.Clear(); bootedSessions.Remove(session); return; }
            if (method == M_ResolveRewards) bootedSessions.Add(session);
            if (pendingPushes.Count == 0 || !bootedSessions.Contains(session)) return;
            methods = pendingPushes.ToArray();
            pendingPushes.Clear();
        }
        foreach (int pushed in methods)
        {
            byte[] payload = pushed switch
            {
                M_GetPlayerInfo => BuildGetPlayerInfoPayload(),
                M_GetInventory => BuildGetInventoryPayload(),
                M_GetPlayerModifiers => BuildGetPlayerModifiersResponse(),
                _ => InitialPlayerDataPart(pushed),
            };
            var push = ApiProtocol.BuildResponse(0, pushed, payload, ack: Array.Empty<long>());
            await FrameCodec.WriteAsync(stream, Ch_Api, push, ct);
            log.LogInformation("  TX  Api push Method={Method} debug ({Len}B)", pushed, push.Length);
        }
    }

    private void ForgetBootedSession(Guid session)
    {
        lock (pushGate) bootedSessions.Remove(session);
    }
}
