using System.Net;
using WitcherRevival.Server.Net;
using WitcherRevival.Server.Transport;

if (args.Length > 0 && args[0] == "--transport-admin")
{
    Environment.ExitCode = TransportAdmin.Run(args);
    return;
}

var builder = WebApplication.CreateBuilder(args);
var drivingWarningSettings = DrivingWarningSettings.FromConfiguration(builder.Configuration);
builder.Services.AddSingleton(drivingWarningSettings);
builder.Services.AddSingleton<TimeProvider>(TimeProvider.System);
builder.Services.AddSingleton<TaskCatalog>();
builder.Services.AddSingleton<TaskEngine>();
builder.Services.AddSingleton<WorldPolicy>();
builder.Services.AddSingleton<StaticDataSnapshot>();
int httpPort = builder.Configuration.GetValue("Http:Port", 8080);
if (httpPort is < 1 or > 65535) throw new InvalidOperationException("Http:Port is outside 1..65535.");
builder.WebHost.ConfigureKestrel(k => k.Listen(IPAddress.Loopback, httpPort));
// Framework request diagnostics can include URL paths and query strings.
// HTTP observability is supplied only by our constant-label middleware below.
builder.Logging.AddFilter("Microsoft.AspNetCore", LogLevel.None);
// One weather cache for every player: a 0.1° cell is asked for once per cache period.
builder.Services.AddSingleton(sp => new WorldWeather(builder.Configuration["Weather:Url"],
    TimeSpan.FromMinutes(builder.Configuration.GetValue("Weather:CacheMinutes", 15)), builder.Configuration["World:Directory"]));
builder.Services.AddSingleton<ProfileRegistry>();
builder.Services.AddSingleton<NewsFeed>();
builder.Services.AddSingleton<GameSocketService>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<GameSocketService>());
builder.Services.AddHostedService<TransportServer>();
builder.Services.AddHostedService<WitcherRevival.Server.Admin.AdminServer>();
var app = builder.Build();
// Validate task files before creating player storage.
_ = app.Services.GetRequiredService<TaskCatalog>();
_ = app.Services.GetRequiredService<WorldPolicy>();
_ = app.Services.GetRequiredService<StaticDataSnapshot>();
var registry = app.Services.GetRequiredService<ProfileRegistry>();
app.UseMiddleware<HttpMetadataMiddleware>();

// Local endpoints name the profile they act on (?profile=<id>); a profile not saved yet reads as new.
LocalProfileStore? Selected(string? profile)
{
    if (profile is null) return null;
    try { LocalProfileStore.CheckProfileId(profile); } catch (InvalidOperationException) { return null; }
    return registry.Store(profile);
}

app.MapGet("/health", () => Results.Json(new {
    status = "ready", compatibility = "unverified-1.1.116", bind = "127.0.0.1"
})).WithMetadata(new LocalHttpEndpoint("health"));
app.MapGet("/prototype/profiles", () => Results.Json(registry.Saved())).WithMetadata(new LocalHttpEndpoint("prototype_profiles"));
app.MapGet("/prototype/state", (string? profile) => Selected(profile) is { } profiles
    ? Results.Json(profiles.Snapshot()) : Results.NotFound()).WithMetadata(new LocalHttpEndpoint("prototype_state"));
// Local test aids for season 1: the story data, and moving the profile's story clock on by `add` seconds.
app.MapGet("/prototype/story", () => Results.Text(StoryEngine.Json, "application/json")).WithMetadata(new LocalHttpEndpoint("prototype_story"));
app.MapPost("/prototype/story/clock", (long add, string? profile) =>
{
    if (add is < 0 or > 30L * 86400) return Results.BadRequest();
    if (Selected(profile) is not { } profiles) return Results.NotFound();
    long clock = 0;
    profiles.UpdatePlayer(new Dictionary<int, int>(), null, player =>
    {
        var story = player.Story ?? LocalProfileStore.StoryProgress.Empty;
        clock = story.Clock + add;
        return player with { Story = story with { Clock = clock } };
    });
    return Results.Json(new { clock });
}).WithMetadata(new LocalHttpEndpoint("prototype_story_clock"));
app.MapGet("/staticdata", (HttpContext context, StaticDataSnapshot data) =>
{
    // The native downloader expects a complete gzip body; never send an unproven 304 response.
    context.Response.Headers.CacheControl = "no-store";
    context.Response.Headers.ETag = "\"" + data.Revision + "\"";
    return Results.Bytes(data.Gzip, "application/octet-stream");
})
    .WithMetadata(new LocalHttpEndpoint("staticdata"));
app.MapGet("/news", (HttpContext context, NewsFeed news) => news.Response(context, null))
    .WithMetadata(new LocalHttpEndpoint("news"));
app.MapGet("/news/{language}", (HttpContext context, NewsFeed news, string language) => news.Response(context, language))
    .WithMetadata(new LocalHttpEndpoint("news"));
app.MapGet("/news/images/{name}", (NewsFeed news, string name) => news.Image(name))
    .WithMetadata(new LocalHttpEndpoint("news_image"));
app.MapGet("/v1/featuretiles/{**rest}", () => Results.Bytes(Array.Empty<byte>(), "application/x-protobuf")).WithMetadata(new LocalHttpEndpoint("featuretiles"));
foreach (string route in new[] { "/gatekeeper", "/idjson", "/idjson/bob" })
    app.MapGet(route, () => Results.Json(new { Type = 0, Message = 0, EndTime = "", Address = "127.0.0.1", WitcherId = 1L },
        new System.Text.Json.JsonSerializerOptions { PropertyNamingPolicy = null })).WithMetadata(new LocalHttpEndpoint("gatekeeper"));
app.Logger.LogInformation("Local prototype HTTP ready on 127.0.0.1:{Port}; client wire compatibility remains unverified", httpPort);
app.Run();
