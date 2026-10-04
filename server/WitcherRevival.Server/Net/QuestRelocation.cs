using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    private sealed record MovableQuest(int Id, StoryEngine.Node Root,
        IReadOnlyList<StoryEngine.Node> Nodes, IReadOnlyList<StoryEngine.Node> Active);

    private readonly object relocationOfferGate = new();
    private readonly HashSet<long> recentRelocationOffers = [];
    private readonly Queue<long> relocationOfferOrder = new();

    // Diagnostic history only: never admits an otherwise unknown or stale destination.
    // Keep numeric IDs in memory; logs contain classifications and counts, not identifiers or positions.
    private void RememberRelocationOffers(IEnumerable<long> instances)
    {
        lock (relocationOfferGate)
            foreach (long instance in instances)
                if (recentRelocationOffers.Add(instance))
                {
                    relocationOfferOrder.Enqueue(instance);
                    while (relocationOfferOrder.Count > 256) recentRelocationOffers.Remove(relocationOfferOrder.Dequeue());
                }
    }

    private string UnknownRelocationKind(LocalProfileStore.Profile snapshot, IReadOnlyList<MovableQuest> quests, long instance)
    {
        if (instance == -1) return "client-missing-giver";
        if (instance == 0) return "client-zero-giver";
        if (snapshot.Player?.StoryPlaces?.Where(p => p.Key.StartsWith("relocation-", StringComparison.Ordinal))
                .Any(p => RelocationInstance(p.Value) == instance) == true) return "saved-inactive-giver";
        if (quests.Any(q => q.Root.Instance == instance)) return "story-root-instance";
        if (quests.SelectMany(q => q.Active).Any(n => Enumerable.Range(0, Math.Max(1, n.Copies))
                .Any(copy => n.Instance + copy == instance))) return "active-goal-instance";
        lock (relocationOfferGate)
            if (recentRelocationOffers.Contains(instance)) return "retired-map-offer";
        return ((ulong)instance & 0xFFFF000000000000UL) == 0x6000000000000000UL
            ? "unknown-generated-giver" : "other-instance";
    }

    private static StoryEngine.Node RelocationNode(int quest, Reconstruction.StoryNode node) =>
        new(node.NodeId, quest, node.Key, node.Graph, node.PoiSettings, node.InstanceId, "poi", "", "",
            node.MinDistance, node.MaxDistance, node.Near, null, 1);

    private static IEnumerable<MovableQuest> MovableQuests(LocalProfileStore.Profile snapshot)
    {
        if (snapshot.Player is not { } player) yield break;
        if (SeasonOne(snapshot) is { } story)
        {
            var active = StoryEngine.Active(story, snapshot.Facts, StoryNow(story)).ToList();
            foreach (int id in story.Started.Where(id => !story.Finished.Contains(id)))
                if (StoryEngine.RootOf(id) is { } root)
                    yield return new(id, root, StoryEngine.Nodes.Where(n => n.Quest == id).ToList(),
                        active.Where(n => n.Quest == id).ToList());
        }
        else if (Reconstruction.JointVentureNodes(snapshot.QuestStage, player.StoryDone) is { } joint)
        {
            var root = Reconstruction.JointVentureStart;
            yield return new(146, new(root.NodeId, 146, "relocation-root-146", root.Graph, root.PoiSettings,
                    root.InstanceId, "giver", "", "", 80, 300, null, null, 1),
                Reconstruction.JointVentureAll.Select(n => RelocationNode(146, n)).ToList(),
                joint.Select(n => RelocationNode(146, n)).ToList());
        }
        else if (Reconstruction.StoryDistance(snapshot.QuestStage) is { } band)
        {
            bool griffin = snapshot.QuestStage == LocalProfileStore.GriffinStage;
            var node = new StoryEngine.Node(griffin ? 3 : 2, 145, snapshot.QuestStage!,
                griffin ? GriffinGraphPath : "s00/prolog/prolog_01_dead_horse",
                griffin ? GriffinSettingsPath : "assets/_bundledassets/story/poi_settings/s00/prolog/dead_horse_head.asset",
                griffin ? GriffinInstanceId : 5124756197357912298L, "poi", "", "", band.Min, band.Max, null, null, 1);
            var root = new StoryEngine.Node(1, 145, "relocation-root-145", "s00/prolog/prolog_01_thorstein",
                "assets/_bundledassets/story/poi_settings/s00/prolog/thorstein_hurt_lq.asset",
                5124757777905877225L, "giver", "", "", 80, 300, null, null, 1);
            yield return new(145, root, [node], [node]);
        }
    }

    private static string RelocationKey(int quest) => $"relocation-{quest}";

    private static bool IsRelocationKey(string key, int quest) =>
        key == RelocationKey(quest) || key.StartsWith(RelocationKey(quest) + "-", StringComparison.Ordinal);

    private static IEnumerable<LocalProfileStore.StoryPlace> RelocationTargets(
        Dictionary<string, LocalProfileStore.StoryPlace>? places, int quest) =>
        places?.Where(p => IsRelocationKey(p.Key, quest)).Select(p => p.Value).DistinctBy(p => p.Id) ?? [];

    // A separate, hidden giver is needed even after the root's activation criteria stop holding.
    // SetActiveQuestGivers (RVA 0x1901768) hides started quests, but GetTrackedQuestGiverPOIInstanceID
    // (0x19A5F24) searches IsQuestGiver regardless of Activated. The original story anchor must stay put.
    // New place AND instance ids matter: UpdateLocations (0x19015E0) and RPC40 (0x1903108) skip known ids.
    private static long RelocationInstance(LocalProfileStore.StoryPlace place) =>
        0x6000000000000000L | (BinaryPrimitives.ReadInt64BigEndian(SHA256.HashData(Encoding.UTF8.GetBytes(place.Id)))
            & 0x0000FFFFFFFFFFFFL);

    private IEnumerable<(StoryEngine.Node Node, LocalProfileStore.StoryPlace Place, long Instance)> RelocationGivers(
        LocalProfileStore.Profile snapshot, IReadOnlyList<PlayableLocations.Cell> requested)
    {
        var quests = MovableQuests(snapshot).Where(q => q.Active.Any(n => !n.Queued)).ToList();
        var area = playable.Area;
        if (quests.Count == 0 || area.Count == 0 || requested.Count == 0) yield break;
        foreach (var quest in quests)
        {
            string key = RelocationKey(quest.Id);
            var offered = RelocationTargets(snapshot.Player!.StoryPlaces, quest.Id).ToList();
            var place = offered.FirstOrDefault(p => p.CellId is ulong id && area.Contains(id) && requested.Any(c => c.Id == id));
            if (place is null)
            {
                // New destinations must be in this response. A point in a retained neighboring
                // cell would be filtered out below and remain unknown to the client's giver search.
                place = PickRelocationPlace(key, 80, 300, null, [], requested.Where(c => area.Contains(c.Id)).ToList());
                if (place is null) continue;
                // The client chooses its nearest cached giver, which can still be an older offer.
                // Keep one issued offer per observed cell, bounded by Area (at most 64 cells), so
                // a new delta never invalidates a still-nearby giver the journal may select.
                profiles.UpdatePlayer(new Dictionary<int, int>(), null, p =>
                {
                    var places = new Dictionary<string, LocalProfileStore.StoryPlace>(p.StoryPlaces ?? new());
                    var retained = RelocationTargets(places, quest.Id)
                        .Where(t => t.CellId is ulong id && area.Contains(id)).ToList();
                    foreach (string oldKey in places.Keys.Where(k => IsRelocationKey(k, quest.Id)).ToList()) places.Remove(oldKey);
                    foreach (var target in retained) places[$"{key}-{target.CellId:X16}"] = target;
                    places[$"{key}-{place.CellId:X16}"] = place;
                    places[key] = place;
                    return p with { StoryPlaces = places };
                });
                log.LogInformation("  Relocation destination quest={Quest} result=ready", quest.Id);
            }
            yield return (quest.Root, place, RelocationInstance(place));
        }
    }

    private static LocalProfileStore.StoryPlace? PickRelocationPlace(string key, double min, double max,
        LocalProfileStore.StoryPlace? near, IEnumerable<LocalProfileStore.StoryPlace> taken,
        IReadOnlyList<PlayableLocations.Cell> cells, (double Lat, double Lng)? player = null)
    {
        if (cells.Count == 0) return null;
        double lat = near?.Lat ?? player?.Lat ?? cells.Average(c => c.Lat),
            lng = near?.Lng ?? player?.Lng ?? cells.Average(c => c.Lng);
        var band = cells.SelectMany(c => c.Places.Select(p => (Cell: c.Id, Place: p))).Where(p =>
            PlayableLocations.Distance(lat, lng, p.Place.Lat, p.Place.Lng) is var d && d >= min && d <= max).ToList();
        var spaced = band.Where(p => taken.All(t =>
            PlayableLocations.Distance(t.Lat, t.Lng, p.Place.Lat, p.Place.Lng) >= (near is null ? 100 : 40))).ToList();
        var pool = spaced.Count > 0 ? spaced : band;
        if (pool.Count == 0) return null;
        var open = pool.Where(p => p.Place.Biomes.Contains(1) || p.Place.Biomes.Contains(4)).ToList();
        if (open.Count > 0) pool = open;
        var pick = pool[Random.Shared.Next(pool.Count)];
        return new($"lab-story-{key}-{Guid.NewGuid():N}", pick.Place.Lat, pick.Place.Lng, pick.Place.Biomes, pick.Cell);
    }

    private byte[] RelocateQuest(long instance)
    {
        byte[] Refuse(string reason)
        {
            log.LogInformation("  RelocateQuest result=refused reason={Reason}", reason);
            return new byte[13]; // Success=false, all three collections are still mandatory.
        }
        var snapshot = profiles.Snapshot();
        var saved = snapshot.Player?.StoryPlaces;
        if (saved is null) return Refuse("no-places");
        var quests = MovableQuests(snapshot).ToList();
        var quest = quests.FirstOrDefault(q =>
            RelocationTargets(saved, q.Id).Any(target => RelocationInstance(target) == instance));
        if (quest is null)
        {
            var offers = quests.SelectMany(q => RelocationTargets(saved, q.Id)).ToList();
            log.LogInformation("  Relocation lookup kind={Kind} movable={Movable} offers={Offers} inArea={InArea}",
                UnknownRelocationKind(snapshot, quests, instance), quests.Count, offers.Count,
                offers.Count(p => p.CellId is ulong id && playable.Area.Contains(id)));
            return Refuse("unknown-giver");
        }
        var target = RelocationTargets(saved, quest.Id).First(t => RelocationInstance(t) == instance);
        var area = playable.Area;
        if (target.CellId is not ulong cell || !area.Contains(cell)) return Refuse("stale-area");

        LocalProfileStore.StoryPlace? Existing(StoryEngine.Node node, int copy) => node.PlaceOf is { } owner
            ? saved.GetValueOrDefault(owner) : saved.GetValueOrDefault(StoryPlaceKey(node, copy));
        // The client owns the distance rule (goal > AllowRelocateQuestMinDistance, 1000 m). The server sees cells, not
        // GPS: requiring the goal outside its 2 km area estimate refused every goal 1-2 km away, so only a placed goal is required.
        if (!quest.Active.Any(n => !n.Queued && Enumerable.Range(0, Math.Max(1, n.Copies))
                .Any(copy => Existing(n, copy) is not null)))
            return Refuse("goals-unplaced");
        // A retry with a new request id for the giver the quest already moved to cannot move it again.
        if (saved.GetValueOrDefault(quest.Root.Key)?.Id == target.Id) return Refuse("already-moved-here");
        var cells = playable.Cells(area, 0)?.Where(c => area.Contains(c.Id)).ToList();
        if (cells is null || cells.Count == 0) return Refuse("no-map");
        // Goals go around the player's GPS position when the collector reports one, else the area's centre.
        var player = PlayerPosition();
        var planned = new Dictionary<string, LocalProfileStore.StoryPlace>(saved);
        var keys = quest.Nodes.SelectMany(n => Enumerable.Range(0, Math.Max(1, n.Copies))
            .Select(copy => StoryPlaceKey(n, copy))).ToHashSet();
        foreach (string key in keys) planned.Remove(key);
        // Return visits to the original giver now belong at the destination. Merely loading an area
        // never changes this anchor; only this accepted relocation does.
        planned[quest.Root.Key] = target;
        var visiting = new HashSet<string>();
        LocalProfileStore.StoryPlace? Plan(StoryEngine.Node node, int copy = 0)
        {
            if (node.PlaceOf is { } owner)
                return quest.Nodes.FirstOrDefault(n => n.Key == owner) is { } parent ? Plan(parent) : null;
            string key = StoryPlaceKey(node, copy);
            if (planned.TryGetValue(key, out var known)) return known;
            if (!visiting.Add(key)) return null;
            var near = node.Near is { } anchor && quest.Nodes.FirstOrDefault(n => n.Key == anchor) is { } parentNode
                ? Plan(parentNode) : null;
            if (node.Near is not null && near is null) return null;
            var chosen = PickRelocationPlace(key, node.Min, node.Max, near, planned.Values, cells, player);
            visiting.Remove(key);
            if (chosen is not null) planned[key] = chosen;
            return chosen;
        }
        foreach (var node in quest.Nodes.Where(n => !n.Queued && !n.Button &&
                     (quest.Active.Any(a => a.Id == n.Id) || Enumerable.Range(0, Math.Max(1, n.Copies))
                         .Any(copy => saved.ContainsKey(StoryPlaceKey(n, copy))))))
            for (int copy = 0; copy < Math.Max(1, node.Copies); copy++)
                if (Plan(node, copy) is null) return Refuse("no-fitting-place");

        var updated = snapshot with { Player = snapshot.Player! with { StoryPlaces = planned } };
        // Serialize without StoryView's lazy writes: unrelated quests, rewards and facts are untouched.
        var b = new ByteBuffer(); b.WriteByte(1);
        if (SeasonOne(updated) is { } story)
        {
            var active = StoryEngine.Active(story, updated.Facts, StoryNow(story)).ToList();
            var placed = new List<(StoryEngine.Node Node, LocalProfileStore.StoryPlace Place, int Copy)>();
            foreach (var node in active.Where(n => !n.Queued))
                for (int copy = 0; copy < Math.Max(1, node.Copies); copy++)
                    if (planned.GetValueOrDefault(node.PlaceOf ?? StoryPlaceKey(node, copy)) is { } place)
                        placed.Add((node, place, copy));
            WriteQuestLocations(b, placed.Select(p => p.Place).DistinctBy(p => p.Id).ToList());
            b.WriteInt(placed.Count + active.Count(n => n.Queued));
            foreach (var (node, place, copy) in placed) WriteStoryNode(b, node, node.Instance + copy, place.Id, Reconstruction.DisplayNormal);
            foreach (var node in active.Where(n => n.Queued)) WriteStoryNode(b, node, node.Instance, TutPlaceId, Reconstruction.DisplayCloseFollow);
        }
        else
        {
            var placed = quest.Active.Select(n => (Node: n, Place: planned[n.Key])).ToList();
            WriteQuestLocations(b, placed.Select(p => p.Place).DistinctBy(p => p.Id).ToList());
            b.WriteInt(placed.Count);
            foreach (var (node, place) in placed) WriteStoryNode(b, node, node.Instance, place.Id,
                quest.Id == 145 ? Reconstruction.StoryDisplayMode(snapshot.QuestStage) : Reconstruction.DisplayNormal);
        }
        b.WriteInt(0);
        byte[] response = b.ToArray();
        bool applied = false;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
        {
            if (profiles.Snapshot().Revision != snapshot.Revision || !area.SequenceEqual(playable.Area)) return null;
            applied = true;
            return player with { StoryPlaces = planned };
        });
        if (!applied) return Refuse("state-changed");
        log.LogInformation("  RelocateQuest quest={Quest} result=moved nodes={Count}", quest.Id, quest.Active.Count);
        return response;
    }
}
