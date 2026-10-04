namespace WitcherRevival.Server.Net;

/// <summary>Bounded integrity ledger outside copyable game progress. No coordinates or route are persisted.</summary>
public sealed record DistanceLedger(bool Protected, int? LegacyBaselineMetres, long CreditedMetres,
    long ShadowMillimetres, int RemainderMillimetres, long ObservedAtMs, string Epoch, long NextSeq, long HighWaterUtcMs,
    long ProtectedAcceptedFixes, long ProtectedRejectedFixes, long ShadowAcceptedFixes, long ShadowRejectedFixes,
    Dictionary<string, long> RejectedReasons, List<DistanceLedger.Receipt> Receipts, long RebasedAtMs = 0)
{
    public sealed record Receipt(long FirstSeq, int Count, string Digest);
    public static DistanceLedger Empty => new(false, null, 0, 0, 0, 0, "", 1, 0, 0, 0, 0, 0, [], []);
    public DistanceLedger Copy() => this with { RejectedReasons = new(RejectedReasons), Receipts = Receipts.ToList() };
    public DistanceLedger Rebase(int total) => Empty with { Protected = Protected,
        LegacyBaselineMetres = Protected ? total : null, ObservedAtMs = ObservedAtMs, HighWaterUtcMs = HighWaterUtcMs,
        Epoch = Guid.NewGuid().ToString("N").ToUpperInvariant(), RebasedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
    public static bool Valid(DistanceLedger? d) => d is null ||
        (d.NextSeq >= 1 && d.HighWaterUtcMs >= 0 && d.CreditedMetres >= 0 && d.ShadowMillimetres >= 0 &&
        d.RemainderMillimetres is >= 0 and < 1000 && d.ObservedAtMs > 0 && d.LegacyBaselineMetres is null or >= 0 &&
        (!d.Protected || d.LegacyBaselineMetres is not null) && d.Epoch is { Length: 32 } && d.Epoch.All(Uri.IsHexDigit) &&
        d.ProtectedAcceptedFixes >= 0 && d.ProtectedRejectedFixes >= 0 && d.ShadowAcceptedFixes >= 0 && d.ShadowRejectedFixes >= 0 &&
        d.RejectedReasons is not null && d.RejectedReasons.Count <= DistanceIntegrity.Reasons.Length &&
        d.RejectedReasons.All(p => DistanceIntegrity.Reasons.Contains(p.Key) && p.Value >= 0) &&
        d.Receipts is not null && d.Receipts.Count <= 64 && d.Receipts.All(r => r.FirstSeq >= 1 && r.Count is >= 1 and <= 32 &&
            r.Digest is { Length: 64 } && r.Digest.All(Uri.IsHexDigit)));
}
