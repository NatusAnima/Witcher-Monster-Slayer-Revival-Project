using System.Security.Cryptography;
using System.Text.Json;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    /// <summary>An owned summoning scroll (SummonScrolls): its group follows its own description ("Summons 5 random
    /// draconids", "one rare or legendary elemental", …), within the player's level when the level gate is on (a rarity
    /// the gate leaves empty falls back to the next lower one) and never a full-moon-only monster outside the full moon.
    /// Habitat, time and weather do not apply: the monsters are summoned. Species repeat when a family has too few.
    /// The lifetime is the client default 500 s.</summary>
    private byte[] SummonOwnedScroll(SummonScrolls.Scroll scroll, int longitude, int latitude)
    {
        int level = Reconstruction.LevelForExp(profiles.Snapshot().Player?.Exp ?? 0);
        bool fullMoon = WorldSpawns.Sky(0, 0, DateTimeOffset.UtcNow, WorldWeather.Clear).FullMoon;
        var eligible = WorldBestiary.All.Where(s => (scroll.Family is null || s.Family == scroll.Family) &&
            WorldSpawns.Allowed(s, level) && (fullMoon || !WorldSpawns.TagsOf(s).Contains("FULL_MOON_ONLY"))).ToList();
        WorldBestiary.Species? Pick(params int[] rarities)
        {
            for (int fallback = 0; fallback < 3; fallback++)
            {
                var pool = eligible.Where(s => rarities.Contains(s.Rarity + fallback)).ToList();
                if (pool.Count > 0) return pool[Random.Shared.Next(pool.Count)];
            }
            return null;
        }
        var picks = Enumerable.Range(0, scroll.Common).Select(_ => Pick(1))
            .Concat(Enumerable.Range(0, scroll.CommonOrRare).Select(_ => Pick(1, 2)))
            .Concat(Enumerable.Range(0, scroll.RareOrLegendary).Select(_ => Pick(2, 3)))
            .Concat(Enumerable.Range(0, scroll.LegendaryOnly).Select(_ => Pick(3)))
            .OfType<WorldBestiary.Species>().Select(s => (s.MonsterId, s.Difficulty)).ToArray();
        var group = picks.Length == 0 ? null : summons.TrySummonOwned(scroll.Id, UnixSeconds(), longitude, latitude, picks, (created, groups) =>
        {
            bool paid = false;
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, p =>
            {
                var owned = p.Items.GetValueOrDefault(ItemKinds.SummoningScrolls);
                if (owned?.GetValueOrDefault(scroll.Id) is not > 0) return null;
                if (--owned[scroll.Id] == 0) owned.Remove(scroll.Id);
                paid = true;
                var modifiers = (p.Modifiers ?? []).Where(m => m.Id != 13).ToList();
                modifiers.Add(new(13, created.StartTime, created.StartTime + 500));
                return p with { Summons = groups.ToList(), Modifiers = modifiers };
            });
            return paid;
        });
        log.LogInformation("  SummonLocalMonsters scroll {Scroll} {Result} monsters={Monsters}", scroll.Slug,
            group is null ? "refused" : "summoned", string.Join(",", picks.Select(p => p.MonsterId)));
        var b = new ByteBuffer(); b.WriteByte(group is null ? (byte)0 : (byte)1); b.WriteInt(group is null ? 0 : 1);
        if (group is not null) WriteSummonedGroup(b, group);
        return b.ToArray();
    }

    private static readonly HashSet<int> TaskMutations = [21, 22, 23, 81, 86, 95, 123];
    private bool TasksEnabled => tasks.Catalog is not null && profiles.Snapshot().Player is not null;

    private TaskEngine.State? RefreshTasks(bool issue = false)
    {
        if (!TasksEnabled || tasks.Catalog is not { } c) return null;
        TaskEngine.State? result = null;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, p =>
        {
            result = tasks.Refresh(p, c, tasks.Now);
            if (issue) result = tasks.Issue(p, profiles.ProfileId, c, result);
            return JsonSerializer.Serialize(result) == JsonSerializer.Serialize(p.Tasks) ? null : p with { Tasks = result };
        });
        return result;
    }

    private byte[] DailyTasksResponse()
    {
        if (RefreshTasks(issue: true) is not { } s) return BuildGetDailyContractsResponse();
        var b = new ByteBuffer(); b.WriteByte(1); b.WriteInt(0);
        b.WriteInt(s.Issued < 3 && s.Daily.Count < 3 ? 1 : 0);
        b.WriteInt(s.Reshuffled ? 0 : 1);
        WriteTasks(b, s.Daily);
        return b.ToArray();
    }

    private static void WriteTasks(ByteBuffer b, IEnumerable<TaskEngine.Entry> entries)
    {
        var list = entries.ToArray(); b.WriteInt(list.Length);
        foreach (var e in list)
        {
            b.WriteInt(e.Definition.Id);
            var progress = TaskEngine.WireProgress(e); b.WriteInt(progress.Length);
            foreach (int value in progress) b.WriteInt(value);
        }
    }

    private byte[] HuntResponse()
    {
        if (RefreshTasks() is not { } s || tasks.Catalog is not { } c) return BuildGetWeeklyContractProgressResponse();
        var b = new ByteBuffer(); b.WriteByte(1); b.WriteInt(Math.Max(0, s.LastStamp));
        b.WriteInt(c.Hunt.RewardId); b.WriteInt(s.Stamps.Count);
        foreach (int stamp in s.Stamps) b.WriteInt(stamp);
        return b.ToArray();
    }

    private byte[] TimedTasksResponse()
    {
        if (RefreshTasks() is not { } s || tasks.Catalog is not { } c)
            return BuildMonsterEventUnavailableResponse();
        if (ActiveEvent(c) is not { } e)
        {
            // OnGetMonsterEventProgressInternal 0x18288BC clears the previous event when TryGetEvent
            // cannot resolve this reserved ID. A failure byte would retain the expired event and its UI.
            var empty = new ByteBuffer(); empty.WriteByte(1); empty.WriteInt(0); empty.WriteInt(-1);
            empty.WriteInt(0); empty.WriteInt(0); empty.WriteInt(0);
            return empty.ToArray();
        }
        var state = s.Events[e.Id];
        var b = new ByteBuffer(); b.WriteByte(1); b.WriteInt(0); b.WriteInt(e.Id);
        // Native OnGetMonsterEventProgressInternal (0x18288BC) appends claimed objects first,
        // then creates a separate unclaimed object for every progress row. These lists must be disjoint.
        WriteTasks(b, state.Tasks.Where(t => !t.Claimed));
        var claimed = state.Tasks.Where(t => t.Claimed).ToArray(); b.WriteInt(claimed.Length);
        foreach (var t in claimed) b.WriteInt(t.Definition.Id);
        b.WriteInt(state.Claimed ? 1 : 0);
        return b.ToArray();
    }

    private TaskCatalog.Event? ActiveEvent(TaskCatalog.Catalog c)
    {
        long now = Math.Max(tasks.Now, profiles.Snapshot().Player?.Tasks?.LastTime ?? 0);
        return c.Timed.Events.SingleOrDefault(e => now >= e.Start && now <= e.End);
    }
    private byte[] TaskRefusal(ApiProtocol.ApiRequest req)
    {
        int id = req.Data.Length == 4 ? new ByteBuffer(req.Data).ReadInt() : 0;
        return req.Method switch
        {
            21 => new byte[5],
            22 or 23 or 86 => BuildIntResponse(false, id),
            81 => ClaimResponse(false, id, profiles.Snapshot().Player?.Gold ?? 0,
                tasks.Catalog?.Timed.Events.Any(e => e.Tasks.Any(t => t.Id == id)) == true ? 2 : 1),
            95 => new byte[9],
            _ => new byte[1],
        };
    }

    /// <summary>The client counts a walk done as it happens but reports it in steps of 100 m (RPC 27), so its claim can arrive while the
    /// server is a step behind, or after a report was lost. Unless the profile is protected (then the server's own position fixes are
    /// the only count), the client is the only witness of the walk anyway: RPC 27 takes whatever it reports.</summary>
    private bool WalkedEnough(TaskEngine.Entry e) => e.Definition.Type == 3 && profiles.Snapshot().Movement?.Protected != true;

    // Factory 0x247D000: result=0 succeeds; questType must survive refusal so the matching callback unblocks.
    private static byte[] ClaimResponse(bool success, int id, int gold, int type)
    {
        var b = new ByteBuffer(); b.WriteInt(success ? 0 : 1); b.WriteInt(id); b.WriteInt(gold); b.WriteInt(type);
        return b.ToArray();
    }

    private byte[] HandleTaskRequest(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != (req.Method is 22 or 23 or 81 or 86 ? 4 : 0)) return TaskRefusal(req);
        if (!TasksEnabled || tasks.Catalog is not { } c) return TaskRefusal(req);
        if (req.Method == 125) return ApiProtocol.Boolean(true); // Refresh122 also clears an expired event.
        // Unknown AddSpecifiedContract cannot be used to create tasks or bypass the daily draw.
        if (req.Method == 86) return TaskRefusal(req);
        lock (settled)
        {
            string receiptKey = $"{req.Method}:{req.Id}";
            string fingerprint = Convert.ToHexString(SHA256.HashData(req.Data));
            byte[] reply = TaskRefusal(req);
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, p =>
            {
                var s = tasks.Refresh(p, c, tasks.Now);
                if (s.Receipts.TryGetValue(receiptKey, out var old))
                {
                    reply = old.Fingerprint == fingerprint ? old.Response : TaskRefusal(req);
                    return null;
                }
                int id = req.Data.Length == 4 ? new ByteBuffer(req.Data).ReadInt() : 0;
                switch (req.Method)
                {
                    case 21:
                        s = tasks.Issue(p, profiles.ProfileId, c, s);
                        var added = new ByteBuffer(); added.WriteByte(1); added.WriteInt(s.Daily.Count);
                        foreach (var entry in s.Daily) added.WriteInt(entry.Definition.Id);
                        reply = added.ToArray(); break;
                    case 22:
                        int replace = s.Daily.FindIndex(t => t.Definition.Id == id);
                        if (replace >= 0 && !s.Reshuffled && TaskEngine.Draw(p, profiles.ProfileId, c, s, "reroll") is { } replacement)
                        {
                            s.Daily[replace] = TaskEngine.NewEntry(replacement, p); s.Seen.Add(replacement.Id);
                            s = s with { Reshuffled = true }; reply = BuildIntResponse(true, replacement.Id);
                        }
                        break;
                    case 23:
                        if (s.Daily.RemoveAll(t => t.Definition.Id == id) > 0) reply = BuildIntResponse(true, id);
                        break;
                    case 81:
                        if (profiles.Snapshot().Facts.GetValueOrDefault(3) != 1)
                        {
                            log.LogInformation("  Task claim {Task} refused: the tutorial is not finished", id);
                            break;
                        }
                        int index = s.Daily.FindIndex(t => t.Definition.Id == id);
                        if (index >= 0 && (TaskEngine.Complete(s.Daily[index]) || WalkedEnough(s.Daily[index])))
                        {
                            // The panel shows the gold (its daily_quests row); the experience and the items (the Rewards
                            // page's daily pool) arrive with the pushes below, or at the next game start.
                            int gold = TaskCatalog.DailyGold(s.Daily[index].Definition), exp = (int)world.Tuning.Get(WorldTuning.TaskExp);
                            var items = world.Tuning.Rewards.DrawDaily(Reconstruction.LevelForExp(p.Exp), Random.Shared);
                            p = Reconstruction.WithExp(TaskEngine.Reward(p, gold, []), exp);
                            foreach (var item in items) AddItems(p, [(item.Kind, item.Id, item.Amount)]);
                            log.LogInformation("  Task claim {Task} daily: paid {Gold} gold, {Exp} exp, items {Items}, wallet {Wallet}, " +
                                "progress {Progress} of {Target}", id, gold, exp,
                                items.Count == 0 ? "none" : string.Join(", ", items.Select(i => $"{i.Kind} {i.Id}")), p.Gold,
                                s.Daily[index].Progress, s.Daily[index].Definition.Target);
                            if (exp > 0 || items.Count > 0) lock (pushGate) pendingPushes.UnionWith([M_GetPlayerInfo, M_GetInventory]);
                            s.Daily.RemoveAt(index); reply = ClaimResponse(true, id, p.Gold, 1);
                        }
                        else if (index >= 0)
                        {
                            // task ids are distinct across daily and timed tasks, so there is no event task to look for
                            log.LogInformation("  Task claim {Task} refused: progress {Progress} of {Target}", id, s.Daily[index].Progress, s.Daily[index].Definition.Target);
                        }
                        else if (ActiveEvent(c) is { } e)
                        {
                            var eventState = s.Events[e.Id];
                            int ti = eventState.Tasks.FindIndex(t => t.Definition.Id == id);
                            if (ti >= 0 && !eventState.Tasks[ti].Claimed && TaskEngine.Complete(eventState.Tasks[ti]))
                            {
                                var entry = eventState.Tasks[ti];
                                p = TaskEngine.Reward(p, entry.Definition.Gold, entry.Definition.Rewards ?? []);
                                eventState.Tasks[ti] = entry with { Claimed = true };
                                log.LogInformation("  Task claim {Task} event: paid {Gold} gold, wallet {Wallet}", id, entry.Definition.Gold, p.Gold);
                                reply = ClaimResponse(true, id, p.Gold, 2);
                            }
                            else log.LogInformation("  Task claim {Task} refused: not a finished, unclaimed task of the event", id);
                        }
                        else log.LogInformation("  Task claim {Task} refused: not one of today's tasks", id);
                        break;
                    case 95:
                        if (s.Stamps.Count >= c.Hunt.Size)
                        {
                            p = TaskEngine.Reward(p, 0, [c.Hunt.Reward]);
                            s.Stamps.Clear(); s = s with { HuntClaims = checked(s.HuntClaims + 1) };
                            var hunt = new ByteBuffer(); hunt.WriteByte(1); hunt.WriteInt(c.Hunt.RewardId); hunt.WriteInt(c.Hunt.RewardId);
                            reply = hunt.ToArray();
                        }
                        break;
                    case 123:
                        if (ActiveEvent(c) is { } active && s.Events[active.Id] is { Claimed: false } state && state.Tasks.All(t => t.Claimed))
                        {
                            p = TaskEngine.Reward(p, active.Gold, active.Rewards);
                            s.Events[active.Id] = state with { Claimed = true };
                            var reward = new ByteBuffer(); reward.WriteByte(1); reward.WriteInt(0); reward.WriteInt(active.Id);
                            reward.WriteInt(active.Gold); reward.WriteInt(active.Rewards.Length); // gold delta, never wallet total
                            foreach (var r in active.Rewards) { reward.WriteInt(r.Type); reward.WriteInt(r.Item); reward.WriteInt(r.Amount); }
                            reply = reward.ToArray();
                        }
                        break;
                }
                s.Receipts[receiptKey] = new(fingerprint, reply);
                while (s.Receipts.Count > 256) s.Receipts.Remove(s.Receipts.Keys.First());
                return p with { Tasks = s };
            });
            return reply;
        }
    }
}
