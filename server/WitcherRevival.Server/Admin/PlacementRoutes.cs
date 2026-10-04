using System.Text.Json;
using System.Text.Json.Nodes;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    private static readonly HttpClient PlacementHttp = new() { Timeout = TimeSpan.FromSeconds(15) };
    private string PlacementPath => Path.Combine(worldRoot, "placement-policy.json");
    private static readonly byte[] EmptyPlacementSchedule = "{\"schemaVersion\":1,\"versions\":[]}"u8.ToArray();

    private void MapPlacementRoutes(WebApplication app)
    {
        app.MapGet("/api/placement-policy", async () => Results.Json(await PlacementRequest("/admin/policy")));
        app.MapGet("/api/map/context", async (string profile) =>
        {
            var ids = PlacementCells(profile);
            long epoch = WorldSpawns.PlacesEpoch(DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            return Results.Json(await PlacementRequest($"/admin/map?ids={string.Join(',', ids)}&epoch={epoch}"));
        });
        app.MapPost("/api/placement-policy/preview", async (string profile, HttpRequest request) =>
        {
            var ids = PlacementCells(profile);
            var write = await Body<DocumentWrite>(request);
            return Results.Json(await PlacementRequest("/admin/preview", new
            { ids, epoch = WorldSpawns.PlacesEpoch(DateTimeOffset.UtcNow.ToUnixTimeSeconds()) + 1, document = write.Document }));
        });
        app.MapPut("/api/placement-policy", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            var checkedPolicy = await PlacementRequest("/admin/validate", new { document = write.Document });
            var state = checkedPolicy.GetProperty("policyStatus");
            if (!state.GetProperty("enabled").GetBoolean() || state.GetProperty("status").GetString() != "ready")
                throw new Refusal(409, "Placement policy is unavailable. The last valid configuration remains in use.");
            lock (gate)
            {
                var bytes = File.Exists(PlacementPath) ? File.ReadAllBytes(PlacementPath) : null;
                var revision = bytes is null ? "missing" : Digest(bytes);
                if (write.Revision != revision || state.GetProperty("revision").GetString() != revision)
                    throw new Refusal(409, "This resource changed since it was opened. Refresh and review your changes before retrying.");
                var schedule = JsonNode.Parse(bytes ?? EmptyPlacementSchedule)!.AsObject();
                var versions = schedule["versions"]!.AsArray();
                long next = WorldSpawns.PlacesEpoch(DateTimeOffset.UtcNow.ToUnixTimeSeconds()) + 1;
                if (versions.Count > 0 && versions[^1]!["fromEpoch"]!.GetValue<long>() >= next)
                {
                    if (versions[^1]!["fromEpoch"]!.GetValue<long>() != next)
                        throw new Refusal(409, "Placement schedule contains a later activation. Review it before saving.");
                    versions.RemoveAt(versions.Count - 1); // Replace tomorrow's draft only; history is immutable.
                }
                if (versions.Count >= 128) throw new Refusal(409, "Placement history is full. Export and review it before further changes.");
                versions.Add(new JsonObject { ["fromEpoch"] = next,
                    ["policy"] = JsonNode.Parse(checkedPolicy.GetProperty("document").GetRawText()) });
                byte[] scheduled = JsonSerializer.SerializeToUtf8Bytes(schedule, Json);
                if (scheduled.Length > 1024 * 1024)
                    throw new Refusal(409, "Placement history is full. Export and review it before further changes.");
                Directory.CreateDirectory(worldRoot);
                return SaveDocument(PlacementPath, revision, scheduled,
                    "placement-policy", "future-world-placements",
                    $"Placement day {next} starts at {DateTimeOffset.FromUnixTimeSeconds(next * 86400):O}. Existing placement days and encounter identities are retained.",
                    EmptyPlacementSchedule);
            }
        });
    }

    private string[] PlacementCells(string profile)
    {
        RequireProfile(profile);
        var ids = MapObservation.CellIds(profile);
        if (ids.Length == 0) throw new Refusal(409, "No retained map area. Open the LAB map and refresh this view first.");
        return ids;
    }

    private async Task<JsonElement> PlacementRequest(string path, object? document = null)
    {
        string endpoint = cfg["Playable:Url"]?.TrimEnd('/') ?? "";
        if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || !uri.IsLoopback || uri.Scheme != "http")
            throw new Refusal(503, "Local placement service is unavailable. Retry after checking its status.");
        try
        {
            using var request = new HttpRequestMessage(document is null ? HttpMethod.Get : HttpMethod.Post, endpoint + path);
            if (document is not null)
            {
                request.Content = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(document, Json));
                request.Content.Headers.ContentType = new("application/json");
            }
            using var response = await PlacementHttp.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
            if ((int)response.StatusCode == 400)
                throw new Refusal(400, "Check placement limits and preferred points. Every preferred point must be on mapped walkable ground, inside coverage, outside exclusions and clear of roads, buildings and water.");
            if (!response.IsSuccessStatusCode)
                throw new Refusal(503, "Local placement service is unavailable. Retry after checking its status.");
            using var stream = await response.Content.ReadAsStreamAsync();
            using var buffer = new MemoryStream();
            byte[] block = new byte[8192]; int count;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            while ((count = await stream.ReadAsync(block, deadline.Token)) > 0)
            {
                if (buffer.Length + count > 4 * 1024 * 1024) throw new InvalidDataException();
                buffer.Write(block, 0, count);
            }
            return JsonDocument.Parse(buffer.ToArray()).RootElement.Clone();
        }
        catch (Exception e) when (e is HttpRequestException or OperationCanceledException or JsonException or InvalidDataException)
        { throw new Refusal(503, "Local placement service is unavailable. Retry after checking its status."); }
    }
}
