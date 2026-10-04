using System.Text.Json;
using System.Text.RegularExpressions;

namespace WitcherRevival.Server.Net;

/// <summary>One configured local test profile; never derived from client account/device identifiers.</summary>
public sealed class LocalProfileStore : IDisposable
{
    public const string DeadHorseStage = "dead_horse";
    public const string GriffinStage = "griffin";
    public const string PrologueDoneStage = "prologue_done";
    public const string JointVentureStage = "joint_venture";
    // "A Joint Venture" after the map dialog: the obelisk, then the gifts and the gargoyle, then done.
    public const string JvObeliskStage = "jv_obelisk", JvGiftsStage = "jv_gifts", JvDoneStage = "jv_done";

    private readonly object _gate = new();
    private readonly string _path;
    private readonly FileStream _processLock;
    private Profile _profile;
    private readonly TaskEngine? _tasks;
    public string ProfileId { get; }
    public sealed record Profile(int SchemaVersion, string ProfileId, long Revision,
        Dictionary<int, int> Facts, string? QuestStage = null, PlayerState? Player = null, DistanceLedger? Movement = null);

    /// <summary>Reconstructed player state (schema 2). Legacy schema-1 profiles have none and keep
    /// the inherited demonstration values. Items are keyed by kind ("oils", "potions", "bombs").
    /// Kills counts won fights per monster id (the bestiary); Summons holds summoned monster groups;
    /// StoryPlaces holds the point chosen for each story stage or node; KilledInstances maps defeated world
    /// monsters to the Unix second their window ends; StoryDone lists story nodes whose goal is reached
    /// (e.g. the stone crown taken); KnowledgeClaimed maps a monster id to its last claimed bestiary
    /// knowledge tier; Brewers holds owned crafting stations and their work; OneTimeBundles lists shop bundles
    /// bought once; Sensed maps monsters revealed by the witcher senses to the Unix second they leave; Modifiers
    /// holds the expiring player modifiers added by story graphs; LevelAnnounced is the last level announced to
    /// the client with a LevelUp push; HerbRespawns maps gathered herbs to the Unix second they grow back. Older
    /// files have none of them.</summary>
    public sealed record PlayerState(int Exp, int Gold, int SkillPoints, List<int> Skills,
        Dictionary<string, Dictionary<int, int>> Items, List<string> Granted, string? Name = null, byte Gender = 0,
        Dictionary<int, int>? Kills = null, List<SummonedMonsters.Group>? Summons = null,
        Dictionary<string, StoryPlace>? StoryPlaces = null, Dictionary<long, long>? KilledInstances = null,
        List<string>? StoryDone = null, Dictionary<int, int>? KnowledgeClaimed = null,
        List<BrewerState>? Brewers = null, List<int>? OneTimeBundles = null, string? CurrentObjective = null,
        Dictionary<long, long>? Sensed = null, List<ModifierState>? Modifiers = null, int? LevelAnnounced = null,
        Dictionary<long, long>? HerbRespawns = null, NestDay? Nests = null, StoryProgress? Story = null,
        EquipmentState? Equipment = null, Dictionary<long, TransactionRecord>? Transactions = null,
        TaskEngine.State? Tasks = null, AuraUsage? Aura = null, DistanceState? Distance = null);

    /// <summary>Earned metres from legacy RPC27 or validated companion segments after protection. Old reconstructed saves
    /// start at zero: the former constant 15000 was never earned progress. Recent random request IDs
    /// survive restart so transport retries do not count a segment twice.</summary>
    public sealed record DistanceState(int Metres, Dictionary<long, int> Requests);

    /// <summary>The last successful Witcher Aura request. Kept after its group expires so restart/retry
    /// cannot bypass the cooldown. Request coordinates are private profile state, never diagnostics.</summary>
    public sealed record AuraUsage(int At, long RequestId, int Longitude, int Latitude);

    /// <summary>The outcome of a shop purchase by its transaction nonce (OrenTransactionProcessor's random long):
    /// the bundle, whether it was bought, and when (Unix seconds). The newest TransactionLimit are kept.</summary>
    public sealed record TransactionRecord(int Bundle, bool Bought, long At);

    public const int TransactionLimit = 256;

    /// <summary>Owned and equipped swords and armours (Reconstruction.Swords and Armors); older files start with
    /// Reconstruction.StartingGear.</summary>
    public sealed record EquipmentState(List<int> Swords, List<int> Armors, int Sword, int Armor)
    {
        public static EquipmentState Starting => new(Reconstruction.StartingGear.Swords.ToList(),
            Reconstruction.StartingGear.Armors.ToList(), Reconstruction.StartingGear.Sword, Reconstruction.StartingGear.Armor);
    }

