using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    /// <summary>The player's own numbers (WorldTuning): read with their definitions, saved whole, no restart.</summary>
    private void MapTuningRoutes(WebApplication app)
    {
        string TuningPath() => Path.Combine(worldRoot, "tuning.json");
        app.MapGet("/api/tuning", () =>
        {
            lock (gate)
            {
                world.Tuning.Refresh();
                return Results.Json(new { revision = File.Exists(TuningPath()) ? Digest(File.ReadAllBytes(TuningPath())) : "missing",
                    values = world.Tuning.Effective(), definitions = WorldTuning.Settings });
            }
        });
        app.MapPut("/api/tuning", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            var values = WorldTuning.Parse(write.Document, strict: true);
            lock (gate)
            {
                Directory.CreateDirectory(worldRoot);
                var result = SaveDocument(TuningPath(), write.Revision, WorldTuning.Serialize(values), "tuning", "world-tuning",
                    "The settings are saved and each takes effect as its line says; no restart is needed.",
                    WorldTuning.Serialize(WorldTuning.Defaults()));
                world.Tuning.Refresh();
                return result;
            }
        });
    }
}
