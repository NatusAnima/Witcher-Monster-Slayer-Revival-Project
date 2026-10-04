namespace WitcherRevival.Server.Net;

/// <summary>Authored walking policy for full location fixes, independent of the rendered player transform.
/// Coordinates and baselines exist only in memory. A segment waits for a subsequent plausible fix before
/// credit; gaps, resets and jumps discard that pending segment. This is not location attestation.</summary>
public static class DistanceIntegrity
{
    public const double MaxAccuracy = 25, MaxSpeed = 3.5;
    public const int SessionLeaseSeconds = 90;

    /// <summary>Caller serializes access. A silent or half-open session cannot reserve the profile forever.
    /// Takeover needs a fresh HELLO; an expired or replaced owner cannot renew by sending an old batch.</summary>
    public sealed class SessionLease(Func<long>? monotonicMilliseconds = null)
    {
        private readonly Func<long> clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
        private Guid? owner;
        private long activity;
        private const long DurationMs = SessionLeaseSeconds * 1000L;
        public bool Active => owner is not null && clock() - activity is >= 0 and < DurationMs;
        public bool Owns(Guid session) => owner == session;
        public bool IsCurrent(Guid session) => Owns(session) && Active;
        public bool CanAcquire(Guid session) => !Active || Owns(session);
        public void Acquire(Guid session) { owner = session; activity = clock(); }
        public bool Renew(Guid session)
        {
            if (!IsCurrent(session)) return false;
            activity = clock(); return true;
        }
        public bool Release(Guid session)
        {
            if (!Owns(session)) return false;
            owner = null; return true;
        }
    }
    public const int MaxGapSeconds = 30, MaxAgeSeconds = 120, ConfirmationSeconds = 5,
        AcquisitionSeconds = 10, RetentionSeconds = 120, MaxEvents = 32, EventRetentionSeconds = 3600;
    public sealed record Fix(long CapturedUtcMs, long ElapsedMs, double Lat, double Lng, float Accuracy, uint Flags);
    public sealed record Pending(Fix From, Fix To, double Metres);
    public sealed record Track(Fix? Last = null, Fix? Anchor = null, Fix? AcquiringFrom = null,
        int Stable = 0, Pending? Pending = null);
    public sealed record Result(Track Track, string Decision, string Reason, double Metres = 0);
    public static readonly string[] Reasons = ["baseline", "acquiring", "walking", "stationary", "confirming",
        "invalid-fix", "missing-accuracy", "inaccurate", "mock-location", "non-monotonic", "clock-discontinuity",
        "stale-fix", "future-fix", "long-gap", "speed-jump", "return-jump", "resynchronized", "session-reset",
        "capture-overlap", "legacy-blocked"];

    private static Track Acquire(Fix f) => new(Last: f, AcquiringFrom: f, Stable: 1);
    private static Result Reject(string reason, Fix? baseline = null) =>
        new(baseline is null ? new Track() : Acquire(baseline), "rejected", reason);
    private static double Noise(Fix a, Fix b) => Math.Max(3, a.Accuracy + b.Accuracy);
    public static double Metres(Fix a, Fix b)
    {
        const double radians = Math.PI / 180;
        double dlat = (b.Lat - a.Lat) * radians, dlon = (b.Lng - a.Lng) * radians;
        double h = Math.Pow(Math.Sin(dlat / 2), 2) + Math.Cos(a.Lat * radians) * Math.Cos(b.Lat * radians) * Math.Pow(Math.Sin(dlon / 2), 2);
        return 6371000 * 2 * Math.Asin(Math.Sqrt(Math.Clamp(h, 0, 1)));
    }

    public static Result Evaluate(Track track, Fix f, long nowMs)
    {
        if (!double.IsFinite(f.Lat) || !double.IsFinite(f.Lng) || f.Lat is < -90 or > 90 || f.Lng is < -180 or > 180 ||
            f.ElapsedMs < 0 || f.CapturedUtcMs <= 0) return Reject("invalid-fix");
        if ((f.Flags & 1) == 0) return Reject("missing-accuracy");
        if ((f.Flags & 2) != 0) return Reject("mock-location");
        if (!float.IsFinite(f.Accuracy) || f.Accuracy <= 0 || f.Accuracy > MaxAccuracy) return Reject("inaccurate");
        if (f.CapturedUtcMs < nowMs - MaxAgeSeconds * 1000L) return Reject("stale-fix");
        if (f.CapturedUtcMs > nowMs + 15000) return Reject("future-fix");
        if ((f.Flags & 4) != 0) return new(Acquire(f), "ignored", "session-reset");
        if (track.Last is not { } last) return new(Acquire(f), "ignored", "baseline");
        if (f.ElapsedMs <= last.ElapsedMs || f.CapturedUtcMs <= last.CapturedUtcMs) return Reject("non-monotonic");
        // Differences are safe after positive ordered timestamps. Speed always uses monotonic capture time.
        long dtMs = f.ElapsedMs - last.ElapsedMs, utcDt = f.CapturedUtcMs - last.CapturedUtcMs;
        if (Math.Abs((double)utcDt - dtMs) > 5000) return Reject("clock-discontinuity", f);
        if (dtMs > MaxGapSeconds * 1000L) return Reject("long-gap", f);
        if (Metres(last, f) > MaxSpeed * dtMs / 1000d + Noise(last, f)) return Reject("speed-jump", f);
        if (track.Anchor is null)
        {
            var start = track.AcquiringFrom ?? last;
            if (Metres(start, f) > MaxSpeed * (f.ElapsedMs - start.ElapsedMs) / 1000d + Noise(start, f))
                return Reject("speed-jump", f);
            int stable = track.Stable + 1;
            return stable >= 3 && f.ElapsedMs - start.ElapsedMs >= AcquisitionSeconds * 1000L
                ? new(new Track(Last: f, Anchor: f), "ignored", "resynchronized")
                : new(track with { Last = f, Stable = stable }, "ignored", "acquiring");
        }
        var anchor = track.Anchor;
        // Long stationary runs must not retain an old coordinate indefinitely or credit a later drift from it.
        if (f.ElapsedMs - anchor.ElapsedMs > RetentionSeconds * 1000L)
            return new(new Track(Last: f, Anchor: f), "ignored", "resynchronized");
        double window = (f.ElapsedMs - anchor.ElapsedMs) / 1000d, displacement = Metres(anchor, f);
        if (window >= AcquisitionSeconds && displacement > Noise(anchor, f) && displacement / window > MaxSpeed)
            return Reject("speed-jump", f);
        double credit = 0;
        var pending = track.Pending;
        if (pending is not null)
        {
            // Returning immediately to the pre-jump point must not settle an outbound spike.
            if (Metres(pending.From, f) <= Noise(pending.From, f) && pending.Metres > Noise(pending.From, pending.To))
                return Reject("return-jump", f);
            if (f.ElapsedMs - pending.To.ElapsedMs >= ConfirmationSeconds * 1000L)
            { credit = pending.Metres; pending = null; }
        }
        if (pending is null && window >= AcquisitionSeconds && displacement > Noise(anchor, f))
        {
            pending = new(anchor, f, displacement);
            anchor = f;
        }
        return new(new Track(Last: f, Anchor: anchor, Pending: pending), credit > 0 ? "accepted" : "ignored",
            credit > 0 ? "walking" : pending is not null ? "confirming" : "stationary", credit);
    }
}
