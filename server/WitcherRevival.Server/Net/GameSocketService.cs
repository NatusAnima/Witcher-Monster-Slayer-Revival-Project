using System.Net;
using System.Net.Sockets;
using System.Text;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// TCP game server. Right now it accepts connections and hex-logs every frame, so the first real
/// client session confirms the still-unconfirmed wire details (channel <c>Type</c> bytes, ByteBuffer
/// string framing, auth payload layout). Reply logic is stubbed until those are confirmed against
/// captured bytes — see <c>docs/protocol-boot.md</c> §10.
/// </summary>
public sealed class GameSocketService(ILogger<GameSocketService> log, IConfiguration cfg) : BackgroundService
{
    private readonly int _port = cfg.GetValue("GameServer:Port", 4253);

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        var listener = new TcpListener(IPAddress.Any, _port);
        listener.Start();
        log.LogInformation("Game socket listening on 0.0.0.0:{Port}", _port);
        try
        {
            while (!ct.IsCancellationRequested)
            {
                var client = await listener.AcceptTcpClientAsync(ct);
                _ = HandleClientAsync(client, ct);
            }
        }
        finally { listener.Stop(); }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken ct)
    {
        var ep = client.Client.RemoteEndPoint;
        log.LogInformation("Client connected: {EP}", ep);
        try
        {
            using (client)
            await using (var stream = client.GetStream())
            {
                // The client (ThreadedClient) prepends the 4-byte magic 0x9043284A (SECRET_BYTES) to
                // EVERY outgoing message, then a SocketMessageFactory frame [1B type][4B BE size][payload].
                // The server does NOT prepend magic on replies (client's TryDeserialize doesn't expect it).
                while (!ct.IsCancellationRequested)
                {
                    var magic = await ReadExactAsync(stream, 4, ct);
                    if (magic is null) break;
                    if (!magic.AsSpan().SequenceEqual(PreloaderStaticData.Magic))
                    {
                        log.LogWarning("Expected per-message magic, got {Hex} — desynced, closing.", BitConverter.ToString(magic));
                        break;
                    }
                    var frame = await FrameCodec.ReadAsync(stream, ct);
                    if (frame is null) break;
                    var f = frame.Value;
                    log.LogInformation("RX  type={Type} ({Chan})  len={Len}\n{Hex}", f.Type, ChannelName(f.Type), f.Data.Length, HexDump(f.Data));
                    await DispatchAsync(stream, f, ct);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            log.LogWarning("Client {EP} error: {Msg}", ep, ex.Message);
        }
        finally { log.LogInformation("Client disconnected: {EP}", ep); }
    }

    // Outer channel type bytes, confirmed from ApiBuilder.CreateHandler key registrations.
    private const byte Ch_Api = 1, Ch_Logging = 2, Ch_Auth = 3, Ch_StaticGameData = 4;

    private static string ChannelName(byte t) => t switch
    {
        Ch_Api => "Api", Ch_Logging => "Logging", Ch_Auth => "Authentication",
        Ch_StaticGameData => "StaticGameData", _ => "?"
    };

    private async Task DispatchAsync(Stream stream, Frame f, CancellationToken ct)
    {
        switch (f.Type)
        {
            case Ch_Auth:
                DecodeAuthRequest(f);
                // Reply on the Authentication channel: inner Message = [int MethodId=AUTHENTICATE(1)][byte code].
                // AuthenticationHandler reads one byte; code 0 => Success=true (see protocol-boot.md §6).
                var auth = new ByteBuffer();
                auth.WriteInt(1);          // inner MethodId = AUTHENTICATE
                auth.WriteByte(0);         // code 0 = success
                await FrameCodec.WriteAsync(stream, Ch_Auth, auth.ToArray(), ct);
                log.LogInformation("TX  Authentication OK (Success=true, ErrCode=0)");
                break;

            case Ch_StaticGameData:
                await HandleStaticGameDataAsync(stream, f, ct);
                break;

            case Ch_Api:
                await HandleApiAsync(stream, f, ct);
                break;

            case Ch_Logging:
                break; // client log upload; ignore
        }
    }

    // StaticGameData channel (type 4): StaticGameDataMessage = [int MethodId][Data]. TypeId FETCH=1, GET_DATA_URL=2.
    private const int SGD_Fetch = 1, SGD_GetDataUrl = 2;

    private async Task HandleStaticGameDataAsync(Stream stream, Frame f, CancellationToken ct)
    {
        int methodId;
        try { methodId = new ByteBuffer(f.Data).ReadInt(); }
        catch { log.LogWarning("  StaticGameData parse failed"); return; }

        if (methodId == SGD_GetDataUrl)
        {
            // CdnPreloader downloads this URL, GZip-decompresses, DataContractJson -> Container.
            string url = cfg["StaticData:Url"] ?? "http://127.0.0.1:8080/staticdata";
            var resp = new ByteBuffer();
            resp.WriteInt(SGD_GetDataUrl);   // echo MethodId (GET_DATA_URL)
            resp.WriteString(url);           // GetStaticDataUrlResponse.StaticDataUrl
            await FrameCodec.WriteAsync(stream, Ch_StaticGameData, resp.ToArray(), ct);
            log.LogInformation("  TX  StaticGameData GET_DATA_URL -> {Url}", url);
        }
        else if (methodId == SGD_Fetch)
        {
            // FetchStaticGameDataResponse = [int len][gzip bytes] (inline).
            byte[] gz = PreloaderStaticData.GzipContainer(cfg.GetValue("Preloader:EmptyObject", false));
            var resp = new ByteBuffer();
            resp.WriteInt(SGD_Fetch);
            resp.WriteInt(gz.Length);
            resp.WriteBytes(gz);
            await FrameCodec.WriteAsync(stream, Ch_StaticGameData, resp.ToArray(), ct);
            log.LogInformation("  TX  StaticGameData FETCH inline ({Len}B gzip)", gz.Length);
        }
        else log.LogInformation("  StaticGameData MethodId={M} not handled", methodId);
    }

    // Api Method ids (from Api.Method enum). Boot-time + post-boot.
    private const int M_GetPlayerInfo = 3, M_GetInventory = 5, M_GetEquipment = 9;
    private const int M_GetDailyContracts = 20, M_GetLocationsByCell = 40;
    private const int M_GetSensedMonsters = 43, M_GetCurrentObjective = 61;
    private const int M_GetWeather = 67, M_GetDailyShopBundles = 79;
    private const int M_GetOneTimeShopBundles = 83, M_GetExpiringEffects = 85;
    private const int M_LoadCells = 88, M_GetPlayerModifiers = 91;
    private const int M_GetWeeklyContractProgress = 94, M_GetFriends = 102;
    private const int M_GetFriendsNotifications = 110, M_GetInitialPlayerData = 115;
    private const int M_Ping = 141;

    // Post-boot player-action Method ids (Api.Method enum) — handled explicitly below so their
    // IntResponse readers don't under-run on the 1-byte BooleanResponse catch-all.
    private const int M_EquipArmor = 11, M_EquipSteelSword = 12, M_EquipSilverSword = 13;
    private const int M_DistanceTraveled = 27, M_SetCustomizationHead = 28;
    private const int M_SetTutorialFinished = 30, M_EquipSword = 55, M_EndBehaviourGraph = 57;
    private const int M_GetFacts = 58, M_AcquireSkill = 64, M_TrackQuest = 72, M_AddSkillPoints = 93, M_ResolveRewards = 119;

    // Shared player-state values (server is stateless this round; keeps the boot batch and the
    // post-boot action replies coherent with each other and with the ID contract).
    private const int TotalDistanceTraveled = 15000;  // DistanceTraveled(27) Param — batch AND post-boot
    private const int InitialSkillPoints = 10;        // GetSkills(63) SkillPoints; AddSkillPoints(93) base

    // S00 tutorial quest-giver (Thorstein) placement. Coords = the player's center S2 cell, decoded from the
    // method-40 GetLocationsByCell request (2026-07-05). Update these to the player's real GPS if they move.
    private const string TutPlaceId = "tut_thorstein";
    private const float TutLat = 32.453864f;
    private const float TutLng = 35.058088f;

    private async Task HandleApiAsync(Stream stream, Frame f, CancellationToken ct)
    {
        ApiProtocol.ApiRequest req;
        try { req = ApiProtocol.Parse(f.Data); }
        catch (Exception ex) { log.LogWarning("  Api parse failed: {Msg}", ex.Message); return; }

        log.LogInformation("  Api request: Id={Id} Method={Method} dataLen={Len}", req.Id, req.Method, req.Data.Length);
        if (req.Data.Length > 0)
        {
            log.LogInformation("  [PAYLOAD] Method={Method} data={Hex}", req.Method, Convert.ToHexString(req.Data));
        }

        byte[] methodPayload = req.Method switch
        {
            M_LoadCells => ApiProtocol.Boolean(true),      // LoadCellsResponse : BooleanResponse -> 1 byte
            M_GetInitialPlayerData => BuildInitialPlayerData(),
            // GetPlayerInfo(3) + GetInventory(5) are re-requested STANDALONE post-boot (PlayerData re-sync),
            // not just inside the 115 batch — answer them with the same payloads or the client under-runs.
            M_GetPlayerInfo => BuildGetPlayerInfoPayload(),
            M_GetInventory => BuildGetInventoryPayload(),
            M_GetWeather => BuildGetWeatherResponse(),
            M_GetLocationsByCell => BuildGetLocationsByCellResponse(),
            M_GetExpiringEffects => BuildGetExpiringEffectsResponse(),
            M_GetFriends => BuildGetFriendsResponse(),
            M_GetFriendsNotifications => BuildGetFriendsNotificationsResponse(),
            M_GetDailyContracts => BuildGetDailyContractsResponse(),
            M_GetWeeklyContractProgress => BuildGetWeeklyContractProgressResponse(),
            M_GetSensedMonsters => BuildGetSensedMonstersResponse(),
            M_GetCurrentObjective => BuildGetCurrentObjectiveResponse(),
            M_GetDailyShopBundles => BuildGetDailyShopBundlesResponse(),
            M_GetOneTimeShopBundles => BuildGetOneTimeShopBundlesResponse(),
            M_GetPlayerModifiers => BuildGetPlayerModifiersResponse(),
            // Post-boot player actions (request layouts decoded from dump.cs — see each builder/helper):
            M_DistanceTraveled => BuildIntResponse(true, TotalDistanceTraveled),
            M_EquipArmor or M_EquipSword or M_EquipSteelSword or M_EquipSilverSword
                => BuildIntResponse(true, ReadIntParam(req, fallback: 1)),   // echo the equipped item id
            M_SetCustomizationHead => BuildIntResponse(true, ReadIntParam(req, fallback: 1)), // echo head id
            M_SetTutorialFinished => BuildIntResponse(true, 1),  // request has NO payload (dump.cs 602627)
            M_AcquireSkill => BuildIntResponse(true, ReadIntParam(req, fallback: 1)),
            M_TrackQuest => BuildIntResponse(true, ReadIntParam(req, fallback: 0)),
            M_AddSkillPoints => BuildIntResponse(true, InitialSkillPoints + ReadIntParam(req, fallback: 0)),
            M_ResolveRewards => BuildResolveRewardsResponse(),  // post-sync reward gate — see builder
            M_EndBehaviourGraph => BuildEndBehaviourGraphResponse(),
            M_GetFacts => BuildGetFactsResponse(),
            M_Ping => ApiProtocol.Boolean(true),            // PingResponse — keep alive
            _ => BuildCatchAllResponse(req.Method),
        };

        var payload = ApiProtocol.BuildResponse(req.Id, req.Method, methodPayload);
        await FrameCodec.WriteAsync(stream, Ch_Api, payload, ct);
        log.LogInformation("  TX  Api response Method={Method} Id={Id} ({Len}B)", req.Method, req.Id, payload.Length);
    }

    /// GetInitialPlayerDataResponse wire = [int count][ for each: int methodId, sub-response fields read
    /// INLINE by that method's Factory (no per-item length prefix) ].
    /// Sub-response wire formats decoded from *Response.Serialize() (write order == ctor order, big-endian):
    ///   GetPlayerInfo(3): [byte Success][string Name][int Gold][int Exp][int Head][byte TutorialFinished][byte Gender]
    ///   GetEquipment(9):  [int SwordsCount][int*swords][int ArmorsCount][int*armors][int EquippedArmor][int EquippedSword]
    ///
    /// Gated behind Player:SendInitialData. Default is now TRUE: hook.js un-bypasses PlayerData by default,
    /// and an un-bypassed PlayerData.InitializeModule NREs on an empty batch (it dereferences the missing
    /// sub-responses). So the coherent default for the UI bring-up run is to send the full 12-response batch.
    /// The 12 keys = the exact union that the un-bypassed, batch-synchronizing modules pull out of the dict:
    ///   PlayerData.InitializeModule (0x17436E8) + PlayerInventory.Initialize (0x1747F04): {3,5,6,7,9,24,27,63,69}
    ///   ServerFactDatabaseModule.InitializeModule (0x178A3D0): {59}   (un-bypassed for PlayerModule.GetFact)
    ///   ShopStorageModule.InitializeModule (0x18FD0F0): {83, 79} (GetDailyShopBundles, GetOneTimeShopBundles)
    ///   PlayerModifiersModule.InitializeModule (0x1787BC4): {91} (GetPlayerModifiers)
    /// The gate is kept (not removed) only as a debug escape hatch: set Player:SendInitialData=false to
    /// force an empty batch AND re-bypass PlayerData in hook.js together if you need the old bare boot.
    /// All 12 sub-response wire formats below were byte-verified against each *Response.Serialize() in the
    /// v1.0.43 binary (disasm) — write order == the client's Deserialize read order (mirror image).
    /// It equips the id=1 sword/armor/head that PreloaderStaticData ships, so PlayerAvatar.Initialize
    /// resolves a real (non-null) loadout. FORCE_SYNC in hook.js still covers the sync gate.
    private byte[] BuildInitialPlayerData()
    {
        var b = new ByteBuffer();
        if (!cfg.GetValue("Player:SendInitialData", true))
        {
            b.WriteInt(0);   // empty batch — nothing to deserialize (debug only; re-bypass PlayerData too)
            return b.ToArray();
        }

        const int equippedId = 1;   // MUST match the ids in PreloaderStaticData.LoadoutOverrides
  
        b.WriteInt(19); // 19 responses
  
        // Method 3 — GetPlayerInfo (shared builder — also served standalone post-boot)
        b.WriteInt(M_GetPlayerInfo);
        b.WriteBytes(BuildGetPlayerInfoPayload());

        // Method 9 — GetEquipment
        // Constructor: SwordsCount (int), [int*SwordsCount], ArmorsCount (int), [int*ArmorsCount], EquippedArmor (int), EquippedSword (int)
        // Owned ids per the ID contract — every id here MUST exist in PreloaderStaticData (Track A: swords 1..6, armors 1..6).
        b.WriteInt(M_GetEquipment);
        b.WriteInt(3);                     // SwordsCount
        b.WriteInt(1);                     // owned sword ids
        b.WriteInt(2);
        b.WriteInt(3);
        b.WriteInt(2);                     // ArmorsCount
        b.WriteInt(1);                     // owned armor ids
        b.WriteInt(2);
        b.WriteInt(equippedId);            // EquippedArmor
        b.WriteInt(equippedId);            // EquippedSword

        // Method 5 — GetInventory (shared builder — also served standalone post-boot)
        b.WriteInt(M_GetInventory);
        b.WriteBytes(BuildGetInventoryPayload());

        // Method 6 — GetKnownRecipes  (empty Dictionary<int, HashSet<int>>)
        // PlayerInventory.Initialize (0x1747F04) synchronizes this key DIRECTLY (not via SignalBus) and
        // invokes OnGetKnownRecipesResponse even when the key is missing -> null Data -> NRE that froze the
        // boot at 68% (runtime 2026-07-04). Wire format verified via GetKnownRecipesResponse.Factory.ReadHashSet
        // (0x1F7DCB8): [int outerCount] then per entry [int key][int innerCount][int*innerCount]. Empty = [int 0].
        b.WriteInt(6);
        b.WriteInt(0);  // KnownRecipes (0 entries)

        // Method 7 — GetKilledMonsters
        // [int KilledMonsters count][(int monsterId,int count)…] then [int ClaimedTiers count][(int,int)…]
        // Bestiary content: kill counts for monster ids 1..3 (Track A defines monsters 1..8 in static data).
        b.WriteInt(7);
        b.WriteInt(3);                  // KilledMonsters (3 entries)
        b.WriteInt(1); b.WriteInt(5);   // monster 1 killed 5×
        b.WriteInt(2); b.WriteInt(2);   // monster 2 killed 2×
        b.WriteInt(3); b.WriteInt(1);   // monster 3 killed 1×
        b.WriteInt(0);                  // ClaimedMonsterKnowledgeTiers (empty)

        // Method 24 — GetAchievements  (bool Success, Dictionary<int,int> achievementId -> value)
        // CRITICAL: the client deserializer (0x1F736E4) reads [byte Success][int N][N ints] where the loop
        // counter increments by 2 (add w24,w24,#2) — so N is the number of INTS (2 × entries), NOT the pair
        // count. Writing N=2 for 2 entries made the client read only 1 pair and leave 8 bytes, which drifted
        // the whole batch and DROPPED the last two methods (43, 56) — the exact cause of the PoiModule NRE.
        b.WriteInt(24);
        b.WriteByte(1);                 // Success = true
        b.WriteInt(4);                  // N = 4 ints = 2 achievement entries (Track A defines achievements 1..6)
        b.WriteInt(1); b.WriteInt(1);   // achievement 1 -> 1
        b.WriteInt(2); b.WriteInt(1);   // achievement 2 -> 1

        // Method 63 — GetSkills
        // Constructor order: Skills (List<int> of skill ids, NO DTO), SkillPoints (int)
        b.WriteInt(63);
        b.WriteInt(3);  // Skills list count (Track A defines skills 1..8)
        b.WriteInt(1);  // owned skill ids
        b.WriteInt(2);
        b.WriteInt(3);
        b.WriteInt(InitialSkillPoints);  // SkillPoints = 10

        // Method 27 — DistanceTraveled (IntResponse: bool Result, int Param = total distance)
        b.WriteInt(M_DistanceTraveled);
        b.WriteByte(1);                    // Result
        b.WriteInt(TotalDistanceTraveled); // Param

        // Method 69 — GetBrewers
        // Constructor order: Success (bool), Brewers (List)
        b.WriteInt(69);
        b.WriteByte(1); // Success
        b.WriteInt(0);  // Brewers list count

        // Method 59 — GetAllFacts  (empty Dictionary<int, int> Facts — NO leading Success byte)
        // ServerFactDatabaseModule.InitializeModule (0x178A3D0, now un-bypassed in hook.js) synchronizes this
        // key; HandleGetAllFactsResponse (0x178A4E8) builds _factDatabase from it AND sets Initialized=true.
        // Without it: _factDatabase stays null -> PlayerModule.GetFact(4) NREs (froze boot at 76%), and SFDB
        // never flips Initialized -> boot hangs. Wire format verified via GetAllFactsResponse.Factory.Deserialize
        // (0x1F74664): just [int count] then [int key][int value] pairs. Empty = [int 0]. GetFact returns 0 for
        // a missing key (ContainsKey guard, no throw), so an empty fact DB is safe.
        b.WriteInt(59);
        b.WriteInt(1);  // Facts count
        b.WriteInt(2); b.WriteInt(1); // Fact 2 = 1

        // Method 83 — GetDailyShopBundles
        // Deserializer (0x1F75C80): [byte Success] [int count] [items...]
        b.WriteInt(83);
        b.WriteByte(1);
        b.WriteInt(0);

        // Method 79 — GetOneTimeShopBundles
        // Deserializer (0x1F7AFF8): [byte Success] [int count] [items...]
        b.WriteInt(79);
        b.WriteByte(1);
        b.WriteInt(0);

        // Method 91 — GetPlayerModifiers
        // Deserializer (0x1F7B160): [int unknown/status] [int count] [items...]
        b.WriteInt(91);
        b.WriteInt(0);
        b.WriteInt(0);

        // Method 70 — GetFinishedSeasonQuests
        // [int Season][int setN][set][int TrackedQuestId=-1][int listN][list]
        b.WriteInt(70);
        b.WriteInt(0);  // CurrentSeason
        b.WriteInt(0);  // setN
        b.WriteInt(-1);  // TrackedQuestId
        
        int numQuests = 300;
        b.WriteInt(numQuests);  // listN
        for(int i = 0; i < numQuests; i++) {
            b.WriteInt(i);
        }

        // Method 60 — GetActiveQuestNodeInstances — spawns the S00 tutorial quest-giver (Thorstein) near player.
        // Handler order (StoryModule 0x17A3614): UpdateLocations(Locations) registers PlaceId->coords, THEN
        // SetActiveQuestNodes(QuestNodeInstances) looks up PlaceId and positions the POI via CoordsToWorldSpace.
        //   Location wire (0x31D0B28):  [int placeIdLen][placeId][float lat][float lng][int biomeCount][int*biomes]
        //   QuestNodeInstance (0x31D1334): [long InstanceId][int QuestNodeId][string PlaceId]
        //                                  [string SettingsPath][string BehaviourGraphName][int DisplayMode]
        //   (all strings = WriteString = [int len][UTF8]; DisplayMode Normal=1)
        // Coords = player's center S2 cell decoded from the method-40 request (2026-07-05): 32.453864, 35.058088.
        b.WriteInt(60);
        b.WriteInt(1);                       // Locations count = 1
        b.WriteString(TutPlaceId);           // Location.PlaceId
        b.WriteFloat(TutLat);                // Location.Latitude
        b.WriteFloat(TutLng);                // Location.Longitude
        b.WriteInt(0);                       // Location.Biomes count = 0
        b.WriteInt(1);                       // QuestNodeInstances count = 1
        b.WriteLong(1);                      // InstanceId
        b.WriteInt(1);                       // QuestNodeId (spawn is independent of this; click needs StoryGraph)
        b.WriteString(TutPlaceId);           // QNI.PlaceId (must match the Location above)
        b.WriteString("assets/_bundledassets/story/poi_settings/_common/thorstein_lq.asset"); // SettingsPath
        b.WriteString("s00/prolog/prolog_01_thorstein"); // BehaviourGraphName; AssetsPaths.GetBehaviourGraphPath adds prefix/suffix
        b.WriteInt(2);                       // DisplayMode = CloseFollow (keeps the quest giver interactable)
        b.WriteInt(0);                       // ExpiringQuestNodeInstances count = 0

        // Method 20 — GetDailyContracts
        // [byte Success][int ignored][int CanAdd][int CanReshuffle][int count]
        b.WriteInt(M_GetDailyContracts);
        b.WriteByte(1); // Success
        b.WriteInt(0);  // ignored
        b.WriteInt(0);  // CanAdd = false
        b.WriteInt(0);  // CanReshuffle = false
        b.WriteInt(0);  // Contracts list count

        // Method 94 — GetWeeklyContractProgress
        // [byte Success][int LastStampAcquiredDate][int stampsCount][int*stamps]
        b.WriteInt(M_GetWeeklyContractProgress);
        b.WriteByte(1); // Success
        b.WriteInt(0);  // LastStampAcquiredDate
        b.WriteInt(0);  // Stamps list count

        // Method 43 — GetSensedMonsters
        // [byte Success][int count][long*sensedMonsters]
        b.WriteInt(M_GetSensedMonsters);
        b.WriteByte(1); // Success
        b.WriteInt(0);  // SensedMonsters list count

        // Method 56 — GetKilledMonsterInstances  (empty List<long>)
        // PoiModule.InitializeModule's final Subscribe fires OnGetKilledMonstersResponse, which
        // synchronizes THIS key; missing -> null Data -> NRE aborted PoiModule init (stuck at "Loading
        // Points of Interest", runtime 2026-07-05). Wire format verified via Factory.Deserialize
        // (0x1F7A7CC): just [int count] then [long*count]. Empty = [int 0].
        b.WriteInt(56);
        b.WriteInt(0);  // KilledMonsterInstances list count

        log.LogInformation("  BuildInitialPlayerData: 19 sub-responses, equipped id={Id}, gold=5000, exp=4500, tutorial ENABLED", equippedId);
        return b.ToArray();
    }

    // ── Post-boot Api response builders ─────────────────────────────────────────
    // Wire formats decoded from the dump.cs *Response classes (ctor field order = Serialize write order).
    // All return empty/default data so the client's response handler doesn't NRE and the response
    // timeout overlay ("Ожидание ответа сервера…") never fires.

    /// GetWeatherResponse: [int WeatherCode]. WeatherCode.Clear = 6.
    private static byte[] BuildGetWeatherResponse()
    {
        var b = new ByteBuffer();
        b.WriteInt(6);  // WeatherCode.Clear
        return b.ToArray();
    }

    /// GetLocationsByCellResponse: [byte Success][int locationMapCount][...][int monsterCount][...]
    /// [int herbCount][...][int questNodeCount][...][int nestCount][...].
    /// Empty = Success + five zero counts (the Deserialize reads Success then 5 list/dict counts).
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
    private static byte[] BuildGetFriendsResponse()
    {
        var b = new ByteBuffer();
        b.WriteLong(1L);  // CurrentPlayerId
        b.WriteInt(0);    // Friends list count
        b.WriteInt(0);    // PlayerStateChanges list count
        return b.ToArray();
    }

    /// GetFriendsNotificationsResponse: [byte Result][int receivedInvitesN][...][int sentAcceptedN][...]
    /// [int receivedPacksN][...][int stateChangesN][...].
    private static byte[] BuildGetFriendsNotificationsResponse()
    {
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

    /// GetWeeklyContractProgressResponse: [byte Success][int LastStampAcquiredDate][int stampsCount][int×count].
    /// Ctor: (bool success, int lastStampAcquiredDate, List<int> stamps).
    private static byte[] BuildGetWeeklyContractProgressResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success
        b.WriteInt(0);  // LastStampAcquiredDate
        b.WriteInt(0);  // Stamps list count
        return b.ToArray();
    }

    /// GetSensedMonstersResponse (Method 43): [byte Success][int count][long×count].
    private static byte[] BuildGetSensedMonstersResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success
        b.WriteInt(0);  // SensedMonsters list count
        return b.ToArray();
    }

    /// GetCurrentObjectiveResponse (Method 61): [byte Success][string CurrentObjective].
    /// Ctor: (bool success, string currentObjective). Empty objective = success + empty string.
    private static byte[] BuildGetCurrentObjectiveResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1);         // Success
        b.WriteString("");      // CurrentObjective (empty)
        return b.ToArray();
    }

    /// GetDailyShopBundlesResponse: [byte Success][int count][items...].
    private static byte[] BuildGetDailyShopBundlesResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success = true
        b.WriteInt(0);  // list count
        return b.ToArray();
    }

    /// GetOneTimeShopBundlesResponse: [byte Success][int count][items...].
    private static byte[] BuildGetOneTimeShopBundlesResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1); // Success = true
        b.WriteInt(0);  // list count
        return b.ToArray();
    }

    /// GetPlayerModifiersResponse: [int Result/Success][int count][items...].
    private static byte[] BuildGetPlayerModifiersResponse()
    {
        var b = new ByteBuffer();
        b.WriteInt(0);  // Success/Result = 0
        b.WriteInt(0);  // list count
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
        var b = new ByteBuffer();
        b.WriteByte(1);                    // Success
        b.WriteString("Geralt");           // Name
        b.WriteInt(5000);                  // Gold (ID contract)
        b.WriteInt(4500);                  // Exp ≈ level-5 threshold on Track A's level_ups curve
        b.WriteInt(1);                     // Head (id 1 = head_caucasian_1 in static data)
        b.WriteByte((byte)(cfg.GetValue("Player:TutorialFinished", false) ? 1 : 0));
        b.WriteByte(0);                    // Gender
        return b.ToArray();
    }

    /// GetInventoryResponse (Method 5): 9 empty Dictionary<int,int> maps + [int BagSize]. Shared by the
    /// 115 batch and the standalone re-sync.
    private static byte[] BuildGetInventoryPayload()
    {
        var b = new ByteBuffer();
        for (int i = 0; i < 9; i++) b.WriteInt(0);  // Ingredient/Bomb/Potion/Oil/Lure/Senses/Consumables/FriendsPacks/SummoningScrolls
        b.WriteInt(200);                            // BagSize
        return b.ToArray();
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

    /// EndBehaviourGraphResponse (Method 57, dump.cs 597848, TypeDefIndex 11557) — minimal valid reply.
    /// Members: bool Success, 7×Dict<int,int> (Potions, Bombs, Oils, Lures, SensesPotions,
    /// BestiaryEntries, Ingredients), List<int> Armors, List<int> Swords, int Exp, int Gold,
    /// List<Location> Locations, List<QuestNodeInstance> QuestNodeInstances,
    /// Dict<long,int> ExpiringQuestNodeInstances.
    /// CAVEAT: the dump's field order and its 15-arg ctor order DISAGREE, and Factory.Deserialize
    /// (0x31DE4BC) hasn't been disassembled — but with every dict/list empty and Exp=Gold=0, BOTH
    /// candidate orders serialize to the identical byte stream [byte 1][int 0 ×14], so this all-empty
    /// reply is valid under either layout. Real loot/exp grants need the read order byte-verified first
    /// (combat completion is a follow-up milestone).
    private static byte[] BuildEndBehaviourGraphResponse()
    {
        var b = new ByteBuffer();
        b.WriteByte(1);                              // Success
        for (int i = 0; i < 14; i++) b.WriteInt(0);  // 7 dicts + 2 int-lists + Exp + Gold + 2 DTO-lists + 1 dict, all empty/zero
        return b.ToArray();
    }

    /// GetFactsResponse (Method 58): [int count][...items]. Empty = [int 0].
    private static byte[] BuildGetFactsResponse()
    {
        var b = new ByteBuffer();
        b.WriteInt(0);  // Facts dictionary count
        return b.ToArray();
    }
    /// Catch-all for any unimplemented Method — replies with BooleanResponse(true) so the client's
    /// response timeout doesn't fire. If the client's Deserialize expects more data, it will read past
    /// the end and throw, but the exception is caught by the handler framework (same as any network error).
    /// The log line lets us identify which methods need explicit handlers in the future.
    private byte[] BuildCatchAllResponse(int method)
    {
        log.LogWarning("  Method {Method} not explicitly handled — sending BooleanResponse(true) catch-all", method);
        return ApiProtocol.Boolean(true);
    }

    /// Decode the auth request: [int MethodId][int apiVersion][long clientVersion][int len+deviceId][int len+accountId].
    private void DecodeAuthRequest(Frame f)
    {
        try
        {
            var b = new ByteBuffer(f.Data);
            int methodId = b.ReadInt();
            int apiVersion = b.ReadInt();
            long clientVersion = b.ReadLong();
            int devLen = b.ReadInt();
            string deviceId = System.Text.Encoding.UTF8.GetString(b.ReadBytes(devLen));
            int accLen = b.ReadInt();
            string accountId = accLen > 0 ? System.Text.Encoding.UTF8.GetString(b.ReadBytes(accLen)) : "(empty)";
            log.LogInformation("  auth: methodId={M} apiVersion={A} clientVersion={C} deviceId={D} accountId={Acc}",
                methodId, apiVersion, clientVersion, deviceId, accountId);
        }
        catch (Exception ex) { log.LogWarning("  auth decode failed: {Msg}", ex.Message); }
    }

    private static async Task<byte[]?> ReadExactAsync(Stream s, int n, CancellationToken ct)
    {
        var buf = new byte[n];
        int off = 0;
        while (off < n)
        {
            int r = await s.ReadAsync(buf.AsMemory(off, n - off), ct);
            if (r == 0) return null;
            off += r;
        }
        return buf;
    }

    private static string HexDump(byte[] data)
    {
        if (data.Length == 0) return "  (empty)";
        var sb = new StringBuilder();
        for (int i = 0; i < data.Length; i += 16)
        {
            int n = Math.Min(16, data.Length - i);
            sb.Append($"  {i:x4}  ");
            for (int j = 0; j < 16; j++) sb.Append(j < n ? data[i + j].ToString("x2") + " " : "   ");
            sb.Append(' ');
            for (int j = 0; j < n; j++) { byte c = data[i + j]; sb.Append(c is >= 32 and < 127 ? (char)c : '.'); }
            if (i + 16 < data.Length) sb.Append('\n');
        }
        return sb.ToString();
    }
}


