using System.Text.Json;
using WitcherRevival.Server.Transport;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    private TransportRegistry? InstallationRegistry()
    {
        string? directory = cfg["Transport:RegistryDirectory"];
        return cfg.GetValue("Transport:Port", 0) == 0 || string.IsNullOrWhiteSpace(directory)
            ? null : new TransportRegistry(directory);
    }

    private void MapTransportRoutes(WebApplication app)
    {
        app.MapGet("/api/transport", () =>
        {
            var store = InstallationRegistry();
            if (store is null) return Results.Json(new { available = false });
            return Results.Json(new { available = true, state = store.ManagementSnapshot(),
                profiles = registry.Saved().Select(id => ProfileSummary(id)),
                limits = new { enrollmentSeconds = 600, enrollmentSlots = 16, accessSeconds = 31536000 } });
        });
        app.MapPost("/api/transport", async (HttpRequest request) =>
        {
            var write = JsonSerializer.Deserialize<TransportRegistry.ManagementWrite>(await Bytes(request, 8192), Json)
                ?? throw new InvalidDataException();
            var store = InstallationRegistry() ?? throw new Refusal(409, "Installation transport is not configured.");
            lock (gate)
            {
                var before = store.ManagementSnapshot();
                // Only explicit non-secret fields enter the durable operator receipt.
                string Summary(TransportRegistry.ManagementState state) => JsonSerializer.Serialize(new
                { state.Revision, state.EnrollmentUntil, state.EnrollmentRemaining,
                    installation = state.Entries.SingleOrDefault(e => e.Code == write.Code) }, Json);
                var receipt = NewReceipt("transport-" + write.Action, write.Code ?? "enrollment", "accepted", Summary(before));
                SaveReceipt(receipt);
                try
                {
                    var result = store.Manage(write, cfg["LocalProfile:DataDirectory"] ?? "data/profiles");
                    receipt = receipt with { Outcome = "applied", After = Summary(result), Effect = write.Action switch
                    {
                        "rebind" => "The selected installation must reconnect. Existing player saves are preserved. The access deadline is unchanged.",
                        "revoke" => "Access is revoked. Active transport sessions close on the next registry check.",
                        "approve" or "renew" => "Access ends at the saved deadline. The duration starts at the time of this change.",
                        _ => "The enrollment window affects new pairing requests; existing approvals remain active."
                    } };
                    SaveReceipt(receipt);
                    return Results.Json(new { receipt, revision = result.Revision, state = result });
                }
                catch (InvalidOperationException e)
                {
                    SaveReceipt(receipt with { Outcome = "refused" });
                    throw new Refusal(409, e.Message);
                }
                catch { SaveReceipt(receipt with { Outcome = "failed" }); throw; }
            }
        });
    }
}
