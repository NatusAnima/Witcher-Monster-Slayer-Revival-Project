using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Text.Json;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    private void MapOperatorRoutes(WebApplication app)
    {
        app.MapGet("/api/map", (string? profile) =>
        {
            if (string.IsNullOrWhiteSpace(profile)) throw new Refusal(400, "Select a saved profile to inspect its last map response.");
            RequireProfile(profile);
            return Results.Json(MapObservation.Read(profile));
        });
        app.MapGet("/api/profiles/{id}/distance", (string id) =>
        {
            RequireProfile(id);
            return Results.Json(registry.Player(id).DistanceStatus());
        });
        app.MapGet("/api/distance-policy", () =>
        {
            lock (gate)
            {
                var path = Path.Combine(worldRoot, "distance-policy.json");
                bool exists = File.Exists(path);
                byte[] bytes = exists ? File.ReadAllBytes(path) : JsonSerializer.SerializeToUtf8Bytes(new DistancePolicy.Settings(), Json);
                using var document = JsonDocument.Parse(bytes);
                var settings = DistancePolicy.Parse(document.RootElement);
                return Results.Json(new { revision = exists ? Digest(bytes) : "missing", document = settings,
                    effect = "Only a fresh capable-client HELLO applies this policy. Existing protected profiles remain protected; shadow never re-enables legacy distance for them.",
                    scope = "capable-authenticated-profiles", protectedProfilesRemainProtected = true, appliesOn = "new-hello" });
            }
        });
        app.MapPut("/api/distance-policy", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            var settings = DistancePolicy.Parse(write.Document);
            lock (gate)
            {
                var result = SaveDocument(Path.Combine(worldRoot, "distance-policy.json"), write.Revision,
                    JsonSerializer.SerializeToUtf8Bytes(settings, Json), "distance-policy", "capable-authenticated-profiles",
                    "The next fresh capable-client HELLO uses this policy. Protection already latched to a profile remains permanent; shadow does not re-enable legacy distance.",
                    JsonSerializer.SerializeToUtf8Bytes(new DistancePolicy.Settings(), Json));
                world.Distance.Read(refresh: true);
                return result;
            }
        });
        app.MapGet("/api/world/balance", SpawnBalance);
        app.MapPut("/api/world/balance", async (HttpRequest request) => ChangeSpawnBalance(await Body<DocumentWrite>(request)));
        app.MapGet("/api/weather", Weather);
        app.MapPut("/api/weather", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            var settings = write.Document.Deserialize<WorldWeather.OverrideSettings>(WorldWeather.PolicyJson) ?? throw new InvalidDataException();
            WorldWeather.ValidateOverride(settings);
            return SaveDocument(Path.Combine(worldRoot, "weather.json"), write.Revision,
                JsonSerializer.SerializeToUtf8Bytes(settings, WorldWeather.PolicyJson), "weather", "global-weather",
                "The next weather request uses this global policy after at most one second (the client normally asks every five minutes). " +
                "The override does not clear cached monster generations; generations still in cache retain their weather. " +
                "Manual weather returns to the configured provider or clear fallback at expiration. Server restart or generation-cache eviction loses that memory.");
        });
        app.MapGet("/api/catalogue", Catalogue);
        app.MapGet("/api/profiles/{id}", (string id) => ProfileDetail(id));
        app.MapGet("/api/profiles/{id}/label", (string id) =>
        {
            RequireProfile(id);
            lock (gate) return Results.Json(ReadDocument(ProfileLabelPath(id), EmptyProfileLabel()));
        });
        app.MapPut("/api/profiles/{id}/label", async (string id, HttpRequest request) =>
            ChangeProfileLabel(id, await Body<DocumentWrite>(request)));
        app.MapGet("/api/news", () => Results.Json(new { observedAt = DateTimeOffset.UtcNow,
            defaultLanguage = cfg["News:DefaultLanguage"] ?? "pl",
            languages = Directory.Exists(newsRoot) ? Directory.EnumerateFiles(newsRoot, "*.json")
                .Select(Path.GetFileNameWithoutExtension).Where(n => n is not null && Language.IsMatch(n)).Order().ToArray() : [] }));
        app.MapGet("/api/images/{name}", (string name) => news.Image(name));
        app.MapGet("/api/system", SystemStatus);
        app.MapGet("/api/receipts/{id}/backup", (string id) => ReadBackup(id));
    }

    private (string Revision, WorldBalance.Schedule Schedule) ReadSpawnBalance()
    {
        string path = Path.Combine(worldRoot, "spawn-balance.json");
        if (!File.Exists(path)) return ("missing", WorldBalance.Default);
        byte[] bytes = File.ReadAllBytes(path);
        return (Digest(bytes), WorldBalance.Parse(bytes));
    }

    private long BalanceFrom(WorldBalance.Schedule schedule) =>
        Math.Max(world.SpawnBalanceFromUnixSeconds, schedule.Versions[^1].FromUnixSeconds);
    private static long BalanceAllNewBy(long from) => from == 0 ? 0 :
        from > long.MaxValue - WorldSpawns.LifetimeSeconds ? long.MaxValue : from + WorldSpawns.LifetimeSeconds;

    private IResult SpawnBalance()
    {
        lock (gate)
        {
            var (revision, schedule) = ReadSpawnBalance();
            long from = BalanceFrom(schedule);
            return Results.Json(new { saved = new { revision, document = schedule.Versions[^1].Rules },
                effective = schedule.At(DateTimeOffset.UtcNow.ToUnixTimeSeconds()),
                fromUnixSeconds = from, allNewByUnixSeconds = BalanceAllNewBy(from),
                species = WorldBestiary.All, defaults = WorldBalance.DefaultRules, scope = "ordinary-shared-world" });
        }
    }

    private IResult WorldSettings()
    {
        lock (gate)
        {
            var (_, schedule) = ReadSpawnBalance();
            var rules = schedule.Versions[^1].Rules;
            long from = BalanceFrom(schedule);
            return Results.Json(new { saved = ReadDocument(Path.Combine(worldRoot, "world.json"),
                JsonSerializer.SerializeToUtf8Bytes(world.Read(), WorldPolicy.Json)), effective = world.Read(),
                lifetimeSeconds = WorldSpawns.LifetimeSeconds,
                spawnBalance = new { version = rules.IdentitySuffix == ":balance88-18-3" ? "category-88-18-3" : "operator-configured",
                    common = rules.Common, rare = rules.Rare, legendary = rules.Legendary,
                    fromUnixSeconds = from, allNewByUnixSeconds = BalanceAllNewBy(from), scope = "ordinary-shared-world",
                    speciesWeights = rules.SpeciesWeights!.Count == 0 ? "equal-base-with-environmental-boosts" : "operator-multipliers-with-environmental-boosts" } });
        }
    }

    private IResult ChangeSpawnBalance(DocumentWrite write)
    {
        var desired = WorldBalance.ParseRules(write.Document);
        lock (gate)
        {
            var (revision, previous) = ReadSpawnBalance();
            if (write.Revision != revision)
                throw new Refusal(409, "This resource changed since it was opened. Refresh and review your changes before retrying.");
            var next = WorldBalance.Append(previous, desired, DateTimeOffset.UtcNow.ToUnixTimeSeconds(), world.SpawnBalanceFromUnixSeconds);
            Directory.CreateDirectory(worldRoot);
            var result = SaveDocument(Path.Combine(worldRoot, "spawn-balance.json"), write.Revision,
                JsonSerializer.SerializeToUtf8Bytes(next, WorldPolicy.Json), "spawn-balance", "ordinary-shared-world",
                "Future generations use the saved weights. Living generations keep their lottery and identity until their 30-minute lifetime ends. Restoring previous settings creates a new future revision.",
                JsonSerializer.SerializeToUtf8Bytes(previous, WorldPolicy.Json));
            world.Balance.Read(refresh: true);
            return result;
        }
    }

    private void RequireProfile(string id)
    {
        try { LocalProfileStore.CheckProfileId(id); }
        catch (InvalidOperationException) { throw new Refusal(400, "Invalid profile ID."); }
        if (!registry.Saved().Contains(id)) throw new Refusal(404, "This saved profile does not exist.");
    }

    private sealed record ProfileLabel(string Label);
    private string ProfileLabelPath(string id) => Path.Combine(root, "profile-labels", id + ".json");
    private static byte[] EmptyProfileLabel() => JsonSerializer.SerializeToUtf8Bytes(new ProfileLabel(""), Json);

    private ProfileLabel ReadProfileLabel(string id)
    {
        lock (gate)
        {
            string path = ProfileLabelPath(id);
            return File.Exists(path)
                ? JsonSerializer.Deserialize<ProfileLabel>(File.ReadAllBytes(path), Json) ?? throw new InvalidDataException()
                : new ProfileLabel("");
        }
    }

    private IResult ChangeProfileLabel(string id, DocumentWrite write)
    {
        RequireProfile(id);
        if (write.Document.ValueKind != JsonValueKind.Object || write.Document.EnumerateObject().Count() != 1 ||
            !write.Document.TryGetProperty("label", out var property) || property.ValueKind != JsonValueKind.String)
            throw new InvalidDataException();
        string proposed = property.GetString()!;
        if (proposed.Length > 64 || proposed.Any(char.IsControl))
            throw new Refusal(400, "Use an operator label of at most 64 characters without control characters.");
        var label = new ProfileLabel(proposed.Trim());
        return SaveDocument(ProfileLabelPath(id), write.Revision, JsonSerializer.SerializeToUtf8Bytes(label, Json),
            "profile-label", id, "The operator label is saved. Game name, identity bindings and player progress are unchanged.",
            EmptyProfileLabel());
    }

    private IResult Weather() => Results.Json(new { observedAt = DateTimeOffset.UtcNow, scope = "global",
        saved = ReadDocument(Path.Combine(worldRoot, "weather.json"), JsonSerializer.SerializeToUtf8Bytes(new WorldWeather.OverrideSettings(), WorldWeather.PolicyJson)),
        effective = weather.Status(),
        codes = new[] { new { code = 1, name = "Thunderstorm" }, new { code = 2, name = "Drizzle" }, new { code = 3, name = "Rain" },
            new { code = 4, name = "Snow" }, new { code = 5, name = "Fog / atmosphere" }, new { code = 6, name = "Clear" }, new { code = 7, name = "Clouds" } },
        effect = "Global override for all players; this action does not clear cached monster generations. Uncached generations use the new weather. Native clients request weather about every five minutes.",
        limitations = new[] { "Effective describes the policy for the next lookup. lastAnswered is the last server weather lookup, also used by map generation; it is not a per-player observation or necessarily an RPC 67 response.",
            "Provider cells are rounded to 0.1 degrees. Policy inspection does not request remote weather. Server restart or generation-cache eviction loses cached generation weather." } });

    private IResult Catalogue()
    {
        using var compressed = new MemoryStream(staticData.Gzip, writable: false);
        using var gzip = new GZipStream(compressed, CompressionMode.Decompress);
        using var document = JsonDocument.Parse(gzip);
        var tables = document.RootElement.EnumerateObject().Where(p => p.Value.ValueKind == JsonValueKind.Array)
            .Select(p => new { name = p.Name, count = p.Value.GetArrayLength(), rows = p.Value.Clone() }).ToArray();
        return Results.Json(new { observedAt = DateTimeOffset.UtcNow, revision = staticData.Revision,
            source = "active-static-catalogue", readOnly = true, tables, bestiary = WorldBestiary.All,
            limitations = new[] { "These are the active reconstructed server definitions, not a complete recovered original backend.",
                "Static definitions are read-only here. Clients load this catalogue at startup; task additions use the separate staged workflow." } });
    }

    private IResult ProfileDetail(string id)
    {
        RequireProfile(id);
        var p = registry.Store(id).Snapshot(); var player = p.Player; var taskState = player?.Tasks;
        return Results.Json(new { observedAt = DateTimeOffset.UtcNow, source = "saved-profile-snapshot", summary = ProfileSummary(id, p),
            inventory = player?.Items, equipment = player?.Equipment, skills = player?.Skills,
            bestiary = player?.Kills?.OrderBy(k => k.Key).Select(k => new { monsterId = k.Key,
                name = WorldBestiary.Of(k.Key)?.Name ?? $"Monster {k.Key}", kills = k.Value,
                claimedTier = player.KnowledgeClaimed?.GetValueOrDefault(k.Key) ?? 0 }),
            story = player?.Story, questStage = p.QuestStage, objective = player?.CurrentObjective,
            distanceMetres = player?.Distance?.Metres ?? 0,
            social = registry.SocialSummary(id),
            crafting = player?.Brewers?.Select(b => new { type = b.Type, usesLeft = b.UsesLeft, workingRecipe = b.WorkingRecipe,
                finishTime = b.FinishTime, outputCount = b.OutputCount }),
            tasks = taskState is null ? null : new { day = taskState.Day, daily = taskState.Daily, stamps = taskState.Stamps,
                lastStamp = taskState.LastStamp, huntClaims = taskState.HuntClaims, events = taskState.Events.Values,
                achievements = taskState.Achievements, trophyProgress = taskState.TrophyProgress },
            purchases = new { transactions = player?.Transactions?.Count ?? 0,
                accepted = player?.Transactions?.Values.Count(t => t.Bought) ?? 0,
                refused = player?.Transactions?.Values.Count(t => !t.Bought) ?? 0 },
            limitations = new[] { "Read-only saved progress; inspection does not reconcile tasks or claim rewards.",
                "Account/device bindings, transaction nonces, Aura coordinates, summons and story place coordinates are omitted." } });
    }

    private IResult SystemStatus()
    {
        using var process = Process.GetCurrentProcess();
        return Results.Json(new { observedAt = DateTimeOffset.UtcNow, scope = "current-backend-process", status = "running",
            version = typeof(AdminServer).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
            startedAt = process.StartTime.ToUniversalTime(), uptimeSeconds = (DateTime.UtcNow - process.StartTime.ToUniversalTime()).TotalSeconds,
            memoryBytes = process.WorkingSet64, cpuSeconds = process.TotalProcessorTime.TotalSeconds,
            staticCatalogue = new { revision = staticData.Revision, compressedBytes = staticData.Gzip.Length },
            features = new[] {
                new { name = "World placement", configured = !string.IsNullOrWhiteSpace(cfg["Playable:Url"]), status = "not-probed", effect = "Map sidecar; panel reads retained client responses without requesting new geometry." },
                new { name = "Weather provider", configured = weather.Enabled, status = "see-weather", effect = "Open-Meteo cache or clear fallback; bounded global overrides are available." },
                new { name = "Task catalogue", configured = tasks.Enabled, status = tasks.Enabled ? "loaded" : "disabled", effect = "Live draw weights; static additions require offline maintenance." },
                new { name = "Player storage", configured = true, status = "available", effect = "Profile changes require disconnected targets and matching revisions." } },
            limits = new { mapProfiles = MapObservation.MaximumProfiles, mapRetentionSeconds = MapObservation.RetentionSeconds,
                mapStaleAfterSeconds = MapObservation.StaleAfterSeconds, weatherOverrideMaximumHours = 24, receiptsShown = 30 },
            limitations = new[] { "This is process telemetry, not host health or a dependency reachability check.",
                "Restart, deployment, network exposure and task-catalogue activation remain controlled maintenance operations." } });
    }

    private IResult ReadBackup(string id)
    {
        if (!System.Text.RegularExpressions.Regex.IsMatch(id, "^[0-9]{8}T[0-9]{13}-[a-f0-9]{12}$")) throw new Refusal(400, "Invalid receipt ID.");
        var receiptPath = Path.Combine(root, "receipts", id + ".json");
        if (!File.Exists(receiptPath)) throw new Refusal(404, "This receipt does not exist.");
        var receipt = JsonSerializer.Deserialize<Receipt>(File.ReadAllBytes(receiptPath), Json) ?? throw new InvalidDataException();
        if (receipt.Outcome != "applied" || receipt.Action is not ("news" or "world" or "weather" or "spawn-balance" or "distance-policy" or "placement-policy" or "profile-label" or "daily-rotation" or "hunt-policy"))
            throw new Refusal(409, "This operation has no restorable configuration document.");
        string backup = Path.Combine(root, "backups", id + ".bin");
        if (!File.Exists(backup)) throw new Refusal(404, "This operation created a new document; no previous document exists.");
        object previous;
        if (receipt.Action == "spawn-balance")
        {
            byte[] bytes = File.ReadAllBytes(backup);
            previous = new { revision = receipt.Before, document = WorldBalance.Parse(bytes).Versions[^1].Rules };
        }
        else if (receipt.Action == "placement-policy")
        {
            var versions = JsonDocument.Parse(File.ReadAllBytes(backup)).RootElement.GetProperty("versions");
            var policy = versions.GetArrayLength() > 0 ? versions[versions.GetArrayLength()-1].GetProperty("policy").Clone()
                : JsonDocument.Parse("{\"maxPoints\":24,\"spacingMeters\":50,\"exclusions\":[],\"preferred\":[]}").RootElement.Clone();
            previous = new { revision = receipt.Before, document = policy };
        }
        else previous = ReadDocument(backup);
        return Results.Json(new { receipt, previous,
            effect = "Review this previous document against the current resource, then save with its current revision. This read does not restore anything." });
    }
}
