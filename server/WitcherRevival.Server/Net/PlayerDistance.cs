using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    // A bounded persisted replay history: at least 409.6 km of ordinary >=100 m native reports.
    // No expiry based on wall-clock changes. Extremely old IDs outside this history are not deduplicated.
    private const int DistanceReceiptLimit = 4096;

    private int CurrentDistance() => profiles.Snapshot().Player is { } p
        ? p.Distance?.Metres ?? 0 : LegacyDistanceTraveled;

    /// <summary>Original 1.1.116 PlayerController.TrySendServerWalkedDistance, RVA 0x1A321C0,
    /// sends a rounded positive metre delta once its accumulator reaches 100 and five seconds pass.
    /// Scale is one (.cctor 0x1A32A50). OnDistanceTraveledResponse (0x1A08D70) assigns Param even
    /// on failure, so every response carries the retained cumulative total. No GPS is inferred.</summary>
    private byte[] HandleDistanceTraveled(ApiProtocol.ApiRequest req)
    {
        if (req.Data.Length != 4) return BuildIntResponse(false, CurrentDistance());
        int delta = new ByteBuffer(req.Data).ReadInt();
        if (delta < 0) return BuildIntResponse(false, CurrentDistance());
        if (profiles.Snapshot().Player is null) return BuildIntResponse(true, LegacyDistanceTraveled);
        bool accepted = true;
        var saved = profiles.UpdateMovement(snapshot =>
        {
            if (snapshot.Movement?.Protected == true && delta > 0) { accepted = false; return null; }
            var p = snapshot.Player!;
            var state = p.Distance ?? new LocalProfileStore.DistanceState(0, []);
            if (state.Requests.TryGetValue(req.Id, out int previous))
            {
                accepted = previous == delta;
                return null;
            }
            if (delta > int.MaxValue - state.Metres) { accepted = false; return null; }
            if (delta == 0) return null;
            var receipts = new Dictionary<long, int>(state.Requests) { [req.Id] = delta };
            while (receipts.Count > DistanceReceiptLimit) receipts.Remove(receipts.First().Key);
            return snapshot with { Player = p with { Distance = new(state.Metres + delta, receipts) } };
        }, new TaskEngine.Action(M_DistanceTraveled));
        // Return today's total also for a retried old request, avoiding visible counter regression.
        log.LogInformation("  DistanceTraveled delta={Delta} m accepted={Accepted} total={Total} m", delta, accepted, saved.Player!.Distance?.Metres ?? 0);
        return BuildIntResponse(accepted, saved.Player!.Distance?.Metres ?? 0);
    }
}
