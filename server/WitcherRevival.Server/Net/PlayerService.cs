using System.Net;
using System.Net.Sockets;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// One player's game: answers the API requests of that player's sessions (GameSocketService) from their profile, and
/// keeps the player's live state (served monsters, herbs and nests, encounters, summons, the area, settled requests).
/// ProfileRegistry creates one per profile; the weather cache is shared by all players. Wire layouts follow the pinned
/// upstream layouts checked against 1.1.116 where noted; see CONTRACT.md. Graph names are bounded and sanitized for
/// diagnostics.
/// </summary>
public sealed partial class PlayerService(ILogger<PlayerService> log, IConfiguration cfg, LocalProfileStore profiles,
    WorldWeather weather, TaskEngine tasks, WorldPolicy world, SocialService? social = null)
{
    private const byte Ch_Api = 1;   // outer channel type of API frames (GameSocketService)
    private const string UnnamedPlayer = "Unnamed";
    private readonly SkillBalancePolicy skillBalance = SkillBalancePolicy.FromConfiguration(cfg);

    // Api Method ids (from Api.Method enum). Boot-time + post-boot.
    private const int M_GetPlayerInfo = 3, M_GetInventory = 5, M_GetEquipment = 9;
    private const int M_GetDailyContracts = 20, M_GetLocationsByCell = 40;
    private const int M_GetSensedMonsters = 43, M_GetCurrentObjective = 61;
    private const int M_GetWeather = 67, M_GetDailyShopBundles = 79;
    private const int M_GetOneTimeShopBundles = 83, M_GetExpiringEffects = 85;
    private const int M_LoadCells = 88, M_GetPlayerModifiers = 91, M_AddPlayerModifier = 90, M_RemovePlayerModifier = 92;
    private const int M_LevelUp = 31, M_CheckInApp = 101, M_GatherHerb = 19;
    private const int M_UseLure = 18, M_EncounterNest = 52, M_EndNestCombat = 53;
    private const int M_GetWeeklyContractProgress = 94, M_GetFriends = 102;
    private const int M_GetFriendsNotifications = 110, M_GetInitialPlayerData = 115;
    private const int M_GetMonsterEventProgress = 122;

    // Post-boot player-action Method ids (Api.Method enum) — handled explicitly below so their
    // IntResponse readers don't under-run on the 1-byte BooleanResponse catch-all.
    private const int M_EquipArmor = 11, M_EquipSteelSword = 12, M_EquipSilverSword = 13;
    private const int M_DistanceTraveled = 27, M_SetCustomizationHead = 28;
    private const int M_SetTutorialFinished = 30, M_EquipSword = 55, M_EndBehaviourGraph = 57;
    private const int M_GetFacts = 58, M_GetAllFacts = 59, M_AcquireSkill = 64, M_TrackQuest = 72, M_RelocateQuest = 77;
    private const int M_PrepareToCombat = 10, M_ClaimMonsterKnowledgeReward = 65, M_BuyAutoEquipItems = 98;
    private const int M_CraftItem = 4, M_UseSenses = 42, M_GetCraftingQueue = 44, M_CancelCrafting = 45,
        M_ClaimRecipe = 68, M_BuyShopBundle = 75, M_FinishCrafting = 97, M_GetTransactionStatus = 80, M_BuyShopInAppBundle = 76;
    private const int M_SetFacts = 78, M_UseOilPotions = 89, M_AddSkillPoints = 93, M_ResolveRewards = 119;
    private const int M_SetName = 29, M_ThrowBomb = 39, M_SetGender = 46, M_SetCurrentObjective = 62;

    // ItemManagementWindow.OnRemovePressed: one drop method per item storage (null = not kept by this server).
    private static readonly Dictionary<int, string?> DropMethods = new()
    {
        [47] = ItemKinds.Potions, [48] = ItemKinds.Bombs, [49] = ItemKinds.Oils, [50] = ItemKinds.Lures,
        [51] = ItemKinds.SensesPotions, [71] = ItemKinds.Ingredients, [100] = null, [109] = SocialService.PackItems, [118] = null,
    };
    private const int M_SummonLocalMonsters = 111, M_GetSummonedMonsters = 112;
    private const int M_EncounterSummonedMonster = 113, M_CombatEndSummonedMonster = 114;

    private const int M_GetLastSummoningSkillUsageTime = 117;
    private const int M_CombatEnd = 8, M_EncounterMonster = 41, M_GetMonsterInstances = 87;

    // World monsters generated for the current windows (WorldSpawns), by instance id, and the one being fought.
    private readonly object worldGate = new();
    private readonly Dictionary<long, WorldSpawns.Spawn> worldSpawns = new();
    private long? worldEncountered;

    // Reconstructed profiles keep summoned groups, with their point, across server restarts.
    private readonly PlayableLocations playable = new(cfg["Playable:Url"]);

    private readonly SummonedMonsters summons = new(profiles.Snapshot().Player?.Summons, groups =>
    {
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player => player with { Summons = groups.ToList() });
    });

    // Demonstration values inherited from upstream. Only local profile facts are persisted here.
    private const int LegacyDistanceTraveled = 15000; // Unchanged schema-1 demonstration fixture only.
    private const int InitialSkillPoints = 10;        // GetSkills(63) SkillPoints; AddSkillPoints(93) base

    // Synthetic fixture place: (0,0) by default. Reconstructed story nodes use a place chosen around the
    // LoadCells area instead (StoryPlaceFor); no GPS or account location is read.
    private const string TutPlaceId = "tut_thorstein";
    // Griffin graph identity is recovered from the 1.3.102 donor; its POI setting is present in the original 1.1.116 APK.
    private const long GriffinInstanceId = 5124757777905877227L;
    private const string GriffinSettingsPath = "assets/_bundledassets/story/poi_settings/s00/prolog/gryphon_lq.asset";
    private const string GriffinGraphPath = "s00/prolog/prolog_01_griffin";
    private float TutLat => cfg.GetValue("Tutorial:Latitude", 0f);
    private float TutLng => cfg.GetValue("Tutorial:Longitude", 0f);

    private void StoreFacts(Dictionary<int, int> facts) => profiles.MergeFacts(facts);

    /// <summary>The profile, with a missed "A Joint Venture" stage caught up from the saved facts.</summary>
    private LocalProfileStore.Profile CaughtUp(LocalProfileStore.Profile snapshot)
    {
        if (snapshot.Player is null || Reconstruction.StageFromFacts(snapshot.QuestStage, snapshot.Facts) is not { } stage)
            return snapshot;
        log.LogInformation("  Story stage caught up from facts: {From} -> {To}", snapshot.QuestStage, stage);
        return profiles.UpdatePlayer(new Dictionary<int, int>(), stage, _ => null);
    }

    private static string SafeGraphOutputForLog(string value)
    {
        const int maxChars = 96;
        string safe = new(value.Take(maxChars).Select(c => char.IsControl(c) || c is '\u2028' or '\u2029' ? '?' : c).ToArray());
        return value.Length > maxChars ? safe + "…" : safe;
    }

    private void WriteFactsDict(ByteBuffer b, LocalProfileStore.Profile? snapshot = null)
    {
        snapshot ??= profiles.Snapshot();
        b.WriteInt(snapshot.Facts.Count);
        foreach (var (key, value) in snapshot.Facts.OrderBy(pair => pair.Key)) { b.WriteInt(key); b.WriteInt(value); }
    }

    public async Task HandleApiAsync(Stream stream, Frame f, CancellationToken ct, Guid movementSession = default)
    {
        ApiProtocol.ApiRequest req;
        req = ApiProtocol.Parse(f.Data);

        log.LogInformation("  Api request: Id={Id} Method={Method} dataLen={Len}", req.Id, req.Method, req.Data.Length);

        // Client: ClientWorker.HandleRetries (0x1931EE8) re-sends every unanswered request with the same bytes and
        // request id every ClientSettings.RetryIntervalSeconds (7 s). A request that changes the profile is answered
        // once; its repeat gets the same response without being settled again.
        if (ReplayedResponse(req) is { } replay)
        {
            await FrameCodec.WriteAsync(stream, Ch_Api, ApiProtocol.BuildResponse(req.Id, req.Method, replay), ct);
            log.LogInformation("  TX  Api response Method={Method} Id={Id} replayed", req.Method, req.Id);
            return;
        }

        // A request that fails is answered with its method's verified refusal and the session goes on; a method
        // without a verified refusal body stays unanswered rather than getting an invented one (the client asks
        // again after ClientSettings.RetryIntervalSeconds). Frame, envelope and write errors still end the session.
        var achievementsBefore = profiles.Snapshot().Player?.Tasks?.Achievements.Keys.ToHashSet() ?? [];
        byte[] methodPayload;
        Admin.MapObservation.Snapshot? observedMap = null;
        try
        {
            methodPayload = req.Method switch
            {
                M_LoadCells => HandleLoadCells(req),           // LoadCellsResponse : BooleanResponse -> 1 byte
                M_GetInitialPlayerData => BuildInitialPlayerData(),
                60 => BuildActiveQuestNodeInstances(),
                // GetPlayerInfo(3) + GetInventory(5) are re-requested STANDALONE post-boot (PlayerData re-sync),
                // not just inside the 115 batch — answer them with the same payloads or the client under-runs.
                M_GetPlayerInfo => BuildGetPlayerInfoPayload(),
                M_GetInventory => BuildGetInventoryPayload(),
                M_GetWeather => BuildGetWeatherResponse(req),
                M_GetLocationsByCell => BuildGetLocationsByCellResponse(req, out observedMap),
                M_GetMonsterInstances => BuildGetMonsterInstancesResponse(req),
                M_EncounterMonster => HandleEncounterMonster(req),
                M_CombatEnd => HandleCombatEnd(req),
                M_GetExpiringEffects => BuildGetExpiringEffectsResponse(),
                M_GetFriends => BuildGetFriendsResponse(),
                M_GetFriendsNotifications => BuildGetFriendsNotificationsResponse(),
                M_GetDailyContracts => DailyTasksResponse(),
                M_GetWeeklyContractProgress => HuntResponse(),
                M_GetMonsterEventProgress => TimedTasksResponse(),
                21 or 22 or 23 or 81 or 86 or 95 or 123 or 125 => HandleTaskRequest(req),
                M_GetSensedMonsters => BuildGetSensedMonstersResponse(),
                M_GetCurrentObjective => BuildGetCurrentObjectiveResponse(),
                M_SetCurrentObjective => HandleSetCurrentObjective(req),
                M_GetDailyShopBundles => BuildGetDailyShopBundlesResponse(),
                M_GetOneTimeShopBundles => BuildGetOneTimeShopBundlesResponse(),
                M_GetPlayerModifiers => BuildGetPlayerModifiersResponse(),
                M_CheckInApp => HandleCheckInApp(req),
                M_GatherHerb => HandleGatherHerb(req),
                M_EncounterNest => HandleEncounterNest(req),
                M_UseLure => HandleUseLure(req),
                M_EndNestCombat => HandleEndNestCombat(req),
                M_AddPlayerModifier => HandleAddPlayerModifier(req),
                M_RemovePlayerModifier => HandleRemovePlayerModifier(req),
                >= 103 and <= 108 => HandleFriendAction(req),
                M_GetEquipment or 6 or 7 or 24 or 56 or 63 or 69 or 70 => InitialPlayerDataPart(req.Method),
                // Post-boot player actions (request layouts decoded from dump.cs — see each builder/helper):
                M_DistanceTraveled => HandleDistanceTraveled(req),
                2001 => HandleMovement(req, movementSession, f.Data),
                M_EquipArmor or M_EquipSword or M_EquipSteelSword or M_EquipSilverSword => HandleEquip(req),
                M_SetCustomizationHead => BuildIntResponse(true, ReadIntParam(req, fallback: 1)), // echo head id
                M_SetTutorialFinished => BuildIntResponse(true, 1),  // request has NO payload (dump.cs 602627)
                M_AcquireSkill => HandleAcquireSkill(req),
                M_TrackQuest => HandleTrackQuest(req),
                M_RelocateQuest => HandleRelocateQuest(req),
                M_AddSkillPoints => HandleAddSkillPoints(req),
                M_UseOilPotions => BuildUseOilPotionsResponse(req),
                M_PrepareToCombat => HandlePrepareToCombat(req),
                M_BuyAutoEquipItems => HandleBuyAutoEquipItems(req),
                M_BuyShopBundle => HandleBuyShopBundle(req),
                M_GetTransactionStatus => HandleGetTransactionStatus(req),
                M_BuyShopInAppBundle => HandleBuyShopInAppBundle(req),
                M_CraftItem => HandleCraftItem(req),
                M_ClaimRecipe => HandleClaimRecipe(req),
                M_CancelCrafting => HandleCancelCrafting(req),
                M_FinishCrafting => ApiProtocol.Boolean(false),
                M_GetCraftingQueue => BuildGetCraftingQueue(),
                M_UseSenses => HandleUseSenses(req),
                M_ClaimMonsterKnowledgeReward => HandleClaimMonsterKnowledgeReward(req),
                M_SetName => HandleSetName(req),
                M_SetGender => HandleSetGender(req),
                M_ThrowBomb => HandleThrowBomb(req),
                M_SummonLocalMonsters => HandleSummonLocalMonsters(req),
                M_GetSummonedMonsters => BuildGetSummonedMonstersResponse(),
                M_EncounterSummonedMonster => HandleEncounterSummonedMonster(req),
                M_CombatEndSummonedMonster => HandleCombatEndSummonedMonster(req),
                // GetLastSummoningSkillUsageTime (117): no request fields; IntResponse [byte Result][int Param]
                // (Factory 0x1E79FE4) with the last successful use in Unix seconds; 0 = never.
                M_GetLastSummoningSkillUsageTime => GetLastAuraUsage(req),
                M_ResolveRewards => BuildResolveRewardsResponse(),  // post-sync reward gate — see builder
                M_EndBehaviourGraph => BuildEndBehaviourGraphResponse(req),
                M_SetFacts => HandleSetFacts(req),
                _ when DropMethods.TryGetValue(req.Method, out var dropKind) => HandleDropItems(req, dropKind),
                M_GetFacts or M_GetAllFacts => BuildGetFactsResponse(),
                _ => BuildCatchAllResponse(req.Method),
            };
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            if ((TaskMutations.Contains(req.Method) || req.Method == 125 ? TaskRefusal(req) : RefusalFor(req)) is not { } refusal)
            {
                log.LogWarning("  Api request unanswered Method={Method} Id={Id} reason={Reason}", req.Method, req.Id, ex.GetType().Name);
                return;
            }
            log.LogWarning("  Api request refused Method={Method} Id={Id} reason={Reason}", req.Method, req.Id, ex.GetType().Name);
            methodPayload = refusal;
        }

        RememberResponse(req, methodPayload);
        var payload = ApiProtocol.BuildResponse(req.Id, req.Method, methodPayload);
        await FrameCodec.WriteAsync(stream, Ch_Api, payload, ct);
        if (observedMap is not null) Admin.MapObservation.Record(profiles.ProfileId, observedMap);
        log.LogInformation("  TX  Api response Method={Method} Id={Id} ({Len}B)", req.Method, req.Id, payload.Length);
        foreach (int level in LevelsToAnnounce(push: ExpMethods.Contains(req.Method)))
        {
            var push = ApiProtocol.BuildResponse(0, M_LevelUp, BuildLevelUpPush(level), ack: Array.Empty<long>());
            await FrameCodec.WriteAsync(stream, Ch_Api, push, ct);
            log.LogInformation("  TX  Api push LevelUp level={Level} ({Len}B)", level, push.Length);
        }
        // RPC25 carries only the trophy ID. Bootstrap/reconciliation uses the timestamped RPC24 map.
        if (req.Method is 8 or 114 or 53 or 57 or 78 or 19 or 27 or 64 or 68 or 2001)
            foreach (int id in (profiles.Snapshot().Player?.Tasks?.Achievements.Keys.AsEnumerable() ?? []).Except(achievementsBefore))
            {
                var trophy = new ByteBuffer(); trophy.WriteInt(id);
                await FrameCodec.WriteAsync(stream, Ch_Api, ApiProtocol.BuildResponse(0, 25, trophy.ToArray(), ack: []), ct);
            }
    }

    // Requests that change the profile (rewards, purchases, spending, crafting, skills, modifiers, drops).
    private static readonly HashSet<int> SettledMethods =
    [
        M_CombatEnd, M_CombatEndSummonedMonster, M_EndBehaviourGraph, M_EndNestCombat, M_EncounterNest,
        M_PrepareToCombat, M_UseOilPotions, M_ClaimMonsterKnowledgeReward, M_UseLure, M_GatherHerb, M_ThrowBomb,
        M_CraftItem, M_CancelCrafting, M_ClaimRecipe, M_BuyShopBundle, M_BuyShopInAppBundle, M_FinishCrafting, M_BuyAutoEquipItems,
        M_AcquireSkill, M_AddSkillPoints, M_ResolveRewards, M_AddPlayerModifier, M_SummonLocalMonsters,
        47, 48, 49, 50, 51, 71, 109, M_RelocateQuest,
    ];
    private static readonly TimeSpan ReplayWindow = TimeSpan.FromMinutes(15);
    private readonly Dictionary<(int Method, long Id), (DateTime At, byte[] Payload)> settled = new();

    private byte[]? ReplayedResponse(ApiProtocol.ApiRequest req)
    {
        if (IsAuraRequest(req)) return null; // Aura validates its persisted nonce and payload together.
        if (!SettledMethods.Contains(req.Method)) return null;
        lock (settled)
            return settled.TryGetValue((req.Method, req.Id), out var hit) && DateTime.UtcNow - hit.At < ReplayWindow
                ? hit.Payload : null;
    }

    private void RememberResponse(ApiProtocol.ApiRequest req, byte[] payload)
    {
        if (IsAuraRequest(req)) return;
        if (!SettledMethods.Contains(req.Method)) return;
        lock (settled)
        {
            var now = DateTime.UtcNow;
            foreach (var key in settled.Where(e => now - e.Value.At >= ReplayWindow).Select(e => e.Key).ToList())
                settled.Remove(key);
            settled[(req.Method, req.Id)] = (now, payload);
        }
    }

    // Level-ups are pushed only after the requests that grant experience (CombatEnd 8, CombatEndSummonedMonster
    // 114, EndBehaviourGraph 57, EndNestCombat 53). A push during boot reaches PlayerData.OnLevelUp before the level table is
    // loaded: its GetPlayerInfo answer throws in CharacterProgression.GetLevel and the level-up window never
    // opens (seen on LAB 16 when a push followed LoadCells).
    private static readonly HashSet<int> ExpMethods = [M_CombatEnd, M_CombatEndSummonedMonster, M_EndBehaviourGraph, M_EndNestCombat];

    /// <summary>The levels a reconstructed profile has reached since the last LevelUp push, in order, with their
    /// rewards added to the inventory; empty unless <paramref name="push"/>. A profile without the mark (new or
    /// older files) gets its current level on its first request, so levels gained before this push existed are not
    /// replayed.</summary>
    private List<int> LevelsToAnnounce(bool push)
    {
        var levels = new List<int>();
        if (profiles.Snapshot().Player is not { } current ||
            current.LevelAnnounced is int known && (!push || known >= Reconstruction.LevelForExp(current.Exp)))
            return levels;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
        {
            int level = Reconstruction.LevelForExp(player.Exp);
            if (player.LevelAnnounced is int from)
                for (int next = from + 1; next <= level; next++)
                {
                    levels.Add(next);
                    AddItems(player, Reconstruction.LevelRewards(next));
                }
            return player with { LevelAnnounced = level };
        });
        return levels;
    }

    // LevelUpResponse list order (Factory.Deserialize 0x1E78330), by the item kinds this server keeps.
    private static readonly string?[] LevelUpLists =
    [
        ItemKinds.Potions, ItemKinds.Bombs, ItemKinds.Oils, ItemKinds.Lures, null, null, null, null, ItemKinds.SensesPotions, null,
        ItemKinds.Ingredients, null, null,
    ];

    /// <summary>LevelUp (31) is a server push: an Api RESPONSE message with TypeMessage [long 0][int 31] and no
    /// acknowledged request. LevelUpResponse.Factory.Deserialize (0x1E78330): [int Level] then 13 lists, each
    /// ByteBuffer.ReadList (0x19308EC) [int n][int × n], in field order: potions, bombs, oils, lures, potion,
    /// bomb, oil and lure recipes, senses potions, consumables, ingredients, brewers and summoning scrolls; an id
    /// is repeated once per unit. PlayerData.OnLevelUp (0x1A09568) runs the level-up events (ShowWindowsEvent: the
    /// level-up window, then CheckInApp 101) and asks for GetPlayerInfo (3); PlayerInventory.OnLevelUp
    /// (0x1A0AB68) marks the listed items as new; PlayerSkills.OnLevelUp (0x1A14664) announces skills whose
    /// required level is reached. The lists carry the level's rewards (Reconstruction.LevelRewards).</summary>
    private static byte[] BuildLevelUpPush(int level)
    {
        var rewards = Reconstruction.LevelRewards(level);
        var b = new ByteBuffer();
        b.WriteInt(level);
        foreach (var kind in LevelUpLists)
        {
            var ids = kind is null ? [] : rewards.Where(r => r.Kind == kind).SelectMany(r => Enumerable.Repeat(r.Id, r.Count)).ToList();
            b.WriteInt(ids.Count);
            foreach (int id in ids) b.WriteInt(id);
        }
        return b.ToArray();
    }

    /// <summary>CheckInApp (101), sent by ShowWindowsEvent.ResolveWindows after the level-up windows; the
    /// coroutine waits for the answer. CheckInAppStatusRequest has no fields; the response is a BooleanResponse
    /// [byte Success] (Factory 0x247CD58). OnCheckInAppStatusResponse (0x1A05E84) finishes on true and, on false, opens the
    /// recommended purchase window with an in-app bundle. The LAB server sells no in-app bundles, so it answers
    /// true.</summary>
    private static byte[] HandleCheckInApp(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 0) throw new InvalidDataException("Unexpected CheckInApp payload.");
        return ApiProtocol.Boolean(true);
    }

    /// <summary>
    /// The inherited 19-item demonstration batch plus one explicit unavailable response for method122.
    /// Each sub-response is inline, with no length prefix.
    /// The facts and active node use one immutable profile snapshot; all other data remain fixtures.
    /// Field layouts must still be compared with the 1.1.116 serializers.
    /// </summary>
    private byte[] BuildInitialPlayerData() => BuildInitialPlayerData(out _);

    /// <summary>Serves a method of the 115 batch requested on its own with the same bytes as in the batch
    /// (the reconstructed tutorial profile re-requests recipes and brewers after boot).</summary>
    private byte[] InitialPlayerDataPart(int method)
    {
        BuildInitialPlayerData(out var parts);
        return parts.TryGetValue(method, out var part) ? part : throw new NotSupportedException("Not a batch method.");
    }

    private byte[] BuildInitialPlayerData(out Dictionary<int, byte[]> parts)
    {
        parts = new Dictionary<int, byte[]>();
        RefreshTasks(issue: true);
        var snapshot = CaughtUp(profiles.Snapshot());
        var b = new ByteBuffer();
        var marks = new List<(int Method, int Start)>();
        void Part(int method) { b.WriteInt(method); marks.Add((method, b.Length)); }
        if (!cfg.GetValue("Player:SendInitialData", true))
        {
            b.WriteInt(0);   // empty batch — nothing to deserialize (debug only; re-bypass PlayerData too)
            return b.ToArray();
        }

        const int equippedId = 1;   // MUST match the ids in PreloaderStaticData.LoadoutOverrides
  
        bool reconstructed = snapshot.Player is not null;
        // 19 inherited responses, Aura timestamp and unavailable seasonal event progress; reconstructed profiles add 112.
        b.WriteInt(reconstructed ? 22 : 21);
  
        // Method 3 — GetPlayerInfo (shared builder — also served standalone post-boot)
        Part(M_GetPlayerInfo);
        b.WriteBytes(BuildGetPlayerInfoPayload());

        // Method 9 — GetEquipment
        // Constructor: SwordsCount (int), [int*SwordsCount], ArmorsCount (int), [int*ArmorsCount], EquippedArmor (int), EquippedSword (int)
        // Owned ids per the ID contract — every id here MUST exist in PreloaderStaticData (Track A: swords 1..6, armors 1..6).
        Part(M_GetEquipment);
        if (snapshot.Player is { } owner)
        {
            // Reconstructed profiles: the owned and equipped swords and armours (starting gear for older files).
            var gear = EquipmentOf(owner);
            b.WriteInt(gear.Swords.Count);
            foreach (int sword in gear.Swords) b.WriteInt(sword);
            b.WriteInt(gear.Armors.Count);
            foreach (int armor in gear.Armors) b.WriteInt(armor);
            b.WriteInt(gear.Armor);
            b.WriteInt(gear.Sword);
        }
        else
        {
            b.WriteInt(3);                     // SwordsCount
            b.WriteInt(1);                     // owned sword ids
            b.WriteInt(2);
            b.WriteInt(3);
            b.WriteInt(2);                     // ArmorsCount
            b.WriteInt(1);                     // owned armor ids
            b.WriteInt(2);
            b.WriteInt(equippedId);            // EquippedArmor
            b.WriteInt(equippedId);            // EquippedSword
        }

        // Method 5 — GetInventory (shared builder — also served standalone post-boot)
        Part(M_GetInventory);
        b.WriteBytes(BuildGetInventoryPayload());

        // Method 6 — GetKnownRecipes  (empty Dictionary<int, HashSet<int>>)
        // PlayerInventory.Initialize (0x1747F04) synchronizes this key DIRECTLY (not via SignalBus) and
        // invokes OnGetKnownRecipesResponse even when the key is missing -> null Data -> NRE that froze the
        // boot at 68% (runtime 2026-07-04). Wire format verified via GetKnownRecipesResponse.Factory.ReadHashSet
        // (0x1F7DCB8): [int outerCount] then per entry [int key][int innerCount][int*innerCount]. Empty = [int 0].
        Part(6);
        if (snapshot.Player is not null) b.WriteBytes(BuildKnownRecipes(snapshot.Player));
        else b.WriteInt(0);  // KnownRecipes (0 entries)

        // Method 7 — GetKilledMonsters
        // [int KilledMonsters count][(int monsterId,int count)…] then [int ClaimedTiers count][(int,int)…]
        // Bestiary content: kill counts for monster ids 1..3 (Track A defines monsters 1..8 in static data).
        Part(7);
        if (snapshot.Player is not null)
        {
            WriteItemMap(b, Reconstruction.AllKills(snapshot.Player, snapshot.Facts));  // Reconstructed profiles: won fights per monster id.
        }
        else
        {
            b.WriteInt(3);                  // KilledMonsters (3 entries)
            b.WriteInt(1); b.WriteInt(5);   // monster 1 killed 5×
            b.WriteInt(2); b.WriteInt(2);   // monster 2 killed 2×
            b.WriteInt(3); b.WriteInt(1);   // monster 3 killed 1×
        }
        // ClaimedMonsterKnowledgeTiers: reconstructed profiles' claimed tiers; legacy profiles none.
        WriteItemMap(b, snapshot.Player?.KnowledgeClaimed);

        // Method 24 — GetAchievements  (bool Success, Dictionary<int,int> achievementId -> value)
        // CRITICAL: the client deserializer (0x1F736E4) reads [byte Success][int N][N ints] where the loop
        // counter increments by 2 (add w24,w24,#2) — so N is the number of INTS (2 × entries), NOT the pair
        // count. Writing N=2 for 2 entries made the client read only 1 pair and leave 8 bytes, which drifted
        // the whole batch and DROPPED the last two methods (43, 56) — the exact cause of the PoiModule NRE.
        Part(24);
        b.WriteByte(1);                 // Success = true
        if (snapshot.Player is not null)
        {
            var earned = TasksEnabled ? snapshot.Player.Tasks?.Achievements ?? [] : new Dictionary<int, int>();
            b.WriteInt(earned.Count * 2); // Factory 0x2483D40 counts integers, not pairs.
            foreach (var (id, at) in earned.OrderBy(p => p.Key)) { b.WriteInt(id); b.WriteInt(at); }
        }
        else
        {
            b.WriteInt(4);                  // N = 4 ints = 2 achievement entries (Track A defines achievements 1..6)
            b.WriteInt(1); b.WriteInt(1);   // achievement 1 -> 1
            b.WriteInt(2); b.WriteInt(1);   // achievement 2 -> 1
        }

        // Method 63 — GetSkills
        // Constructor order: Skills (List<int> of skill ids, NO DTO), SkillPoints (int)
        Part(63);
        if (snapshot.Player is { } owned)
        {
            b.WriteInt(owned.Skills.Count);
            foreach (int skill in owned.Skills) b.WriteInt(skill);
            b.WriteInt(owned.SkillPoints);
        }
        else
        {
            b.WriteInt(3);  // Skills list count (Track A defines skills 1..8)
            b.WriteInt(1);  // owned skill ids
            b.WriteInt(2);
            b.WriteInt(3);
            b.WriteInt(InitialSkillPoints);  // SkillPoints = 10
        }

        // Method 27 — DistanceTraveled (IntResponse: bool Result, int Param = total distance)
        Part(M_DistanceTraveled);
        b.WriteByte(1);                    // Result
        b.WriteInt(snapshot.Player is { } distancePlayer ? distancePlayer.Distance?.Metres ?? 0 : LegacyDistanceTraveled);

        // Method 69 — GetBrewers
        // Constructor order: Success (bool), Brewers (List)
        Part(69);
        if (snapshot.Player is not null) b.WriteBytes(BuildGetBrewers());
        else
        {
            b.WriteByte(1); // Success
            b.WriteInt(0);  // Brewers list count
        }

        // Method 59 — GetAllFacts  (Dictionary<int, int> Facts — NO leading Success byte)
        // ServerFactDatabaseModule.InitializeModule (0x178A3D0, now un-bypassed in hook.js) synchronizes this
        // key; HandleGetAllFactsResponse (0x178A4E8) builds _factDatabase from it AND sets Initialized=true.
        // Without it: _factDatabase stays null -> PlayerModule.GetFact(4) NREs (froze boot at 76%), and SFDB
        // never flips Initialized -> boot hangs. Wire format verified via GetAllFactsResponse.Factory.Deserialize
        // (0x1F74664): just [int count] then [int key][int value] pairs. GetFact returns 0 for a missing key
        // (ContainsKey guard, no throw). Serves the persisted fact store (seeded {2:1} on fresh state — see
        // LoadFacts) so tutorial progress survives a client reboot.
        Part(M_GetAllFacts);
        WriteFactsDict(b, snapshot);

        // Method 83 — GetDailyShopBundles
        // Deserializer (0x1F75C80): [byte Success] [int count] [items...]
        Part(83);
        if (snapshot.Player is not null) b.WriteBytes(BuildGetOneTimeShopBundlesResponse());
        else
        {
            b.WriteByte(1);
            b.WriteInt(0);
        }

        // Method 79 — GetOneTimeShopBundles
        // Deserializer (0x1F7AFF8): [byte Success] [int count] [items...]
        Part(79);
        if (snapshot.Player is not null) b.WriteBytes(BuildGetDailyShopBundlesResponse());
        else
        {
            b.WriteByte(1);
            b.WriteInt(0);
        }

        // Method 91 — GetPlayerModifiers
        // Deserializer (0x1F7B160): [int Result] [int count] [ExpiringPlayerModifier...]
        Part(91);
        WritePlayerModifiers(b, snapshot);

        // Method 70 — GetFinishedSeasonQuests
        // [int Season][int setN][set][int TrackedQuestId][int listN][list]
        // The single authored prologue uses quest145 and static node IDs1/2.
        // Old StoryModule copies this field directly; ActiveQuestIdList does not select it.
        Part(70);
        b.WriteInt(0);  // CurrentSeason
        // After the griffin (reconstructed profiles) the tutorial 144 and the prologue 145 are finished and
        // "A Joint Venture" 146 is the active quest; the client shows only nodes of active quests (node 287
        // belongs to quest 146). StoryGraph.FillAvailableNodes descends from the season root (144) only through
        // finished quests, so 144 must be finished for 146's root node to become available, and the journal
        // lists the logs of finished and active children of the root (145 finished, 146 active).
        // Once its gargoyle is beaten "A Joint Venture" is finished too and no quest is tracked (-1).
        bool jointVentureDone = snapshot.QuestStage == LocalProfileStore.JvDoneStage;
        bool jointVenture = QueuedStoryNode(snapshot) is not null || snapshot.QuestStage is LocalProfileStore.JointVentureStage
            or LocalProfileStore.JvObeliskStage or LocalProfileStore.JvGiftsStage;
        // Season 1 (StoryEngine) follows with its finished and started quests and the tracked one.
        var season1 = SeasonOne(snapshot);
        if (jointVentureDone)
        {
            var finished = new List<int> { 144, 145, 146 };
            finished.AddRange(season1!.Finished);
            b.WriteInt(finished.Count);
            foreach (int quest in finished) b.WriteInt(quest);
        }
        else if (jointVenture) { b.WriteInt(2); b.WriteInt(144); b.WriteInt(145); }
        else b.WriteInt(0);
        int trackedQuest = CurrentTrackedQuest(snapshot);
        b.WriteInt(trackedQuest);  // TrackedQuestId: tutorial 144, the prologue 145, "A Joint Venture" 146, then season 1.

        if (jointVentureDone)  // ActiveQuestIdList: the started season 1 quests.
        {
            b.WriteInt(season1!.Started.Count);
            foreach (int quest in season1.Started) b.WriteInt(quest);
        }
        else { b.WriteInt(1); b.WriteInt(trackedQuest); }  // ActiveQuestIdList: the single tracked quest.

        // Same node snapshot as standalone RPC 60, consistent with the facts in this batch.
        Part(60);
        b.WriteBytes(BuildActiveQuestNodeInstances(snapshot));

        // Method 20 — the same persisted tasks as the standalone response.
        Part(M_GetDailyContracts);
        b.WriteBytes(DailyTasksResponse());

        // Method 94 — GetWeeklyContractProgress
        // Share the 1.1.116-aligned writer with standalone RPC 94.
        Part(M_GetWeeklyContractProgress);
        b.WriteBytes(HuntResponse());

        // Method 43 — GetSensedMonsters
        // [byte Success][int count][long*sensedMonsters]
        Part(M_GetSensedMonsters);
        WriteSensedMonsters(b, snapshot);

        // Method 56 — GetKilledMonsterInstances  (empty List<long>)
        // PoiModule.InitializeModule's final Subscribe fires OnGetKilledMonstersResponse, which
        // synchronizes THIS key; missing -> null Data -> NRE aborted PoiModule init (stuck at "Loading
        // Points of Interest", runtime 2026-07-05). Wire format verified via Factory.Deserialize
        // (0x1F7A7CC): just [int count] then [long*count]. Empty = [int 0].
        Part(56);
        if (snapshot.Player is { } killer)
        {
            // Reconstructed profiles: defeated world monsters whose window has not ended yet.
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            var killed = (killer.KilledInstances ?? new Dictionary<long, long>()).Where(k => k.Value > now).Select(k => k.Key).ToList();
            b.WriteInt(killed.Count);
            foreach (long id in killed) b.WriteLong(id);
        }
        else
        {
            b.WriteInt(0);  // KilledMonsterInstances list count
        }

        // Method 112 — GetSummonedMonsters: PoiModule.OnGetSummonedMonstersResponse places the living
        // summoned monsters around their saved point again after the client restarts.
        if (reconstructed)
        {
            Part(M_GetSummonedMonsters);
            b.WriteBytes(BuildGetSummonedMonstersResponse());
        }

        // OnGameStarted (0x1A2A8C0) synchronizes Aura from this cache. A missing 117 invokes its
        // callback with null; use the same IntResponse body as standalone GetLastAuraUsage.
        Part(M_GetLastSummoningSkillUsageTime);
        b.WriteBytes(BuildIntResponse(true, snapshot.Player?.Aura?.At ?? 0));

        // Method122 is required by SeasonContractsModule initialization. Failure is explicit;
        // this prototype does not claim to provide a historical no-active-event state.
        Part(M_GetMonsterEventProgress);
        b.WriteBytes(TimedTasksResponse());

        log.LogInformation("  BuildInitialPlayerData: {Count} sub-responses, equipped id={Id}, mode={Mode}", marks.Count, equippedId,
            snapshot.Player is null ? "legacy" : "reconstructed");
        var bytes = b.ToArray();
        for (int i = 0; i < marks.Count; i++)
        {
            int partEnd = i + 1 < marks.Count ? marks[i + 1].Start - 4 : bytes.Length;
            parts[marks[i].Method] = bytes[marks[i].Start..partEnd];
        }
        return bytes;
    }

    // ── Post-boot Api response builders ─────────────────────────────────────────
    // Wire formats decoded from the dump.cs *Response classes (ctor field order = Serialize write order).
    // All return empty/default data so the client's response handler doesn't NRE and the response
    // timeout overlay ("Ожидание ответа сервера…") never fires.

    /// <summary>GetWeather (67): GetWeatherRequest [float lat][float lng] (0x2476E24); GetWeatherResponse
    /// [int WeatherCode] (0x247A5F4). The weather of the position's 0.1° cell (WorldWeather); Clear when no
    /// weather source is configured or the request carries no position.</summary>
    private byte[] BuildGetWeatherResponse(ApiProtocol.ApiRequest req)
    {
        int code = WorldWeather.Clear;
        if (req.Data.Length == 8)
        {
            var r = new ByteBuffer(req.Data);
            float lat = r.ReadFloat(), lng = r.ReadFloat();
            code = weather.Code(lat, lng);
        }
        log.LogInformation("  GetWeather code={Code} source={Source}", code, weather.Enabled ? "open-meteo" : "none");
        var b = new ByteBuffer();
        b.WriteInt(code);
        return b.ToArray();
    }

    /// GetLocationsByCellResponse: [byte Success][int locationMapCount][...][int monsterCount][...]
    /// [int herbCount][...][int questNodeCount][...][int nestCount][...].
    /// Empty = Success + five zero counts (the Deserialize reads Success then 5 list/dict counts).
    /// <summary>GetLocationsByCell (40), Factory 0x2479934: [byte Success][int cellCount] then per cell
    /// [ulong cellId][int n][Location × n], then the Monster, Herb, QuestNodeInstance and Nest placement
    /// lists, each [int n][Placement × n] with Placement = [byte Type][string PlaceId][entity]; the client
    /// drops placements whose place is not in the response. Reconstructed profiles get the day's safe places
    /// of each requested cell and the monsters of the current window (WorldSpawns); others stay empty.</summary>
    private byte[] BuildGetLocationsByCellResponse(ApiProtocol.ApiRequest req, out Admin.MapObservation.Snapshot? observation)
    {
        observation = null;
        var snapshot = profiles.Snapshot();
        if (snapshot.Player is null || !playable.Enabled) return BuildGetLocationsByCellResponse();
        var ids = PlayableLocations.ReadCellIds(req.Data);
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var cells = ids.Length == 0 ? new List<PlayableLocations.Cell>()
            : playable.Cells(ids, WorldSpawns.PlacesEpoch(now))?.ToList();
        if (cells is null) return BuildGetLocationsByCellResponse();
        playable.ObserveCells(cells);
        var monsters = CurrentSpawns(snapshot, cells, now);
        var givers = StoryGivers(snapshot).Select(g => (g.Node, g.Place, Instance: g.Node.Instance))
            .Concat(RelocationGivers(snapshot, cells)).Where(g => cells.Any(c => c.Id == g.Place.CellId)).ToList();
        var b = new ByteBuffer();
        b.WriteByte(1);
        b.WriteInt(cells.Count);
        foreach (var cell in cells)
        {
            var extra = givers.Where(g => g.Place.CellId == cell.Id).Select(g => g.Place).DistinctBy(p => p.Id).ToList();
            b.WriteULong(cell.Id);
            b.WriteInt(cell.Places.Count + extra.Count);
            foreach (var place in cell.Places)
            {
                b.WriteString(place.Id); b.WriteFloat((float)place.Lat); b.WriteFloat((float)place.Lng);
                b.WriteInt(place.Biomes.Length);
                foreach (int biome in place.Biomes) b.WriteInt(biome);
            }
            foreach (var place in extra)
            {
                b.WriteString(place.Id); b.WriteFloat((float)place.Lat); b.WriteFloat((float)place.Lng);
                b.WriteInt(place.Biomes.Length);
                foreach (int biome in place.Biomes) b.WriteInt(biome);
            }
        }
        WriteMonsterPlacements(b, monsters);
        var herbs = CurrentHerbs(snapshot, cells);
        b.WriteInt(herbs.Count);  // HerbPlacements
        long now2 = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var respawns = snapshot.Player?.HerbRespawns ?? new Dictionary<long, long>();
        foreach (var herb in herbs)
        {
            b.WriteByte(0);
            b.WriteString(herb.PlaceId);
            b.WriteLong(herb.InstanceId);
            b.WriteInt(herb.Type);
            b.WriteInt((int)(respawns.GetValueOrDefault(herb.InstanceId) is var at && at > now2 ? at : 0));
        }
        // QuestNodeInstancePlacements: the season 1 quest givers (Placement<QuestNodeInstance>: [byte Type][string
        // PlaceId] then QuestNodeInstance.Deserialize 0x1934B40 [long InstanceId][int QuestNodeId][string PlaceId]
        // [string SettingsPath][string BehaviourGraphName][int DisplayMode]); the client marks them IsQuestGiver and
        // shows those whose quest it offers. Other story nodes come with RPC 60 and 57.
        b.WriteInt(givers.Count);
        foreach (var (node, place, instance) in givers)
        {
            b.WriteByte(0);
            b.WriteString(place.Id);
            b.WriteLong(instance);
            b.WriteInt(node.Id);
            b.WriteString(place.Id);
            b.WriteString(node.Poi);
            b.WriteString(node.Graph);
            b.WriteInt(Reconstruction.DisplayNormal);
        }
        var nests = CurrentNests(snapshot, cells, now);
        var today = TodaysNests(snapshot.Player, now);
        b.WriteInt(nests.Count);  // NestPlacements: [byte Type][string PlaceId][long InstanceId][int BossType][int NestState]
        foreach (var nest in nests)
        {
            b.WriteByte(0);
            b.WriteString(nest.PlaceId);
            b.WriteLong(nest.InstanceId);
            b.WriteInt(nest.Boss);
            b.WriteInt(today.Nests.TryGetValue(nest.InstanceId, out var progress) ? progress.State : WorldNests.Default);
        }
        log.LogInformation("  GetLocationsByCell cells={Cells} places={Places} monsters={Monsters} herbs={Herbs} nests={Nests} givers={Givers}",
            cells.Count, cells.Sum(c => c.Places.Count), monsters.Count, herbs.Count, nests.Count, givers.Count);
        RememberRelocationOffers(givers.Select(g => g.Instance));
        RememberAuraPlaces(cells, now);
        if (cfg.GetValue("Admin:Port", 0) > 0 && cells.Count > 0)
            observation = Admin.MapObservation.Create(cells, monsters, herbs, nests, givers.Select(g =>
                new Admin.MapObservation.Point(g.Instance.ToString(), "quest", (float)g.Place.Lat, (float)g.Place.Lng,
                    g.Place.Id, $"Quest {g.Node.Id}")));
        return b.ToArray();
    }

    /// <summary>The living world monsters of the given cells; remembered for encounters and the senses.</summary>
    private List<WorldSpawns.Spawn> CurrentSpawns(LocalProfileStore.Profile snapshot,
        IEnumerable<PlayableLocations.Cell> cells, long now)
    {
        // Ordinary world encounters are shared across player levels; kills remain personal.
        var killed = snapshot.Player?.KilledInstances ?? new Dictionary<long, long>();
        int monsterSlots = world.Read().MonsterSlotsPerCell;
        var balance = world.Balance.Read();
        var spawns = cells.SelectMany(cell => WorldSpawns.ForCell(cell, now,
                generation => weather.ForGeneration(cell.Id, cell.Lat, cell.Lng, generation), monsterSlots,
                world.SpawnBalanceFromUnixSeconds, balance.At))
            .Where(spawn => !killed.ContainsKey(spawn.InstanceId)).ToList();
        lock (worldGate)
        {
            foreach (var old in worldSpawns.Where(pair => pair.Value.SpawnTimeMs / 1000 + pair.Value.Ttl <
                                                          DateTimeOffset.UtcNow.ToUnixTimeSeconds()).Select(p => p.Key).ToList())
                worldSpawns.Remove(old);
            foreach (var spawn in spawns) worldSpawns[spawn.InstanceId] = spawn;
        }
        return spawns;
    }

    // Herbs served to this session, by instance id, for GatherHerb.
    private readonly Dictionary<long, WorldHerbs.Herb> worldHerbs = new();

    private List<WorldHerbs.Herb> CurrentHerbs(LocalProfileStore.Profile snapshot, IEnumerable<PlayableLocations.Cell> cells)
    {
        var herbs = cells.SelectMany(cell => WorldHerbs.ForCell(cell)).ToList();
        lock (worldGate) foreach (var herb in herbs) worldHerbs[herb.InstanceId] = herb;
        return herbs;
    }

    /// <summary>GatherHerb (19): request [ulong InstanceId] (GatherHerbRequest.Serialize 0x1936184); response
    /// (Factory 0x24837C4) [byte Success][int n][int ingredient id × n][int RespawnTime][long HerbInstanceId].
    /// PoiModule.HandleGatherHerbResponse (0x1903BD8) adds the loot and hides the herb until RespawnTime (Unix
    /// seconds). A served herb that has grown back is gathered: its loot goes to the inventory and it grows back
    /// after WorldHerbs.Respawn; anything else is refused with no loot.</summary>
    private byte[] HandleGatherHerb(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 8) throw new InvalidDataException("Invalid GatherHerb payload.");
        long id = new ByteBuffer(req.Data).ReadLong();
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        bool known;
        lock (worldGate) known = worldHerbs.ContainsKey(id);
        var loot = new List<int>();
        long respawn = 0;
        if (known && profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var respawns = (player.HerbRespawns ?? new Dictionary<long, long>()).Where(r => r.Value > now)
                    .ToDictionary(r => r.Key, r => r.Value);
                if (respawns.ContainsKey(id)) return null;
                long period = WorldHerbs.Respawn;
                var gathered = Fit(player, WorldHerbs.Loot(id, (now + period) / period));
                if (gathered.Count == 0) return null;   // a full bag leaves the herb for later, as the client does
                respawn = now + period;
                respawns[id] = respawn;
                loot = gathered;
                AddItems(player, loot.GroupBy(i => i).Select(g => (ItemKinds.Ingredients, g.Key, g.Count())));
                return player with { HerbRespawns = respawns };
            }, new TaskEngine.Action(19));
        log.LogInformation("  GatherHerb known={Known} result={Result} loot={Loot}", known, loot.Count > 0 ? "gathered" : "refused", loot.Count);
        var b = new ByteBuffer();
        b.WriteByte(loot.Count > 0 ? (byte)1 : (byte)0);
        b.WriteInt(loot.Count);
        foreach (int item in loot) b.WriteInt(item);
        b.WriteInt((int)respawn);
        b.WriteLong(id);
        return b.ToArray();
    }

    // Nemeta served to this session, by instance id, and the one whose window is open (EncounterNest).
    private readonly Dictionary<long, WorldNests.Nest> worldNests = new();
    private long? nestEncountered;

    private List<WorldNests.Nest> CurrentNests(LocalProfileStore.Profile snapshot, IEnumerable<PlayableLocations.Cell> cells,
        long now)
    {
        long epoch = WorldSpawns.PlacesEpoch(now);
        var nests = cells.Select(cell => WorldNests.ForCell(cell, epoch)).OfType<WorldNests.Nest>().ToList();
        lock (worldGate) foreach (var nest in nests) worldNests[nest.InstanceId] = nest;
        return nests;
    }

    /// <summary>The profile's nemeta of the current UTC day (an older day counts as a fresh one).</summary>
    private static LocalProfileStore.NestDay TodaysNests(LocalProfileStore.PlayerState? player, long now)
    {
        long day = WorldNests.Day(now);
        return player?.Nests is { } nests && nests.Day == day ? nests
            : new LocalProfileStore.NestDay(day, 0, new Dictionary<long, LocalProfileStore.NestProgress>());
    }

    /// <summary>NestStateResponse (EncounterNest and UseLure, Deserialize 0x247B184): [byte Result]; on success
    /// [long NestInstanceId][int WonNestCombats][int DailyNestLimit][int n][int monster × n][byte State][int Gold]
    /// [int Exp][int Iteration]. NestWindow shows the monsters (SetupMonstersPanel with Gold, Exp and the won
    /// combats); Iteration is not read by the 1.1.116 paths seen and carries the nest's clears today.</summary>
    private static byte[] NestStateResponse(WorldNests.Nest? nest, LocalProfileStore.NestDay today, int state)
    {
        var b = new ByteBuffer();
        if (nest is null) { b.WriteByte(0); return b.ToArray(); }
        var progress = today.Nests.GetValueOrDefault(nest.InstanceId);
        var monsters = progress?.Monsters ?? nest.Monsters;
        b.WriteByte(1);
        b.WriteLong(nest.InstanceId);
        b.WriteInt(today.Wins);
        b.WriteInt(WorldNests.DailyLimit);
        b.WriteInt(monsters.Length);
        foreach (int monster in monsters) b.WriteInt(monster);
        b.WriteByte((byte)state);
        b.WriteInt(WorldNests.Bounty);
        b.WriteInt(WorldNests.ClearingExp);
        b.WriteInt(progress?.Clears ?? 0);
        return b.ToArray();
    }

    /// <summary>EncounterNest (52), sent on a tap on the nest (NestOnMapController.OnClicked 0x18FA9E4): LongRequest
    /// [long nestId]; NestStateResponse. A served nest answers with today's state, NotAllowed below the minimal
    /// level; anything else is refused.</summary>
    private byte[] HandleEncounterNest(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 8) throw new InvalidDataException("Invalid EncounterNest payload.");
        long id = new ByteBuffer(req.Data).ReadLong();
        var player = profiles.Snapshot().Player;
        WorldNests.Nest? nest = null;
        lock (worldGate)
        {
            if (player is not null && worldNests.TryGetValue(id, out var found)) nest = found;
            nestEncountered = nest?.InstanceId;
        }
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var today = TodaysNests(player, now);
        int state = nest is null ? 0
            : Reconstruction.LevelForExp(player!.Exp) < WorldNests.PlayerMinimalLevel ? WorldNests.NotAllowed
            : today.Nests.TryGetValue(id, out var progress) ? progress.State : WorldNests.Default;
        log.LogInformation("  EncounterNest known={Known} state={State} wins={Wins}", nest is not null, state, today.Wins);
        return NestStateResponse(nest, today, state);
    }

    /// <summary>UseLure (18), from the bait panel of a cleared nest (NestWindow.OnAppliedLureToNest): request [long
    /// InstanceId][int LureId] (Serialize 0x24783F0); NestStateResponse (Factory 0x1E77D64). On success the client
    /// removes the bait itself (NestWindow.OnUseLureResponse, IPlayerInventory slot 47 with item type 5) and shows
    /// the lured monsters. A nest cleared of its own monsters today takes one owned bait whose class has monsters;
    /// the nest becomes Lured with that class's monsters.</summary>
    private byte[] HandleUseLure(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 12) throw new InvalidDataException("Invalid UseLure payload.");
        var r = new ByteBuffer(req.Data);
        long id = r.ReadLong();
        int lureId = r.ReadInt();
        WorldNests.Nest? nest;
        lock (worldGate) worldNests.TryGetValue(id, out nest);
        var lure = WorldNests.LureById(lureId);
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        LocalProfileStore.NestDay? after = null;
        if (nest is not null && lure is not null && profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var today = TodaysNests(player, now);
                var progress = today.Nests.GetValueOrDefault(id);
                if (Reconstruction.LevelForExp(player.Exp) < WorldNests.PlayerMinimalLevel || progress?.State != WorldNests.DefaultClear ||
                    !player.Items.TryGetValue(ItemKinds.Lures, out var lures) || lures.GetValueOrDefault(lureId) < 1)
                    return null;
                var lured = WorldNests.LuredClass(lure, nest.Family, WorldSpawns.StableHash($"{id}:{today.Day}:{progress.Clears}:lure"));
                if (lured is null) return null;
                if (--lures[lureId] == 0) lures.Remove(lureId);
                var monsters = WorldNests.Monsters(lured, WorldSpawns.StableHash($"{id}:{today.Day}:{progress.Clears}:{lureId}"));
                var nests = new Dictionary<long, LocalProfileStore.NestProgress>(today.Nests)
                {
                    [id] = progress with { State = WorldNests.Lured, Monsters = monsters },
                };
                after = today with { Nests = nests };
                return player with { Nests = after };
            });
        lock (worldGate) if (after is not null) nestEncountered = id;
        log.LogInformation("  UseLure lure={Lure} result={Result}", lureId, after is null ? "refused" : "lured");
        return after is null ? new byte[] { 0 } : NestStateResponse(nest, after, WorldNests.Lured);
    }

    /// <summary>EndNestCombat (53), after the third fight (GetNestRewardsNode.EnterNode 0x17EFF28), after a lost one
    /// (EndLostNestFightNode 0x17EBD34) or on surrender: request [byte Win][ulong InstanceId][uint BombId] and
    /// three [uint n][uint × n] CombatDetails lists (Serialize 0x1935F4C); response (Factory 0x2482AC4) [byte
    /// Success]; on success [int n][int loot × n][int Reward][int EntireRarityMonsterExp]
    /// [int EntireFirstTimeSlayedMonstersExp][int PerfectAttacksExp][int ProperOilUsageExp][int DurationExp]
    /// [int PerfectParriesExp][int NestClearingExp][int BoostedExp]. GetNestRewardsNode adds Reward as gold, the
    /// sum of the eight experience fields as experience (SummaryRewardInfo 0x17CDE14) and the loot. Bombs thrown
    /// (CombatDetails.BombsUsed) are spent on a win or a loss. A win over the encountered nest clears it, counts the
    /// kills, and pays the bounty for the first three clears of the day.</summary>
    private byte[] HandleEndNestCombat(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        bool win = r.ReadByte() != 0;
        long id = (long)r.ReadULong();
        int bombId = checked((int)r.ReadUInt());
        var details = new int[3][];
        for (int fight = 0; fight < 3; fight++)
        {
            uint count = r.ReadUInt();
            if (count > 64 || r.RemainingToRead < count * 4) throw new InvalidDataException("Invalid nest combat payload.");
            details[fight] = new int[count];
            for (int i = 0; i < count; i++) details[fight][i] = checked((int)r.ReadUInt());
        }
        if (r.RemainingToRead != 0) throw new InvalidDataException("Invalid nest combat payload.");
        int Sum(int index) => details.Sum(d => index < d.Length ? d[index] : 0);
        int Count(int index) => details.Count(d => index < d.Length && d[index] > 0);

        WorldNests.Nest? nest = null;
        lock (worldGate)
        {
            if (nestEncountered == id && worldNests.TryGetValue(id, out var found)) nest = found;
            nestEncountered = null;
        }
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        bool success = false;
        int gold = 0, rarityExp = 0, firstExp = 0, attackExp = 0, oilExp = 0, parryExp = 0, clearingExp = 0, boostedExp = 0;
        var loot = new List<int>();
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                int bombs = Sum(Reconstruction.DetailBombsUsed);
                var owned = player.Items.GetValueOrDefault(ItemKinds.Bombs);
                bool spent = bombs > 0 && owned is not null && owned.GetValueOrDefault(bombId) > 0;
                if (spent && (owned![bombId] = Math.Max(0, owned[bombId] - bombs)) == 0) owned.Remove(bombId);
                var today = TodaysNests(player, now);
                var progress = nest is null ? null : today.Nests.GetValueOrDefault(nest.InstanceId);
                int state = progress?.State ?? WorldNests.Default;
                success = nest is not null && Reconstruction.LevelForExp(player.Exp) >= WorldNests.PlayerMinimalLevel &&
                          state is WorldNests.Default or WorldNests.Lured;
                if (!success || !win) return spent || success && TasksEnabled ? player : null;
                var monsters = progress?.Monsters ?? nest!.Monsters;
                var kills = player.Kills!;
                foreach (int monster in monsters)
                {
                    var species = WorldNests.SpeciesOf(monster);
                    rarityExp += Exp(WorldNests.RarityExp(species?.Rarity ?? 1));
                    if (kills.GetValueOrDefault(monster) == 0) firstExp += Exp(Reconstruction.FirstKillExp);
                    kills[monster] = kills.GetValueOrDefault(monster) + 1;
                    loot.AddRange(Economy.FightLoot(monster, species?.Difficulty ?? 1));
                }
                loot = Fit(player, Looted(loot));
                attackExp = Exp(Reconstruction.CriticalHitExp * Sum(Reconstruction.DetailPerfectAttacks));
                parryExp = Exp(Reconstruction.PerfectParryExp * Sum(Reconstruction.DetailPerfectParries));
                oilExp = Exp(Reconstruction.ProperOilExp * Count(Reconstruction.DetailUsedProperOil));
                clearingExp = Exp(WorldNests.ClearingExp);
                boostedExp = rarityExp * Reconstruction.ExperienceBonus(Worn(player)) / 100;   // equipment (effect 65)
                gold = today.Wins < WorldNests.DailyLimit ? WorldNests.Bounty : 0;
                AddItems(player, loot.Select(item => (ItemKinds.Ingredients, item, 1)));
                var nests = new Dictionary<long, LocalProfileStore.NestProgress>(today.Nests)
                {
                    [nest!.InstanceId] = new(state == WorldNests.Default ? WorldNests.DefaultClear : WorldNests.LuredClear,
                        (progress?.Clears ?? 0) + 1, progress?.Monsters),
                };
                return Reconstruction.WithExp(player with { Nests = today with { Wins = today.Wins + 1, Nests = nests } },
                    rarityExp + firstExp + attackExp + oilExp + parryExp + clearingExp + boostedExp, gold);
            }, taskActionFactory: () => success ? new TaskEngine.Action(53, details) : null);
        log.LogInformation("  EndNestCombat win={Win} known={Known} result={Result} gold={Gold} exp={Exp}", win, nest is not null,
            success ? (win ? "cleared" : "lost") : "refused", gold, rarityExp + firstExp + attackExp + oilExp + parryExp + clearingExp + boostedExp);
        var b = new ByteBuffer();
        b.WriteByte(success ? (byte)1 : (byte)0);
        if (!success) return b.ToArray();
        b.WriteInt(loot.Count);
        foreach (int item in loot) b.WriteInt(item);
        b.WriteInt(gold);          // Reward
        b.WriteInt(rarityExp);     // EntireRarityMonsterExp
        b.WriteInt(firstExp);      // EntireFirstTimeSlayedMonstersExp
        b.WriteInt(attackExp);     // PerfectAttacksExp
        b.WriteInt(oilExp);        // ProperOilUsageExp: 50 per fight with the proper oil (Details[10])
        b.WriteInt(0);             // DurationExp
        b.WriteInt(parryExp);      // PerfectParriesExp
        b.WriteInt(clearingExp);   // NestClearingExp
        b.WriteInt(boostedExp);    // BoostedExp: the worn equipment's experience bonus
        return b.ToArray();
    }

    /// <summary>Placement&lt;Monster&gt; list: [int n] then [byte Type 0][string PlaceId][long SpawnTime ms]
    /// [int Ttl s][int Type = monster id][int Level = difficulty id][long InstanceId] (Monster 0x19347A8).</summary>
    private static void WriteMonsterPlacements(ByteBuffer b, IReadOnlyCollection<WorldSpawns.Spawn> monsters)
    {
        b.WriteInt(monsters.Count);
        foreach (var monster in monsters)
        {
            b.WriteByte(0);
            b.WriteString(monster.PlaceId);
            b.WriteLong(monster.SpawnTimeMs);
            b.WriteInt(monster.Ttl);
            b.WriteInt(monster.MonsterId);
            b.WriteInt(monster.Difficulty);
            b.WriteLong(monster.InstanceId);
        }
    }

    /// <summary>GetMonsterInstances (87): request [int n][string PlaceId × n] (Serialize 0x2476818), sent when
    /// monsters on those places expire; response (Factory 0x247A390) [byte ErrorCode, 0 = success]
    /// [int n][Placement&lt;Monster&gt; × n]. Answers the current window's monsters of the cells of those
    /// places, on places of the same day's set the client already knows.</summary>
    private byte[] BuildGetMonsterInstancesResponse(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int count = r.ReadInt();
        if (count < 0 || count > 256) throw new InvalidDataException("Invalid place id list.");
        var placeIds = new List<string>();
        for (int i = 0; i < count; i++) placeIds.Add(r.ReadString());
        var snapshot = profiles.Snapshot();
        var monsters = new List<WorldSpawns.Spawn>();
        var byEpoch = placeIds.Select(id => (Cell: WorldSpawns.CellOf(id), Epoch: WorldSpawns.EpochOf(id)))
            .Where(x => x.Cell is not null && x.Epoch is not null).Distinct().GroupBy(x => x.Epoch!.Value);
        if (snapshot.Player is not null && playable.Enabled)
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            foreach (var group in byEpoch)
                if (playable.Cells(group.Select(x => x.Cell!.Value).ToList(), group.Key) is { } cells)
                    monsters.AddRange(CurrentSpawns(snapshot, cells, now));
        }
        log.LogInformation("  GetMonsterInstances places={Places} monsters={Monsters}", count, monsters.Count);
        var b = new ByteBuffer();
        b.WriteByte(0);
        WriteMonsterPlacements(b, monsters);
        return b.ToArray();
    }

    /// <summary>EncounterMonster (41): LongRequest [long InstanceId]; BooleanResponse. True for a living
    /// monster of the current windows, which becomes the one being fought.</summary>
    private byte[] HandleEncounterMonster(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 8) throw new InvalidDataException("Invalid EncounterMonster payload.");
        long id = new ByteBuffer(req.Data).ReadLong();
        var killed = profiles.Snapshot().Player?.KilledInstances;
        bool alive;
        lock (worldGate)
        {
            alive = worldSpawns.TryGetValue(id, out var spawn) && killed?.ContainsKey(id) != true &&
                    spawn.SpawnTimeMs / 1000 + spawn.Ttl > DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            worldEncountered = alive ? id : null;
        }
        log.LogInformation("  EncounterMonster alive={Alive}", alive);
        return ApiProtocol.Boolean(alive);
    }

    /// <summary>CombatEnd (8): the fight with the encountered world monster. A win records the instance as
    /// defeated until its window ends, so GetKilledMonsterInstances (56) and new cell answers leave it out.</summary>
    private byte[] HandleCombatEnd(ApiProtocol.ApiRequest req)
    {
        var end = ReadCombatEnd(req);
        WorldSpawns.Spawn? spawn = null;
        lock (worldGate)
        {
            if (worldEncountered is long id && worldSpawns.TryGetValue(id, out var found)) spawn = found;
            worldEncountered = null;
        }
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        return CombatEndPayload("CombatEnd", end, spawn is null ? null : (spawn.MonsterId, spawn.Difficulty), player =>
        {
            var killed = player.KilledInstances!;
            foreach (long expired in killed.Where(k => k.Value <= now).Select(k => k.Key).ToList()) killed.Remove(expired);
            killed[spawn!.InstanceId] = spawn.SpawnTimeMs / 1000 + spawn.Ttl;
        });
    }

    private static byte[] BuildGetLocationsByCellResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success
        b.WriteInt(0);  // LocationMap (dict count)
        b.WriteInt(0);  // MonsterPlacements (list count)
        b.WriteInt(0);  // HerbPlacements (list count)
        b.WriteInt(0);  // QuestNodeInstancePlacements (list count)
        b.WriteInt(0);  // NestPlacements (list count)
        return b.ToArray();
    }

    /// GetExpiringEffectsResponse: [int count][items...]. Empty = [int 0].
    private static byte[] BuildGetExpiringEffectsResponse()
    {
        var b = new ByteBuffer();
        b.WriteInt(0);  // ExpiringEffects list count
        return b.ToArray();
    }

    /// GetFriendsResponse: [long CurrentPlayerId][int friendsCount][...][int stateChangesCount][...].
    private byte[] BuildGetFriendsResponse()
    {
        if (social is not null && profiles.Snapshot().Player is not null) return social.Friends(profiles.ProfileId);
        var b = new ByteBuffer();
        b.WriteLong(1L);  // CurrentPlayerId
        b.WriteInt(0);    // Friends list count
        b.WriteInt(0);    // PlayerStateChanges list count
        return b.ToArray();
    }

    /// GetFriendsNotificationsResponse: [byte Result][int receivedInvitesN][...][int sentAcceptedN][...]
    /// [int receivedPacksN][...][int stateChangesN][...].
    private byte[] BuildGetFriendsNotificationsResponse()
    {
        if (social is not null && profiles.Snapshot().Player is not null) return social.Notifications(profiles.ProfileId);
        var b = new ByteBuffer();
        b.WriteByte(1); // Result = true
        b.WriteInt(0);  // ReceivedInvites list count
        b.WriteInt(0);  // SentInvitesAccepted list count
        b.WriteInt(0);  // ReceivedPacks list count
        b.WriteInt(0);  // PlayerStateChanges list count
        return b.ToArray();
    }

    /// GetDailyContractsResponse: [byte Success][int ignored][int CanAdd][int CanReshuffle][int count].
    private static byte[] BuildGetDailyContractsResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success
        b.WriteInt(0);  // ignored
        b.WriteInt(0);  // CanAdd = false
        b.WriteInt(0);  // CanReshuffle = false
        b.WriteInt(0);  // count
        return b.ToArray();
    }

    /// 1.1.116 Factory.Deserialize (own ELF RVA 0x1e794a4):
    /// [byte Success][int LastStampAcquiredDate][int RewardId][int stampsCount][int×count].
    /// See connection/weekly-progress-review/. Zero values remain demonstration data.
    private static byte[] BuildGetWeeklyContractProgressResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success
        b.WriteInt(0);  // LastStampAcquiredDate
        b.WriteInt(0);  // RewardId — required field; historical reward data not reconstructed
        b.WriteInt(0);  // Stamps list count
        return b.ToArray();
    }

    /// 1.1.116 Factory.Deserialize RVA0x1e7a09c returns immediately after a non-success byte.
    /// Callback122 accepts the non-null failed response and completes module initialization.
    /// Explicitly unavailable seasonal events, not fabricated success or recovered no-event semantics.
    /// See connection/monster-event-review/. Do not append success-path fields or padding.
    private static byte[] BuildMonsterEventUnavailableResponse() => new byte[] { 0 };

    /// GetSensedMonstersResponse (Method 43): [byte Success][int count][long×count]. WitcherSensesModule
    /// .OnGetSensedMonsters puts the senses plates back on these monsters after a restart; reconstructed
    /// profiles list the revealed monsters that are still on the map, legacy profiles none.
    private byte[] BuildGetSensedMonstersResponse()
    {
        var b = new ByteBuffer();
        WriteSensedMonsters(b, profiles.Snapshot());
        return b.ToArray();
    }

    private static void WriteSensedMonsters(ByteBuffer b, LocalProfileStore.Profile snapshot)
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var sensed = (snapshot.Player?.Sensed ?? new Dictionary<long, long>()).Where(s => s.Value > now)
            .Select(s => s.Key).OrderBy(id => id).ToList();
        b.WriteByte(1); // Success
        b.WriteInt(sensed.Count);
        foreach (long id in sensed) b.WriteLong(id);
    }

    /// GetCurrentObjectiveResponse (Method 61): [byte Success][string CurrentObjective].
    /// Ctor: (bool success, string currentObjective). Empty objective = success + empty string.
    private byte[] BuildGetCurrentObjectiveResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1);         // Success
        b.WriteString(profiles.Snapshot().Player?.CurrentObjective ?? "");
        return b.ToArray();
    }

    /// <summary>SetCurrentObjective (62), sent by the SetQuestObjective graph action: request [string]
    /// (SetCurrentObjectiveRequest.Serialize 0x2477BFC); response [byte Success][string CurrentObjective]
    /// (Factory 0x1E78A50). Reconstructed profiles keep it for GetCurrentObjective (61).</summary>
    private byte[] HandleSetCurrentObjective(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        string objective = r.ReadString();
        bool ok = r.RemainingToRead == 0 && objective.Length <= 256 && !objective.Any(char.IsControl);
        if (ok && profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player => player with { CurrentObjective = objective });
        log.LogInformation("  SetCurrentObjective result={Result} length={Length}", ok, objective.Length);
        var b = new ByteBuffer();
        b.WriteByte(ok ? (byte)1 : (byte)0);
        b.WriteString(ok ? objective : "");
        return b.ToArray();
    }

    /// <summary>Drop* (47-51, 71, 100, 109, 118) from the item window's remove button: IntIntRequest
    /// [int itemId][int amount]; IntIntResponse [byte Result][int itemId][int amount], on which the client calls
    /// PlayerStorage.Remove(itemId, amount) (OnDropItemsResponse 0x1876F78). A reconstructed profile drops owned
    /// items of the kinds it keeps; anything else is refused and nothing changes.</summary>
    private byte[] HandleDropItems(ApiProtocol.ApiRequest req, string? kind)
    {
        var r = new ByteBuffer(req.Data);
        int id = r.ReadInt(), amount = r.ReadInt();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Unsupported drop payload shape.");
        bool dropped = false;
        if (kind is not null && amount > 0 && profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                if (!player.Items.TryGetValue(kind, out var owned) || owned.GetValueOrDefault(id) < amount) return null;
                owned[id] -= amount;
                if (owned[id] == 0) owned.Remove(id);
                dropped = true;
                return player;
            });
        log.LogInformation("  Drop method={Method} result={Result} amount={Amount}", req.Method, dropped, amount);
        var b = new ByteBuffer();
        b.WriteByte(dropped ? (byte)1 : (byte)0);
        b.WriteInt(id);
        b.WriteInt(dropped ? amount : 0);
        return b.ToArray();
    }

    /// GetDailyShopBundlesResponse (79): [byte Success][int count][int bundleId...]; reconstructed profiles get
    /// the day's deals (Economy.DailyDeals).
    private byte[] BuildGetDailyShopBundlesResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success = true
        var deals = profiles.Snapshot().Player is null ? new List<int>() : Economy.DailyDeals(DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        b.WriteInt(deals.Count);
        foreach (int id in deals) b.WriteInt(id);
        return b.ToArray();
    }

    /// GetOneTimeShopBundlesResponse (83): [byte Success][int count][int bundleId...], the one-time bundles
    /// already bought.
    private byte[] BuildGetOneTimeShopBundlesResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success = true
        var bought = profiles.Snapshot().Player?.OneTimeBundles ?? new List<int>();
        b.WriteInt(bought.Count);
        foreach (int id in bought) b.WriteInt(id);
        return b.ToArray();
    }

    /// GetPlayerModifiersResponse: [int Result/Success][int count][items...].
    /// <summary>GetPlayerModifiersResponse (91): [int Result, 0 = success][int n][ExpiringPlayerModifier × n] with
    /// ExpiringPlayerModifier.Deserialize (0x1933F8C) reading [int Id][int StartTimestamp][int ExpireTimestamp].
    /// Reconstructed profiles list their modifiers that have not expired.</summary>
    private byte[] BuildGetPlayerModifiersResponse()
    {
        var b = new ByteBuffer();
        WritePlayerModifiers(b, profiles.Snapshot());
        return b.ToArray();
    }

    private static List<LocalProfileStore.ModifierState> LiveModifiers(LocalProfileStore.PlayerState? player, long now) =>
        (player?.Modifiers ?? new List<LocalProfileStore.ModifierState>()).Where(m => m.Expire < 1 || m.Expire > now).ToList();

    private void WritePlayerModifiers(ByteBuffer b, LocalProfileStore.Profile snapshot)
    {
        var live = LiveModifiers(snapshot.Player, DateTimeOffset.UtcNow.ToUnixTimeSeconds())
            .Where(m => m.Id != 13 || tasks.Catalog is not null).ToList();
        b.WriteInt(0);
        b.WriteInt(live.Count);
        foreach (var m in live) { b.WriteInt(m.Id); b.WriteInt(m.Start); b.WriteInt(m.Expire); }
    }

    /// <summary>Friend actions from FriendsModule (103 AddFriend, 104 AcceptFriendInvitation, 105
    /// RejectFriendInvitation, 106 SendPack, 107 OpenPack, 108 DeleteFriend). Requests: LongRequest [long playerId],
    /// 106 IntLongRequest [int packType][long playerId]. Responses (Factory.Deserialize): 103/104/105/108
    /// BooleanLongResponse [byte Result][long friendId] (0x247C020, 0x247B370, 0x1E79D44, 0x247F3AC), 106
    /// IntLongResponse [byte Result][int packType][long friendId] (0x1E79DFC), 107 LongIntIntIntResponse
    /// [byte Result][long][int][int][int] (0x1E79ED0). Reconstructed profiles use durable social state;
    /// legacy fixtures retain the original typed refusals.</summary>
    private byte[] HandleFriendAction(ApiProtocol.ApiRequest req)
    {
        if (social is not null && profiles.Snapshot().Player is not null) return social.Action(profiles.ProfileId, req);
        var r = new ByteBuffer(req.Data);
        int packType = req.Method == 106 ? r.ReadInt() : 0;
        long playerId = r.ReadLong();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Invalid friend action payload.");
        log.LogInformation("  Friend action method={Method} refused (single-player server)", req.Method);
        var b = new ByteBuffer();
        b.WriteByte(0);
        if (req.Method == 106) b.WriteInt(packType);
        b.WriteLong(playerId);
        if (req.Method == 107) { b.WriteInt(0); b.WriteInt(0); b.WriteInt(0); }
        return b.ToArray();
    }

    /// <summary>AddPlayerModifier (90), sent by the AddExpiringEffect graph action (TriggerAction 0x17E1C3C):
    /// IntIntRequest [int modifierId][int seconds, -1 = until removed]. Response (Factory 0x247C338, matching the
    /// client's own Serialize 0x247C244): [int 4][int Result, 0 = success][int Id][int StartTimestamp]
    /// [int ExpireTimestamp]; the factory returns null unless the first int is at least 4.
    /// PlayerModifiersModule.Tick and GetActiveEffects treat an expiry below 1 as permanent. Reconstructed
    /// profiles keep a known modifier (Reconstruction.PlayerModifiers), replacing one with the same id;
    /// anything else is refused with Result 1.</summary>
    private byte[] HandleAddPlayerModifier(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int id = r.ReadInt(), seconds = r.ReadInt();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Invalid AddPlayerModifier payload.");
        // LAB pacing: the long season 1 timers are shortened to the story's own wait (StoryEngine.Modifier.Seconds).
        if (seconds > 0 && StoryEngine.Modifiers.FirstOrDefault(m => m.Id == id)?.Seconds is int shortened) seconds = shortened;
        int now = (int)DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var added = new LocalProfileStore.ModifierState(id, now, seconds > 0 ? now + seconds : 0);
        bool ok = false;
        if (Reconstruction.PlayerModifiers.Any(m => m.Id == id) && profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var kept = LiveModifiers(player, now).Where(m => m.Id != id).ToList();
                kept.Add(added);
                ok = true;
                return player with { Modifiers = kept };
            });
        log.LogInformation("  AddPlayerModifier result={Result} permanent={Permanent}", ok ? "added" : "refused", seconds <= 0);
        var b = new ByteBuffer();
        b.WriteInt(4);
        b.WriteInt(ok ? 0 : 1);
        b.WriteInt(id);
        b.WriteInt(ok ? added.Start : 0);
        b.WriteInt(ok ? added.Expire : 0);
        return b.ToArray();
    }

    /// <summary>RemovePlayerModifier (92), sent by the RemoveExpiringEffect graph action: IntRequest
    /// [int modifierId]; response (Factory 0x1E793F8) [int Result, 0 = success][int ModifierId]. Removing a
    /// modifier that is not held (it may have expired) succeeds; legacy profiles are refused.</summary>
    private byte[] HandleRemovePlayerModifier(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 4) throw new InvalidDataException("Invalid RemovePlayerModifier payload.");
        int id = new ByteBuffer(req.Data).ReadInt();
        bool ok = profiles.Snapshot().Player is not null;
        if (ok)
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
                player with { Modifiers = LiveModifiers(player, now).Where(m => m.Id != id).ToList() });
        }
        log.LogInformation("  RemovePlayerModifier result={Result}", ok ? "removed" : "refused");
        var b = new ByteBuffer();
        b.WriteInt(ok ? 0 : 1);
        b.WriteInt(id);
        return b.ToArray();
    }

    // ── Post-boot ACTION response builders ──────────────────────────────────────
    // These methods used to fall through to the 1-byte BooleanResponse catch-all, which UNDER-RUNS
    // every IntResponse reader (client expects [byte][int] = 5 bytes, got 1). Request payloads are
    // parsed from req.Data (the TypeMessage method payload — ApiProtocol.Parse already stripped Id+Method).

    /// IntResponse: [byte Result][int Param]. Reply shape for DistanceTraveled(27), EquipArmor(11),
    /// EquipSteelSword(12), EquipSilverSword(13), SetCustomizationHead(28), SetTutorialFinished(30),
    /// EquipSword(55) and AddSkillPoints(93).
    private static byte[] BuildIntResponse(bool result, int param)
    {
        var b = new ByteBuffer();
        b.WriteByte((byte)(result ? 1 : 0));
        b.WriteInt(param);
        return b.ToArray();
    }

    /// Reads the [int Param] request payload shared by every IntRequest subclass (dump.cs 601068,
    /// TypeDefIndex 11706: single int field, so Serialize can only be the 4-byte BE int) — covers
    /// EquipArmorRequest (601935), EquipSwordRequest (601947), SetCustomizationHeadRequest (602559),
    /// AddSkillPointsRequest (601371), DistanceTraveledRequest (601702) — and AcquireSkillRequest
    /// (601302, [int Skill]: same shape). NOTE: methods 12/13 (EquipSteel/SilverSword) have NO request
    /// class in the client dump, so their payload shape is unverified — hence the fallback instead of
    /// letting a short read throw.
    private int ReadIntParam(ApiProtocol.ApiRequest req, int fallback)
    {
        if (req.Data.Length < 4)
        {
            log.LogWarning("  Method {Method}: expected [int] request payload, got {Len}B — replying fallback id {Fallback}",
                req.Method, req.Data.Length, fallback);
            return fallback;
        }
        return new ByteBuffer(req.Data).ReadInt();
    }

    /// AcquireSkillResponse (Method 64): [byte Success][int Skill] — echoes the acquired skill id
    /// from AcquireSkillRequest ([int Skill], dump.cs 601302).
    private byte[] BuildAcquireSkillResponse(ApiProtocol.ApiRequest req)
    {
        int skill = ReadIntParam(req, fallback: 1);
        var b = new ByteBuffer();
        b.WriteByte(1);     // Success
        b.WriteInt(skill);  // Skill
        return b.ToArray();
    }

    /// GetPlayerInfoResponse (Method 3): [byte Success][string Name][int Gold][int Exp][int Head]
    /// [byte TutorialFinished][byte Gender]. Shared by the 115 batch and the standalone re-sync.
    /// TutorialFinished: default 0 -> tutorial ENABLED (the goal). Set Player:TutorialFinished=true to
    /// force-skip it — used to STAGE the phone bring-up without recompiling.
    private byte[] BuildGetPlayerInfoPayload()
    {
        var snapshot = profiles.Snapshot();
        var player = snapshot.Player;
        var b = new ByteBuffer();
        b.WriteByte(1);                    // Success
        // Name: the player's own, chosen at character creation (SetName 29) and kept in their profile. Before that,
        // "Unnamed", the client's own mark of a player without a name (NameCustomizationController.OnShow 0x1848894
        // offers a random name for it).
        b.WriteString(player?.Name ?? UnnamedPlayer);
        b.WriteInt(player?.Gold ?? 5000);  // Gold (legacy: ID contract)
        b.WriteInt(player?.Exp ?? 4500);   // Exp (legacy: demonstration value)
        b.WriteInt(1);                     // Head (id 1 = head_caucasian_1 in static data)
        // Reconstructed profiles report the tutorial as finished once its fact 3 is set (tut_gravehag/tut_exit).
        bool tutorialFinished = player is null
            ? cfg.GetValue("Player:TutorialFinished", false)
            : snapshot.Facts.GetValueOrDefault(3) != 0;
        b.WriteByte((byte)(tutorialFinished ? 1 : 0));
        b.WriteByte(player?.Gender ?? 0);  // Gender
        return b.ToArray();
    }

    /// <summary>SetName (29): SetNameRequest [string Name]; IntResponse [byte Result][int Param].
    /// Reconstructed profiles store a bounded name (character creation in tut_gravehag).</summary>
    private byte[] HandleSetName(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        string name = r.ReadString();
        if (r.RemainingToRead != 0 || name.Length is < 1 or > 32 || name.Any(char.IsControl))
            return BuildIntResponse(false, 0);
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player => player with { Name = name });
        log.LogInformation("  SetName accepted length={Length}", name.Length);
        return BuildIntResponse(true, 0);
    }

    /// <summary>SetGender (46): ByteRequest [byte]; IntResponse echoing the gender.</summary>
    private byte[] HandleSetGender(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 1 || req.Data[0] > 1) return BuildIntResponse(false, 0);
        byte gender = req.Data[0];
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player => player with { Gender = gender });
        return BuildIntResponse(true, gender);
    }

    /// <summary>ThrowBomb (39): IntRequest [int bombId]; IntResponse [byte Result][int remaining].
    /// Reconstructed profiles consume an owned bomb; graph-supplied tutorial bombs are not owned and
    /// are acknowledged without a change.</summary>
    private byte[] HandleThrowBomb(ApiProtocol.ApiRequest req)
    {
        int bomb = ReadIntParam(req, fallback: 0);
        int remaining = 0;
        if (profiles.Snapshot().Player is not null)
        {
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                if (!player.Items.TryGetValue(ItemKinds.Bombs, out var bombs) || bombs.GetValueOrDefault(bomb) < 1)
                    return null;
                remaining = --bombs[bomb];
                if (remaining == 0) bombs.Remove(bomb);
                return player;
            }, new TaskEngine.Action(39));
        }
        return BuildIntResponse(true, remaining);
    }

    private static int UnixSeconds() => checked((int)DateTimeOffset.UtcNow.ToUnixTimeSeconds());

    /// <summary>SummonLocalMonsters (111): request [int ItemTypeId][int ItemId][int Longitude][int Latitude]
    /// (Serialize 0x2478180); response [byte Result][int groupCount] then groups (Factory 0x1E796D8).
    /// Supports the free post-tutorial scroll and, with Tasks enabled, the owned basic scroll.
    /// Witcher Aura uses its verified skill request and persistent cooldown; other scrolls are refused.
    /// The position is echoed to the client and never logged.</summary>
    private byte[] HandleSummonLocalMonsters(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 16) throw new InvalidDataException("Invalid SummonLocalMonsters payload.");
        var r = new ByteBuffer(req.Data);
        int itemType = r.ReadInt(), itemId = r.ReadInt(), longitude = r.ReadInt(), latitude = r.ReadInt();
        if (itemType == 13) return SummonWitcherAura(req.Id, itemId, longitude, latitude);
        if (TasksEnabled && itemType == 16 && itemId == 2) return SummonOwnedScroll(longitude, latitude);
        var b = new ByteBuffer();
        if (itemType != Reconstruction.SummoningScrollItemType || itemId != Reconstruction.TutorialSummoningScrollId)
        {
            log.LogInformation("  SummonLocalMonsters itemType={Type} itemId={Id} refused", itemType, itemId);
            b.WriteByte(0);
            b.WriteInt(0);
            return b.ToArray();
        }
        var group = summons.Summon(itemType, itemId, UnixSeconds(), Reconstruction.TutorialSummonTtlSeconds,
            longitude, latitude, Reconstruction.TutorialSummonMonsters);
        log.LogInformation("  SummonLocalMonsters tutorial scroll monsters={Count}", group.Monsters.Count);
        b.WriteByte(1);
        b.WriteInt(1);
        WriteSummonedGroup(b, group);
        return b.ToArray();
    }

    /// <summary>GetSummonedMonstersResponse (112): [int groupCount] then groups, no Result byte
    /// (Factory 0x1E79A34). The request has no fields.</summary>
    private byte[] BuildGetSummonedMonstersResponse()
    {
        var groups = summons.Active(UnixSeconds()).Where(g => TasksEnabled || g.ItemId != 2).ToList();
        var b = new ByteBuffer();
        b.WriteInt(groups.Count);
        foreach (var group in groups) WriteSummonedGroup(b, group);
        return b.ToArray();
    }

    /// <summary>LocalMonstersEntity: [int SummoningItemType][int SummoningItemId][int StartTime]
    /// [int DespawnTime][int Longitude][int Latitude][int count] then SummonedMonsterEntity
    /// [int MonsterId][long InstanceId][byte Alive].</summary>
    private static void WriteSummonedGroup(ByteBuffer b, SummonedMonsters.Group group)
    {
        b.WriteInt(group.ItemType);
        b.WriteInt(group.ItemId);
        b.WriteInt(group.StartTime);
        b.WriteInt(group.DespawnTime);
        b.WriteInt(group.Longitude ?? throw new InvalidOperationException("Summoned group without position."));
        b.WriteInt(group.Latitude ?? throw new InvalidOperationException("Summoned group without position."));
        b.WriteInt(group.Monsters.Count);
        foreach (var monster in group.Monsters)
        {
            b.WriteInt(monster.MonsterId);
            b.WriteLong(monster.InstanceId);
            b.WriteByte((byte)(monster.Alive ? 1 : 0));
        }
    }

    /// <summary>EncounterSummonedMonster (113): LongRequest [long InstanceId]; BooleanResponse.</summary>
    private byte[] HandleEncounterSummonedMonster(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 8) throw new InvalidDataException("Invalid EncounterSummonedMonster payload.");
        bool alive = summons.Encounter(new ByteBuffer(req.Data).ReadLong(), UnixSeconds());
        log.LogInformation("  EncounterSummonedMonster alive={Alive}", alive);
        return ApiProtocol.Boolean(alive);
    }

    /// <summary>CombatEndSummonedMonster (114): request [byte Win][uint count][uint×count Details]
    /// [byte PlayerSurrendered] (Serialize 0x19359FC, Details indexed by CombatDetails.Index); response
    /// [int lootCount][int×loot][int BaseExp][int ComboExp][int OilExp][int TimeExp][int PerfectParryExp]
    /// [int FirstTimeExp][int BoostedExp][int PackType] (Factory 0x247EC60). FightNode.OnCombatEnd adds the
    /// experience on the client, so the server adds the same sum. Loot is not reconstructed yet.</summary>
    private byte[] HandleCombatEndSummonedMonster(ApiProtocol.ApiRequest req)
    {
        var end = ReadCombatEnd(req);
        var monster = summons.EndEncounter(end.Won);
        return CombatEndPayload("CombatEndSummonedMonster", end, monster is null ? null : (monster.MonsterId, monster.Difficulty));
    }

    private readonly record struct CombatEndRequest(bool Win, bool Surrendered, int[] Details)
    {
        public bool Won => Win && !Surrendered;
        public int Detail(int index) => index < Details.Length ? Details[index] : 0;
    }

    /// <summary>CombatEnd (8) and CombatEndSummonedMonster (114) request: [byte Win][uint count]
    /// [uint × count Details][byte PlayerSurrendered] (Serialize 0x193588C / 0x19359FC).</summary>
    private static CombatEndRequest ReadCombatEnd(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        bool win = r.ReadByte() != 0;
        uint count = r.ReadUInt();
        if (count > 64 || r.RemainingToRead != count * 4 + 1)
            throw new InvalidDataException("Invalid combat end payload.");
        var details = new int[count];
        for (int i = 0; i < count; i++) details[i] = checked((int)r.ReadUInt());
        return new CombatEndRequest(win, r.ReadByte() != 0, details);
    }

    /// <summary>[amount] of fight experience as the dashboard has it set (a share of the normal amount).</summary>
    private int Exp(int amount) =>
        (int)Math.Min(int.MaxValue / 8, (long)amount * (long)world.Tuning.Get(WorldTuning.ExpPercent) / 100);

    /// <summary>The ingredients a won fight drops, as many as the dashboard says: 200 % doubles each, 150 % adds half of them by chance.</summary>
    private List<int> Looted(List<int> loot)
    {
        double percent = world.Tuning.Get(WorldTuning.LootPercent);
        if (percent == 100) return loot;
        var scaled = new List<int>();
        foreach (int item in loot)
            for (int copies = (int)(percent / 100) + (Random.Shared.NextDouble() * 100 < percent % 100 ? 1 : 0); copies > 0; copies--)
                scaled.Add(item);
        return scaled;
    }

    /// <summary>As much of [loot] as the player's bag still holds; the rest is left behind (the client lists what the
    /// reply lists, so it stays in step).</summary>
    private static List<int> Fit(LocalProfileStore.PlayerState player, List<int> loot) =>
        loot.Take((int)Math.Max(0, Economy.BagSize(player) - SocialPolicy.Occupied(player))).ToList();

    /// <summary>Grants the fight experience of a won fight (see Reconstruction.BaseExp) and records the kill;
    /// <paramref name="record"/> may add more to the same saved revision. Response layout of CombatEnd (8,
    /// Factory 0x247E50C) and CombatEndSummonedMonster (114, 0x247EC60): [int lootCount][int × loot]
    /// [BaseExp][ComboExp][OilExp][TimeExp][PerfectParryExp][FirstTimeExp][BoostedExp][PackType].</summary>
    private byte[] CombatEndPayload(string label, CombatEndRequest end, (int MonsterId, int Difficulty)? monster,
        Action<LocalProfileStore.PlayerState>? record = null)
    {
        int baseExp = 0, comboExp = 0, oilExp = 0, parryExp = 0, firstExp = 0, boostedExp = 0, packType = 0;
        var loot = new List<int>();
        if (monster is { } fought && end.Won)
        {
            baseExp = Exp(Reconstruction.BaseExp(fought.Difficulty));
            comboExp = Exp(Reconstruction.CriticalHitExp * end.Detail(Reconstruction.DetailPerfectAttacks));
            parryExp = Exp(Reconstruction.PerfectParryExp * end.Detail(Reconstruction.DetailPerfectParries));
            oilExp = end.Detail(Reconstruction.DetailUsedProperOil) > 0 ? Exp(Reconstruction.ProperOilExp) : 0;
            if (profiles.Snapshot().Player is not null)
            {
                profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
                {
                    var before = player with { Kills = new(player.Kills!) };
                    var kills = player.Kills!;
                    if (kills.GetValueOrDefault(fought.MonsterId) == 0) firstExp = Exp(Reconstruction.FirstKillExp);
                    kills[fought.MonsterId] = kills.GetValueOrDefault(fought.MonsterId) + 1;
                    record?.Invoke(player);
                    loot = Looted(Economy.FightLoot(fought.MonsterId, fought.Difficulty));
                    // Equipment effects the client leaves to the server (Dummy classes): experience from the kill
                    // (65, reported as BoostedExp) and a chance of extra alchemy ingredients (Reconstruction.ExtraIngredientEffect).
                    var worn = Worn(player);
                    boostedExp = baseExp * Reconstruction.ExperienceBonus(worn) / 100;
                    if (Random.Shared.Next(100) < Reconstruction.ExtraIngredientChance(worn)) loot.AddRange(loot.Skip(2).DefaultIfEmpty(Economy.Tissue));
                    loot = Fit(player, loot);
                    AddItems(player, loot.Select(id => (ItemKinds.Ingredients, id, 1)));
                    var after = Reconstruction.WithExp(player, baseExp + comboExp + oilExp + parryExp + firstExp + boostedExp);
                    return social is null ? after : SocialPolicy.AwardCombatPack(cfg, before, after, out packType);
                }, new TaskEngine.Action(label == "CombatEnd" ? 8 : 114, [end.Details]));
            }
        }
        if (monster is not null && !end.Won && TasksEnabled)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player => player,
                new TaskEngine.Action(label == "CombatEnd" ? 8 : 114, [end.Details]));
        log.LogInformation("  {Label} win={Win} surrendered={Surrendered} monster={Monster} exp={Exp}",
            label, end.Win, end.Surrendered, monster?.MonsterId, baseExp + comboExp + oilExp + parryExp + firstExp + boostedExp);
        var b = new ByteBuffer();
        b.WriteInt(loot.Count); // Loot: item ids, one per unit (reconstructed profiles: ingredients)
        foreach (int item in loot) b.WriteInt(item);
        b.WriteInt(baseExp);
        b.WriteInt(comboExp);
        b.WriteInt(oilExp);     // OilExp: the client's own proper-oil flag (Details[10], SwordModule.GrantOilXP)
        b.WriteInt(0);          // TimeExp: the time threshold is not in the client (EVIDENCE.md §5)
        b.WriteInt(parryExp);
        b.WriteInt(firstExp);
        b.WriteInt(boostedExp); // BoostedExp: the worn equipment's experience bonus (effect 65, a Dummy in the client)
        b.WriteInt(packType);   // PackType: saved with the fight; native FightNode adds this pack to inventory.
        return b.ToArray();
    }

    /// GetInventoryResponse (Method 5): 9 empty Dictionary<int,int> maps + [int BagSize]. Shared by the
    /// 115 batch and the standalone re-sync.
    private byte[] BuildGetInventoryPayload()
    {
        // 1.1.116 GetInventoryResponse.Factory.ReadMap (0x1e7b1f8): [int pairCount] then [int id][int count];
        // counts below 1 are skipped. Order: ingredients, bombs, potions, oils, lures, senses potions,
        // consumables, friends packs, summoning scrolls, then BagSize.
        var player = profiles.Snapshot().Player;
        var items = player?.Items;
        var b = new ByteBuffer();
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.Ingredients));
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.Bombs));
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.Potions));
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.Oils));
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.Lures));
        WriteItemMap(b, items?.GetValueOrDefault(ItemKinds.SensesPotions));
        WriteItemMap(b, null); // consumables
        WriteItemMap(b, items?.GetValueOrDefault(SocialService.PackItems));
        WriteItemMap(b, tasks.Catalog is null ? null : items?.GetValueOrDefault("summoning_scrolls"));
        b.WriteInt(Economy.BagSize(player));                     // BagSize
        return b.ToArray();
    }

    private static void WriteItemMap(ByteBuffer b, IReadOnlyDictionary<int, int>? map)
    {
        var rows = map?.Where(pair => pair.Value > 0).OrderBy(pair => pair.Key).ToList() ?? new();
        b.WriteInt(rows.Count);
        foreach (var (id, count) in rows) { b.WriteInt(id); b.WriteInt(count); }
    }

    /// <summary>AcquireSkill (64): [byte Success][int Skill]. Reconstructed profiles check the skill exists,
    /// is not owned, meets its level gate and requirement, and that enough points remain; legacy profiles
    /// keep the inherited echo.</summary>
    private byte[] HandleAcquireSkill(ApiProtocol.ApiRequest req)
    {
        int skillId = ReadIntParam(req, fallback: 1);
        if (profiles.Snapshot().Player is null) return BuildIntResponse(true, skillId);
        bool acquired = false;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
        {
            var skill = Reconstruction.SkillById(skillId);
            if (skill is null || player.Skills.Contains(skillId) || player.SkillPoints < skill.Cost ||
                Reconstruction.LevelForExp(player.Exp) < skill.RequiredLevel ||
                Reconstruction.SkillRequirements(skill).Any(required => !player.Skills.Contains(required)))
                return null;
            acquired = true;
            player.Skills.Add(skillId);
            return player with { SkillPoints = player.SkillPoints - skill.Cost };
        });
        log.LogInformation("  AcquireSkill result={Result}", acquired ? "acquired" : "refused");
        return BuildIntResponse(acquired, skillId);
    }

    /// <summary>AddSkillPoints (93) is not a reconstructed grant: skill points follow level-ups on the
    /// server. Reconstructed profiles answer with their unchanged total.</summary>
    private byte[] HandleAddSkillPoints(ApiProtocol.ApiRequest req)
    {
        var player = profiles.Snapshot().Player;
        if (player is null) return BuildIntResponse(true, InitialSkillPoints + ReadIntParam(req, fallback: 0));
        return BuildIntResponse(false, player.SkillPoints);
    }

    /// ResolveRewardsResponse (Method 119, dump.cs 600035): [byte Success][List<Item> Items] where
    /// List<Item> = [int count][Item...]. Empty (no rewards) = [byte 1][int 0]. CRITICAL: the client polls
    /// ResolveRewards every ~7s as a POST-SYNC gate (RewardsModule); the 1-byte BooleanResponse catch-all
    /// under-ran the reader ("Tried to read 4 bytes, but only 0 available"), so the client retried forever,
    /// Game.ModulesInitialized never flipped true, and the bottom HUD never appeared. A valid empty reply
    /// lets the gate complete so the Map-state HUD shows.
    private static byte[] BuildResolveRewardsResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1);  // Success
        b.WriteInt(0);   // Items list count (no pending rewards)
        return b.ToArray();
    }

    /// <summary>
    /// Exact 1.1.116 Factory.Deserialize (token 0x6004004, RVA 0x2481d74):
    /// Success, Locations, QuestNodeInstances, Exp, Gold, seven inventory dictionaries,
    /// Armors, Swords, then ExpiringQuestNodeInstances. Node TTL is not a node field.
    /// The synthetic location and successor match RPC60/115; all reward deltas stay zero.
    /// See the immediate-successor contract evidence and tests/results/successor-01.
    /// </summary>
    private byte[] BuildEndBehaviourGraphResponse(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        long instanceId = r.ReadLong();
        string outputName = r.ReadString();
        int count = r.ReadInt();
        if (count < 0 || count > 1024 || r.RemainingToRead != count * 8)
            throw new InvalidDataException("Invalid EndBehaviourGraph fact count.");
        var facts = new Dictionary<int, int>();
        for (int i = 0; i < count; i++) { int key = r.ReadInt(); if (!facts.TryAdd(key, r.ReadInt())) throw new InvalidDataException("Duplicate fact."); }
        log.LogInformation("  Method 57 graph save instanceId={InstanceId} outputName={OutputName} outputLength={OutputLength} facts={FactCount}",
            instanceId, SafeGraphOutputForLog(outputName), outputName.Length, count);
        // After "A Joint Venture" every graph output belongs to season 1 (unknown ones only save their facts).
        if (SeasonOne(profiles.Snapshot()) is not null)
            return StoryEndBehaviourGraph(instanceId, outputName, facts);
        // Every structurally valid graph still saves its facts. These two observed output labels
        // also advance the synthetic quest fixture; unknown labels do not change its stage.
        string? prologueStage = outputName switch
        {
            "thorstein" => LocalProfileStore.DeadHorseStage,
            "2ghouls_left" => LocalProfileStore.GriffinStage,
            _ => null,
        };
        Reconstruction.Reward? granted = null;
        LocalProfileStore.Profile snapshot;
        if (profiles.Snapshot().Player is null)
        {
            snapshot = prologueStage is null
                ? profiles.MergeFacts(facts, persistNoOp: false)
                : profiles.MergeFactsAndStage(facts, prologueStage, persistNoOp: false);
        }
        else
        {
            // Reconstructed profiles: tutorial stages, then the prologue stages; one-time rewards per output.
            string? nextStage = Reconstruction.NextStage(profiles.Snapshot().QuestStage, outputName) ?? prologueStage;
            var reward = Reconstruction.RewardFor(outputName);
            string key = Reconstruction.RewardKey(outputName);
            string? reached = Reconstruction.CompletedStoryNode(outputName);
            snapshot = profiles.UpdatePlayer(facts, nextStage, player =>
            {
                bool marked = false;
                if (reached is not null && !(player.StoryDone ?? []).Contains(reached))
                {
                    player = player with { StoryDone = [.. player.StoryDone ?? [], reached] };
                    marked = true;
                }
                if (reward is null || player.Granted.Contains(key)) return marked ? player : null;
                granted = reward;
                player.Granted.Add(key);
                foreach (var (kind, map) in reward.Items)
                {
                    if (!player.Items.TryGetValue(kind, out var owned)) player.Items[kind] = owned = new Dictionary<int, int>();
                    foreach (var (id, count) in map) owned[id] = owned.GetValueOrDefault(id) + count;
                }
                return Reconstruction.WithExp(player, reward.Exp, reward.Gold);
            });
            log.LogInformation("  Method 57 reward={Reward}", granted is null ? "none" : "granted");
        }
        snapshot = CaughtUp(snapshot);
        log.LogInformation("  Method 57 synthetic quest stage={Stage}", snapshot.QuestStage ?? "legacy");
        var b = new ByteBuffer(); b.WriteByte(1);
        WriteStory(b, snapshot);
        // 1.1.116 Deserialize (0x2481d74): Exp and Gold are deltas (QuestEndRequestNode passes them to
        // PlayerData.AddXp/AddGold); then potions, bombs, oils, lures, senses potions, bestiary entries and
        // ingredients as [int pairCount][int id][int count], then the armour and sword id lists.
        b.WriteInt(granted?.Exp ?? 0);
        b.WriteInt(granted?.Gold ?? 0);
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Potions));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Bombs));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Oils));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Lures));
        b.WriteInt(0); // senses potions
        // BestiaryEntries: the monsters of a story fight, once with its reward (Reconstruction.OutputKills).
        WriteItemMap(b, granted is null ? null : Reconstruction.OutputKills(outputName, snapshot.Facts));
        b.WriteInt(0); // ingredients
        b.WriteInt(0); // Armors
        b.WriteInt(0); // Swords
        b.WriteInt(0); // ExpiringQuestNodeInstances (after rewards in RPC57)
        return b.ToArray();
    }

    /// <summary>EndBehaviourGraph (57) after "A Joint Venture" (StoryEngine): saves the facts; for a season 1 node
    /// (by instance, or a journal button by output name) it starts or finishes the quest, records the output and,
    /// the first time the output is reached, grants its experience, gold and items and counts its monsters. The
    /// response has the same layout as for the prologue: the active nodes, then Exp and Gold (deltas the client
    /// adds; an endpoint output shows them in the quest-completed window), the item maps and BestiaryEntries.</summary>
    private byte[] StoryEndBehaviourGraph(long instanceId, string outputName, Dictionary<int, int> facts)
    {
        StoryEngine.Step? step = null;
        var snapshot = profiles.UpdatePlayer(facts, null, player =>
        {
            var progress = player.Story ?? LocalProfileStore.StoryProgress.Empty;
            if (StoryEngine.Resolve(progress, instanceId, outputName) is not { } node) return null;
            step = StoryEngine.Advance(progress, node, outputName, StoryNow(progress));
            if (step is null) return null;
            player = player with { Story = step.Progress };
            if (!step.FirstTime) return player;
            foreach (var (monster, kills) in step.Output.Kills)
                player.Kills![monster] = player.Kills.GetValueOrDefault(monster) + kills;
            var gear = EquipmentOf(player);
            foreach (var (kind, map) in step.Output.Items)
            {
                // Swords and armours join the equipment (GetEquipment 9); other items the inventory.
                if (kind == "swords") { gear = gear with { Swords = [.. gear.Swords, .. map.Keys.Where(id => !gear.Swords.Contains(id))] }; continue; }
                if (kind == "armors") { gear = gear with { Armors = [.. gear.Armors, .. map.Keys.Where(id => !gear.Armors.Contains(id))] }; continue; }
                if (!player.Items.TryGetValue(kind, out var owned)) player.Items[kind] = owned = new Dictionary<int, int>();
                foreach (var (id, count) in map) owned[id] = owned.GetValueOrDefault(id) + count;
            }
            if (step.Output.Items.ContainsKey("swords") || step.Output.Items.ContainsKey("armors")) player = player with { Equipment = gear };
            return Reconstruction.WithExp(player, step.Output.Exp, step.Output.Gold);
        });
        var granted = step is { FirstTime: true } ? step.Output : null;
        log.LogInformation("  Method 57 story node={Node} output={Output} result={Result} reward={Reward}",
            step?.Node.Key ?? "unknown", SafeGraphOutputForLog(outputName),
            step is null ? "facts only" : step.Output.Endpoint ? "quest finished" : "recorded",
            granted is null ? "none" : "granted");
        var b = new ByteBuffer(); b.WriteByte(1);
        WriteStory(b, snapshot);
        b.WriteInt(granted?.Exp ?? 0);
        b.WriteInt(granted?.Gold ?? 0);
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Potions));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Bombs));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Oils));
        WriteItemMap(b, granted?.Items.GetValueOrDefault(ItemKinds.Lures));
        b.WriteInt(0); // senses potions
        WriteItemMap(b, granted?.Kills);   // BestiaryEntries
        b.WriteInt(0); // ingredients
        foreach (string kind in new[] { "armors", "swords" })   // Armors, Swords: id lists the client adds to its storage
        {
            var ids = granted?.Items.GetValueOrDefault(kind)?.Keys.ToList() ?? new List<int>();
            b.WriteInt(ids.Count);
            foreach (int id in ids) b.WriteInt(id);
        }
        b.WriteInt(0); // ExpiringQuestNodeInstances
        return b.ToArray();
    }

    /// <summary>The story clock: now, moved on by the local test endpoint's offset.</summary>
    private static long StoryNow(LocalProfileStore.StoryProgress progress) =>
        DateTimeOffset.UtcNow.ToUnixTimeSeconds() + progress.Clock;

    private static LocalProfileStore.EquipmentState EquipmentOf(LocalProfileStore.PlayerState player) =>
        player.Equipment ?? LocalProfileStore.EquipmentState.Starting;

    /// <summary>The equipped armour and sword.</summary>
    private static Reconstruction.Gear?[] Worn(LocalProfileStore.PlayerState player)
    {
        var gear = EquipmentOf(player);
        return new[] { Reconstruction.ArmorById(gear.Armor), Reconstruction.SwordById(gear.Sword) };
    }

    /// <summary>EquipArmor (11), EquipSteelSword (12), EquipSilverSword (13), EquipSword (55): IntRequest [int id];
    /// IntResponse [byte Result][int id]. Reconstructed profiles equip an owned item and keep it (GetEquipment 9);
    /// anything else is refused. Legacy profiles echo the id.</summary>
    private byte[] HandleEquip(ApiProtocol.ApiRequest req)
    {
        int id = ReadIntParam(req, fallback: 1);
        if (profiles.Snapshot().Player is null) return BuildIntResponse(true, id);
        bool armor = req.Method == M_EquipArmor, done = false;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
        {
            var gear = EquipmentOf(player);
            if (!(armor ? gear.Armors : gear.Swords).Contains(id)) return null;
            done = true;
            return player with { Equipment = armor ? gear with { Armor = id } : gear with { Sword = id } };
        });
        log.LogInformation("  Equip {Kind} id={Id} result={Result}", armor ? "armor" : "sword", id, done ? "equipped" : "refused");
        // Native OnEquipSwordResponse ignores Result: retain the saved selection on refusal.
        return BuildIntResponse(done, done ? id : CurrentEquipment(armor));
    }

    /// <summary>TrackQuest (72): IntRequest [int questId]; IntResponse [byte Result][int questId]. Season 1 keeps
    /// the tracked quest for GetFinishedSeasonQuests (70).</summary>
    private byte[] HandleTrackQuest(ApiProtocol.ApiRequest req)
    {
        int quest = ReadIntParam(req, fallback: 0);
        if (SeasonOne(profiles.Snapshot()) is { } story && story.Tracked != quest)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
                player with { Story = (player.Story ?? LocalProfileStore.StoryProgress.Empty) with { Tracked = quest } });
        return BuildIntResponse(true, quest);
    }

    /// <summary>
    /// Accepts exact pair-count or count-of-ints forms, bounded to 1024 pairs.
    /// This deliberate compatibility probe remains unverified against the old client serializer.
    /// </summary>
    private byte[] HandleSetFacts(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int declared = r.ReadInt();
        if (r.RemainingToRead % 8 != 0 || r.RemainingToRead > 8192)
            throw new InvalidDataException("Invalid SetFacts pair payload.");
        int pairs = r.RemainingToRead / 8;
        // Upstream captures use count-of-ints; accept exact pair-count too while the old serializer is unverified.
        if (declared != pairs && declared != pairs * 2) throw new InvalidDataException("Invalid SetFacts count.");
        var facts = new Dictionary<int, int>();
        while (r.RemainingToRead > 0) { int key = r.ReadInt(); if (!facts.TryAdd(key, r.ReadInt())) throw new InvalidDataException("Duplicate fact."); }
        StoreFacts(facts);
        return ApiProtocol.Boolean(true);
    }

    /// GetFactsResponse (Method 58, dump.cs 598697) and GetAllFactsResponse (Method 59, dump.cs 598307)
    /// have the identical wire shape (single Dictionary<int,int> Facts field) — see WriteFactsDict.
    /// Serves the full persisted store; GetFactsRequest's RequestedFacts filter (dump.cs 602150) is
    /// ignored — a superset is safe, the handler merges it into the client-side fact database.
    private byte[] BuildGetFactsResponse()
    {
        var b = new ByteBuffer();
        WriteFactsDict(b);
        return b.ToArray();
    }
    /// No unverified error DTO is invented: an unsupported method is left unanswered (HandleApiAsync).
    private byte[] BuildCatchAllResponse(int method)
    {
        log.LogWarning("Unsupported RPC method={Method}; no verified response body", method);
        throw new NotSupportedException("Unsupported RPC.");
    }

    private byte[] BuildUseOilPotionsResponse(ApiProtocol.ApiRequest req)
    {
        // The 1.1.116 request has Oil and Potions fields and its response derives from
        // BooleanResponse. An empty pre-fight loadout serializes Oil as the unset sentinel -1
        // followed by an empty Potions list (count 0); this was observed on the 1.1.116 client.
        // Until item-use persistence is implemented, acknowledge only that form; never pretend
        // a selected item was consumed. Diagnostics classify fields without logging item IDs.
        if (profiles.Snapshot().Player is not null) return HandleUseOilPotions(req);
        if (req.Data.Length != 8) throw new InvalidDataException("Unsupported UseOilPotions payload shape.");
        var request = new ByteBuffer(req.Data);
        var oil = request.ReadInt();
        var potionCount = request.ReadInt();
        var oilClass = oil switch { -1 => "unset", 0 => "zero", > 0 => "selected", _ => "other-negative" };
        if (request.RemainingToRead != 0 || oil != -1 || potionCount != 0)
        {
            log.LogWarning("UseOilPotions refused: bytes={Bytes} oilClass={OilClass} potionListEmpty={PotionListEmpty}",
                req.Data.Length, oilClass, potionCount == 0);
            throw new NotSupportedException("UseOilPotions with selected consumables is not implemented.");
        }
        log.LogInformation("UseOilPotions acknowledged: oilClass={OilClass} potionListEmpty=true", oilClass);
        return ApiProtocol.Boolean(true);
    }

    /// <summary>Reconstructed UseOilPotions (89): [int Oil (-1 = none)][int potionCount][int potion…].
    /// Consumes one of each selected item when every one is owned; otherwise nothing changes and the
    /// BooleanResponse is false.</summary>
    private byte[] HandleUseOilPotions(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int oil = r.ReadInt();
        int count = r.ReadInt();
        if (count < 0 || count > 16 || r.RemainingToRead != count * 4)
            throw new InvalidDataException("Unsupported UseOilPotions payload shape.");
        var potions = new List<int>();
        for (int i = 0; i < count; i++) potions.Add(r.ReadInt());
        var wanted = new List<(string Kind, int Id)>();
        if (oil != -1) wanted.Add((ItemKinds.Oils, oil));
        wanted.AddRange(potions.Select(potion => (ItemKinds.Potions, potion)));
        bool used = ConsumeItems(wanted, selectedPotions: potions);
        log.LogInformation("UseOilPotions result={Result} oilSelected={Oil} potions={Count}", used ? "used" : "refused", oil != -1, count);
        return ApiProtocol.Boolean(used);
    }

    /// <summary>Consumes one of each listed item when every one is owned; otherwise nothing changes.</summary>
    private bool ConsumeItems(IReadOnlyList<(string Kind, int Id)> wanted,
        IReadOnlyList<(string Kind, int Id)>? mustOwn = null, IReadOnlyList<int>? selectedPotions = null)
    {
        if (wanted.Count == 0 && (mustOwn is null || mustOwn.Count == 0)) return true;
        bool used = false;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
        {
            if (selectedPotions is not null && !Economy.ValidPotionSelection(player, selectedPotions)) return null;
            foreach (var group in wanted.Concat(mustOwn ?? []).GroupBy(item => item))
                if (!player.Items.TryGetValue(group.Key.Kind, out var owned) || owned.GetValueOrDefault(group.Key.Id) < group.Count())
                    return null;
            used = true;
            if (wanted.Count == 0) return null;
            foreach (var (kind, id) in wanted)
            {
                var owned = player.Items[kind];
                owned[id]--;
                if (owned[id] == 0) owned.Remove(id);
            }
            return player;
        }, new TaskEngine.Action(89));
        return used;
    }

    /// <summary>ClaimMonsterKnowledgeReward (65): request [int MonsterId]; response (Factory.Deserialize
    /// 0x247D948) [byte Success][int MonsterId][int SkillPoints], the points being added by the client. A
    /// reconstructed profile claims its next reached tier (Reconstruction.KnowledgeTier) once; otherwise, and for
    /// legacy profiles, Success is false with no points.</summary>
    private byte[] HandleClaimMonsterKnowledgeReward(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int monsterId = r.ReadInt();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Unsupported ClaimMonsterKnowledgeReward payload shape.");
        int points = 0;
        var facts = profiles.Snapshot().Facts;
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                int reached = Reconstruction.KnowledgeTier(monsterId, Reconstruction.AllKills(player, facts).GetValueOrDefault(monsterId));
                var claimed = new Dictionary<int, int>(player.KnowledgeClaimed ?? new Dictionary<int, int>());
                if (claimed.GetValueOrDefault(monsterId) >= reached) return null;
                claimed[monsterId] = claimed.GetValueOrDefault(monsterId) + 1;
                points = Reconstruction.KnowledgeTierSkillPoints;
                return player with { KnowledgeClaimed = claimed, SkillPoints = player.SkillPoints + points };
            });
        log.LogInformation("ClaimMonsterKnowledgeReward result={Result}", points > 0 ? "claimed" : "refused");
        var b = new ByteBuffer();
        b.WriteByte(points > 0 ? (byte)1 : (byte)0);
        // Both native subscribers ignore Success; an unresolved monster must accompany zero points.
        b.WriteInt(points > 0 ? monsterId : -1);
        b.WriteInt(points);
        return b.ToArray();
    }

    /// <summary>BuyAutoEquipItems (98), the combat preparation's "buy recommended items": the request has the
    /// PrepareToCombat shape and the response is a BooleanResponse. Reconstructed profiles pay the unit prices of
    /// auto_equip_items_prices (Economy.UnitPrices) and get one of each item; without enough gold, or on a legacy
    /// profile, nothing changes and the answer is false.</summary>
    private byte[] HandleBuyAutoEquipItems(ApiProtocol.ApiRequest req)
    {
        var (bombs, potions, oil) = ReadLoadout(new ByteBuffer(req.Data));
        var wanted = new List<(int Type, int Item)>();
        if (oil != -1) wanted.Add((Economy.TypeOil, oil));
        wanted.AddRange(bombs.Select(bomb => (Economy.TypeBomb, bomb)));
        wanted.AddRange(potions.Select(potion => (Economy.TypePotion, potion)));
        var prices = Economy.UnitPrices().ToDictionary(p => (p.Type, p.Item), p => p.Price);
        bool bought = false;
        if (profiles.Snapshot().Player is not null && wanted.Count > 0 && wanted.All(prices.ContainsKey))
        {
            int cost = wanted.Sum(w => prices[w]);
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                if (player.Gold < cost || !Economy.ValidPotionSelection(player, potions) ||
                    SocialPolicy.Occupied(player) + wanted.Count > Economy.BagSize(player)) return null;
                AddItems(player, wanted.Select(w => (Economy.KindOf(w.Type)!, w.Item, 1)));
                bought = true;
                return player with { Gold = player.Gold - cost };
            });
        }
        log.LogInformation("BuyAutoEquipItems result={Result} oilSelected={Oil} bombs={Bombs} potions={Potions}",
            bought ? "bought" : "refused", oil != -1, bombs.Count, potions.Count);
        return ApiProtocol.Boolean(bought);
    }

    /// <summary>Adds items to a detached player state (Items by kind).</summary>
    private static void AddItems(LocalProfileStore.PlayerState player, IEnumerable<(string Kind, int Id, int Count)> items)
    {
        foreach (var (kind, id, count) in items)
        {
            if (!player.Items.TryGetValue(kind, out var owned)) player.Items[kind] = owned = new Dictionary<int, int>();
            owned[id] = owned.GetValueOrDefault(id) + count;
        }
    }

    /// <summary>BuyShopBundle (75): request [int bundleId][long nonce] (OrenTransactionProcessor sends a random
    /// long); response [byte Result][int BundleId][int OrensAmount] (Factory 0x247CA18). The client checks
    /// Result and BundleId and then refreshes the player's data. Reconstructed profiles pay the bundle's gold
    /// price (daily deals discounted) and get its items, stations and bags (Economy.BagSize), or nothing when its
    /// items do not fit in the bag; OrensAmount is the gold left.</summary>
    private byte[] HandleBuyShopBundle(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 12) throw new InvalidDataException("Invalid BuyShopBundle payload.");
        var r = new ByteBuffer(req.Data);
        int bundleId = r.ReadInt();
        long transaction = r.ReadLong();
        bool bought = false;
        int gold = profiles.Snapshot().Player?.Gold ?? 0;
        string outcome = "refused";
        // Oren packs are bought with real money only (76), never with orens.
        if (Economy.BundleById(bundleId) is { InAppPrice: null } bundle && profiles.Snapshot().Player is not null)
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            int price = Economy.PriceOf(bundle, now);
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                gold = player.Gold;
                // The ledger settles a transaction once, across retries, reconnections and restarts: a known nonce
                // answers its first outcome, a nonce seen with another bundle is refused, and neither pays again.
                if (player.Transactions?.GetValueOrDefault(transaction) is { } known)
                {
                    bought = known.Bundle == bundleId && known.Bought;
                    outcome = known.Bundle == bundleId ? "replayed" : "nonce-reused";
                    return null;
                }
                LocalProfileStore.PlayerState Declined() => player with { Transactions = Record(player, transaction, bundleId, false, now) };
                if (player.Gold < price || (bundle.OneTime && (player.OneTimeBundles ?? []).Contains(bundleId))) return Declined();
                // what fits in the bag, counted as the client's CanBuyThisShopItem counts it
                int space = bundle.Items.Where(i => Economy.KindOf(i.Type) is not null).Sum(i => i.Amount);
                if (space > 0 && SocialPolicy.Occupied(player) + space > Economy.BagSize(player)) return Declined();
                var brewers = EnsureBrewers(player).ToList();
                var gear = EquipmentOf(player);
                if (bundle.Items.Any(i => (i.Type == Economy.TypeArmor && gear.Armors.Contains(i.Item)) ||
                                          (i.Type == Economy.TypeSword && gear.Swords.Contains(i.Item))))
                    return Declined();   // equipment is owned once
                foreach (var (type, item, amount) in bundle.Items)
                {
                    if (type == Economy.TypeArmor) gear = gear with { Armors = [.. gear.Armors, item] };
                    else if (type == Economy.TypeSword) gear = gear with { Swords = [.. gear.Swords, item] };
                    else if (type == Economy.TypeBrewer && Economy.Brewers.FirstOrDefault(b => b.Id == item) is { } kind)
                        for (int i = 0; i < amount; i++)
                            brewers.Add(new LocalProfileStore.BrewerState(brewers.Max(b => b.InstanceId) + 1, kind.Id, kind.Uses, Idle, 0));
                    else if (Economy.KindOf(type) is { } itemKind)
                        AddItems(player, new[] { (itemKind, item, amount) });
                }
                bought = true;
                outcome = "bought";
                gold = player.Gold - price;
                return player with
                {
                    Gold = gold, Brewers = brewers, Equipment = gear,
                    OneTimeBundles = bundle.OneTime ? [.. player.OneTimeBundles ?? [], bundleId] : player.OneTimeBundles,
                    Transactions = Record(player, transaction, bundleId, true, now),
                };
            });
        }
        log.LogInformation("BuyShopBundle bundle={Bundle} result={Result}", bundleId, outcome);
        var b = new ByteBuffer();
        b.WriteByte(bought ? (byte)1 : (byte)0);
        b.WriteInt(bundleId);
        b.WriteInt(gold);
        return b.ToArray();
    }

    /// <summary>BuyShopInAppBundle (76), the purchase of an oren pack with the store's receipt
    /// (ValidateReceiptStep.ValidateReceiptOnServer 0x18AD550; BuyShopInAppBundleRequest.Serialize 0x19352F0): [int
    /// BundleId][int n][n bytes ShopName][int n][n bytes Receipt][long Timestamp][int n][n bytes IsoCurrencyCode][int
    /// Quantity][int Price]. Response BuyShopInAppBundleResponse, an IntIntResponse [byte Result][int BundleId][int
    /// OrensAmount]: OnBuyShopInAppBundleResponse (0x18ADC74) succeeds when the result is true and the bundle id is
    /// the one bought, then synchronizes the inventory; a false result shows the failure window. A LAB client buys
    /// through the client's fake store, so the purchase is free: the server grants the pack's orens, once per
    /// Timestamp (the transaction ledger), and refuses anything that is not an oren pack. The receipt is neither kept
    /// nor logged.</summary>
    private byte[] HandleBuyShopInAppBundle(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int bundleId = r.ReadInt();
        foreach (int limit in new[] { 64, 64 * 1024 })
        {
            int length = r.ReadInt();
            if (length < 0 || length > limit) throw new InvalidDataException("Invalid BuyShopInAppBundle field.");
            r.ReadBytes(length);   // shop name, then the receipt
        }
        long transaction = r.ReadLong();
        int currency = r.ReadInt();
        if (currency < 0 || currency > 16) throw new InvalidDataException("Invalid BuyShopInAppBundle currency.");
        r.ReadBytes(currency);
        r.ReadInt(); r.ReadInt();  // quantity and price: one pack is granted whatever they say
        if (r.RemainingToRead != 0) throw new InvalidDataException("Invalid BuyShopInAppBundle payload.");
        bool granted = false;
        string outcome = "refused";
        int gold = profiles.Snapshot().Player?.Gold ?? 0;
        if (Economy.OrenPackOf(bundleId) is { } pack && profiles.Snapshot().Player is not null)
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                gold = player.Gold;
                if (player.Transactions?.GetValueOrDefault(transaction) is { } known)
                {
                    granted = known.Bundle == bundleId && known.Bought;
                    outcome = known.Bundle == bundleId ? "replayed" : "nonce-reused";
                    return null;
                }
                granted = true;
                outcome = "granted";
                gold = player.Gold + pack.Orens;
                return player with { Gold = gold, Transactions = Record(player, transaction, bundleId, true, now) };
            });
        }
        log.LogInformation("BuyShopInAppBundle bundle={Bundle} result={Result}", bundleId, outcome);
        var b = new ByteBuffer();
        b.WriteByte(granted ? (byte)1 : (byte)0);
        b.WriteInt(bundleId);
        b.WriteInt(gold);
        return b.ToArray();
    }

    /// <summary>WorkingRecipe of an idle station: the client crafts while WorkingRecipe >= 0
    /// (BrewerInstance.IsCrafting) and looks that recipe up, so an idle station sends -1.</summary>
    private const int Idle = -1;

    /// <summary>The profile's transaction ledger with one more outcome, trimmed to the newest TransactionLimit.</summary>
    private static Dictionary<long, LocalProfileStore.TransactionRecord> Record(LocalProfileStore.PlayerState player,
        long transaction, int bundle, bool bought, long now)
    {
        var ledger = new Dictionary<long, LocalProfileStore.TransactionRecord>(player.Transactions ?? new())
            { [transaction] = new(bundle, bought, now) };
        return ledger.Count <= LocalProfileStore.TransactionLimit ? ledger
            : ledger.OrderByDescending(pair => pair.Value.At).Take(LocalProfileStore.TransactionLimit)
                .ToDictionary(pair => pair.Key, pair => pair.Value);
    }

    /// <summary>GetTransactionStatus (80): request [int][long transaction] (IntLongRequest), response IntResponse
    /// [byte Result][int status] with GetTransactionStatusResponse TRANSACTION_NOT_FOUND 1, INVALID 2, SUCCESS 3.
    /// OrenTransactionProcessor asks before buying: not found sends BuyShopBundle, success completes the
    /// purchase without buying again. The answer comes from the profile's transaction ledger.</summary>
    private byte[] HandleGetTransactionStatus(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 12) throw new InvalidDataException("Invalid GetTransactionStatus payload.");
        var r = new ByteBuffer(req.Data);
        r.ReadInt();
        long transaction = r.ReadLong();
        // Only a bought bundle counts as completed; a declined nonce is "not found", so the client asks
        // BuyShopBundle again and the ledger repeats the refusal without charging.
        bool done = profiles.Snapshot().Player?.Transactions?.GetValueOrDefault(transaction) is { Bought: true };
        return BuildIntResponse(true, done ? 3 : 1);
    }

    /// <summary>The player's stations, with the unlimited basic station always first. Stations saved with the old
    /// type ids 1201-1203 come back as the client's 1-3.</summary>
    private static List<LocalProfileStore.BrewerState> EnsureBrewers(LocalProfileStore.PlayerState player)
    {
        var brewers = player.Brewers?.Select(b => b.Type > 1200 ? b with { Type = b.Type - 1200 } : b).ToList()
            ?? new List<LocalProfileStore.BrewerState>();
        if (!brewers.Any(b => b.InstanceId == Economy.BasicBrewerInstance))
            brewers.Insert(0, new LocalProfileStore.BrewerState(Economy.BasicBrewerInstance, Economy.BasicBrewer.Id, -1, Idle, 0));
        return brewers;
    }

    /// <summary>GetKnownRecipes (6): [int count]{[int itemType][int n]{[int recipeId]}} (Factory.ReadHashSet
    /// 0x1E7C10C). Base alchemy skills and potion-specific recipe skills determine knowledge.</summary>
    private static byte[] BuildKnownRecipes(LocalProfileStore.PlayerState player)
    {
        var b = new ByteBuffer();
        var byType = Economy.Recipes.Where(recipe => Economy.KnowsRecipe(player, recipe))
            .GroupBy(r => r.ItemType).OrderBy(g => g.Key).ToList();
        b.WriteInt(byType.Count);
        foreach (var group in byType)
        {
            b.WriteInt(group.Key);
            b.WriteInt(group.Count());
            foreach (var recipe in group) b.WriteInt(recipe.Id);
        }
        return b.ToArray();
    }

    /// <summary>GetBrewers (69): [byte Success][int n]{[long InstanceId][int Type][int UsesLeft][int WorkingRecipe]
    /// [int FinishTime]} (Factory 0x24850D0, Brewer ctor order); WorkingRecipe -1 when idle.</summary>
    private byte[] BuildGetBrewers()
    {
        var player = profiles.Snapshot().Player;
        var brewers = player is null ? new List<LocalProfileStore.BrewerState>() : EnsureBrewers(player);
        var b = new ByteBuffer();
        b.WriteByte(1);
        b.WriteInt(brewers.Count);
        foreach (var brewer in brewers) WriteBrewer(b, brewer);
        return b.ToArray();
    }

    private static void WriteBrewer(ByteBuffer b, LocalProfileStore.BrewerState brewer)
    {
        b.WriteLong(brewer.InstanceId); b.WriteInt(brewer.Type); b.WriteInt(brewer.UsesLeft);
        b.WriteInt(brewer.WorkingRecipe); b.WriteInt(brewer.FinishTime);
    }

    /// <summary>GetCraftingQueue (44): [int n]{[int RecipeId][int Count][int StartTime][int EndTime]}; crafting
    /// runs on the stations (Brewer.WorkingRecipe), so the queue is empty.</summary>
    private static byte[] BuildGetCraftingQueue() => new byte[4];

    /// <summary>CraftItem (4): request [long BrewerInstanceId][int RecipeId][int ItemType]; response [byte Success]
    /// [long BrewerInstanceId][int UsesLeft][int WorkingRecipe][int FinishTime] (Factory 0x247F034). An idle
    /// station takes a known formula when every ingredient is owned; the ingredients are used up, a limited
    /// station loses a use, and the item is ready after the formula's time times the station's factor.</summary>
    private byte[] HandleCraftItem(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        long instance = r.ReadLong();
        int recipeId = r.ReadInt();
        int itemType = r.ReadInt();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Unsupported CraftItem payload shape.");
        LocalProfileStore.BrewerState? result = null;
        bool crafted = false;
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var brewers = EnsureBrewers(player);
                int index = brewers.FindIndex(x => x.InstanceId == instance);
                if (index < 0) return null;
                result = brewers[index];
                var recipe = Economy.Recipes.FirstOrDefault(x => x.Id == recipeId && x.ItemType == itemType);
                if (recipe is not null) recipe = Economy.ApplyPolicy(recipe, skillBalance);
                var kind = Economy.Brewers.FirstOrDefault(x => x.Id == result.Type);
                if (recipe is null || kind is null || result.WorkingRecipe != Idle || result.UsesLeft == 0 ||
                    !Economy.KnowsRecipe(player, recipe)) return null;
                var owned = player.Items.GetValueOrDefault(ItemKinds.Ingredients) ?? new Dictionary<int, int>();
                if (recipe.Ingredients.Any(n => owned.GetValueOrDefault(n.Ingredient) < n.Amount)) return null;
                foreach (var (ingredient, amount) in recipe.Ingredients)
                {
                    owned[ingredient] -= amount;
                    if (owned[ingredient] == 0) owned.Remove(ingredient);
                }
                int finish = (int)DateTimeOffset.UtcNow.ToUnixTimeSeconds() + Economy.CraftingSeconds(recipe, kind);
                result = result with
                {
                    WorkingRecipe = recipe.Id, FinishTime = finish,
                    OutputCount = skillBalance.CraftOutputCount(player, recipe),
                    UsesLeft = result.UsesLeft > 0 ? result.UsesLeft - 1 : result.UsesLeft,
                };
                brewers[index] = result;
                crafted = true;
                return player with { Brewers = brewers };
            });
        log.LogInformation("CraftItem recipe={Recipe} result={Result}", recipeId, crafted ? "started" : "refused");
        var b = new ByteBuffer();
        b.WriteByte(crafted ? (byte)1 : (byte)0);
        b.WriteLong(instance);
        b.WriteInt(result?.UsesLeft ?? 0);
        b.WriteInt(result?.WorkingRecipe ?? 0);
        b.WriteInt(result?.FinishTime ?? 0);
        return b.ToArray();
    }

    /// <summary>ClaimRecipe (68): request [long BrewerInstanceId]; response [byte Success][long BrewerInstanceId]
    /// [int n]{[int Type][int ItemId]} (Factory 0x247DCE4), one entry per item. A finished station hands over
    /// its saved output quantity; a limited station with no uses left is used up.</summary>
    private byte[] HandleClaimRecipe(ApiProtocol.ApiRequest req)
    {
        long instance = new ByteBuffer(req.Data).ReadLong();
        var items = new List<(int Type, int Item)>();
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var brewers = EnsureBrewers(player);
                int index = brewers.FindIndex(x => x.InstanceId == instance);
                if (index < 0) return null;
                var brewer = brewers[index];
                var recipe = Economy.Recipes.FirstOrDefault(x => x.Id == brewer.WorkingRecipe);
                if (recipe is null || DateTimeOffset.UtcNow.ToUnixTimeSeconds() < brewer.FinishTime) return null;
                if (brewer.OutputCount is < 1 or > 2) return null;
                AddItems(player, new[] { (Economy.KindOf(recipe.ItemType)!, recipe.Output, brewer.OutputCount) });
                for (int i = 0; i < brewer.OutputCount; i++) items.Add((recipe.ItemType, recipe.Output));
                if (brewer.UsesLeft == 0) brewers.RemoveAt(index);
                else brewers[index] = brewer with { WorkingRecipe = Idle, FinishTime = 0, OutputCount = 1 };
                return player with { Brewers = brewers };
            }, new TaskEngine.Action(68));
        log.LogInformation("ClaimRecipe result={Result}", items.Count > 0 ? "claimed" : "refused");
        var b = new ByteBuffer();
        b.WriteByte(items.Count > 0 ? (byte)1 : (byte)0);
        b.WriteLong(instance);
        b.WriteInt(items.Count);
        foreach (var (type, item) in items) { b.WriteInt(type); b.WriteInt(item); }
        return b.ToArray();
    }

    /// <summary>CancelCrafting (45): request [long BrewerInstanceId]; BooleanResponse. The work stops and its
    /// ingredients are lost (UI/PANELS/ALCHEMY/BREWING_CANCEL_DESCRIPTION_TEXT); a used-up station goes.</summary>
    private byte[] HandleCancelCrafting(ApiProtocol.ApiRequest req)
    {
        long instance = new ByteBuffer(req.Data).ReadLong();
        bool cancelled = false;
        if (profiles.Snapshot().Player is not null)
            profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
            {
                var brewers = EnsureBrewers(player);
                int index = brewers.FindIndex(x => x.InstanceId == instance && x.WorkingRecipe != Idle);
                if (index < 0) return null;
                if (brewers[index].UsesLeft == 0) brewers.RemoveAt(index);
                else brewers[index] = brewers[index] with { WorkingRecipe = Idle, FinishTime = 0, OutputCount = 1 };
                cancelled = true;
                return player with { Brewers = brewers };
            });
        return ApiProtocol.Boolean(cancelled);
    }

    /// <summary>UseSenses (42): request [int potionId][int n][long sensed…]; response [byte Success]. The senses
    /// view is free; a senses potion (Falcon) is used up when one is owned.</summary>
    private byte[] HandleUseSenses(ApiProtocol.ApiRequest req)
    {
        var r = new ByteBuffer(req.Data);
        int potion = r.ReadInt();
        int count = r.ReadInt();
        if (count < 0 || count > 256 || r.RemainingToRead != count * 8) throw new InvalidDataException("Invalid UseSenses payload.");
        var sensed = new List<long>();
        for (int i = 0; i < count; i++) sensed.Add(r.ReadLong());
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        bool ok = true;
        if (profiles.Snapshot().Player is not null)
        {
            // A potion that would reveal nothing new is not spent (the client removes it only on success).
            ok = potion <= 0 || (sensed.Count > 0 && ConsumeItems(new[] { (ItemKinds.SensesPotions, potion) }));
            if (ok && sensed.Count > 0)
            {
                Dictionary<long, long> ends;
                lock (worldGate) ends = sensed.ToDictionary(id => id, id => worldSpawns.TryGetValue(id, out var spawn)
                    ? spawn.SpawnTimeMs / 1000 + spawn.Ttl : now + WorldSpawns.LifetimeSeconds);
                profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
                {
                    var kept = (player.Sensed ?? new Dictionary<long, long>()).Where(s => s.Value > now)
                        .ToDictionary(s => s.Key, s => s.Value);
                    foreach (var (id, end) in ends) kept[id] = end;
                    return player with { Sensed = kept };
                });
            }
        }
        else if (potion > 0) ok = false;
        log.LogInformation("UseSenses potion={Potion} sensed={Count} result={Result}", potion > 0, sensed.Count, ok);
        return ApiProtocol.Boolean(ok);
    }

    /// <summary>PrepareToCombat (10), sent by

    /// <summary>PrepareToCombatAbstractRequest.Serialize (0x2477798): [int bombCount][int bomb…]
    /// [int potionCount][int potion…][int Oil (-1 = none)].</summary>
    private static (List<int> Bombs, List<int> Potions, int Oil) ReadLoadout(ByteBuffer r)
    {
        List<int> ReadList()
        {
            int n = r.ReadInt();
            if (n < 0 || n > 16 || r.RemainingToRead < n * 4) throw new InvalidDataException("Invalid loadout list.");
            var list = new List<int>();
            for (int i = 0; i < n; i++) list.Add(r.ReadInt());
            return list;
        }
        var bombs = ReadList();
        var potions = ReadList();
        int oil = r.ReadInt();
        if (r.RemainingToRead != 0) throw new InvalidDataException("Unsupported loadout payload shape.");
        return (bombs, potions, oil);
    }

    /// <summary>PrepareToCombat (10), sent by a story combat preparation that does not send the standard
    /// request (FightEquipmentNode SendStandardServerRequest = 0, e.g. the wraiths of "A Joint Venture").
    /// Request (PrepareToCombatAbstractRequest.Serialize 0x2477798): [int bombCount][int bomb…]
    /// [int potionCount][int potion…][int Oil (-1 = none)]. Response (Factory.Deserialize 0x1E77CB0):
    /// [byte Success]. Reconstructed profiles spend the selected oil and potions when everything selected is
    /// owned; a selected bomb is only checked, because the fight takes it with its inventory quantity
    /// (BehaviourGraphModule.PreNestGraphEnded 0x17E828C: PlayerStorage&lt;Bomb&gt;.TryGetQuantity into an
    /// InventorableFightEquipment) and bombs are spent when thrown (ThrowBomb 39, or BombsUsed in EndNestCombat 53).
    /// Legacy profiles accept only an empty loadout.</summary>
    private byte[] HandlePrepareToCombat(ApiProtocol.ApiRequest req)
    {
        var (bombs, potions, oil) = ReadLoadout(new ByteBuffer(req.Data));
        var wanted = new List<(string Kind, int Id)>();
        if (oil != -1) wanted.Add((ItemKinds.Oils, oil));
        wanted.AddRange(potions.Select(potion => (ItemKinds.Potions, potion)));
        var selectedBombs = bombs.Select(bomb => (ItemKinds.Bombs, bomb)).ToList();
        bool ok = profiles.Snapshot().Player is not null ? ConsumeItems(wanted, selectedBombs, potions)
            : wanted.Count == 0 && selectedBombs.Count == 0;
        if (!ok && profiles.Snapshot().Player is null)
            throw new NotSupportedException("PrepareToCombat with selected consumables is not implemented for legacy profiles.");
        log.LogInformation("PrepareToCombat result={Result} oilSelected={Oil} bombs={Bombs} potions={Potions}",
            ok ? "used" : "refused", oil != -1, bombs.Count, potions.Count);
        var b = new ByteBuffer(); b.WriteByte(ok ? (byte)1 : (byte)0);
        return b.ToArray();
    }

    private byte[] BuildActiveQuestNodeInstances(LocalProfileStore.Profile? snapshot = null)
    {
        snapshot ??= CaughtUp(profiles.Snapshot());
        var b = new ByteBuffer();
        WriteStory(b, snapshot);
        b.WriteInt(0); // ExpiringQuestNodeInstances (immediately after nodes in RPC60)
        return b.ToArray();
    }

    /// <summary>The quest locations and nodes of RPC 60 and 57: the several nodes of "A Joint Venture" on
    /// their own places, otherwise the single node of the stage.</summary>
    private void WriteStory(ByteBuffer b, LocalProfileStore.Profile snapshot)
    {
        if (SeasonOne(snapshot) is { } story)
        {
            // Map nodes of started quests on their places (each copy on its own); queued nodes on the fixture place
            // beside the player (CloseFollow), where the client's FireQueuedGraph (0x17E89D0) finds the nearest
            // quest POI with the queued node id once the queuing graph ends.
            var shown = StoryEngine.Active(story, snapshot.Facts, StoryNow(story)).ToList();
            var placed = StoryView(shown.Where(n => !n.Queued));
            WriteQuestLocations(b, placed.Select(item => item.Place).DistinctBy(place => place.Id).ToList());
            var queued = shown.Where(n => n.Queued).ToList();
            b.WriteInt(placed.Count + queued.Count);
            foreach (var (node, place, copy) in placed)
                WriteStoryNode(b, node, node.Instance + copy, place.Id, Reconstruction.DisplayNormal);
            foreach (var node in queued)
                WriteStoryNode(b, node, node.Instance, TutPlaceId, Reconstruction.DisplayCloseFollow);
            return;
        }
        if (JointVentureView(snapshot) is { } view)
        {
            WriteQuestLocations(b, view.Select(item => item.Place).ToList());
            b.WriteInt(view.Count);
            foreach (var (node, place) in view)
            {
                b.WriteLong(node.InstanceId);
                b.WriteInt(node.NodeId); b.WriteString(place.Id);
                b.WriteString(node.PoiSettings);
                b.WriteString(node.Graph);
                b.WriteInt(Reconstruction.DisplayNormal);
            }
            return;
        }
        var single = StoryPlaceFor(snapshot);
        WriteQuestLocations(b, single is null ? [] : [single]);
        WriteQuestNodes(b, snapshot, single);
    }

    /// <summary>Season 1 progress of a reconstructed profile once "A Joint Venture" is over; null before that.</summary>
    private static LocalProfileStore.StoryProgress? SeasonOne(LocalProfileStore.Profile snapshot) =>
        snapshot.Player is { } player && snapshot.QuestStage == LocalProfileStore.JvDoneStage
            ? player.Story ?? LocalProfileStore.StoryProgress.Empty : null;

    /// <summary>QuestNodeInstance (0x1934B40): [long InstanceId][int QuestNodeId][string PlaceId][string SettingsPath]
    /// [string BehaviourGraphName][int DisplayMode].</summary>
    private static void WriteStoryNode(ByteBuffer b, StoryEngine.Node node, long instance, string placeId, int display)
    {
        b.WriteLong(instance);
        b.WriteInt(node.Id); b.WriteString(placeId);
        b.WriteString(node.Poi);
        b.WriteString(node.Graph);
        b.WriteInt(display);
    }

    /// <summary>Season 1 nodes with their places, chosen once and kept (StoryEngine.Node: a band around the loaded
    /// area, near another node, or another node's place), one entry per copy. A node without a place yet is left
    /// out until an area is loaded.</summary>
    private List<(StoryEngine.Node Node, LocalProfileStore.StoryPlace Place, int Copy)> StoryView(IEnumerable<StoryEngine.Node> nodes)
    {
        var view = new List<(StoryEngine.Node, LocalProfileStore.StoryPlace, int)>();
        foreach (var node in nodes)
            for (int copy = 0; copy < Math.Max(1, node.Copies); copy++)
            {
                if (StoryPlaceOf(node, copy) is { } place) view.Add((node, place, copy));
                else log.LogWarning("  Story node {Node} has no place yet (no area loaded)", node.Key);
            }
        return view;
    }

    private static string StoryPlaceKey(StoryEngine.Node node, int copy) => copy == 0 ? node.Key : $"{node.Key}#{copy}";

    private LocalProfileStore.StoryPlace? StoryPlaceOf(StoryEngine.Node node, int copy = 0)
    {
        var saved = profiles.Snapshot().Player?.StoryPlaces ?? new Dictionary<string, LocalProfileStore.StoryPlace>();
        if (node.PlaceOf is not null && StoryEngine.NodeByKey(node.PlaceOf) is { } owner)
            return saved.GetValueOrDefault(owner.Key) ?? StoryPlaceOf(owner);
        string key = StoryPlaceKey(node, copy);
        // A giver shows only within the giver hide distance (QuestPoiInstance.ShouldBeInstantiated 0x1909F58), so
        // one left outside the loaded area (the player moved away) gets a new place there.
        var area = playable.Area;
        if (saved.GetValueOrDefault(key) is { } known &&
            !(node.Giver && profiles.Snapshot().Player?.Story?.Started.Contains(node.Quest) != true &&
                known.CellId is ulong cell && area.Count > 0 && !area.Contains(cell)))
            return known;
        // Spots of other nodes of unfinished quests and of copies are kept apart.
        var finished = profiles.Snapshot().Player?.Story?.Finished ?? new List<int>();
        var taken = StoryEngine.Nodes.Where(other => other.Quest == node.Quest || !finished.Contains(other.Quest))
            .SelectMany(other => Enumerable.Range(0, Math.Max(1, other.Copies)).Select(k => StoryPlaceKey(other, k)))
            .Where(other => other != key)
            .Select(other => saved.GetValueOrDefault(other)).OfType<LocalProfileStore.StoryPlace>().ToList();
        var near = node.Near is null ? null : StoryEngine.NodeByKey(node.Near) is { } anchor ? StoryPlaceOf(anchor) : null;
        if (node.Near is not null && near is null) return null;
        return ChooseStoryPlace(key, node.Min, node.Max, near, taken);
    }

    /// <summary>The givers of the season 1 quests the client offers now, with their places.</summary>
    private List<(StoryEngine.Node Node, LocalProfileStore.StoryPlace Place)> StoryGivers(LocalProfileStore.Profile snapshot) =>
        SeasonOne(snapshot) is { } story
            ? StoryView(StoryEngine.Available(story, snapshot.Facts).Select(q => StoryEngine.RootOf(q.Id)!))
                .Select(item => (item.Node, item.Place)).ToList()
            : new List<(StoryEngine.Node, LocalProfileStore.StoryPlace)>();

    /// <summary>The nodes of the current "A Joint Venture" stage with their places (null for other stages).
    /// A node whose place cannot be chosen yet (no area loaded) is left out until the next request.</summary>
    private List<(Reconstruction.StoryNode Node, LocalProfileStore.StoryPlace Place)>? JointVentureView(
        LocalProfileStore.Profile snapshot)
    {
        if (snapshot.Player is not { } player ||
            Reconstruction.JointVentureNodes(snapshot.QuestStage, player.StoryDone) is not { } nodes)
            return null;
        var view = new List<(Reconstruction.StoryNode, LocalProfileStore.StoryPlace)>();
        foreach (var node in nodes)
        {
            var saved = profiles.Snapshot().Player?.StoryPlaces ?? new Dictionary<string, LocalProfileStore.StoryPlace>();
            // Spots of the quest's other nodes are kept apart; earlier quests' spots may be reused.
            var taken = Reconstruction.JointVentureAll.Where(other => other.Key != node.Key)
                .Select(other => saved.GetValueOrDefault(other.Key)).OfType<LocalProfileStore.StoryPlace>().ToList();
            var place = saved.GetValueOrDefault(node.Key) ?? ChooseStoryPlace(node.Key, node.MinDistance, node.MaxDistance,
                node.Near is null ? null : saved.GetValueOrDefault(node.Near), taken);
            if (place is not null) view.Add((node, place));
            else log.LogWarning("  Story node {Node} has no place yet (no area loaded)", node.Key);
        }
        return view;
    }

    /// <summary>List&lt;Location&gt; (Location.Factory 0x19343C0): [int count] then [string placeId]
    /// [float lat][float lng][int biomeCount][int biome × count]. The fixture place keeps its zero
    /// coordinates; the chosen story places follow it.</summary>
    private void WriteQuestLocations(ByteBuffer b, IReadOnlyList<LocalProfileStore.StoryPlace> places)
    {
        b.WriteInt(1 + places.Count);
        b.WriteString(TutPlaceId); b.WriteFloat(TutLat); b.WriteFloat(TutLng); b.WriteInt(0);
        foreach (var place in places)
        {
            b.WriteString(place.Id); b.WriteFloat((float)place.Lat); b.WriteFloat((float)place.Lng);
            b.WriteInt(place.Biomes.Length);
            foreach (int biome in place.Biomes) b.WriteInt(biome);
        }
    }

    /// <summary>LoadCells (88): [int count][ulong cellId × count]; the client sends the 3×3 level-14
    /// cells around the player. They are kept in memory as the player's area and never logged.</summary>
    private byte[] HandleLoadCells(ApiProtocol.ApiRequest req)
    {
        try { playable.SetArea(PlayableLocations.ReadCellIds(req.Data)); }
        catch (InvalidDataException) { log.LogWarning("  LoadCells payload is not a cell list ({Len}B)", req.Data.Length); }
        return ApiProtocol.Boolean(true);
    }

    /// <summary>The point of the current story node for reconstructed profiles: the saved one, or a new
    /// pedestrian-safe place in the stage's distance band around the player's area (saved once chosen).
    /// Null keeps the fixture place, shown beside the player.</summary>
    private LocalProfileStore.StoryPlace? StoryPlaceFor(LocalProfileStore.Profile snapshot)
    {
        if (snapshot.Player is not { } player || snapshot.QuestStage is not { } stage ||
            Reconstruction.StoryDistance(stage) is not { } band)
            return null;
        if (player.StoryPlaces?.GetValueOrDefault(stage) is { } saved) return saved;
        return ChooseStoryPlace(stage, band.Min, band.Max, near: null, taken: []);
    }

    /// <summary>Chooses and saves a pedestrian-safe place for a story stage or node: a playable place of the
    /// loaded area in the distance band around the player's GPS position, else the area's centre (or around
    /// <paramref name="near"/>), away from the places already taken. A node that belongs beside another one
    /// falls back to that one's point. Null when no area is loaded or no place fits.</summary>
    private LocalProfileStore.StoryPlace? ChooseStoryPlace(string key, double min, double max,
        LocalProfileStore.StoryPlace? near, IReadOnlyCollection<LocalProfileStore.StoryPlace> taken)
    {
        var area = playable.Area;
        var cells = area.Count == 0 ? null : playable.Cells(area, epoch: 0);
        var options = new List<PlayableLocations.Place>();
        if (cells is { Count: > 0 })
        {
            var player = PlayerPosition();
            double lat = near?.Lat ?? player?.Lat ?? cells.Average(c => c.Lat),
                lng = near?.Lng ?? player?.Lng ?? cells.Average(c => c.Lng);
            // Authored spacing: separate spots for separate goals; a companion node may stand closer.
            double spacing = near is null ? 100 : 40;
            var band = cells.SelectMany(c => c.Places).Where(p =>
                PlayableLocations.Distance(lat, lng, p.Lat, p.Lng) is var d && d >= min && d <= max).ToList();
            options = band.Where(p => taken.All(t => PlayableLocations.Distance(t.Lat, t.Lng, p.Lat, p.Lng) >= spacing)).ToList();
            // A crowded band still gets a spot, shared with another node if need be.
            if (options.Count == 0) options = band;
        }
        LocalProfileStore.StoryPlace place;
        if (options.Count > 0)
        {
            // Prefer open ground and woods (Grassland 4, Forest 1) to built-up spots.
            var open = options.Where(p => p.Biomes.Contains(1) || p.Biomes.Contains(4)).ToList();
            var pool = open.Count > 0 ? open : options;
            var pick = pool[Random.Shared.Next(pool.Count)];
            ulong cell = cells!.First(c => c.Places.Contains(pick)).Id;
            place = new LocalProfileStore.StoryPlace($"lab-story-{key}", pick.Lat, pick.Lng, pick.Biomes, cell);
        }
        else if (near is not null) place = near with { Id = $"lab-story-{key}" };
        else return null;
        profiles.UpdatePlayer(new Dictionary<int, int>(), null, p => p with
        {
            StoryPlaces = new Dictionary<string, LocalProfileStore.StoryPlace>(
                p.StoryPlaces ?? new Dictionary<string, LocalProfileStore.StoryPlace>()) { [key] = place },
        });
        log.LogInformation("  Story place chosen for {Key} options={Count}", key, options.Count);
        return place;
    }

    /// <summary>Quest node 287 for reconstructed profiles after the griffin; a griffin beaten before the
    /// closing stage existed counts too, by its one-time reward.</summary>
    private static Reconstruction.QuestNode? QueuedStoryNode(LocalProfileStore.Profile snapshot) =>
        snapshot.Player is { } player && (snapshot.QuestStage == LocalProfileStore.PrologueDoneStage ||
            (snapshot.QuestStage == LocalProfileStore.GriffinStage && player.Granted.Contains("griffin")))
            ? Reconstruction.JointVentureStart : null;

    private static void WriteQuestNodes(ByteBuffer b, LocalProfileStore.Profile snapshot,
        LocalProfileStore.StoryPlace? place = null)
    {
        if ((Reconstruction.TutorialNode(snapshot.QuestStage) ?? QueuedStoryNode(snapshot)) is { } node)
        {
            b.WriteInt(1);
            b.WriteLong(node.InstanceId);
            b.WriteInt(node.NodeId); b.WriteString(TutPlaceId);
            b.WriteString(node.PoiSettings);
            b.WriteString(node.Graph);
            b.WriteInt(2);
            return;
        }
        // "A Joint Venture" before the map is examined (the journal's button, not a map POI) and after its
        // end: no story node.
        if (snapshot.QuestStage is LocalProfileStore.JointVentureStage or LocalProfileStore.JvDoneStage)
        {
            b.WriteInt(0);
            return;
        }
        bool griffin = snapshot.QuestStage == LocalProfileStore.GriffinStage;
        bool deadHorse = snapshot.QuestStage == LocalProfileStore.DeadHorseStage ||
            (snapshot.QuestStage is null or Reconstruction.Prologue && snapshot.Facts.TryGetValue(10145, out int state) && state == 1);
        b.WriteInt(1);
        b.WriteLong(griffin ? GriffinInstanceId : deadHorse ? 5124756197357912298L : 5124757777905877225L);
        b.WriteInt(griffin ? 3 : deadHorse ? 2 : 1); b.WriteString(place?.Id ?? TutPlaceId);
        // Thorstein lies on the map, knocked off his horse, until his first dialog. Client (1.1.116 catalog):
        // poi_settings/s00/prolog/thorstein_hurt_lq with the thorstein_hurt_lq prefab (hurt mesh and the
        // thorstein_hurt_idle_map sound), beside the prolog_01 dialog's dlg_prolog_thorstein_getting_up. The
        // standing _common/thorstein_lq is the season 1 quests' Thorstein.
        b.WriteString(griffin ? GriffinSettingsPath : deadHorse
            ? "assets/_bundledassets/story/poi_settings/s00/prolog/dead_horse_head.asset"
            : "assets/_bundledassets/story/poi_settings/s00/prolog/thorstein_hurt_lq.asset");
        b.WriteString(griffin ? GriffinGraphPath : deadHorse
            ? "s00/prolog/prolog_01_dead_horse"
            : "s00/prolog/prolog_01_thorstein");
        b.WriteInt(place is null ? Reconstruction.DisplayCloseFollow : Reconstruction.StoryDisplayMode(snapshot.QuestStage));
    }

    /// <summary>RelocateQuest (77): LongRequest [long InstanceId] of the tracked quest's giver POI
    /// (StoryModule.RelocateQuest 0x19A5E24 via GetTrackedQuestGiverPOIInstanceID 0x19A5F24). Only quest nodes
    /// served as GetLocationsByCell (40) QuestNodeInstancePlacements get IsQuestGiver (0x190321C; nodes of RPC 60
    /// and 57 get false at 0x1900E2C). The client offers relocation (CheckTrackedQuestForRelocation 0x19A526C)
    /// when an active node of the quest is more than PoiSettings.AllowRelocateQuestMinDistance (1000 m on
    /// LAB 16) away and a giver of that quest stands in a cell other than the one the quest was started in
    /// (IsRelocatableQuest 0x19A57B8). Response (Factory 0x1E78DD4): [byte Success] followed by the RPC 60 body;
    /// the lists are read on refusal too. On success HandleRelocateQuestResponse (0x19A6CAC) looks the giver up
    /// again and saves its cell. The plan is built without writes and saved in one revision.</summary>
    private byte[] HandleRelocateQuest(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 8) throw new InvalidDataException("Invalid RelocateQuest payload.");
        // Reconnected sockets share this player. Publish the reply before another socket can plan the
        // same request, otherwise its revision guard can turn a successful retry into a refusal.
        lock (settled)
        {
            if (ReplayedResponse(req) is { } replay) return replay;
            var response = RelocateQuest(new ByteBuffer(req.Data).ReadLong());
            RememberResponse(req, response);
            return response;
        }
    }

}
