using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Server-side quest progression, driven by StaticData/quests.json (its _notes describe the format). The original
/// server advanced quests by node output (static-data quest_node_outputs -> quest_node_edges, never shipped to us);
/// quests.json rebuilds those edges from the graph assets. State = the active steps, several at once (S01 runs its
/// quest lines in parallel), each with the Unix second its Auto node may fire (0 = no timer), persisted to
/// data/quest_state.json. Static so the debug endpoints in Program.cs can reach it.
/// </summary>
public static class QuestFlow
{
    public sealed record Step(string Name, string Graph, long Instance, int Node, string Poi, int Mode, int Ttl);
    private sealed record Target(string Step, bool Retire, int Fact = 0, string? Op = null, int Value = 0);

    private const string StatePath = "data/quest_state.json";
    private const string OldStepPath = "data/quest_step.json";  // single-step state from before quests.json
    private static readonly object Lock = new();
    private static readonly Dictionary<string, Step> Steps;
    private static readonly Dictionary<string, Dictionary<string, List<Target>>> Edges;
    private static readonly string[] Start;
    private static readonly Dictionary<string, long> Active;

    static QuestFlow()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "StaticData", "quests.json")));
        var root = doc.RootElement;
        Steps = root.GetProperty("steps").EnumerateObject().ToDictionary(p => p.Name, p => new Step(p.Name,
            p.Value.GetProperty("graph").GetString()!, p.Value.GetProperty("instance").GetInt64(),
            p.Value.GetProperty("node").GetInt32(), p.Value.GetProperty("poi").GetString()!,
            p.Value.GetProperty("mode").GetInt32(), p.Value.TryGetProperty("ttl", out var ttl) ? ttl.GetInt32() : 0));
        Edges = root.GetProperty("edges").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.EnumerateObject()
            .ToDictionary(o => o.Name, o => o.Value.EnumerateArray().Select(ParseTarget).ToList()));
        Start = root.GetProperty("start").EnumerateArray().Select(e => e.GetString()!).ToArray();
        var unknown = Edges.SelectMany(e => e.Value.Values.SelectMany(t => t).Select(t => t.Step).Append(e.Key))
            .Concat(Start).FirstOrDefault(s => !Steps.ContainsKey(s));
        if (unknown is not null) throw new InvalidDataException($"quests.json names an unknown step '{unknown}'");
        Active = LoadState();
    }

    private static Target ParseTarget(JsonElement t)
    {
        if (t.ValueKind == JsonValueKind.String)
        {
            string s = t.GetString()!;
            return s.StartsWith('-') ? new(s[1..], true) : new(s, false);
        }
        var cond = t.GetProperty("if");
        return new(t.GetProperty("step").GetString()!, false, cond[0].GetInt32(), cond[1].GetString(), cond[2].GetInt32());
    }

    private static Dictionary<string, long> LoadState()
    {
        try
        {
            if (File.Exists(StatePath))
                return JsonSerializer.Deserialize<Dictionary<string, long>>(File.ReadAllText(StatePath))!
                    .Where(kv => Steps.ContainsKey(kv.Key)).ToDictionary();
            if (File.Exists(OldStepPath))  // its value was the active graph's path, "" once the griffin was done
            {
                string graph = JsonSerializer.Deserialize<string>(File.ReadAllText(OldStepPath)) ?? "";
                var old = graph == "" ? Steps["prolog_02_map"] : Steps.Values.FirstOrDefault(s => s.Graph == graph);
                if (old is not null) return new() { [old.Name] = 0 };
            }
        }
        catch { /* unreadable/corrupt file — start over */ }
        return Start.ToDictionary(s => s, s => Due(Steps[s]));
    }

    private static long Due(Step s) => s.Ttl > 0 ? DateTimeOffset.UtcNow.ToUnixTimeSeconds() + s.Ttl : 0;

    private static void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(StatePath))!);
        File.WriteAllText(StatePath, JsonSerializer.Serialize(Active));
    }

    /// The active steps with their fire time (Unix seconds, 0 = none), for GetActiveQuestNodeInstances (60) and
    /// the EndBehaviourGraph (57) reply.
    public static List<(Step Step, long Due)> Snapshot()
    {
        lock (Lock) return Active.Select(kv => (Steps[kv.Key], kv.Value)).ToList();
    }

    /// EndBehaviourGraph: the active step that ran the graph retires and its output's edges apply. An output with
    /// no edge (lost fight, mid-graph progress), or a graph that isn't an active step, changes nothing.
    /// <paramref name="fact"/> reads the fact store, which already holds the facts this request reported.
    public static string Advance(long instanceId, string output, Func<int, int> fact)
    {
        lock (Lock)
        {
            var step = Steps.Values.FirstOrDefault(s => s.Instance == instanceId && Active.ContainsKey(s.Name));
            if (step is null) return $"instance {instanceId} is not an active step --{output}--> unchanged";
            if (!Edges.TryGetValue(step.Name, out var outputs) || !outputs.TryGetValue(output, out var targets))
                return $"{step.Name} --{output}--> unchanged (no edge: step stays for a retry)";
            Active.Remove(step.Name);
            foreach (var t in targets)
                if (t.Retire) Active.Remove(t.Step);
                else if (t.Op is null || Holds(fact(t.Fact), t.Op, t.Value)) Active.TryAdd(t.Step, Due(Steps[t.Step]));
            Save();
            return $"{step.Name} --{output}--> active: {string.Join(", ", Active.Keys)}";
        }
    }

    private static bool Holds(int v, string op, int value) => op switch
    {
        "==" => v == value, "!=" => v != value, ">" => v > value, ">=" => v >= value, "<" => v < value, "<=" => v <= value,
        _ => throw new InvalidDataException($"quests.json: unknown operator '{op}'"),
    };

    // ── Debug (Program.cs /debug/quest*): seen by the client on its next quest reply or boot ──

    public static object Describe()
    {
        lock (Lock) return new { active = Active, steps = Steps.Keys };
    }

    /// Activates a step with no timer (a debug-started Auto step fires at once); replace = drop all others first.
    public static bool Activate(string name, bool replace)
    {
        lock (Lock)
        {
            if (!Steps.ContainsKey(name)) return false;
            if (replace) Active.Clear();
            Active[name] = 0;
            Save();
            return true;
        }
    }

    public static bool Retire(string name)
    {
        lock (Lock)
        {
            if (!Active.Remove(name)) return false;
            Save();
            return true;
        }
    }
}
