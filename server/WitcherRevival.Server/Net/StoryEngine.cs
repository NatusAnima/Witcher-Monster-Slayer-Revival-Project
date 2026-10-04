using System.Text.Json;
using System.Text.Json.Serialization;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Season 1 story, driven by data (Story/season1-story.json, built by server/story-1.1.116/season1_story.py from the
/// client's graphs and the quest overlay).
///
/// Client (1.1.116): StoryGraph builds one quest tree from `quests` and `quest_edges`; a quest's root node is the
/// node no `quest_node_edges` row leads to (BuildQuestMap 0x195A3A4). FillAvailableNodes (0x1959ED0) offers the root
/// node of every unfinished quest whose own and root-node activation criteria hold (IsAvailable 0x195ACE8); criteria
/// are one `f&lt;fact&gt;&lt;op&gt;&lt;value&gt;` expression (FactDatabaseModule.EvaluateSimpleExpression 0x18C07FC).
/// GetJournalLog (0x195A074) reads only the root's direct children, so every quest here is a child of the tutorial
/// (144) with season_id 0. PoiModule.SetActiveQuestGivers shows the GetLocationsByCell quest placements of offered
/// nodes, and other quest POIs only while their quest is started. A graph output (EndBehaviourGraph 57) of a quest
/// that is not started starts it; an endpoint output finishes it (QuestEndRequestNode 0x195CAB4).
///
/// The server keeps, per profile, the started and finished quests, the outputs reached (with the time) and the
/// tracked quest (<see cref="LocalProfileStore.StoryProgress"/>). A node shows while its quest is started and its
/// condition on the saved facts, reached outputs or elapsed time holds; the graphs set those facts themselves, so a
/// missed step is caught up by the next request. Queued nodes (QueueStoryGraphNode) stand beside the player while
/// their condition holds, whether or not their quest has started, because the client starts them right after the
/// queuing graph ends.
/// </summary>
public static class StoryEngine
{
    public const int TutorialQuest = 144;

    public sealed record Quest(int Id, string Code, string Name, string Journal, string Criteria);

    public sealed record Node(int Id, int Quest, string Key, string Graph, string Poi, long Instance, string Kind,
        string Root, string Show, double Min, double Max, string? Near, string? PlaceOf, int Copies)
    {
        [JsonIgnore] public bool Giver => Kind == "giver";
        [JsonIgnore] public bool Queued => Kind == "queued";
        [JsonIgnore] public bool Button => Kind == "button";
        [JsonIgnore] public bool OnMap => Kind is "poi" or "queued";
        public bool HasInstance(long instance) => instance >= Instance && instance < Instance + Copies;
    }

    public sealed record Output(int Id, int Node, string Name, bool Endpoint, int Exp, int Gold,
        Dictionary<string, Dictionary<int, int>> Items, Dictionary<int, int> Kills);

    // Original 1.1.116 uses mushroom_start; the later donor graph uses mushroom_timer_start.
    // These IDs identify extra client rows only. Both spellings reach the existing canonical output,
    // preserving saved completion IDs, first-reached times and rewards across a client rollback.
    private sealed record OutputAlias(int RowId, int Node, string Name, int CanonicalId);
    private static readonly OutputAlias[] OutputAliases =
    [
        new(20001, 18160, "mushroom_start", 1216),
        new(20002, 403, "mushroom_start", 1234),
    ];

    /// <summary>A player modifier of the season 1 graphs; Seconds, when set, replaces the graph's duration (LAB
    /// pacing, see season1_quests.py LAB_WAIT).</summary>
    public sealed record Modifier(int Id, string Slug, int? Seconds = null);

    private sealed record Data(List<Quest> Quests, List<Node> Nodes, List<Output> Outputs, List<Modifier> Modifiers,
        List<JsonElement> Monsters, Dictionary<string, int[]> Vulnerabilities);

    private static readonly JsonSerializerOptions Options = new() { PropertyNameCaseInsensitive = true };

    /// <summary>The story file as shipped (also served to the local tests).</summary>
    public static readonly string Json = LoadJson();

    private static readonly Data Story = JsonSerializer.Deserialize<Data>(Json, Options)
        ?? throw new InvalidDataException("Empty season 1 story.");

    public static IReadOnlyList<Quest> Quests => Story.Quests;
    public static IReadOnlyList<Node> Nodes => Story.Nodes;
    public static IReadOnlyList<Output> Outputs => Story.Outputs;
    public static IReadOnlyList<Modifier> Modifiers => Story.Modifiers;
    public static IReadOnlyDictionary<string, int[]> Vulnerabilities => Story.Vulnerabilities;
    public static IEnumerable<string> MonsterRows => Story.Monsters.Select(row => JsonSerializer.Serialize(row));

    private static string LoadJson()
    {
        using var stream = typeof(StoryEngine).Assembly.GetManifestResourceStream("season1-story.json")
            ?? throw new InvalidDataException("The season 1 story resource is missing.");
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    public static Quest? QuestById(int id) => Quests.FirstOrDefault(q => q.Id == id);
    public static Node? NodeById(int id) => Nodes.FirstOrDefault(n => n.Id == id);
    public static Node? NodeByKey(string key) => Nodes.FirstOrDefault(n => n.Key == key);
    public static Node? RootOf(int questId) =>
        Nodes.FirstOrDefault(n => n.Quest == questId && n.Giver) ?? Nodes.FirstOrDefault(n => n.Quest == questId && n.Queued);
    public static Output? OutputOf(int nodeId, string name)
    {
        var alias = OutputAliases.FirstOrDefault(a => a.Node == nodeId && a.Name == name);
        return Outputs.FirstOrDefault(o => o.Node == nodeId && (o.Name == name || o.Id == alias?.CanonicalId));
    }

    // ── Conditions ──────────────────────────────────────────────────────────────────────────
    /// <summary>A node condition: alternatives joined by `|`, atoms by `&amp;`. Atoms: `f&lt;fact&gt;&lt;op&gt;&lt;value&gt;`
    /// (a missing fact is 0), `out:&lt;node&gt;.&lt;output&gt;`, `wait:&lt;node&gt;.&lt;output&gt;:&lt;seconds&gt;`, `done:&lt;quest&gt;`,
    /// `started:&lt;quest&gt;`, each negated by a leading `!`. Empty holds.</summary>
    public static bool Holds(string condition, IReadOnlyDictionary<int, int> facts, LocalProfileStore.StoryProgress progress,
        long now)
    {
        if (string.IsNullOrWhiteSpace(condition)) return true;
        return condition.Split('|').Any(alternative =>
            alternative.Split('&').All(atom => Atom(atom.Trim(), facts, progress, now)));
    }

    private static bool Atom(string atom, IReadOnlyDictionary<int, int> facts, LocalProfileStore.StoryProgress progress, long now)
    {
        bool negate = atom.StartsWith('!');
        if (negate) atom = atom[1..];
        bool value;
        if (atom.StartsWith("out:")) value = ReachedAt(progress, atom[4..]) is not null;
        else if (atom.StartsWith("wait:"))
        {
            int colon = atom.LastIndexOf(':');
            value = ReachedAt(progress, atom[5..colon]) is long at && now - at >= long.Parse(atom[(colon + 1)..]);
        }
        else if (atom.StartsWith("done:")) value = progress.Finished.Contains(int.Parse(atom[5..]));
        else if (atom.StartsWith("started:")) value = progress.Started.Contains(int.Parse(atom[8..]));
        else value = Fact(atom, facts);
        return value != negate;
    }

    private static long? ReachedAt(LocalProfileStore.StoryProgress progress, string reference)
    {
        int dot = reference.IndexOf('.');
        if (dot < 0 || NodeByKey(reference[..dot]) is not { } node) throw new FormatException($"Unknown output {reference}");
        var ids = Outputs.Where(o => o.Node == node.Id && o.Name == reference[(dot + 1)..]).Select(o => o.Id);
        return ids.Select(id => (progress.Reached ?? new Dictionary<int, long>()).TryGetValue(id, out long at) ? at : (long?)null)
            .FirstOrDefault(at => at is not null);
    }

    /// <summary>The client's simple expression `f&lt;fact&gt;&lt;op&gt;&lt;value&gt;`, plus `!=`.</summary>
    public static bool Fact(string atom, IReadOnlyDictionary<int, int> facts)
    {
        foreach (string op in new[] { "<=", ">=", "!=", "<", ">", "=" })
        {
            int at = atom.IndexOf(op, StringComparison.Ordinal);
            if (at < 0) continue;
            string left = atom[..at].Trim(), right = atom[(at + op.Length)..].Trim();
            if (!left.StartsWith('f') || !int.TryParse(left[1..], out int fact) || !int.TryParse(right, out int value))
                throw new FormatException($"Invalid condition: {atom}");
            int actual = facts.GetValueOrDefault(fact);
            return op switch
            {
                "<=" => actual <= value, ">=" => actual >= value, "!=" => actual != value, "<" => actual < value,
                ">" => actual > value, _ => actual == value,
            };
        }
        throw new FormatException($"Invalid condition: {atom}");
    }

    /// <summary>The client's own check (FactDatabaseModule.EvaluateSimpleExpression): a single fact expression.</summary>
    public static bool Holds(string criteria, IReadOnlyDictionary<int, int> facts) =>
        string.IsNullOrWhiteSpace(criteria) || criteria.Split('&').All(atom => Fact(atom.Trim(), facts));

    // ── State ───────────────────────────────────────────────────────────────────────────────
    /// <summary>Quests the client offers now: not started, not finished, their criteria and their giver's root
    /// criteria holding.</summary>
    public static IEnumerable<Quest> Available(LocalProfileStore.StoryProgress progress, IReadOnlyDictionary<int, int> facts) =>
        Quests.Where(q => !progress.Finished.Contains(q.Id) && !progress.Started.Contains(q.Id) && Holds(q.Criteria, facts) &&
                          Nodes.FirstOrDefault(n => n.Quest == q.Id && n.Giver) is { } giver && Holds(giver.Root, facts));

    /// <summary>The map nodes (RPC 60 and 57) shown now.</summary>
    public static IEnumerable<Node> Active(LocalProfileStore.StoryProgress progress, IReadOnlyDictionary<int, int> facts, long now) =>
        Nodes.Where(n => n.OnMap && !progress.Finished.Contains(n.Quest) &&
                         (n.Queued || progress.Started.Contains(n.Quest)) && Holds(n.Show, facts, progress, now));

    /// <summary>The node a graph output came from: a served instance (with its copies), or, for journal buttons and
    /// windows whose graphs carry no instance, the one button output of that name in a started quest.</summary>
    public static Node? Resolve(LocalProfileStore.StoryProgress progress, long instanceId, string outputName)
    {
        if (Nodes.FirstOrDefault(n => n.HasInstance(instanceId) && OutputOf(n.Id, outputName) is not null) is { } node) return node;
        var buttons = Nodes.Where(n => n.Button && progress.Started.Contains(n.Quest) && OutputOf(n.Id, outputName) is not null)
            .ToList();
        return buttons.Count == 1 ? buttons[0] : null;
    }

    /// <summary>The effect of a graph output: the quest starts on its first output and finishes on an endpoint; the
    /// output's reward is paid the first time it is reached.</summary>
    public sealed record Step(Node Node, Output Output, LocalProfileStore.StoryProgress Progress, bool FirstTime);

    public static Step? Advance(LocalProfileStore.StoryProgress progress, Node node, string outputName, long now)
    {
        if (OutputOf(node.Id, outputName) is not { } output || progress.Finished.Contains(node.Quest)) return null;
        var started = progress.Started.ToList();
        var finished = progress.Finished.ToList();
        if (!started.Contains(node.Quest)) started.Add(node.Quest);
        if (output.Endpoint)
        {
            started.Remove(node.Quest);
            finished.Add(node.Quest);
        }
        var reached = new Dictionary<int, long>(progress.Reached ?? new Dictionary<int, long>());
        bool firstTime = !reached.ContainsKey(output.Id) && !progress.Outputs.Contains(output.Id);
        if (firstTime) reached[output.Id] = now;
        var outputs = firstTime ? progress.Outputs.Append(output.Id).ToList() : progress.Outputs.ToList();
        return new Step(node, output, progress with
        {
            Started = started, Finished = finished, Outputs = outputs, Reached = reached,
            Tracked = output.Endpoint && progress.Tracked == node.Quest ? null : progress.Tracked,
        }, firstTime);
    }

    // ── Static data rows ────────────────────────────────────────────────────────────────────
    private static string J(object value) => JsonSerializer.Serialize(value);

    public static IEnumerable<string> QuestRows() => Quests.Select(q => J(new Dictionary<string, object>
        { ["id"] = q.Id, ["season_id"] = 0, ["name"] = q.Name, ["journal_log"] = q.Journal, ["activation_criteria"] = q.Criteria }));

    public static IEnumerable<string> QuestEdgeRows() => Quests.Select(q => J(new Dictionary<string, object>
        { ["from_quest_id"] = TutorialQuest, ["to_quest_id"] = q.Id }));

    /// <summary>Quest node rows. The client evaluates one simple expression, so a root with several conditions
    /// sends its first one; the server checks all of them before it serves the giver (<see cref="Available"/>).</summary>
    public static IEnumerable<string> NodeRows() => Nodes.Select(n => J(new Dictionary<string, object>
    {
        ["id"] = n.Id, ["quest_id"] = n.Quest, ["name"] = n.Key,
        ["activation_criteria"] = RootOf(n.Quest)?.Id == n.Id ? n.Root.Split('&')[0].Trim() : "",
    }));

    // StoryGraph keys these rows by ID, then groups all rows by node. QuestEndRequestNode looks up the
    // graph's literal output name in that group, so aliases need distinct IDs and the same endpoint flag.
    public static IEnumerable<string> OutputRows() => Outputs.Concat(OutputAliases.Select(a =>
        Outputs.Single(o => o.Node == a.Node && o.Id == a.CanonicalId) with { Id = a.RowId, Name = a.Name }))
        .Select(o => J(new Dictionary<string, object>
        { ["id"] = o.Id, ["quest_node_id"] = o.Node, ["name"] = o.Name, ["endpoint"] = o.Endpoint ? 1 : 0 }));

    /// <summary>Edges from the root's first output to every other node of the quest, so the root is the quest's only
    /// node without an incoming edge (the client's root rule); the story itself follows the facts.</summary>
    public static IEnumerable<string> NodeEdgeRows() => Quests.SelectMany(q =>
    {
        var root = RootOf(q.Id);
        var first = root is null ? null : Outputs.FirstOrDefault(o => o.Node == root.Id);
        return first is null ? [] : Nodes.Where(n => n.Quest == q.Id && n.Id != root!.Id).Select(n => J(new Dictionary<string, object>
            { ["from_quest_node_output_id"] = first.Id, ["to_quest_node_id"] = n.Id }));
    });

    public static IEnumerable<string> ModifierRows() => Modifiers.Select(m => J(new Dictionary<string, object>
        { ["id"] = m.Id, ["slug"] = m.Slug }));
}
