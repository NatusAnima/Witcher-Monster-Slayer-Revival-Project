using System.Net;
using System.Net.Sockets;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The game socket: accepts local sessions, reads frames, answers authentication and static data, and hands every API
/// request of an authenticated session to its player's PlayerService (ProfileRegistry). Authentication bodies and
/// account/device identifiers are never logged.
/// </summary>
public sealed class GameSocketService(ILogger<GameSocketService> log, IConfiguration cfg, ProfileRegistry registry,
    StaticDataSnapshot staticData) : BackgroundService
{
    private readonly int _port = cfg.GetValue("GameServer:Port", 4253);
    private long _nextSessionId;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        if (_port is < 1 or > 65535) throw new InvalidOperationException("GameServer:Port is outside 1..65535.");
        var listener = new TcpListener(IPAddress.Loopback, _port);
        listener.Start();
        log.LogInformation("Game socket listening on 127.0.0.1:{Port}", _port);
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
        using (client)
        await using (var stream = client.GetStream())
            await HandleSessionAsync(stream, null, null, ct);
    }

    // Only the transport listener calls this after authenticating an approved installation.
    // Its immutable server-selected profile replaces the legacy, self-asserted identity lookup.
    public Task HandleTransportAsync(Stream stream, string profileId, string staticDataUrl, CancellationToken ct)
    {
        LocalProfileStore.CheckProfileId(profileId);
        return HandleSessionAsync(stream, profileId, staticDataUrl, ct);
    }

    private async Task HandleSessionAsync(Stream stream, string? boundProfile, string? transportStaticUrl, CancellationToken ct)
    {
        var ep = boundProfile is null ? "local-session" : "approved-transport";
        long sessionId = Interlocked.Increment(ref _nextSessionId);
        log.LogInformation("Client connected: {EP} session={Session}", ep, sessionId);
        void ObserveRead(FrameReadStage stage, int expected, int received, bool complete) =>
            log.LogInformation("TCP read session={Session} stage={Stage} expected={Expected} received={Received} outcome={Outcome}",
                sessionId, stage.ToString().ToLowerInvariant(), expected, received, complete ? "complete" : "eof");
        IDisposable? profileLease = null;
        PlayerService? player = null;
        Guid movementSession = Guid.Empty;
        try
        {
            {
                // The client (ThreadedClient) prepends the 4-byte magic 0x9043284A (SECRET_BYTES) to
                // EVERY outgoing message, then a SocketMessageFactory frame [1B type][4B BE size][payload].
                // The server does NOT prepend magic on replies (client's TryDeserialize doesn't expect it).
                while (!ct.IsCancellationRequested)
                {
                    var magic = await ReadExactAsync(stream, 4, ct, ObserveRead);
                    if (magic is null) break;
                    if (!magic.AsSpan().SequenceEqual(PreloaderStaticData.Magic))
                    {
                        log.LogWarning("Invalid frame marker; closing local session.");
                        break;
                    }
                    var frame = await FrameCodec.ReadAsync(stream, ct, ObserveRead);
                    if (frame is null) break;
                    var f = frame.Value;
                    log.LogInformation("RX channel={Type} bytes={Len}", f.Type, f.Data.Length);
                    if (f.Type == Ch_Auth)
                    {
                        string profileId = Authenticate(f, boundProfile);
                        player?.ReleaseMovementSession(movementSession);
                        profileLease?.Dispose();
                        movementSession = Guid.NewGuid();
                        (player, profileLease) = registry.Connect(profileId);
                        if (boundProfile is null) log.LogInformation("Session authenticated session={Session} profile={Profile}", sessionId, profileId);
                        else log.LogInformation("Approved transport authenticated session={Session}", sessionId);
                    }
                    else if (player is null && (boundProfile is not null || f.Type != Ch_StaticGameData)) throw new InvalidDataException("Authentication is required for this session.");
                    await DispatchAsync(stream, f, player, movementSession, transportStaticUrl, ct);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            log.LogWarning("Local session closed: {ErrorType}", ex.GetType().Name);
        }
        finally { player?.ReleaseMovementSession(movementSession); profileLease?.Dispose(); log.LogInformation("Client disconnected: {EP} session={Session}", ep, sessionId); }
    }

    // Outer channel type bytes, confirmed from ApiBuilder.CreateHandler key registrations.
    private const byte Ch_Api = 1, Ch_Logging = 2, Ch_Auth = 3, Ch_StaticGameData = 4;

    private static string ChannelName(byte t) => t switch
    {
        Ch_Api => "Api", Ch_Logging => "Logging", Ch_Auth => "Authentication",
        Ch_StaticGameData => "StaticGameData", _ => "?"
    };

    private async Task DispatchAsync(Stream stream, Frame f, PlayerService? player, Guid movementSession, string? transportStaticUrl, CancellationToken ct)
    {
        switch (f.Type)
        {
            case Ch_Auth:
                // Reply on the Authentication channel: inner Message = [int MethodId=AUTHENTICATE(1)][byte code].
                // AuthenticationHandler reads one byte; code 0 => Success=true (see protocol-boot.md §6).
                var auth = new ByteBuffer();
                auth.WriteInt(1);          // inner MethodId = AUTHENTICATE
                auth.WriteByte(0);         // code 0 = success
                await FrameCodec.WriteAsync(stream, Ch_Auth, auth.ToArray(), ct);
                log.LogInformation("TX  Authentication OK (Success=true, ErrCode=0)");
                break;

            case Ch_StaticGameData:
                await HandleStaticGameDataAsync(stream, f, transportStaticUrl, ct);
                break;

            case Ch_Api:
                await player!.HandleApiAsync(stream, f, ct, movementSession);
                break;

            case Ch_Logging:
                break; // discard without logging client content
            default:
                throw new NotSupportedException("Unsupported socket channel.");
        }
    }

    // StaticGameData channel (type 4): StaticGameDataMessage = [int MethodId][Data]. TypeId FETCH=1, GET_DATA_URL=2.
    private const int SGD_Fetch = 1, SGD_GetDataUrl = 2;

    private async Task HandleStaticGameDataAsync(Stream stream, Frame f, string? transportStaticUrl, CancellationToken ct)
    {
        int methodId;
        try { methodId = new ByteBuffer(f.Data).ReadInt(); }
        catch { log.LogWarning("  StaticGameData parse failed"); return; }

        if (methodId == SGD_GetDataUrl)
        {
            // CdnPreloader downloads this URL, GZip-decompresses, DataContractJson -> Container.
            // Http:AdvertisedHost names the address the phone reaches the HTTP port on (the WireGuard relay
            // for LAB 16); the server itself still listens on loopback only.
            var resp = new ByteBuffer();
            resp.WriteInt(SGD_GetDataUrl);   // echo MethodId (GET_DATA_URL)
            resp.WriteString(transportStaticUrl ?? staticData.Url); // GetStaticDataUrlResponse.StaticDataUrl
            await FrameCodec.WriteAsync(stream, Ch_StaticGameData, resp.ToArray(), ct);
            log.LogInformation("TX StaticGameData GET_DATA_URL (local prototype)");
        }
        else if (methodId == SGD_Fetch)
        {
            // FetchStaticGameDataResponse = [int len][gzip bytes] (inline).
            byte[] gz = staticData.Gzip;
            var resp = new ByteBuffer();
            resp.WriteInt(SGD_Fetch);
            resp.WriteInt(gz.Length);
            resp.WriteBytes(gz);
            await FrameCodec.WriteAsync(stream, Ch_StaticGameData, resp.ToArray(), ct);
            log.LogInformation("  TX  StaticGameData FETCH inline ({Len}B gzip)", gz.Length);
        }
        else throw new NotSupportedException("Unsupported static data method.");
    }

    /// <summary>Validate the native authentication envelope. Private TCP resolves its identifiers;
    /// approved transport sessions always retain their bound profile. Identifier bytes are cleared afterwards.</summary>
    private string Authenticate(Frame frame, string? boundProfile)
    {
        var b = new ByteBuffer(frame.Data);
        // 1.1.116 ClientWorker.Run passes apiVersion=25 to WriteAuthenticationRequest
        // (own ELF RVA 0x1931308 / 0x1931318); see connection/auth-layout-review/.
        const int supportedClientApiVersion = 25;
        if (b.ReadInt() != 1) throw new InvalidDataException("Unsupported local auth method.");
        if (b.ReadInt() != supportedClientApiVersion) throw new InvalidDataException("Unsupported local auth API version.");
        b.ReadLong(); // client version: never used to imply compatibility
        var identifiers = new byte[2][];   // deviceId, accountId (BuildAuthenticationRequest 0x193218C)
        try
        {
            for (int i = 0; i < 2; i++)
            {
                int length = b.ReadInt();
                if (length < 0 || length > 4096) throw new InvalidDataException("Invalid identifier length.");
                identifiers[i] = b.ReadBytes(length); // never decoded, persisted or logged
            }
            if (b.RemainingToRead != 0) throw new InvalidDataException("Unexpected auth fields.");
            if (identifiers[0].Length == 0 && identifiers[1].Length == 0) throw new InvalidDataException("No player identifier.");
            return boundProfile ?? registry.Resolve(identifiers[0], identifiers[1]);
        }
        finally
        {
            foreach (var identifier in identifiers) if (identifier is not null) Array.Clear(identifier);
            Array.Clear(frame.Data);
        }
    }

    private static async Task<byte[]?> ReadExactAsync(Stream s, int n, CancellationToken ct,
        Action<FrameReadStage, int, int, bool> observe)
    {
        var buf = new byte[n];
        int off = 0;
        while (off < n)
        {
            int r = await s.ReadAsync(buf.AsMemory(off, n - off), ct);
            if (r == 0)
            {
                observe(FrameReadStage.Magic, n, off, false);
                return null;
            }
            off += r;
        }
        observe(FrameReadStage.Magic, n, off, true);
        return buf;
    }
}
