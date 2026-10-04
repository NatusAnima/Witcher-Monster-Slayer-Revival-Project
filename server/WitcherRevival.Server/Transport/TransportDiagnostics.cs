using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Http.Features;

namespace WitcherRevival.Server.Transport;

/// <summary>Opt-in, bounded diagnostic events. No game data or client-supplied text is retained.</summary>
public sealed class TransportDiagnostics : IDisposable
{
    public const int BodyLimit = 8192, FileLimit = 256 * 1024;
    private const long MaxMilliseconds = 30L * 24 * 60 * 60 * 1000;
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private static readonly HashSet<string> Fields = ["schemaVersion", "event", "uptimeMs", "clientBuild",
        "foreground", "nativeHeartbeatAgeMs", "gpsSampleAgeMs", "gpsAckAgeMs", "retryState", "sessionGeneration"];
    private static readonly HashSet<string> Events = ["client-start", "heartbeat", "foreground", "background",
        "transport-lost", "transport-authenticated", "retry-requested", "retry-ready", "retry-failed",
        "native-stale", "native-recovered", "gps-stale", "gps-recovered", "gps-ack-stale", "gps-ack-recovered", "client-stop"];
    private static readonly HashSet<string> RetryStates = ["idle", "waiting", "ready", "running", "blocked", "unavailable"];
    public sealed record DiagnosticEvent(int SchemaVersion, string Event, long UptimeMs, int ClientBuild,
        bool Foreground, long NativeHeartbeatAgeMs, long GpsSampleAgeMs, long GpsAckAgeMs,
        string RetryState, int SessionGeneration);
    private sealed record StoredEvent(long ReceivedAt, string Installation, DiagnosticEvent Diagnostic);
    private sealed class Bucket { public double Tokens = 4; public long Tick = Stopwatch.GetTimestamp(); }
    private readonly object gate = new();
    private readonly Dictionary<string, Bucket> buckets = new();
    private readonly string current, previous;
    private readonly byte[] key;
    private readonly FileStream held;
    private readonly ILogger log;
    private double globalTokens = 16;
    private long globalTick = Stopwatch.GetTimestamp(), accepted, refused;
    private int reading;

