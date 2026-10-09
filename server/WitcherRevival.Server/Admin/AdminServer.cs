using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

/// <summary>Optional operator listener, isolated from the game HTTP routes and bound only to loopback.
/// A protected reverse proxy supplies the credential; it must authenticate the human independently.</summary>
public sealed partial class AdminServer(IConfiguration cfg, ProfileRegistry registry, TaskCatalog tasks,
    WorldPolicy world, WorldWeather weather, StaticDataSnapshot staticData, NewsFeed news, ILogger<AdminServer> log) : BackgroundService
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    { WriteIndented = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow };
    private static readonly Regex Language = new("^[a-z]{2,3}(?:-[a-z]{2,4})?$", RegexOptions.CultureInvariant);
    private static readonly Regex ImageName = new("^[A-Za-z0-9_-]{1,64}\\.(png|jpg|jpeg)$", RegexOptions.CultureInvariant);
    private readonly object gate = new();
    private readonly ServerMetrics metrics = new();
    private string root = "", origin = "", newsRoot = "", taskRoot = "", worldRoot = "";
    private byte[] key = [];
    private sealed class Refusal(int status, string message) : Exception(message) { public int Status => status; }
    public sealed record DocumentWrite(string Revision, JsonElement Document);
    public sealed record ProfileWrite(long Revision, string Action, string Confirm, string? Source = null,
        long? SourceRevision = null, long Seconds = 0, string? Backup = null);
    public sealed record Receipt(string Id, string At, string Action, string Target, string Outcome,
        string? Before = null, string? After = null, string? Effect = null);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        int port = cfg.GetValue("Admin:Port", 0);
        if (port == 0) return;
        if (port is < 1 or > 65535 || port == cfg.GetValue("Http:Port", 8080) || port == cfg.GetValue("GameServer:Port", 4253))
            throw new InvalidOperationException("Admin:Port must be a separate valid port.");
        origin = cfg["Admin:Origin"]?.TrimEnd('/') ?? "";
        if (!Uri.TryCreate(origin, UriKind.Absolute, out var uri) || uri.AbsolutePath != "/" || uri.Query.Length != 0 ||
            uri.Fragment.Length != 0 || uri.UserInfo.Length != 0 || !(uri.Scheme == "https" || uri.Scheme == "http" && uri.IsLoopback))
            throw new InvalidOperationException("Admin:Origin must be an HTTPS origin (HTTP allowed only on loopback).");
        string keyPath = cfg["Admin:KeyFile"] ?? throw new InvalidOperationException("Admin:KeyFile is required.");
        if (new FileInfo(keyPath).Length is < 32 or > 256) throw new InvalidOperationException("Invalid admin proxy key file.");
        key = Encoding.UTF8.GetBytes(File.ReadAllText(keyPath).Trim());
        if (key.Length < 32 || key.Any(b => b < 33 || b > 126)) throw new InvalidOperationException("Invalid admin proxy key format.");
        root = LocalProfileStore.PrepareDirectory(cfg["Admin:DataDirectory"] ?? throw new InvalidOperationException("Admin:DataDirectory is required."));
        newsRoot = Path.GetFullPath(cfg["News:Directory"] ?? Path.Combine(AppContext.BaseDirectory, "news"));
        taskRoot = Path.GetFullPath(cfg["Tasks:Directory"] ?? Path.Combine(AppContext.BaseDirectory, "tasks"));
        worldRoot = Path.GetFullPath(cfg["World:Directory"] ?? throw new InvalidOperationException("Admin requires World:Directory."));
        Directory.CreateDirectory(Path.Combine(root, "receipts"));
        Directory.CreateDirectory(Path.Combine(root, "backups"));
        Directory.CreateDirectory(Path.Combine(root, "staged"));
        LocalProfileStore.PrepareDirectory(Path.Combine(root, "profile-labels"));
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions { Args = [] });
        builder.Logging.ClearProviders();
        builder.WebHost.ConfigureKestrel(k => { k.Listen(IPAddress.Loopback, port); k.Limits.MaxRequestBodySize = 3 * 1024 * 1024; });
        var app = builder.Build();
        app.Use(async (context, next) =>
        {
            context.Response.Headers.CacheControl = "no-store";
            context.Response.Headers["X-Content-Type-Options"] = "nosniff";
            context.Response.Headers["Referrer-Policy"] = "no-referrer";
            context.Response.Headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
            // A proxy injects the header; the phone companion's in-app browser holds the key as a cookie instead.
            string presented = context.Request.Headers["X-Monster-Admin-Key"].ToString();
            byte[] supplied = Encoding.UTF8.GetBytes(presented.Length > 0 ? presented : context.Request.Cookies["monster-admin-key"] ?? "");
            if (!CryptographicOperations.FixedTimeEquals(key, supplied))
            { context.Response.StatusCode = 403; await context.Response.WriteAsJsonAsync(new { error = "Operator access is required." }); return; }
            if (context.Request.Method is not ("GET" or "HEAD") &&
                (context.Request.Headers.Origin != origin || context.Request.Headers["X-Requested-With"] != "MonsterSlayerAdmin"))
            { context.Response.StatusCode = 403; await context.Response.WriteAsJsonAsync(new { error = "Open the panel at its configured origin before saving." }); return; }
            try { await next(context); }
            catch (Refusal e) { context.Response.StatusCode = e.Status; await context.Response.WriteAsJsonAsync(new { error = e.Message }); }
            catch (Exception e) when (e is JsonException or InvalidDataException or ArgumentException or OverflowException or BadHttpRequestException)
            { context.Response.StatusCode = 400; await context.Response.WriteAsJsonAsync(new { error = "The proposed data does not match the game schema. No change was accepted." }); }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or InvalidOperationException)
            { log.LogWarning("Admin request failed; type={Type}", e.GetType().Name); context.Response.StatusCode = 409; await context.Response.WriteAsJsonAsync(new { error = "The operation could not complete. Refresh its state and inspect the receipt before retrying." }); }
        });
        app.MapGet("/", () => Asset("index.html", "text/html; charset=utf-8"));
        app.MapGet("/app.js", () => Asset("app.js", "text/javascript; charset=utf-8"));
        app.MapGet("/transport.js", () => Asset("transport.js", "text/javascript; charset=utf-8"));
        app.MapGet("/engine.js", () => Asset("engine.js", "text/javascript; charset=utf-8"));
        app.MapGet("/i18n.js", () => Asset("i18n.js", "text/javascript; charset=utf-8"));
        foreach (string language in new[] { "pl", "en", "es", "fr", "de", "uk", "hu", "cs", "sl", "sk" })
            app.MapGet($"/lang-{language}.json", () => Asset($"lang-{language}.json", "application/json; charset=utf-8"));
        app.MapGet("/favicon.svg", () => Asset("favicon.svg", "image/svg+xml"));
        app.MapGet("/style.css", () => Asset("style.css", "text/css; charset=utf-8"));
        app.MapGet("/api/overview", Overview);
        app.MapGet("/api/server/status", () => Results.Json(metrics.Read()));
        MapOperatorRoutes(app);
        MapPlacementRoutes(app);
        MapTuningRoutes(app);
        MapTransportRoutes(app);
        MapPlayerProgressRoutes(app);
        app.MapGet("/api/profiles", () => Results.Json(registry.Saved().Select(id => ProfileSummary(id))));
        app.MapPost("/api/profiles/{id}", async (string id, HttpRequest request) => ChangeProfile(id, await Body<ProfileWrite>(request)));
        app.MapGet("/api/news/{language}", (string language) => { CheckLanguage(language); return Results.Json(ReadDocument(Path.Combine(newsRoot, language + ".json"),
            JsonSerializer.SerializeToUtf8Bytes(new NewsContainer { NewsList = [], HighlightedId = 0 }, Json))); });
        app.MapPut("/api/news/{language}", WriteNews);
        app.MapGet("/api/images", () => Results.Json(Directory.Exists(Path.Combine(newsRoot, "images"))
            ? Directory.EnumerateFiles(Path.Combine(newsRoot, "images")).Select(Path.GetFileName).Where(n => n is not null && ImageName.IsMatch(n)).Order().ToArray() : []));
        app.MapPut("/api/images/{name}", async (string name, HttpRequest request) =>
        {
            if (!ImageName.IsMatch(name)) throw new Refusal(400, "Use a short PNG or JPEG filename.");
            byte[] bytes = await Bytes(request, 2 * 1024 * 1024);
            if (!ValidImage(name, bytes)) throw new Refusal(400, "Upload a PNG or JPEG image, at most 4096 × 4096 pixels and 2 MiB.");
            Directory.CreateDirectory(Path.Combine(newsRoot, "images"));
            return SaveDocument(Path.Combine(newsRoot, "images", name), request.Headers.IfMatch.ToString(), bytes,
                "image", name, "The cover is available to news entries that use this filename.");
        });
        app.MapGet("/api/tasks", () => Results.Json(new
        {
            daily = ReadDocument(Path.Combine(taskRoot, "daily.json")), hunt = ReadDocument(Path.Combine(taskRoot, "hunt.json")),
            timed = ReadDocument(Path.Combine(taskRoot, "timed.json")), trinkets = ReadDocument(Path.Combine(taskRoot, "trinkets.json")),
            catalogue = new { revision = Digest(JsonSerializer.SerializeToUtf8Bytes(tasks.Current, TaskCatalog.Json)),
                document = JsonSerializer.SerializeToElement(tasks.Current, TaskCatalog.Json) },
            staged = Directory.EnumerateDirectories(Path.Combine(root, "staged")).Select(Path.GetFileName).Order().ToArray(),
        }));
        app.MapPut("/api/tasks/{kind}", async (string kind, HttpRequest request) => ChangeTasks(kind, await Body<DocumentWrite>(request)));
        app.MapGet("/api/world", WorldSettings);
        app.MapPut("/api/world", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            var settings = write.Document.Deserialize<WorldPolicy.Settings>(WorldPolicy.Json) ?? throw new InvalidDataException();
            WorldPolicy.Validate(settings);
            Directory.CreateDirectory(worldRoot);
            return SaveDocument(Path.Combine(worldRoot, "world.json"), write.Revision, JsonSerializer.SerializeToUtf8Bytes(settings, WorldPolicy.Json),
                "world", "monster-density", "New map requests use the setting after at most one second. Loaded cells may wait for the client refresh; baseline encounters retain their identities.");
        });
        app.MapGet("/api/receipts", () => Results.Json(Directory.EnumerateFiles(Path.Combine(root, "receipts"), "*.json")
            .OrderDescending().Take(30).Select(p => JsonSerializer.Deserialize<Receipt>(File.ReadAllBytes(p), Json))));
        await app.StartAsync(stoppingToken);
        log.LogInformation("Operator listener ready on loopback port {Port}; external authentication is delegated to the protected proxy", port);
        try { await Task.Delay(Timeout.InfiniteTimeSpan, stoppingToken); }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
        finally { await app.StopAsync(CancellationToken.None); await app.DisposeAsync(); CryptographicOperations.ZeroMemory(key); }
    }

    private IResult Overview()
    {
        var now = DateTimeOffset.UtcNow;
        return Results.Json(new { scope = "Monster Slayer LAB", observedAt = now, status = "ready", profiles = registry.Saved().Count,
            activeSessions = registry.Saved().Sum(registry.ActiveSessions), utcReset = "00:00 UTC", nextReset = now.UtcDateTime.Date.AddDays(1),
            resetBasis = "UTC day; GPS position affects daylight and habitats, not the daily reward boundary.",
            density = world.Read().MonsterSlotsPerCell, monsterLifetimeSeconds = WorldSpawns.LifetimeSeconds,
            tasksEnabled = tasks.Enabled, operatorAccess = "Authenticated reverse proxy; isolated loopback listener",
            refresh = new { news = "Next feed opening", world = "Next map request after up to 1 second", dailyRotation = "Next daily draw",
                staticCatalogue = "New definitions require coordinated server and LAB restart" } });
    }

    private object ProfileSummary(string id, LocalProfileStore.Profile? snapshot = null)
    {
        var p = snapshot ?? registry.Store(id).Snapshot();
        var identity = registry.DescribeIdentity(id);
        return new { id, revision = p.Revision, schema = p.SchemaVersion, name = p.Player?.Name, level = p.Player is null ? 0 : Reconstruction.LevelForExp(p.Player.Exp),
            label = ReadProfileLabel(id).Label, identityKind = identity.IdentityKind, deviceCount = identity.DeviceCount,
            gold = p.Player?.Gold, skillPoints = p.Player?.SkillPoints, skillCount = p.Player?.Skills.Count,
            storyClockSeconds = p.Player?.Story?.Clock ?? 0, activeSessions = registry.ActiveSessions(id) };
    }

    private IResult ChangeProfile(string id, ProfileWrite write)
    {
        LocalProfileStore.CheckProfileId(id);
        if (write.Confirm != id) throw new Refusal(400, "Type the exact target profile ID to confirm the operation.");
        if (write.Action is not ("reset" or "copy" or "clock" or "restore")) throw new Refusal(400, "Unsupported profile operation.");
        lock (gate)
        {
            var receipt = NewReceipt("profile-" + write.Action, id, "accepted", write.Revision.ToString());
            SaveReceipt(receipt);
            try
            {
                LocalProfileStore.Profile? restore = null;
                if (write.Action == "restore")
                {
                    if (write.Backup is null || !Regex.IsMatch(write.Backup, "^[0-9]{8}T[0-9]{13}-[a-f0-9]{12}$"))
                        throw new InvalidOperationException("Choose an existing profile backup receipt.");
                    var previous = JsonSerializer.Deserialize<Receipt>(File.ReadAllBytes(Path.Combine(root, "receipts", write.Backup + ".json")), Json);
                    if (previous is null || previous.Target != id || !previous.Action.StartsWith("profile-", StringComparison.Ordinal) || previous.Outcome != "applied")
                        throw new InvalidOperationException("The backup does not belong to this profile operation.");
                    restore = JsonSerializer.Deserialize<LocalProfileStore.Profile>(File.ReadAllBytes(Path.Combine(root, "backups", write.Backup + ".profile.json")))
                        ?? throw new InvalidDataException();
                    if (restore.ProfileId != id) throw new InvalidOperationException("The backup belongs to another profile.");
                }
                var result = registry.AdminChange(id, write.Revision, write.Action, write.Source, write.SourceRevision, write.Seconds,
                    before => Atomic(Path.Combine(root, "backups", receipt.Id + ".profile.json"), JsonSerializer.SerializeToUtf8Bytes(before)), restore);
                MapObservation.Forget(id);
                receipt = receipt with { Outcome = "applied", After = result.Revision.ToString(),
                    Effect = "Saved progress changed. Start LAB again to load it. Existing device and account bindings are preserved." };
                SaveReceipt(receipt);
                return Results.Json(new { receipt, profile = ProfileSummary(id) });
            }
            catch (InvalidOperationException e)
            {
                SaveReceipt(receipt with { Outcome = "refused" });
                throw new Refusal(409, e.Message);
            }
            catch { SaveReceipt(receipt with { Outcome = "failed" }); throw; }
        }
    }

    private IResult ChangeTasks(string kind, DocumentWrite write)
    {
        lock (gate)
        {
            var current = tasks.Current ?? throw new Refusal(409, "Enable the external task catalogue before editing it.");
            if (kind == "daily")
            {
                var next = write.Document.Deserialize<TaskCatalog.DailyFile>(TaskCatalog.Json) ?? throw new InvalidDataException();
                TaskCatalog.Validate(current with { Daily = next });
                string Identity(TaskCatalog.DailyFile d) => JsonSerializer.Serialize(d with { Tasks = d.Tasks.Select(t => t with { Weight = 1, MinLevel = 1 }).ToArray() }, TaskCatalog.Json);
                if (Identity(next) != Identity(current.Daily)) throw new Refusal(409, "Live rotation permits only weight and min_level edits. New definitions must be staged.");
                return SaveDocument(Path.Combine(taskRoot, "daily.json"), write.Revision, JsonSerializer.SerializeToUtf8Bytes(next, TaskCatalog.Json),
                    "daily-rotation", "daily", "Future daily draws use the new weights and level gates. Already assigned tasks are retained.");
            }
            if (kind == "hunt")
            {
                var next = write.Document.Deserialize<TaskCatalog.HuntFile>(TaskCatalog.Json) ?? throw new InvalidDataException();
                TaskCatalog.Validate(current with { Hunt = next });
                if (JsonSerializer.Serialize(next with { Streak = true }, TaskCatalog.Json) != JsonSerializer.Serialize(current.Hunt with { Streak = true }, TaskCatalog.Json))
                    throw new Refusal(409, "Only the missed-day streak policy can change live.");
                return SaveDocument(Path.Combine(taskRoot, "hunt.json"), write.Revision, JsonSerializer.SerializeToUtf8Bytes(next, TaskCatalog.Json),
                    "hunt-policy", "hunt", "The server uses the new missed-day policy on the next stamp reconciliation.");
            }
            if (kind != "staged") throw new Refusal(400, "Unsupported task section.");
            var candidate = write.Document.Deserialize<TaskCatalog.Catalog>(TaskCatalog.Json) ?? throw new InvalidDataException();
            TaskCatalog.Validate(candidate);
            string serialized = JsonSerializer.Serialize(current, TaskCatalog.Json);
            if (Digest(Encoding.UTF8.GetBytes(serialized)) != write.Revision) throw new Refusal(409, "Task catalogue changed. Refresh before staging.");
            bool Keeps(TaskCatalog.Definition[] before, TaskCatalog.Definition[] after) => before.All(d => after.Any(n =>
                n.Id == d.Id && JsonSerializer.Serialize(n with { Weight = 1, MinLevel = 1 }, TaskCatalog.Json) ==
                JsonSerializer.Serialize(d with { Weight = 1, MinLevel = 1 }, TaskCatalog.Json)));
            if (!Keeps(current.Daily.Tasks, candidate.Daily.Tasks) || !Keeps(current.Trinkets.Trinkets, candidate.Trinkets.Trinkets) ||
                current.Timed.Events.Any(e => !candidate.Timed.Events.Any(n => JsonSerializer.Serialize(n, TaskCatalog.Json) == JsonSerializer.Serialize(e, TaskCatalog.Json))) ||
                JsonSerializer.Serialize(current.Hunt with { Streak = true }, TaskCatalog.Json) != JsonSerializer.Serialize(candidate.Hunt with { Streak = true }, TaskCatalog.Json))
                throw new Refusal(409, "Keep every persisted task and event unchanged; append new IDs for new definitions.");
            var receipt = NewReceipt("task-catalogue", "catalogue", "staged", write.Revision,
                Digest(JsonSerializer.SerializeToUtf8Bytes(candidate, TaskCatalog.Json)),
                "Validated and staged only. Apply through the maintenance command with the game stopped, then restart server and LAB.");
            string stage = LocalProfileStore.PrepareDirectory(Path.Combine(root, "staged", receipt.Id));
            Atomic(Path.Combine(stage, "catalogue.json"), JsonSerializer.SerializeToUtf8Bytes(candidate, TaskCatalog.Json));
            Atomic(Path.Combine(stage, "manifest.json"), JsonSerializer.SerializeToUtf8Bytes(new {
                operation = receipt.Id, catalogueSha256 = receipt.After,
                before = new[] { "daily.json", "hunt.json", "timed.json", "trinkets.json" }
                    .ToDictionary(n => n, n => Digest(File.ReadAllBytes(Path.Combine(taskRoot, n))))
            }, Json));
            SaveReceipt(receipt);
            return Results.Json(new { receipt });
        }
    }

    private IResult SaveDocument(string path, string expected, byte[] bytes, string action, string target, string effect, byte[]? backupWhenMissing = null)
    {
        lock (gate)
        {
            byte[]? before = File.Exists(path) ? File.ReadAllBytes(path) : null;
            string version = before is null ? "missing" : Digest(before);
            if (expected != version) throw new Refusal(409, "This resource changed since it was opened. Refresh and review your changes before retrying.");
            var receipt = NewReceipt(action, target, "accepted", version, Digest(bytes), effect);
            SaveReceipt(receipt);
            try
            {
                if (before is not null || backupWhenMissing is not null)
                    Atomic(Path.Combine(root, "backups", receipt.Id + ".bin"), before ?? backupWhenMissing!);
                Atomic(path, bytes);
                receipt = receipt with { Outcome = "applied" };
                SaveReceipt(receipt);
                return Results.Json(new { receipt, revision = Digest(bytes) });
            }
            catch { SaveReceipt(receipt with { Outcome = "failed" }); throw; }
        }
    }

    private static IResult Asset(string name, string type)
    {
        using var stream = typeof(AdminServer).Assembly.GetManifestResourceStream("admin/" + name) ?? throw new InvalidOperationException();
        using var data = new MemoryStream(); stream.CopyTo(data); return Results.Bytes(data.ToArray(), type);
    }
    private static void CheckLanguage(string language) { if (!Language.IsMatch(language)) throw new Refusal(400, "Invalid language code."); }
    private static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static object ReadDocument(string path, byte[]? fallback = null)
    {
        bool exists = File.Exists(path);
        var bytes = exists ? File.ReadAllBytes(path) : fallback ?? throw new Refusal(404, "The requested configuration does not exist.");
        return new { revision = exists ? Digest(bytes) : "missing", document = JsonDocument.Parse(bytes).RootElement.Clone() };
    }
    private static IResult Document(string path) => Results.Json(ReadDocument(path));
    private static async Task<byte[]> Bytes(HttpRequest request, int maximum)
    {
        if (request.ContentLength > maximum) throw new Refusal(413, "The upload exceeds the size limit.");
        using var buffer = new MemoryStream(); byte[] block = new byte[8192]; int count;
        while ((count = await request.Body.ReadAsync(block)) > 0)
        { if (buffer.Length + count > maximum) throw new Refusal(413, "The upload exceeds the size limit."); await buffer.WriteAsync(block.AsMemory(0, count)); }
        return buffer.ToArray();
    }
    private static async Task<T> Body<T>(HttpRequest request) => JsonSerializer.Deserialize<T>(await Bytes(request, 1024 * 1024), Json) ?? throw new InvalidDataException();
    private static Receipt NewReceipt(string action, string target, string result, string? before = null, string? after = null, string? effect = null) =>
        new(DateTimeOffset.UtcNow.ToString("yyyyMMddTHHmmssfffffff") + "-" + Guid.NewGuid().ToString("N")[..12],
            DateTimeOffset.UtcNow.ToString("O"), action, target, result, before, after, effect);
    private void SaveReceipt(Receipt receipt) => Atomic(Path.Combine(root, "receipts", receipt.Id + ".json"), JsonSerializer.SerializeToUtf8Bytes(receipt, Json));
    private static void Atomic(string path, byte[] bytes)
    {
        string pending = path + "." + Guid.NewGuid().ToString("N") + ".pending";
        try
        {
            using (var file = new FileStream(pending, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(pending, UnixFileMode.UserRead | UnixFileMode.UserWrite); file.Write(bytes); file.Flush(true); }
            File.Move(pending, path, true);
        }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }
    private static bool ValidImage(string name, byte[] bytes)
    {
        if (name.EndsWith(".png", StringComparison.Ordinal))
        {
            if (bytes.Length < 33 || !bytes.AsSpan(0, 8).SequenceEqual(new byte[] {137,80,78,71,13,10,26,10}) || Encoding.ASCII.GetString(bytes,12,4) != "IHDR") return false;
            int w = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(16)), h = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(20));
            return w is > 0 and <= 4096 && h is > 0 and <= 4096 && bytes.AsSpan(bytes.Length - 8, 4).SequenceEqual("IEND"u8);
        }
        if (bytes.Length < 4 || bytes[0] != 255 || bytes[1] != 216 || bytes[^2] != 255 || bytes[^1] != 217) return false;
        for (int p = 2; p + 8 < bytes.Length;)
        {
            if (bytes[p++] != 255) return false;
            while (p < bytes.Length && bytes[p] == 255) p++;
            if (p >= bytes.Length) return false;
            byte marker = bytes[p++];
            if (marker is 0xDA or 0xD9) break;
            if (p + 2 > bytes.Length) return false;
            int length = (bytes[p] << 8) | bytes[p + 1];
            if (length < 2 || p + length > bytes.Length) return false;
            if (marker is 0xC0 or 0xC1 or 0xC2)
            { if (length < 8) return false; int h = (bytes[p + 3] << 8) | bytes[p + 4], w = (bytes[p + 5] << 8) | bytes[p + 6]; return w is > 0 and <= 4096 && h is > 0 and <= 4096; }
            p += length;
        }
        return false;
    }
}
