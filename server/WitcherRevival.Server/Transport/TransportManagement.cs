using System.Security.Cryptography;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Transport;

public sealed partial class TransportRegistry
{
    // This projection is the only registry data exposed through the operator API.
    public sealed record Installation(string Code, string Status, string? Profile,
        long CreatedAt, long PendingUntil, long ExpiresAt);
    public sealed record ManagementState(long Revision, long ObservedAt, bool EnrollmentOpen,
        long EnrollmentUntil, int EnrollmentRemaining, Installation[] Entries);
    public sealed record ManagementWrite(long? Revision, string Action, string Confirm,
        string? Code = null, string? Profile = null, bool NewProfile = false, int Seconds = 0, int Slots = 0);

    private static ManagementState ManagementView(Document doc)
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        return new(doc.Revision, now, doc.EnrollmentUntil > now && doc.EnrollmentRemaining > 0,
            doc.EnrollmentUntil, doc.EnrollmentRemaining, doc.Entries.Select(e => new Installation(
                e.Code, e.Status == "revoked" ? "revoked" : e.Status == "pending"
                    ? e.PendingUntil > now ? "pending" : "request-expired"
                    : e.ExpiresAt > now ? "approved" : "expired",
                e.Profile, e.CreatedAt, e.PendingUntil, e.ExpiresAt)).ToArray());
    }

    public ManagementState ManagementSnapshot() => Locked(doc => (doc, ManagementView(doc)));

    public ManagementState Manage(ManagementWrite write, string profileDirectory) => Locked(doc =>
    {
        if (write.Revision is null || write.Revision != doc.Revision)
            throw new InvalidOperationException("Installation state changed. Refresh and review before saving.");
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        Document next;
        if (write.Action is "open" or "close")
        {
            if (write.Confirm != "enrollment" || write.Code is not null || write.Profile is not null || write.NewProfile)
                throw new ArgumentException("Invalid enrollment change.");
            if (write.Action == "open" && (write.Seconds is < 1 or > 600 || write.Slots is < 1 or > 16))
                throw new ArgumentException("Enrollment permits up to ten minutes and sixteen requests.");
            if (write.Action == "close" && (write.Seconds != 0 || write.Slots != 0)) throw new ArgumentException();
            next = doc with { Revision = checked(doc.Revision + 1),
                EnrollmentUntil = write.Action == "open" ? now + write.Seconds : 0,
                EnrollmentRemaining = write.Action == "open" ? write.Slots : 0 };
        }
        else
        {
            if (write.Action is not ("approve" or "renew" or "rebind" or "revoke") || write.Code is null ||
                write.Confirm != write.Code || write.Slots != 0) throw new ArgumentException("Confirm the selected pairing code.");
            var entry = doc.Entries.SingleOrDefault(e => e.Code == write.Code)
                ?? throw new InvalidOperationException("The selected installation is unavailable.");
            if (write.Action is "approve" or "renew" && write.Seconds is < 1 or > 31536000) throw new ArgumentException();
            if (write.Action is "rebind" or "revoke" && write.Seconds != 0) throw new ArgumentException();
            if (write.Action is "renew" or "revoke" && (write.Profile is not null || write.NewProfile)) throw new ArgumentException();
            if (write.Action == "approve" && (entry.Status != "pending" || entry.PendingUntil <= now))
                throw new InvalidOperationException("The pairing request expired or is no longer pending.");
            if (write.Action is "renew" or "rebind" && (entry.Status != "approved" || entry.Profile is null))
                throw new InvalidOperationException("Only approved or expired access can be changed. Revoked access stays revoked.");
            var updated = entry;
            if (write.Action is "approve" or "rebind")
            {
                if (write.NewProfile == (write.Profile is not null)) throw new ArgumentException("Select one profile binding.");
                string profiles = Path.GetFullPath(profileDirectory);
                CheckParents(profiles);
                if (!Directory.Exists(profiles)) throw new InvalidOperationException("Player directory is unavailable.");
                string profile;
                if (write.NewProfile)
                {
                    do { profile = "p" + Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant()[..31]; }
                    while (File.Exists(Path.Combine(profiles, profile + ".json")) || doc.Entries.Any(e => e.Profile == profile));
                }
                else
                {
                    profile = write.Profile!;
                    LocalProfileStore.CheckProfileId(profile);
                    CheckRegular(Path.Combine(profiles, profile + ".json"), privateFile: true);
                }
                if (write.Action == "rebind" && profile == entry.Profile)
                    throw new InvalidOperationException("Choose a different profile.");
                updated = entry with { Profile = profile, Status = "approved",
                    ExpiresAt = write.Action == "approve" ? now + write.Seconds : entry.ExpiresAt,
                    BindingRevision = write.Action == "rebind" ? checked(entry.BindingRevision + 1) : entry.BindingRevision };
            }
            else if (write.Action == "renew") updated = entry with { ExpiresAt = now + write.Seconds };
            else updated = entry with { Status = "revoked" };
            next = doc with { Revision = checked(doc.Revision + 1),
                Entries = doc.Entries.Select(e => e.Code == entry.Code ? updated : e).ToList() };
        }
        return (next, ManagementView(next));
    });
}