    /// <summary>Season 1 story state (StoryEngine): started and finished quests, the outputs already rewarded, the
    /// tracked quest, the Unix second each output was first reached, and a test clock offset in seconds (local
    /// endpoint only). Active is kept for older files and no longer used.</summary>
    public sealed record StoryProgress(List<int> Active, List<int> Started, List<int> Finished, List<int> Outputs,
        int? Tracked = null, Dictionary<int, long>? Reached = null, long Clock = 0)
    {
        public static StoryProgress Empty => new(new List<int>(), new List<int>(), new List<int>(), new List<int>());
    }

    /// <summary>The profile's nemeta on one UTC day: the clears that counted towards the daily bonus and each
    /// visited nest's state (WorldNests). A new day starts empty.</summary>
    public sealed record NestDay(long Day, int Wins, Dictionary<long, NestProgress> Nests);

    /// <summary>A nest's NestState, its clears today and the monsters a bait brought (null: its own).</summary>
    public sealed record NestProgress(int State, int Clears, int[]? Monsters);

    /// <summary>An expiring player modifier (Client ExpiringPlayerModifier): player_modifiers id, start and expiry
    /// in Unix seconds; an expiry below 1 never expires.</summary>
    public sealed record ModifierState(int Id, int Start, int Expire);

    /// <summary>An owned crafting station (Client Brewer: instance id, brewers table type, uses left with -1 for
    /// the unlimited station, the recipe at work or -1, its finish time in Unix seconds). OutputCount is the
    /// craft-start award, defaulting to one for old saves; it is persisted but not sent in the brewer list.</summary>
    public sealed record BrewerState(long InstanceId, int Type, int UsesLeft, int WorkingRecipe, int FinishTime,
        int OutputCount = 1);

    /// <summary>A pedestrian-safe point chosen for a story node (never logged).</summary>
    public sealed record StoryPlace(string Id, double Lat, double Lng, int[] Biomes, ulong? CellId = null);

    private static readonly HashSet<string?> KnownStages = new()
    {
        null, DeadHorseStage, GriffinStage, PrologueDoneStage, JointVentureStage, JvObeliskStage, JvGiftsStage, JvDoneStage,
        Reconstruction.TutorialGhoul, Reconstruction.TutorialWitcher,
        Reconstruction.TutorialExam, Reconstruction.Prologue,
    };

    /// <summary>A profile id is a local pseudonym and a file name: 1..48 lowercase letters, digits, _ or -.</summary>
    public static void CheckProfileId(string profileId)
    {
        if (!Regex.IsMatch(profileId, "^[a-z0-9][a-z0-9_-]{0,47}$"))
            throw new InvalidOperationException("A profile id must be a local pseudonym: 1..48 lowercase letters, digits, _ or -.");
    }

