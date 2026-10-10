using System.Security.Cryptography;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    private readonly object movementGate = new();
    private readonly DistanceIntegrity.SessionLease movementLease = new();
    private long movementHelloId, movementHelloElapsed, movementHelloTick;
    private string? movementHelloDigest;
    private readonly HashSet<long> oldMovementHellos = [];
    private DistanceIntegrity.Track movementTrack = new();
    private DistanceIntegrity.Fix? movementLastFix;
    // Where the game last placed the player, mock or inaccurate fixes included: story places go around it.
    private DistanceIntegrity.Fix? movementPosition;
    // Where the game last asked for the weather (GetWeather 67 carries its own position): memory only, never logged.
    private sealed record Spot(double Lat, double Lng);
    private Spot? weatherSpot;
    private long movementLastReceived;
    private string? movementReason;
    private string movementDecision = "ignored";
    private sealed record MovementEvent(DateTimeOffset At, string Decision, string Reason, double AcceptedMetres,
        double ShadowAcceptedMetres, int FixCount = 1);
    private readonly List<MovementEvent> movementEvents = [];
    private Timer? movementExpiry;

    public void ReleaseMovementSession(Guid session)
    {
        ForgetBootedSession(session);
        lock (movementGate)
            if (movementLease.Release(session))
            {
                movementTrack = new();
                oldMovementHellos.Clear();
                // A recent actual observation may remain visible until its short TTL, never used as a new baseline.
            }
    }

    private byte[] MovementAck(byte op, ushort status, int credited = 0)
    {
        var snapshot = profiles.Snapshot(); var ledger = snapshot.Movement;
        var b = new ByteBuffer(); b.WriteByte(1); b.WriteByte(op);
        b.WriteByte((byte)(status >> 8)); b.WriteByte((byte)status);
        b.WriteBytes(ledger is null ? new byte[16] : Convert.FromHexString(ledger.Epoch));
        b.WriteLong(ledger?.NextSeq ?? 1); b.WriteInt(snapshot.Player?.Distance?.Metres ?? 0);
        b.WriteInt(credited); b.WriteUInt(ledger?.Protected == true ? 1u : 0u);
        b.WriteLong(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        return b.ToArray();
    }

    private byte[] HandleMovement(ApiProtocol.ApiRequest req, Guid session, byte[] frameData)
    {
        try { return ProcessMovement(req, session); }
        finally
        {
            // Socket readers may retain their last frame while idle. Do not leave raw GPS in those buffers.
            Array.Clear(req.Data); Array.Clear(frameData);
        }
    }

    private byte[] ProcessMovement(ApiProtocol.ApiRequest req, Guid session)
    {
        lock (movementGate)
        {
            byte op = req.Data.Length > 1 ? req.Data[1] : (byte)0;
            if (session == Guid.Empty) return MovementAck(op, 2);
            try
            {
                if (req.Data.Length < 4) return MovementAck(op, 1);
                var b = new ByteBuffer(req.Data);
                if (b.ReadByte() != 1 || b.ReadByte() is not (1 or 2) || b.ReadByte() != 0 || b.ReadByte() != 0)
                    return MovementAck(op, 1);
                if (profiles.Snapshot().Player is null) return MovementAck(op, 7);
                if (op == 1)
                {
                    if (req.Data.Length != 24 || b.ReadUInt() != 7) return MovementAck(op, 1);
                    long elapsed = b.ReadLong(), utc = b.ReadLong(), now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    if (elapsed < 0 || utc < now - 120000 || utc > now + 15000) return MovementAck(op, 1);
                    if (!movementLease.CanAcquire(session)) return MovementAck(op, 4);
                    string digest = Convert.ToHexString(SHA256.HashData(req.Data));
                    if (movementLease.Owns(session) && movementHelloId == req.Id)
                    {
                        if (!movementLease.IsCurrent(session)) return MovementAck(op, 2);
                        if (movementHelloDigest != digest) return MovementAck(op, 3);
                        movementLease.Renew(session);
                        return MovementAck(op, 0);
                    }
                    if (movementLease.Owns(session) && oldMovementHellos.Contains(req.Id)) return MovementAck(op, 3);
                    bool protect = world.Distance.Read().Mode == "protected";
                    string epoch = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
                    profiles.UpdateMovement(snapshot =>
                    {
                        var old = snapshot.Movement ?? DistanceLedger.Empty;
                        return snapshot with { Movement = old with { Protected = old.Protected || protect,
                            LegacyBaselineMetres = old.LegacyBaselineMetres ?? (protect ? snapshot.Player!.Distance?.Metres ?? 0 : null),
                            ObservedAtMs = now, Epoch = epoch, NextSeq = 1, Receipts = [], RemainderMillimetres = 0 } };
                    });
                    if (movementLease.Owns(session)) oldMovementHellos.Add(movementHelloId);
                    else oldMovementHellos.Clear();
                    while (oldMovementHellos.Count > 64) oldMovementHellos.Remove(oldMovementHellos.First());
                    movementLease.Acquire(session); movementHelloId = req.Id; movementHelloDigest = digest;
                    movementHelloElapsed = elapsed; movementHelloTick = Environment.TickCount64;
                    movementTrack = new(); movementReason = "session-reset"; movementDecision = "ignored";
                    return MovementAck(op, 0);
                }
                if (req.Data.Length < 72) return MovementAck(op, 1);
                string requestedEpoch = Convert.ToHexString(b.ReadBytes(16));
                long first = b.ReadLong(); uint count = b.ReadUInt();
                if (count is < 1 or > 32 || first < 1 || first > long.MaxValue - count || req.Data.Length != 32 + count * 40)
                    return MovementAck(op, 1);
                var fixes = new DistanceIntegrity.Fix[(int)count];
                for (int i = 0; i < fixes.Length; i++)
                {
                    fixes[i] = new(b.ReadLong(), b.ReadLong(), b.ReadDouble(), b.ReadDouble(), b.ReadFloat(), b.ReadUInt());
                    if ((fixes[i].Flags & ~7u) != 0) return MovementAck(op, 1);
                }
                var current = profiles.Snapshot().Movement;
                if (!movementLease.IsCurrent(session) || current is null || current.Epoch != requestedEpoch) return MovementAck(op, 2);
                string batchDigest = Convert.ToHexString(SHA256.HashData(req.Data));
                if (first < current.NextSeq)
                {
                    var previous = current.Receipts.FirstOrDefault(r => r.FirstSeq == first);
                    if (previous?.Digest != batchDigest) return MovementAck(op, 3);
                    movementLease.Renew(session);
                    return MovementAck(op, 0);
                }
                if (first != current.NextSeq) return MovementAck(op, 3);
                long nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                long allowedElapsed = movementHelloElapsed + Math.Min(long.MaxValue - movementHelloElapsed - 15000,
                    Environment.TickCount64 - movementHelloTick) + 15000;
                var track = movementTrack;
                var decisions = new List<(DistanceIntegrity.Fix Fix, DistanceIntegrity.Result Result)>();
                long highWater = current.HighWaterUtcMs;
                foreach (var fix in fixes)
                {
                    DistanceIntegrity.Result result;
                    if (fix.CapturedUtcMs <= highWater || fix.ElapsedMs < movementHelloElapsed)
                        result = new(new(), "rejected", "capture-overlap");
                    else if (fix.ElapsedMs > allowedElapsed)
                        result = new(new(), "rejected", "clock-discontinuity");
                    else result = DistanceIntegrity.Evaluate(track, fix, nowMs);
                    track = result.Track; decisions.Add((fix, result));
                    // Bad future/invalid timestamps cannot advance the persisted capture frontier.
                    if (fix.CapturedUtcMs > 0 && fix.CapturedUtcMs <= nowMs + 15000 && fix.ElapsedMs <= allowedElapsed)
                        highWater = Math.Max(highWater, fix.CapturedUtcMs);
                }
                int credited = 0;
                profiles.UpdateMovement(snapshot =>
                {
                    var ledger = snapshot.Movement!;
                    long mm = checked((long)Math.Floor(decisions.Sum(d => d.Result.Metres) * 1000));
                    var reasons = new Dictionary<string, long>(ledger.RejectedReasons);
                    long accepted = decisions.Count(d => d.Result.Decision == "accepted"), rejected = decisions.Count(d => d.Result.Decision == "rejected");
                    foreach (var d in decisions.Where(d => d.Result.Decision == "rejected"))
                        reasons[d.Result.Reason] = checked(reasons.GetValueOrDefault(d.Result.Reason) + 1);
                    var receipts = ledger.Receipts.Append(new DistanceLedger.Receipt(first, (int)count, batchDigest)).TakeLast(64).ToList();
                    var player = snapshot.Player!;
                    var distance = player.Distance ?? new LocalProfileStore.DistanceState(0, []);
                    long availableMm = checked(mm + ledger.RemainderMillimetres);
                    if (ledger.Protected)
                    {
                        credited = (int)Math.Min(availableMm / 1000, int.MaxValue - distance.Metres);
                        if (credited > 0) player = player with { Distance = distance with { Metres = distance.Metres + credited } };
                    }
                    ledger = ledger with { NextSeq = first + count, HighWaterUtcMs = highWater, Receipts = receipts,
                        RemainderMillimetres = ledger.Protected ? (int)(availableMm % 1000) : 0,
                        CreditedMetres = checked(ledger.CreditedMetres + credited),
                        ShadowMillimetres = checked(ledger.ShadowMillimetres + (ledger.Protected ? 0 : mm)),
                        ProtectedAcceptedFixes = checked(ledger.ProtectedAcceptedFixes + (ledger.Protected ? accepted : 0)),
                        ProtectedRejectedFixes = checked(ledger.ProtectedRejectedFixes + (ledger.Protected ? rejected : 0)),
                        ShadowAcceptedFixes = checked(ledger.ShadowAcceptedFixes + (ledger.Protected ? 0 : accepted)),
                        ShadowRejectedFixes = checked(ledger.ShadowRejectedFixes + (ledger.Protected ? 0 : rejected)), RejectedReasons = reasons };
                    return snapshot with { Movement = ledger, Player = player };
                }, new TaskEngine.Action(M_DistanceTraveled));
                // Publish spatial state only after the total/frontier transaction is durable.
                movementTrack = track;
                movementLease.Renew(session);
                int eventCreditRemaining = credited;
                foreach (var d in decisions)
                {
                    int eventCredit = current.Protected ? Math.Min(eventCreditRemaining, (int)Math.Ceiling(d.Result.Metres)) : 0;
                    eventCreditRemaining -= eventCredit;
                    movementReason = d.Result.Reason; movementDecision = d.Result.Decision;
                    if (d.Result.Reason is not ("invalid-fix" or "missing-accuracy" or "inaccurate" or "mock-location" or "stale-fix" or "future-fix" or "capture-overlap" or "clock-discontinuity"))
                    { movementLastFix = d.Fix; movementLastReceived = nowMs; }
                    if (d.Result.Reason is not ("invalid-fix" or "stale-fix" or "future-fix" or "capture-overlap" or "clock-discontinuity"))
                        movementPosition = d.Fix;
                    movementEvents.Add(new(DateTimeOffset.FromUnixTimeMilliseconds(nowMs), d.Result.Decision, d.Result.Reason,
                        eventCredit, current.Protected ? 0 : d.Result.Metres));
                }
                long publishedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                PruneMovementEvents(publishedAt);
                ScheduleMovementExpiry(publishedAt);
                return MovementAck(op, 0, credited);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            { return MovementAck(op, 6); }
            catch (Exception ex) when (ex is ArgumentException or InvalidDataException or OverflowException or IndexOutOfRangeException)
            { return MovementAck(op, 1); }
        }
    }

    // A one-shot cleanup releases locations even if neither the client nor the operator asks again.
    // It disposes itself after the last bounded audit event expires, including replaced offline services.
    private void ScheduleMovementExpiry(long nowMs)
    {
        long? next = null;
        foreach (long? deadline in new long?[] {
            movementLastFix is null ? null : movementLastFix.CapturedUtcMs + DistanceIntegrity.RetentionSeconds * 1000L,
            movementPosition is null ? null : movementPosition.CapturedUtcMs + DistanceIntegrity.RetentionSeconds * 1000L,
            OldestMovementCapture() is not { } oldest ? null : oldest + DistanceIntegrity.RetentionSeconds * 1000L,
            movementEvents.Count == 0 ? null : movementEvents[0].At.ToUnixTimeMilliseconds() + DistanceIntegrity.EventRetentionSeconds * 1000L })
            if (deadline is not null) next = next is null ? deadline : Math.Min(next.Value, deadline.Value);
        if (next is null) { movementExpiry?.Dispose(); movementExpiry = null; return; }
        movementExpiry ??= new Timer(_ =>
        {
            lock (movementGate)
            {
                long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                PruneMovementEvents(now); ScheduleMovementExpiry(now);
            }
        }, null, Timeout.Infinite, Timeout.Infinite);
        movementExpiry.Change(TimeSpan.FromMilliseconds(Math.Clamp(next.Value - nowMs + 1, 1, 60000)), Timeout.InfiniteTimeSpan);
    }

    private long? OldestMovementCapture() => new long?[] { movementTrack.Last?.CapturedUtcMs,
        movementTrack.Anchor?.CapturedUtcMs, movementTrack.AcquiringFrom?.CapturedUtcMs,
        movementTrack.Pending?.From.CapturedUtcMs, movementTrack.Pending?.To.CapturedUtcMs }.Min();

    private void PruneMovementEvents(long nowMs)
    {
        movementEvents.RemoveAll(e => e.At.ToUnixTimeMilliseconds() < nowMs - DistanceIntegrity.EventRetentionSeconds * 1000L);
        if (movementEvents.Count > DistanceIntegrity.MaxEvents) movementEvents.RemoveRange(0, movementEvents.Count - DistanceIntegrity.MaxEvents);
        if (OldestMovementCapture() < nowMs - DistanceIntegrity.RetentionSeconds * 1000L) movementTrack = new();
        if (movementLastFix?.CapturedUtcMs < nowMs - DistanceIntegrity.RetentionSeconds * 1000L) movementLastFix = null;
        if (movementPosition?.CapturedUtcMs < nowMs - DistanceIntegrity.RetentionSeconds * 1000L) movementPosition = null;
    }

    /// <summary>The player's GPS position from the collector (RPC 2001) while it is fresh, else null.
    /// Lock-free: placement runs inside other locks, and the reference is replaced whole.</summary>
    private (double Lat, double Lng)? PlayerPosition() =>
        Volatile.Read(ref movementPosition) is { } fix &&
        DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - fix.CapturedUtcMs <= DistanceIntegrity.RetentionSeconds * 1000L
            ? (fix.Lat, fix.Lng) : null;

    /// <summary>Where the player stands, for story goals among the loaded <paramref name="cells"/>: the collector's fresh GPS
    /// fix, else where the game last asked for the weather while that lies inside the loaded area (the 3×3 level-14 cells
    /// reach about 900 m from their centre; the hook reads no GPS on some phones), else null (the area's centre).</summary>
    private (double Lat, double Lng)? PlayerPositionIn(IReadOnlyCollection<PlayableLocations.Cell> cells)
    {
        if (PlayerPosition() is { } fix) return fix;
        return Volatile.Read(ref weatherSpot) is { } spot && cells.Count > 0 &&
            PlayableLocations.Distance(cells.Average(c => c.Lat), cells.Average(c => c.Lng), spot.Lat, spot.Lng) <= 1000
                ? (spot.Lat, spot.Lng) : null;
    }

    public object DistanceStatus()
    {
        lock (movementGate)
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); PruneMovementEvents(now);
            var snapshot = profiles.Snapshot(); var ledger = snapshot.Movement;
            var last = movementLastFix;
            string status = ledger is null ? "not-observed" : last is null ?
                movementLease.Active && now - ledger.ObservedAtMs <= DistanceIntegrity.RetentionSeconds * 1000L ? "acquiring" : "stale" : movementDecision == "rejected" ? "rejected" :
                movementTrack.Anchor is null ? "acquiring" : "tracking";
            return new { observedAt = DateTimeOffset.FromUnixTimeMilliseconds(now), profileId = profiles.ProfileId,
                mode = ledger is null ? "legacy" : ledger.Protected ? "protected" : "shadow",
                capability = new { status = ledger is null ? "not-observed" : "observed", version = ledger is null ? (int?)null : 1,
                    observedAt = ledger is null ? (DateTimeOffset?)null : DateTimeOffset.FromUnixTimeMilliseconds(ledger.ObservedAtMs), sessionActive = movementLease.Active },
                totals = new { metres = snapshot.Player is null ? LegacyDistanceTraveled : snapshot.Player.Distance?.Metres ?? 0,
                    legacyBaselineMetres = ledger?.LegacyBaselineMetres, acceptedMetresSinceProtection = ledger?.CreditedMetres ?? 0,
                    shadowAcceptedMetres = (ledger?.ShadowMillimetres ?? 0) / 1000d,
                    rebasedAt = ledger?.RebasedAtMs is > 0 ? (DateTimeOffset?)DateTimeOffset.FromUnixTimeMilliseconds(ledger.RebasedAtMs) : null },
                counters = new { protectedAcceptedFixes = ledger?.ProtectedAcceptedFixes ?? 0, protectedRejectedFixes = ledger?.ProtectedRejectedFixes ?? 0,
                    shadowAcceptedFixes = ledger?.ShadowAcceptedFixes ?? 0, shadowRejectedFixes = ledger?.ShadowRejectedFixes ?? 0 },
                lastFix = last is null ? null : new { lat = last.Lat, lng = last.Lng, accuracyMetres = last.Accuracy,
                    capturedAt = DateTimeOffset.FromUnixTimeMilliseconds(last.CapturedUtcMs), receivedAt = DateTimeOffset.FromUnixTimeMilliseconds(movementLastReceived),
                    ageSeconds = Math.Max(0, (now - last.CapturedUtcMs) / 1000d) },
                quality = new { status, reason = movementReason }, rejectedReasons = ledger?.RejectedReasons ?? [], lastEvents = movementEvents.ToArray(),
                policy = new { version = 1, maxAccuracyMetres = DistanceIntegrity.MaxAccuracy, maxGapSeconds = DistanceIntegrity.MaxGapSeconds,
                    maxFixAgeSeconds = DistanceIntegrity.MaxAgeSeconds, maxSpeedMetresPerSecond = DistanceIntegrity.MaxSpeed,
                    retentionSeconds = DistanceIntegrity.RetentionSeconds, maxEvents = DistanceIntegrity.MaxEvents,
                    eventRetentionSeconds = DistanceIntegrity.EventRetentionSeconds, confirmationSeconds = DistanceIntegrity.ConfirmationSeconds,
                    acquisitionSeconds = DistanceIntegrity.AcquisitionSeconds, sessionLeaseSeconds = DistanceIntegrity.SessionLeaseSeconds },
                coverage = new { source = "authenticated-session-location-fixes", positionAvailable = last is not null,
                    limitations = new[] { "client-reported-not-attested", "memory-only-client-outbox", "no-distance-across-session-or-gap", "conservative-walking-filter" } } };
        }
    }
}