    public TransportDiagnostics(string directory, byte[] proxyKey, ILogger log)
    {
        this.log = log;
        directory = Path.GetFullPath(directory);
        TransportRegistry.CheckParents(directory);
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(directory);
        else Directory.CreateDirectory(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        if (!OperatingSystem.IsWindows() && (File.GetUnixFileMode(directory) & (UnixFileMode.GroupRead |
            UnixFileMode.GroupWrite | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherWrite |
            UnixFileMode.OtherExecute)) != 0) throw new InvalidOperationException("Diagnostics directory must be private.");
        current = Path.Combine(directory, "diagnostics-current.ndjson");
        previous = Path.Combine(directory, "diagnostics-previous.ndjson");
        string lockPath = Path.Combine(directory, "diagnostics.lock");
        if (new FileInfo(lockPath).LinkTarget is not null) throw new InvalidOperationException("Symlink diagnostics lock refused.");
        if (File.Exists(lockPath)) TransportRegistry.CheckRegular(lockPath, privateFile: true);
        held = new FileStream(lockPath, Options(FileMode.OpenOrCreate, FileShare.None));
        try { CheckLog(current); CheckLog(previous); }
        catch { held.Dispose(); throw; }
        key = proxyKey.ToArray();
    }

    public async Task Receive(HttpContext context, TransportRegistry registry)
    {
        string? hash = TransportRegistry.HashBearer(context.Request.Headers.Authorization.ToString());
        if (hash is null) { Refuse(context, 401); return; }
        if (registry.Approved(hash) is null) { Refuse(context, 403); return; }
        if (context.Request.ContentLength is null || context.Request.Headers.ContainsKey("Transfer-Encoding"))
        { Refuse(context, 400); return; }
        long length = context.Request.ContentLength.Value;
        if (length > BodyLimit) { Refuse(context, 413); return; }
        if (length <= 0) { Refuse(context, 400); return; }
        if (!string.Equals(context.Request.ContentType, "application/json", StringComparison.OrdinalIgnoreCase) ||
            context.Request.Headers.ContainsKey("Content-Encoding")) { Refuse(context, 415); return; }
        if (!Acquire(hash)) { Refuse(context, 429); return; }
        try
        {
            // Other transport routes keep their zero-body default. Set this before the first read.
            var limit = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (limit is null || limit.IsReadOnly) { Refuse(context, 503); return; }
            limit.MaxRequestBodySize = BodyLimit;
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(context.RequestAborted);
            deadline.CancelAfter(TimeSpan.FromSeconds(3));
            byte[] body = new byte[(int)length];
            int offset = 0;
            try
            {
                while (offset < body.Length)
                {
                    int count = await context.Request.Body.ReadAsync(body.AsMemory(offset), deadline.Token);
                    if (count == 0) { Refuse(context, 400); return; }
                    offset += count;
                }
                DiagnosticEvent diagnostic;
                try { diagnostic = Parse(body); }
                catch (JsonException) { Refuse(context, 400); return; }
                // Revocation/expiry while receiving a slow body also refuses persistence.
                if (registry.Approved(hash) is null) { Refuse(context, 403); return; }
                Append(hash, diagnostic);
                context.Response.StatusCode = 204;
            }
            catch (OperationCanceledException) when (deadline.IsCancellationRequested)
            { Refuse(context, 408); }
            finally { CryptographicOperations.ZeroMemory(body); }
        }
        finally { lock (gate) reading--; }
    }

    public static DiagnosticEvent Parse(ReadOnlyMemory<byte> body)
    {
        using var doc = JsonDocument.Parse(body, new JsonDocumentOptions { MaxDepth = 2 });
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object) throw new JsonException("Invalid diagnostics schema.");
        HashSet<string> seen = [];
        foreach (var item in root.EnumerateObject())
            if (!Fields.Contains(item.Name) || !seen.Add(item.Name)) throw new JsonException("Invalid diagnostics fields.");
        if (seen.Count != Fields.Count) throw new JsonException("Incomplete diagnostics schema.");
        long Number(string name, long min, long max)
        {
            var value = root.GetProperty(name);
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out long number) || number < min || number > max)
                throw new JsonException("Invalid diagnostics number.");
            return number;
        }
        string Code(string name, HashSet<string> allowed)
        {
            var value = root.GetProperty(name);
            if (value.ValueKind != JsonValueKind.String || value.GetString() is not { } code || !allowed.Contains(code))
                throw new JsonException("Invalid diagnostics code.");
            return code;
        }
        var foreground = root.GetProperty("foreground");
        if (foreground.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new JsonException("Invalid foreground flag.");
        return new((int)Number("schemaVersion", 1, 1), Code("event", Events), Number("uptimeMs", 0, MaxMilliseconds),
            (int)Number("clientBuild", 1, 999999), foreground.GetBoolean(), Number("nativeHeartbeatAgeMs", -1, MaxMilliseconds),
            Number("gpsSampleAgeMs", -1, MaxMilliseconds), Number("gpsAckAgeMs", -1, MaxMilliseconds),
            Code("retryState", RetryStates), (int)Number("sessionGeneration", 0, int.MaxValue));
    }

    private bool Acquire(string hash)
    {
        lock (gate)
        {
            long now = Stopwatch.GetTimestamp();
            globalTokens = Math.Min(16, globalTokens + Stopwatch.GetElapsedTime(globalTick, now).TotalSeconds * 4);
            globalTick = now;
            if (reading >= 4 || globalTokens < 1) return false;
            if (!buckets.TryGetValue(hash, out var bucket))
            {
                // Registry has at most 4096 entries, and hashes here come only from current approvals.
                if (buckets.Count >= 4096) return false;
                buckets[hash] = bucket = new();
            }
            bucket.Tokens = Math.Min(4, bucket.Tokens + Stopwatch.GetElapsedTime(bucket.Tick, now).TotalSeconds / 5);
            bucket.Tick = now;
            if (bucket.Tokens < 1) return false;
            bucket.Tokens--; globalTokens--; reading++; return true;
        }
    }

    private void Append(string hash, DiagnosticEvent diagnostic)
    {
        byte[] name = Encoding.ASCII.GetBytes("transport-diagnostics-installation-v1\n" + hash);
        string installation = Convert.ToHexString(HMACSHA256.HashData(key, name)).ToLowerInvariant()[..32];
        byte[] line = JsonSerializer.SerializeToUtf8Bytes(new StoredEvent(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), installation, diagnostic), Json);
        lock (gate)
        {
            CheckLog(current); CheckLog(previous);
            if (File.Exists(current) && new FileInfo(current).Length + line.Length + 1 > FileLimit)
            {
                if (File.Exists(previous)) File.Delete(previous);
                File.Move(current, previous);
            }
            using var output = new FileStream(current, Options(FileMode.Append, FileShare.Read));
            output.Write(line); output.WriteByte((byte)'\n'); output.Flush();
            accepted++;
        }
    }

    private void Refuse(HttpContext context, int status)
    {
        lock (gate) refused++;
        context.Response.StatusCode = status;
        if (status == 429) context.Response.Headers.RetryAfter = "5";
    }
    private static void CheckLog(string path)
    {
        if (new FileInfo(path).LinkTarget is not null) throw new InvalidOperationException("Symlink diagnostics file refused.");
        if (!File.Exists(path)) return;
        TransportRegistry.CheckRegular(path, privateFile: true);
        if (new FileInfo(path).Length > FileLimit) throw new InvalidDataException("Diagnostics file exceeds its bound.");
    }
    private static FileStreamOptions Options(FileMode mode, FileShare share)
    {
        var options = new FileStreamOptions { Mode = mode, Access = mode == FileMode.Append ? FileAccess.Write : FileAccess.ReadWrite, Share = share };
        if (!OperatingSystem.IsWindows()) options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        return options;
    }
    public void Dispose()
    {
        held.Dispose(); CryptographicOperations.ZeroMemory(key);
        log.LogInformation("Transport diagnostics stopped accepted={Accepted} refused={Refused}", accepted, refused);
    }
}
