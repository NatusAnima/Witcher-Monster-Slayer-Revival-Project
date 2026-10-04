using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    private void MapPlayerProgressRoutes(WebApplication app) =>
        app.MapGet("/api/profiles/{id}/progress", (string id) => PlayerProgress(id));

    // A projection of one atomic saved snapshot. Never call a game getter here: several
    // task/story getters reconcile state, issue quests or persist elapsed-time changes.
    private IResult PlayerProgress(string id)
    {
        RequireProfile(id);
        var snapshot = registry.Store(id).Snapshot();
        var player = snapshot.Player;
        var state = player?.Tasks;
        var catalogue = tasks.Current;
        long now = Math.Max(cfg.GetValue<long?>("Tasks:FixedUnixTime") ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds(), state?.LastTime ?? 0);
        int day = Math.Max(checked((int)(now / 86400)), state?.Day ?? 0);
        bool tracking = snapshot.Facts.GetValueOrDefault(3) == 1;
        string availability = player is null ? "legacy-unavailable" : catalogue is null ? "catalogue-unavailable" : state is null ? "not-recorded" : "available";
        var daily = (state?.Daily ?? []).Select(e => ProgressTask(e.Definition, e, state, now,
            player is null || catalogue is null ? "unavailable" : !tracking ? "blocked-tracking" : null)).ToArray();
        var events = (catalogue?.Timed.Events.Select(e => e.Id) ?? [])
            .Union(state?.Events.Keys.AsEnumerable() ?? []).Order().Select(eventId =>
        {
            var definition = catalogue?.Timed.Events.FirstOrDefault(e => e.Id == eventId);
            var saved = state?.Events.GetValueOrDefault(eventId);
            string window = definition is null ? "unavailable" : now < definition.Start ? "upcoming" : now > definition.End ? "expired" : "active";
            string? refusal = definition is null || player is null ? "unavailable" : window != "active" ? window : !tracking ? "blocked-tracking" : null;
            var entries = (definition?.Tasks.Select(d => d.Id) ?? []).Union(saved?.Tasks.Select(e => e.Definition.Id) ?? [])
                .Select(taskId =>
                {
                    var entry = saved?.Tasks.FirstOrDefault(e => e.Definition.Id == taskId);
                    var task = entry?.Definition ?? definition!.Tasks.First(d => d.Id == taskId);
                    return ProgressTask(task, entry, state, now, refusal);
                }).ToArray();
            bool finalPending = window == "active" && saved is { Claimed: false } && saved.Tasks.All(e => e.Claimed);
            return new
            {
                id = eventId, name = definition?.Name, nameSource = definition is null ? "unavailable" : "catalogue-name",
                start = definition?.Start, end = definition?.End, window,
                availability = saved is null ? "not-recorded" : definition is null ? "definition-unavailable" : "available",
                tasks = entries, claimed = saved?.Claimed,
                finalRewardState = saved?.Claimed == true ? "claimed" : definition is null || player is null ? "unavailable" :
                    saved is null ? "not-recorded" : window != "active" ? window : finalPending ? "ready-to-claim" : "tasks-unclaimed",
                pendingClaim = finalPending,
                gold = definition?.Gold, rewards = definition?.Rewards,
            };
        }).ToArray();
        var trinkets = (catalogue?.Trinkets.Trinkets.Select(d => d.Id) ?? [])
            .Union(state?.Achievements.Keys.AsEnumerable() ?? [])
            .Union(state?.TrophyProgress?.Keys.AsEnumerable() ?? []).Order().Select(trinketId =>
        {
            var definition = catalogue?.Trinkets.Trinkets.FirstOrDefault(d => d.Id == trinketId);
            var saved = state?.TrophyProgress?.GetValueOrDefault(trinketId);
            int? unlockedAt = state?.Achievements.TryGetValue(trinketId, out int at) == true ? at : null;
            long? progress = definition is null || player is null ? null : definition.WindowSeconds > 0
                ? saved?.Progress : LifetimeTrinketProgress(definition, player, state);
            bool refresh = saved is not null && WindowNeedsRefresh(saved, state, now);
            return new
            {
                id = trinketId, name = definition?.Slug, nameSource = definition is null ? "unavailable" : "catalogue-slug",
                definition, progress, target = definition?.Target,
                progressSource = progress is null ? "unavailable" : definition!.WindowSeconds > 0 ? "saved-window-counter" : "saved-lifetime-counters",
                requiresGameplayRefresh = refresh,
                unlocked = unlockedAt is not null, unlockedAt,
                rewardState = unlockedAt is not null ? "unlocked" : progress is null ? "unavailable" :
                    progress >= definition!.Target ? "awaiting-gameplay-refresh" : "incomplete",
                pendingClaim = false, // The task engine unlocks trinkets automatically, with no reward-claim RPC.
            };
        }).ToArray();
        var hunt = catalogue?.Hunt;
        bool expiredStreak = hunt?.Streak == true && state is { LastStamp: >= 0, Stamps.Count: > 0 } && day > (long)state.LastStamp + 1;
        bool huntPending = hunt is not null && state is not null && !expiredStreak && state.Stamps.Count >= hunt.Size;
        bool requiresRefresh = player is not null && catalogue is not null && (state is null || day > state.Day ||
            daily.Any(t => t.RequiresGameplayRefresh) || trinkets.Any(t => t.requiresGameplayRefresh || t.rewardState == "awaiting-gameplay-refresh") ||
            events.Any(e => e.tasks.Any(t => t.RequiresGameplayRefresh) || e.window == "active" && e.availability == "not-recorded") || expiredStreak);
        return Results.Json(new
        {
            observedAt = DateTimeOffset.UtcNow, source = "saved-profile-snapshot",
            profile = new { id, snapshot.Revision, snapshot.SchemaVersion, name = player?.Name },
            clock = new { unixTime = now, day, reset = "00:00 UTC", savedDay = state?.Day, savedLastTime = state?.LastTime,
                fixedForTesting = cfg.GetValue<long?>("Tasks:FixedUnixTime") is not null, requiresGameplayRefresh = requiresRefresh },
            story = StoryProgress(snapshot),
            daily = new { availability, trackingEnabled = tracking, savedDay = state?.Day, issued = state?.Issued,
                reshuffled = state?.Reshuffled, rows = daily, historyAvailable = false },
            timed = new { availability, rows = events },
            trinkets = new { availability, unlockedCount = state?.Achievements.Count, rows = trinkets },
            hunt = new { availability, stamps = state?.Stamps, lastStamp = state?.LastStamp, claims = state?.HuntClaims,
                target = hunt?.Size, streak = hunt?.Streak, reward = hunt?.Reward, expiredStreak,
                rewardState = hunt is null || player is null ? "unavailable" : state is null ? "not-recorded" :
                    expiredStreak ? "expired-streak" : huntPending ? "ready-to-claim" : "incomplete",
                pendingClaim = huntPending },
            distance = DistanceProgress(snapshot),
            limitations = new[]
            {
                "Inspection does not refresh gameplay state, issue tasks, unlock trinkets or claim rewards.",
                "Daily rewards remove their entries; the save does not contain a complete daily completion history.",
                "Task progress and window counters are saved values. Gameplay may reconcile elapsed windows and rotations.",
                "Story rows describe recorded season 1 state; tutorial/prologue stage is separate. Branch outputs are not a completion percentage.",
                "Names are catalogue identifiers or embedded English story names, not a client-localized text lookup.",
                "Distance is credited game progress, may include historical unverified reports, and can be reset or copied by an operator.",
            },
        });
    }

    private sealed record ProgressTaskRow(int Id, string Name, string NameSource, TaskCatalog.Definition Definition,
        int? Progress, int Target, bool? CompletedSaved, bool? Claimed, string RewardState, bool PendingClaim,
        bool RequiresGameplayRefresh, string ProgressSource);

    private static ProgressTaskRow ProgressTask(TaskCatalog.Definition definition, TaskEngine.Entry? saved,
        TaskEngine.State? state, long now, string? refusal)
    {
        bool? complete = saved is null ? null : TaskEngine.Complete(saved);
        string reward = saved?.Claimed == true ? "claimed" : refusal ??
            (saved is null ? "not-recorded" : complete == true ? "ready-to-claim" : "incomplete");
        return new(definition.Id, definition.Slug, "catalogue-slug", definition, saved?.Progress, definition.Target,
            complete, saved?.Claimed, reward, reward == "ready-to-claim",
            saved is not null && WindowNeedsRefresh(saved, state, now), saved is null ? "unavailable" : "saved-task-counter");
    }

    private static bool WindowNeedsRefresh(TaskEngine.Entry entry, TaskEngine.State? state, long now) =>
        entry.Definition.WindowSeconds > 0 && !entry.Claimed && !TaskEngine.Complete(entry) && now > (state?.LastTime ?? 0);

    // Mirrors TaskEngine's lifetime sources, but does not call Refresh/Unlock. Unknown
    // definitions have no inferred progress; an existing achievement remains authoritative.
    private static long? LifetimeTrinketProgress(TaskCatalog.Definition d, LocalProfileStore.PlayerState player, TaskEngine.State? state)
    {
        bool Matches(int[]? ids, int id) => ids is not { Length: > 0 } || ids.Contains(id);
        return d.Type switch
        {
            1 => (player.Kills ?? []).Where(k => Matches(d.Monsters, k.Key)).Sum(k => (long)k.Value),
            2 => state?.NestsCleared,
            3 => player.Distance?.Metres ?? 0,
            7 => Reconstruction.LevelForExp(player.Exp),
            8 => player.Skills.Count,
            9 => (player.Story?.Finished ?? []).Count(id => Matches(d.Quests, id)),
            13 => (player.Story?.Outputs ?? []).Count(id => Matches(d.Outputs, id)),
            _ => null,
        };
    }

    private static object StoryProgress(LocalProfileStore.Profile snapshot)
    {
        var story = snapshot.Player?.Story;
        var started = story?.Started.Distinct().Order().ToArray() ?? [];
        var finished = story?.Finished.Distinct().Order().ToArray() ?? [];
        var ids = StoryEngine.Quests.Select(q => q.Id).Union(started).Union(finished);
        if (story?.Tracked is int tracked) ids = ids.Append(tracked).Distinct();
        var rows = ids.Order().Select(id =>
        {
            var quest = StoryEngine.QuestById(id);
            var nodes = StoryEngine.Nodes.Where(n => n.Quest == id).Select(n => n.Id).ToHashSet();
            var outputs = StoryEngine.Outputs.Where(o => nodes.Contains(o.Node)).Select(o => o.Id).ToHashSet();
            return new
            {
                id, name = quest?.Name, code = quest?.Code, nameSource = quest is null ? "unavailable" : "embedded-story-english",
                status = finished.Contains(id) ? "finished" : started.Contains(id) ? "started" : "not-recorded",
                tracked = story?.Tracked == id,
                rewardedOutputCount = story is null || quest is null ? (int?)null : story.Outputs.Distinct().Count(outputs.Contains),
            };
        }).ToArray();
        return new
        {
            availability = snapshot.Player is null ? "legacy-unavailable" : story is null ? "not-recorded" : "available",
            introductory = new { questStage = snapshot.QuestStage, objective = snapshot.Player?.CurrentObjective },
            started, finished, tracked = story?.Tracked, recordedFinishedCount = story is null ? (int?)null : finished.Length,
            rewardedOutputCount = story?.Outputs.Distinct().Count(), rows,
        };
    }

    private object DistanceProgress(LocalProfileStore.Profile snapshot)
    {
        var player = snapshot.Player;
        var ledger = snapshot.Movement;
        int? metres = player is null ? null : player.Distance?.Metres ?? 0;
        return new
        {
            availability = player is null ? "legacy-unavailable" : player.Distance is null ? "default-zero" : "available",
            metres, kilometres = metres / 1000d,
            legacyBaselineMetres = ledger?.LegacyBaselineMetres,
            acceptedMetresSinceProtection = ledger is null ? (long?)null : ledger.CreditedMetres,
            shadowAcceptedMetres = ledger is null ? (double?)null : ledger.ShadowMillimetres / 1000d,
            protectedProfile = ledger?.Protected ?? false, currentPolicy = world.Distance.Read().Mode,
            policyAppliesOn = "new-capable-client-hello", protectionRemainsLatched = true,
            observedAtMs = ledger?.ObservedAtMs, rebasedAtMs = ledger is { RebasedAtMs: > 0 } ? (long?)ledger.RebasedAtMs : null,
            acceptedFixes = ledger is null ? (long?)null : ledger.ProtectedAcceptedFixes,
            rejectedFixes = ledger is null ? (long?)null : ledger.ProtectedRejectedFixes,
            rejectedReasons = ledger?.RejectedReasons,
            source = "credited-game-distance", actualWalkingVerified = false,
        };
    }
}
