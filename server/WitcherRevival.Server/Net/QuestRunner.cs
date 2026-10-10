using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The debug tools' quest runner (Players tab): every quest in story order with its state and the next step of its
/// walk-through, and "complete the next step". A step is sent as the game sends it, as a graph output with the facts its
/// graph sets, through the EndBehaviourGraph (57) handler, so rewards, tasks and trophies count it as play; a wait moves
/// the story clock on. Season 1 steps are the story's walk-throughs (season1_quests.py, checked against the client's own
/// graphs by story_audit.py); the tutorial, the prologue and "A Joint Venture" follow their stages
/// (Reconstruction.NextStage) with the facts their graphs send (the prologue tests). The game shows quest changes after a
/// restart: it learns of quests at boot and in the replies to its own requests.
/// </summary>
public sealed partial class PlayerService
{
    public sealed record QuestRow(int Id, string Name, string State, string? Next);

    private sealed record QuestStep(int Quest, long Instance, string? Output, Dictionary<int, int> Facts, int Wait, string Label);

    private static readonly (int Id, string Name)[] PrologueQuests =
        [(StoryEngine.TutorialQuest, "Final Exam"), (145, "Winged Bandit"), (146, "A Joint Venture")];

    private static IEnumerable<(int Id, string Name)> AllQuests => PrologueQuests.Concat(StoryEngine.Quests.Select(q => (q.Id, q.Name)));

    /// <summary>Every quest in story order with its state (done, in progress, offered, locked) and its next step.</summary>
    public IReadOnlyList<QuestRow> QuestBook()
    {
        var snapshot = profiles.Snapshot();
        return snapshot.Player is null ? [] : AllQuests.Select(q =>
        {
            string state = QuestState(snapshot, q.Id);
            return new QuestRow(q.Id, q.Name, state, NextStep(snapshot, q.Id, state)?.Label);
        }).ToList();
    }