    /// <summary>The profiles directory, created readable by the owner only.</summary>
    public static string PrepareDirectory(string configured)
    {
        string directory = Path.GetFullPath(configured);
        bool directoryExisted = Directory.Exists(directory);
        Directory.CreateDirectory(directory);
        if (!directoryExisted && !OperatingSystem.IsWindows())
            File.SetUnixFileMode(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        return directory;
    }

    /// <summary>One player's profile (ProfileRegistry opens one per player). newProfileMode "reconstructed" starts a
    /// new profile at level 1 in the tutorial; null or "legacy" keeps the inherited demonstration start.</summary>
    public LocalProfileStore(string directory, string profileId, string? newProfileMode, TaskEngine? tasks = null)
    {
        _tasks = tasks;
        CheckProfileId(profileId);
        ProfileId = profileId;
        _path = Path.Combine(directory, ProfileId + ".json");
        _processLock = new FileStream(Path.Combine(directory, ProfileId + ".lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            // "reconstructed" starts a new profile at level 1 in the tutorial (docs/SERVER-RECONSTRUCTION.md);
            // the default keeps the inherited demonstration start. Existing files keep their schema.
            bool reconstructed = newProfileMode switch
            {
                null or "legacy" => false,
                "reconstructed" => true,
                _ => throw new InvalidOperationException("LocalProfile:NewProfileMode must be legacy or reconstructed."),
            };
            _profile = File.Exists(_path)
                ? JsonSerializer.Deserialize<Profile>(File.ReadAllBytes(_path)) ?? throw new InvalidDataException("Profile file is empty.")
                : reconstructed
                    ? new Profile(2, ProfileId, 0, new Dictionary<int, int>(), Reconstruction.TutorialGhoul, Reconstruction.StartState())
                    : new Profile(1, ProfileId, 0, new Dictionary<int, int> { [2] = 1 });
            if (_profile.SchemaVersion is not (1 or 2) || _profile.ProfileId != ProfileId || _profile.Facts is null || _profile.Revision < 0 ||
                !DistanceLedger.Valid(_profile.Movement) || !KnownStages.Contains(_profile.QuestStage) || (_profile.SchemaVersion == 2) != (_profile.Player is not null) ||
                (_profile.Player is { } player && (player.Exp < 0 || player.Gold < 0 || player.SkillPoints < 0 ||
                    player.Skills is null || player.Items is null || player.Granted is null ||
                    player.Distance is { } distance && (distance.Metres < 0 || distance.Requests is null ||
                        distance.Requests.Count > 4096 || distance.Requests.Values.Any(v => v <= 0)))))
                throw new InvalidDataException("Profile schema or identity does not match the configured local profile.");
        }
        catch { _processLock.Dispose(); throw; }
    }

    public Profile Snapshot()
    {
        lock (_gate) return Copy(_profile);
    }

    /// <summary>Operator-only replacement. The registry must hold its gate and reject connected profiles.
    /// The backup callback completes before the atomic replacement; caller supplies an existing validated
    /// snapshot or Reconstruction.StartState, never deserialized browser profile data.</summary>
    public Profile AdminReplace(long expectedRevision, Profile template, Action<Profile> backup, bool rebaseMovement = false)
    {
        lock (_gate)
        {
            if (_profile.Revision != expectedRevision) throw new InvalidOperationException("Profile changed; refresh before retrying.");
            if (template.SchemaVersion != 2 || template.Player is null || !KnownStages.Contains(template.QuestStage))
                throw new InvalidOperationException("Only reconstructed profiles can be administered.");
            backup(Copy(_profile));
            return WriteProfile(Copy(template) with { ProfileId = ProfileId, Revision = checked(_profile.Revision + 1), Movement = rebaseMovement ? _profile.Movement?.Rebase(template.Player.Distance?.Metres ?? 0) : _profile.Movement?.Copy() });
        }
    }

    public Profile MergeFacts(IReadOnlyDictionary<int, int> changes, bool persistNoOp = true)
    {
        lock (_gate)
        {
            if (!persistNoOp && changes.All(item => _profile.Facts.TryGetValue(item.Key, out int saved) && saved == item.Value))
                return Copy(_profile);
            return SaveFacts(changes);
        }
    }

    public Profile MergeFactsAndStage(IReadOnlyDictionary<int, int> changes, string questStage, bool persistNoOp = false)
    {
        if (questStage != DeadHorseStage && questStage != GriffinStage)
            throw new ArgumentOutOfRangeException(nameof(questStage), "Unsupported synthetic quest stage.");
        lock (_gate)
        {
            // A stale replayed graph may save facts, but must not move the visible quest backwards.
            string nextStage = StageRank(questStage) > StageRank(_profile.QuestStage)
                ? questStage
                : _profile.QuestStage ?? questStage;
            bool factsUnchanged = changes.All(item => _profile.Facts.TryGetValue(item.Key, out int saved) && saved == item.Value);
            if (!persistNoOp && factsUnchanged && _profile.QuestStage == nextStage)
                return Copy(_profile);
            return SaveFacts(changes, nextStage);
        }
    }

    private static int StageRank(string? stage) => stage switch
    {
        Reconstruction.TutorialGhoul => -3,
        Reconstruction.TutorialWitcher => -2,
        Reconstruction.TutorialExam => -1,
        DeadHorseStage => 1,
        GriffinStage => 2,
        PrologueDoneStage => 3,
        JointVentureStage => 4,
        JvObeliskStage => 5,
        JvGiftsStage => 6,
        JvDoneStage => 7,
        _ => 0,
    };

    /// <summary>Applies a reconstructed-state change and the graph facts in one saved revision.
    /// The change receives a detached copy and returns the new state, or null to keep it.</summary>
    public Profile UpdatePlayer(IReadOnlyDictionary<int, int> facts, string? nextStage,
        Func<PlayerState, PlayerState?> change, TaskEngine.Action? taskAction = null,
        Func<TaskEngine.Action?>? taskActionFactory = null)
    {
        if (nextStage is not null && !KnownStages.Contains(nextStage))
            throw new ArgumentOutOfRangeException(nameof(nextStage), "Unsupported quest stage.");
        lock (_gate)
        {
            if (_profile.Player is null) throw new InvalidOperationException("Legacy profiles have no player state.");
            var changed = change(CopyPlayer(_profile.Player));
            string? stage = nextStage is not null && StageRank(nextStage) > StageRank(_profile.QuestStage)
                ? nextStage : _profile.QuestStage;
            bool factsUnchanged = facts.All(item => _profile.Facts.TryGetValue(item.Key, out int saved) && saved == item.Value);
            if (changed is null && factsUnchanged && stage == _profile.QuestStage)
                return Copy(_profile);
            return SaveFacts(facts, stage, changed, taskActionFactory?.Invoke() ?? taskAction);
        }
    }

    /// <summary>Movement ledger, total and task progress settle in one durable revision under the profile lock.
    /// The callback gets a detached snapshot; failure leaves both the frontier and earned total unchanged.</summary>
    public Profile UpdateMovement(Func<Profile, Profile?> change, TaskEngine.Action? action = null)
    {
        lock (_gate)
        {
            var next = change(Copy(_profile));
            if (next is null) return Copy(_profile);
            if (_tasks is not null && next.Player is { } player)
                next = next with { Player = _tasks.Transition(_profile, player, action) };
            return WriteProfile(next with { Revision = checked(_profile.Revision + 1) });
        }
    }

    private static PlayerState CopyPlayer(PlayerState player) => player with
    {
        Distance = player.Distance is null ? null : player.Distance with { Requests = new(player.Distance.Requests) },
        Skills = new List<int>(player.Skills),
        Items = player.Items.ToDictionary(pair => pair.Key, pair => new Dictionary<int, int>(pair.Value)),
        Granted = new List<string>(player.Granted),
        Kills = new Dictionary<int, int>(player.Kills ?? new Dictionary<int, int>()),
        Summons = player.Summons?.ToList(),
        StoryPlaces = player.StoryPlaces is null ? null : new Dictionary<string, StoryPlace>(player.StoryPlaces),
        KilledInstances = new Dictionary<long, long>(player.KilledInstances ?? new Dictionary<long, long>()),
        StoryDone = player.StoryDone is null ? null : new List<string>(player.StoryDone),
        KnowledgeClaimed = player.KnowledgeClaimed is null ? null : new Dictionary<int, int>(player.KnowledgeClaimed),
        Brewers = player.Brewers?.ToList(),
        OneTimeBundles = player.OneTimeBundles?.ToList(),
        Sensed = player.Sensed is null ? null : new Dictionary<long, long>(player.Sensed),
        Modifiers = player.Modifiers?.ToList(),
        HerbRespawns = player.HerbRespawns is null ? null : new Dictionary<long, long>(player.HerbRespawns),
        Nests = player.Nests is null ? null : player.Nests with { Nests = new Dictionary<long, NestProgress>(player.Nests.Nests) },
        Story = player.Story is null ? null : player.Story with
        {
            Active = player.Story.Active.ToList(), Started = player.Story.Started.ToList(),
            Finished = player.Story.Finished.ToList(), Outputs = player.Story.Outputs.ToList(),
            Reached = player.Story.Reached is null ? null : new Dictionary<int, long>(player.Story.Reached),
        },
        Equipment = player.Equipment is null ? null : player.Equipment with
        {
            Swords = player.Equipment.Swords.ToList(), Armors = player.Equipment.Armors.ToList(),
        },
        Transactions = player.Transactions is null ? null : new Dictionary<long, TransactionRecord>(player.Transactions),
        Tasks = player.Tasks is null ? null : TaskEngine.Copy(player.Tasks),
    };

    private static Profile Copy(Profile profile) => profile with
    {
        Facts = new Dictionary<int, int>(profile.Facts),
        Movement = profile.Movement?.Copy(),
        Player = profile.Player is null ? null : CopyPlayer(profile.Player),
    };

    // Caller holds _gate. Return a detached snapshot of the revision actually saved.
    private Profile SaveFacts(IReadOnlyDictionary<int, int> changes, string? questStage = null, PlayerState? player = null,
        TaskEngine.Action? taskAction = null)
    {
        if (_tasks is not null && (player ?? _profile.Player) is { } p)
            player = _tasks.Transition(_profile, p, taskAction);
        var merged = new Dictionary<int, int>(_profile.Facts);
        foreach (var item in changes) merged[item.Key] = item.Value;
        var next = _profile with
        {
            Revision = checked(_profile.Revision + 1),
            Facts = merged,
            QuestStage = questStage ?? _profile.QuestStage,
            Player = player ?? _profile.Player,
        };
        return WriteProfile(next);
    }

    // Caller holds _gate. Publish in-memory state only after the durable file replacement succeeds.
    private Profile WriteProfile(Profile next)
    {
        string pending = _path + ".pending";
        try
        {
            using (var stream = new FileStream(pending, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(pending, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                JsonSerializer.Serialize(stream, next);
                stream.Flush(flushToDisk: true);
            }
            File.Move(pending, _path, overwrite: true);
            _profile = next;
        }
        finally { if (File.Exists(pending)) File.Delete(pending); }
        return Copy(next);
    }

    public void Dispose() => _processLock.Dispose();
}
