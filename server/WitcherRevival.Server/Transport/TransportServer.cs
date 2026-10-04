using System.Diagnostics;
using System.Net;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Transport;

/// <summary>Optional loopback WSS upstream. A dedicated TLS proxy authenticates with a private header.</summary>
public sealed class TransportServer(IConfiguration cfg, GameSocketService game, ILogger<TransportServer> log) : BackgroundService
{
    private readonly object gate = new();
    private readonly Dictionary<string, int> sessions = new();
    private int active;
    private double enrollmentTokens = 64;
    private long enrollmentTick = Stopwatch.GetTimestamp();

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        int port = cfg.GetValue("Transport:Port", 0);
        if (port == 0) return;
        if (port is < 1 or > 65535 || new[] { cfg.GetValue("Http:Port", 8080), cfg.GetValue("GameServer:Port", 4253),
            cfg.GetValue("Admin:Port", 0) }.Contains(port)) throw new InvalidOperationException("Transport requires a separate loopback port.");
        string host = cfg["Transport:PublicHost"] ?? throw new InvalidOperationException("Transport public host is required.");
        if (!Uri.TryCreate("https://" + host, UriKind.Absolute, out var uri) || uri.Authority != host ||
            uri.AbsolutePath != "/" || uri.UserInfo != "" || uri.Query != "" || uri.Fragment != "")
            throw new InvalidOperationException("Transport public host must be an HTTPS authority.");
        string staticUrl = cfg["Transport:StaticDataUrl"] ?? "https://" + host + "/staticdata";
        if (!Uri.TryCreate(staticUrl, UriKind.Absolute, out var staticUri) || staticUri.Scheme != "https" ||
            !staticUri.Authority.Equals(host, StringComparison.OrdinalIgnoreCase) || staticUri.AbsolutePath != "/staticdata" ||
            staticUri.UserInfo != "" || staticUri.Query != "" || staticUri.Fragment != "")
            throw new InvalidOperationException("Transport static data must use its configured HTTPS host.");
        string keyPath = cfg["Transport:ProxyKeyFile"] ?? throw new InvalidOperationException("Transport proxy key is required.");
        TransportRegistry.CheckParents(Path.GetDirectoryName(Path.GetFullPath(keyPath))!);
        TransportRegistry.CheckRegular(keyPath, privateFile: true);
        if (new FileInfo(keyPath).Length is < 32 or > 256) throw new InvalidOperationException("Invalid transport proxy key length.");
        string keyText = File.ReadAllText(keyPath).Trim();
        if (keyText.Length is < 32 or > 128 || keyText.Any(c => c < 33 || c > 126))
            throw new InvalidOperationException("Invalid transport proxy key format.");
        byte[] key = Encoding.ASCII.GetBytes(keyText);
        var store = new TransportRegistry(cfg["Transport:RegistryDirectory"] ?? throw new InvalidOperationException("Transport registry is required."),
            Bounded("Transport:PendingSeconds", 3600, 1, 86400));
        using var diagnostics = cfg["Transport:DiagnosticsDirectory"] is { Length: > 0 } diagnosticDirectory
            ? new TransportDiagnostics(diagnosticDirectory, key, log) : null;
        int firstSeconds = Bounded("Transport:FirstFrameSeconds", 10, 1, 30);
        int fragmentSeconds = Bounded("Transport:FragmentSeconds", 10, 1, 30);
        int idleSeconds = Bounded("Transport:IdleSeconds", 300, 30, 3600);
        int sessionSeconds = Bounded("Transport:SessionSeconds", 14400, 1, 86400);
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions { Args = [] });
        builder.Logging.ClearProviders();
        builder.WebHost.ConfigureKestrel(k =>
        {
            k.Listen(IPAddress.Loopback, port);
            k.Limits.MaxRequestBodySize = 0;
            k.Limits.MaxRequestHeadersTotalSize = 8192;
            k.Limits.MaxRequestLineSize = 1024;
            k.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(10);
            k.Limits.MaxConcurrentConnections = 64;
            k.Limits.MaxConcurrentUpgradedConnections = 32;
        });
        var app = builder.Build();
        app.UseWebSockets(new WebSocketOptions { KeepAliveInterval = TimeSpan.FromSeconds(20), KeepAliveTimeout = TimeSpan.FromSeconds(20) });
        app.Use(async (context, next) =>
        {
            context.Response.Headers.CacheControl = "no-store";
            context.Response.Headers["X-Content-Type-Options"] = "nosniff";
            // Never infer trust from X-Forwarded-For. Only the private proxy knows this credential,
            // overwrites these headers, terminates TLS, and chooses this dedicated loopback upstream.
            byte[] supplied = Encoding.UTF8.GetBytes(context.Request.Headers["X-Monster-Transport-Key"].ToString());
            bool trusted = context.Connection.RemoteIpAddress is { } remote && IPAddress.IsLoopback(remote) &&
                CryptographicOperations.FixedTimeEquals(key, supplied) &&
                context.Request.Headers["X-Forwarded-Proto"] == "https" &&
                string.Equals(context.Request.Host.Value, host, StringComparison.OrdinalIgnoreCase);
            CryptographicOperations.ZeroMemory(supplied);
            if (!trusted || context.Request.QueryString.HasValue || context.Request.Headers.ContainsKey("Origin"))
            { context.Response.StatusCode = 403; return; }
            try { await next(context); }
            catch (RegistryCapacityException) { if (!context.Response.HasStarted) context.Response.StatusCode = 429; }
            catch (Exception e) when (e is IOException or InvalidDataException or InvalidOperationException or UnauthorizedAccessException or System.Text.Json.JsonException)
            {
                log.LogWarning("Transport request refused type={Type}", e.GetType().Name);
                if (!context.Response.HasStarted) context.Response.StatusCode = 503;
                else context.Abort();
            }
        });
        app.MapPost("/transport/enroll", (HttpContext context) =>
        {
            if (context.Request.ContentLength is > 0 || context.Request.Headers.ContainsKey("Transfer-Encoding"))
                return Results.StatusCode(400);
            string? hash = TransportRegistry.HashBearer(context.Request.Headers.Authorization.ToString());
            if (hash is null) return Results.StatusCode(401);
            if (!IPAddress.TryParse(context.Request.Headers["X-Monster-Client-IP"].ToString(), out var source))
                return Results.StatusCode(403);
            if (!AllowEnrollment()) return Results.StatusCode(429);
            if (source.IsIPv4MappedToIPv6) source = source.MapToIPv4();
            byte[] address = source.GetAddressBytes();
            if (address.Length == 16) Array.Clear(address, 8, 8); // One IPv6 /64 cannot fill the invitation queue.
            string sourceKey = "transport-enrollment-source-v1\n" + Convert.ToHexString(address);
            string sourceHash = Convert.ToHexString(HMACSHA256.HashData(key, Encoding.ASCII.GetBytes(sourceKey))).ToLowerInvariant();
            return Results.Json(store.Enroll(hash, sourceHash));
        });
        app.MapPost("/transport/diagnostics", async (HttpContext context) =>
        {
            if (diagnostics is null) { context.Response.StatusCode = 404; return; }
            await diagnostics.Receive(context, store);
        });
        app.MapGet("/transport/game", async (HttpContext context) =>
        {
            string? hash = TransportRegistry.HashBearer(context.Request.Headers.Authorization.ToString());
            if (hash is null) { context.Response.StatusCode = 401; return; }
            if (!context.WebSockets.IsWebSocketRequest) { context.Response.StatusCode = 400; return; }
            var approved = store.Approved(hash);
            if (approved?.Profile is not { } profile) { context.Response.StatusCode = 403; return; }
            if (!Acquire(hash)) { context.Response.StatusCode = 429; return; }
            try
            {
                using var socket = await context.WebSockets.AcceptWebSocketAsync();
                using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, context.RequestAborted);
                lifetime.CancelAfter(TimeSpan.FromSeconds(sessionSeconds));
                Task monitor = MonitorApproval(store, hash, profile, approved.BindingRevision, lifetime);
                try
                {
                    await using var stream = new GameWebSocketStream(socket, firstSeconds, fragmentSeconds, idleSeconds);
                    await game.HandleTransportAsync(stream, profile, staticUrl, lifetime.Token);
                }
                catch (Exception e) when (e is OperationCanceledException or WebSocketException or IOException)
                { log.LogInformation("Transport session ended type={Type}", e.GetType().Name); }
                finally
                {
                    await lifetime.CancelAsync();
                    await monitor;
                    // Abort avoids an unbounded close handshake with an unresponsive peer.
                    socket.Abort();
                }
            }
            finally { Release(hash); }
        });
        await app.StartAsync(stoppingToken);
        log.LogInformation("Approved transport listener ready on loopback port {Port}", port);
        try { await Task.Delay(Timeout.Infinite, stoppingToken); }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
        finally
        {
            await app.StopAsync(CancellationToken.None);
            await app.DisposeAsync();
            CryptographicOperations.ZeroMemory(key);
        }
    }

    private static async Task MonitorApproval(TransportRegistry store, string hash, string profile, long bindingRevision, CancellationTokenSource lifetime)
    {
        try
        {
            while (!lifetime.IsCancellationRequested)
            {
                var current = store.Approved(hash);
                if (current?.Profile != profile || current.BindingRevision != bindingRevision) { await lifetime.CancelAsync(); return; }
                await Task.Delay(1000, lifetime.Token);
            }
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        catch { await lifetime.CancelAsync(); } // An unreadable registry revokes access until repaired.
    }

    private int Bounded(string name, int fallback, int low, int high)
    {
        int value = cfg.GetValue(name, fallback);
        if (value < low || value > high) throw new InvalidOperationException("Invalid transport timing bound.");
        return value;
    }
    private bool AllowEnrollment()
    {
        lock (gate)
        {
            long now = Stopwatch.GetTimestamp();
            enrollmentTokens = Math.Min(64, enrollmentTokens + Stopwatch.GetElapsedTime(enrollmentTick, now).TotalSeconds);
            enrollmentTick = now;
            if (enrollmentTokens < 1) return false;
            enrollmentTokens--; return true;
        }
    }
    private bool Acquire(string hash)
    {
        lock (gate)
        {
            if (active >= 32 || sessions.GetValueOrDefault(hash) >= 2) return false;
            active++; sessions[hash] = sessions.GetValueOrDefault(hash) + 1; return true;
        }
    }
    private void Release(string hash)
    {
        lock (gate)
        {
            active--;
            int count = sessions[hash] - 1;
            if (count == 0) sessions.Remove(hash); else sessions[hash] = count;
        }
    }
}