    private DebugOutcome CompleteQuestStep(int quest, Action<LocalProfileStore.Profile> backup)
    {
        var snapshot = profiles.Snapshot();
        string name = AllQuests.FirstOrDefault(q => q.Id == quest).Name ?? throw new ArgumentException("Unknown quest.");
        if (NextStep(snapshot, quest, QuestState(snapshot, quest)) is not { } step)
            throw new DebugRefusal($"{name} has no step to complete: it is locked or done, or its walk-through ends here.");
        profiles.DebugUpdate(p => p, backup);
        string effect;
        if (step.Output is null && step.Facts.Count > 0)
        {
            profiles.UpdatePlayer(step.Facts, null, _ => null);
            effect = $"{name}: offered, as if its trigger had happened.";
        }
        else if (step.Output is null)
        {
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, p =>
            {
                var story = p.Story ?? LocalProfileStore.StoryProgress.Empty;
                return p with { Story = story with { Clock = story.Clock + step.Wait } };
            });
            effect = $"{name}: moved the story clock on by {Span(step.Wait)}.";
        }
        else
        {
            var body = new ByteBuffer();
            body.WriteLong(step.Instance); body.WriteString(step.Output); body.WriteInt(step.Facts.Count);
            foreach (var (fact, value) in step.Facts) { body.WriteInt(fact); body.WriteInt(value); }
            BuildEndBehaviourGraphResponse(new ApiProtocol.ApiRequest(0, [], 0, M_EndBehaviourGraph, body.ToArray()));
            var now = profiles.Snapshot();
            effect = NextStep(now, quest, QuestState(now, quest)) is { } next && (next.Output, next.Instance) == (step.Output, step.Instance)
                ? $"{name}: sent {step.Output}, but the quest did not move on (see the server log)."
                : $"{name}: {step.Label}, done.";
        }
        log.LogInformation("Debug quest step quest={Quest} output={Output}", quest, step.Output ?? "wait");
        return new DebugOutcome(profiles.Snapshot().Revision, [], Live, effect + " Restart the game to see it.");
    }

    private static string Span(int seconds) => seconds % 3600 == 0 ? $"{seconds / 3600} h" : $"{seconds / 60} min";

    private static string QuestState(LocalProfileStore.Profile snapshot, int quest)
    {
        bool prologue = PrologueQuests.Any(q => q.Id == quest);
        if (SeasonOne(snapshot) is not { } story)
            return prologue && PrologueStep(snapshot) is { } step
                ? quest < step.Quest ? "done" : quest == step.Quest ? "in progress" : "locked"
                : "locked";
        if (prologue || story.Finished.Contains(quest)) return "done";
        if (story.Started.Contains(quest)) return "in progress";
        return StoryEngine.Available(story, snapshot.Facts).Any(q => q.Id == quest) ||
               StoryEngine.Active(story, snapshot.Facts, StoryNow(story)).Any(n => n.Queued && n.Quest == quest)
            ? "offered" : "locked";
    }

    private static QuestStep? NextStep(LocalProfileStore.Profile snapshot, int quest, string state)
    {
        // Monster Slayer opens on the server's troll trigger (PlayerService.TrollFight) once Good Money has opened it.
        if (state == "locked" && StoryEngine.QuestById(quest)?.Criteria == $"f{StoryEngine.TrollTriggerFact}>=1" &&
            snapshot.Facts.GetValueOrDefault(1000) == 1)
            return new(quest, 0, null, new() { [StoryEngine.TrollTriggerFact] = 1 }, 0,
                "Win a rock-troll fight, then lose to rock trolls (Tuning) → offered at the next game start");
        if (state is not ("in progress" or "offered")) return null;
        if (SeasonOne(snapshot) is not { } story) return PrologueStep(snapshot);
        var active = StoryEngine.Active(story, snapshot.Facts, StoryNow(story)).ToList();
        var steps = StoryEngine.WalkOf(quest);
        for (int i = 0; i < steps.Count; i++)
        {
            if (steps[i] is not { Node: { } node, Output: { } output } step ||
                StoryEngine.OutputOf(node.Id, output) is { } reached && story.Outputs.Contains(reached.Id))
                continue;
            // A wait holds while the node after it is hidden.
            if (i > 0 && steps[i - 1].Node is null && !active.Any(n => n.Id == node.Id))
                return new(quest, 0, null, [], steps[i - 1].Wait, $"Wait {Span(steps[i - 1].Wait)}");
            string where = node.Kind switch { "giver" => "Talk to", "button" => "Journal:", "queued" => "Beside you:", _ => "On the map:" };
            // Its trigger: the giver of an offered quest, a journal button of a started one, or a node the map shows now.
            bool shown = node.Giver ? StoryEngine.Available(story, snapshot.Facts).Any(q => q.Id == quest)
                : node.Button ? story.Started.Contains(quest) : active.Any(n => n.Id == node.Id);
            return new(quest, node.Instance, output, step.Facts, 0,
                $"{where} {node.Key} → {output}{(shown ? "" : " (not shown yet)")}");
        }
        return null;
    }

    // Before season 1 the stage decides the next output (the handler ignores the instance there).
    private static QuestStep? PrologueStep(LocalProfileStore.Profile p) => p.QuestStage switch
    {
        Reconstruction.TutorialGhoul => new(144, 0, "tutorial_end", [], 0, "Beside you: the ghoul fight → tutorial_end"),
        Reconstruction.TutorialWitcher => new(144, 0, "exam", [], 0, "Beside you: the witcher's lesson → exam"),
        Reconstruction.TutorialExam => new(144, 0, "exam_end", new() { [3] = 1 }, 0, "Beside you: the exam fight → exam_end"),
        Reconstruction.Prologue => new(145, 0, "thorstein", [], 0, "Talk to Thorstein → thorstein"),
        LocalProfileStore.DeadHorseStage => new(145, 0, "dead_horse", new() { [94] = -3 }, 0, "On the map: the dead horse → dead_horse"),
        LocalProfileStore.GriffinStage => new(145, 0, "griffin_1", new() { [107] = 2, [109] = 2 }, 0, "On the map: the griffin → griffin_1"),
        LocalProfileStore.PrologueDoneStage => new(146, 0, "empty", new() { [10146] = 1 }, 0, "Beside you: Thorstein → empty"),
        LocalProfileStore.JointVentureStage => new(146, 0, "map", new() { [107] = 3, [10146] = 2 }, 0, "Journal: the treasure map → map"),
        LocalProfileStore.JvObeliskStage => new(146, 0, "obelisk", new() { [97] = 1, [98] = 1, [99] = 1, [107] = 4 }, 0,
            "On the map: the elven obelisk → obelisk"),
        LocalProfileStore.JvGiftsStage when !(p.Player?.StoryDone ?? []).Contains(Reconstruction.StoneHeart.Key) =>
            new(146, 0, "heart", new() { [99] = 3, [100] = 1 }, 0, "On the map: the stone heart → heart"),
        LocalProfileStore.JvGiftsStage when p.Player?.Granted.Contains(Reconstruction.RewardKey("gargoyle")) != true =>
            new(146, 0, "gargoyle", new() { [100] = 3, [112] = 3 }, 0, "On the map: the gargoyle king → gargoyle"),
        LocalProfileStore.JvGiftsStage => new(146, 0, "success_heart", new() { [100] = 4, [102] = 3, [145] = 2 }, 0,
            "On the map: the gargoyle king's figurine → success_heart"),
        _ => null,
    };
}
