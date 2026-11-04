using System.Text.Json;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    /// <summary>The Players tab's debug tools (PlayerService.Debug), only with Admin:DebugTools (the companion app turns it on:
    /// the phone is the player's own server). They work while the player is online. Each action leaves a receipt and a backup
    /// of the profile before it, so History can restore it like any other profile operation (with the game closed). The
    /// character's model (POST /api/profiles/{id}/character {gender, head}) goes the same way without the debug tools.</summary>
    private bool DebugTools => cfg.GetValue("Admin:DebugTools", false);

    private void MapPlayerDebugRoutes(WebApplication app)
    {
        app.MapPost("/api/profiles/{id}/debug", async (string id, HttpRequest request) =>
            ChangeProfileDebug(id, await Body<PlayerService.DebugRequest>(request)));
        app.MapGet("/api/profiles/{id}/blacksmith", (string id) =>
        {
            RequireProfile(id);
            return Results.Json(registry.Player(id).BlacksmithPlace());
        });
        // Where the blacksmith stands for this profile: the player's own world, so it works without the debug tools.
        app.MapPost("/api/profiles/{id}/blacksmith", async (string id, HttpRequest request) =>
        {
            RequireProfile(id);
            var write = await Body<BlacksmithWrite>(request);
            var point = await PlacementRequest("/admin/point", new { lat = write.Lat, lng = write.Lng }, "Check the blacksmith's coordinates.");
            ulong cell = ulong.Parse(point.GetProperty("cell").GetString()!);
            int[] biomes = point.GetProperty("biomes").EnumerateArray().Select(b => b.GetInt32()).ToArray();
            return ChangeProfileDebug(id, new PlayerService.DebugRequest("blacksmith"),
                backup => registry.Player(id).MoveBlacksmith(point.GetProperty("lat").GetDouble(), point.GetProperty("lng").GetDouble(), cell, biomes, backup));
        });
        // The character's model (gender and head): a player's own choice, so it works without the debug tools.
        app.MapPost("/api/profiles/{id}/character", async (string id, HttpRequest request) =>
        {
            var write = await Body<CharacterWrite>(request);
            return ChangeProfileDebug(id, new PlayerService.DebugRequest("character"),
                backup => registry.Player(id).Character(write.Gender, write.Head, backup));
        });
    }

    public sealed record CharacterWrite(int Gender, int Head);
    public sealed record BlacksmithWrite(double Lat, double Lng);

    private IResult ChangeProfileDebug(string id, PlayerService.DebugRequest write,
        Func<Action<LocalProfileStore.Profile>, PlayerService.DebugOutcome>? apply = null)
    {
        if (apply is null && !DebugTools) throw new Refusal(404, "The debug tools are off (Admin:DebugTools).");
        if (apply is null && write.Action is not ("gold" or "level" or "skillPoints" or "allSkills" or "item" or "invincible" or "oneHit"
            or "questsHere" or "questStep" or "sky"))
            throw new Refusal(400, "Unknown debug action.");
        RequireProfile(id);
        lock (gate)
        {
            var receipt = NewReceipt(apply is null ? "profile-debug-" + write.Action : "profile-" + write.Action, id, "accepted",
                registry.Store(id).Snapshot().Revision.ToString());
            SaveReceipt(receipt);
            try
            {
                Action<LocalProfileStore.Profile> backup = before =>
                    Atomic(Path.Combine(root, "backups", receipt.Id + ".profile.json"), JsonSerializer.SerializeToUtf8Bytes(before));
                var outcome = apply?.Invoke(backup) ?? registry.Player(id).Debug(write, backup);
                receipt = receipt with { Outcome = "applied", After = outcome.Revision.ToString(), Effect = outcome.Effect };
                SaveReceipt(receipt);
                return Results.Json(new { receipt, outcome, profile = ProfileSummary(id) });
            }
            catch (PlayerService.DebugRefusal e)
            {
                SaveReceipt(receipt with { Outcome = "refused" });
                throw new Refusal(409, e.Message);
            }
            catch (ArgumentException e)
            {
                SaveReceipt(receipt with { Outcome = "refused" });
                throw new Refusal(400, e.Message);
            }
            catch { SaveReceipt(receipt with { Outcome = "failed" }); throw; }
        }
    }
}
