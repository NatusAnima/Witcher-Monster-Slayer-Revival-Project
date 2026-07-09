using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using WitcherRevival.Server.Net;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");   // gatekeeper HTTP; TLS handled by mitmproxy/phone-side for now
builder.Services.AddHostedService<GameSocketService>();
var app = builder.Build();

var cfg = app.Configuration;
int gamePort = cfg.GetValue("GameServer:Port", 4253);
string address = cfg["Gatekeeper:Address"] ?? DetectLanIp(); // Just the IP
int okType = cfg.GetValue("Gatekeeper:OkType", 0);     // ASSUMPTION: 0 == OK
long witcherId = cfg.GetValue("Gatekeeper:WitcherId", 1L);
var log = app.Logger;

// GatekeeperResponse uses PascalCase [DataMember] names — do NOT camelCase.
var json = new JsonSerializerOptions { PropertyNamingPolicy = null };

// Log every HTTP request (this doubles as capture for the gatekeeper request shape — §10 open item #3).
app.Use(async (ctx, next) =>
{
    log.LogInformation("HTTP {Method} {Path}{Query}", ctx.Request.Method, ctx.Request.Path, ctx.Request.QueryString);
    await next();
});

// Static game data blob: CdnPreloader downloads this, GZip-decompresses, then DataContractJson -> Container.
// Body is raw gzip (the client wraps the stream in GZipStream itself).
app.MapGet("/staticdata", (IConfiguration c) =>
{
    byte[] gz = WitcherRevival.Server.Net.PreloaderStaticData.GzipContainer(c.GetValue("Preloader:EmptyObject", false));
    return Results.Bytes(gz, "application/octet-stream");
});

// Google Maps Gaming SDK vector-tile fetch. hook.js redirects the Google tile GET
// (https://vectortile.googleapis.com/v1/featuretiles/@x,y,Nz?...) to us so ProtoTileProducer gets an
// INSTANT HTTP 200 instead of retrying the force-failed :443 connection for ~60s (cut boot 72s -> ~12s).
// An empty body is a valid empty protobuf FeatureTile: the client's FeatureTileDecoder.ParseFeatureTile
// (0x19B9F10) decodes it as "no features" and renders no roads (vs. the JSON fallback, which the proto
// parser rejected with "input ended unexpectedly" ~2000x/boot — harmless but noisy).
// TO RENDER A ROAD (future): return a real Google SVT FeatureTile proto carrying one road polyline in
// tile-local coords (zoom 17, tile x,y from the @x,y,17z path); client renders it via MapSettings.RoadMaterial.
app.MapGet("/v1/featuretiles/{**rest}", () => Results.Bytes(Array.Empty<byte>(), "application/x-protobuf"));

// Gatekeeper: hand any request back our game-server Address + an OK status.
// GatekeeperResponse fields (PascalCase): Type, Message, EndTime, Address, WitcherId.
// Refine to the exact route once captured; a catch-all is deliberate for the first session.
app.MapFallback(() => Results.Json(new
{
    Type = okType,
    Message = 0,
    EndTime = "",
    Address = address,
    WitcherId = witcherId,
}, json));

log.LogInformation("Gatekeeper HTTP on http://0.0.0.0:8080  ->  Address={Address}  (game TCP port {Port})", address, gamePort);
app.Run();

static string DetectLanIp()
{
    try
    {
        using var s = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
        s.Connect("8.8.8.8", 65530);
        return ((IPEndPoint)s.LocalEndPoint!).Address.ToString();
    }
    catch { return "127.0.0.1"; }
}
