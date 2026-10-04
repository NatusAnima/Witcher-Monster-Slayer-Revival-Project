using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Transport;

/// <summary>Private approval records, separate from player contents and legacy identity mappings.</summary>
public sealed partial class TransportRegistry
{
    public sealed record Entry(string TokenHash, string Code, string Status, string? Profile,
        long CreatedAt, long PendingUntil, long ExpiresAt, string SourceHash,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] long BindingRevision = 0);
    public sealed record Document(int SchemaVersion, long Revision, List<Entry> Entries,
        long EnrollmentUntil = 0, int EnrollmentRemaining = 0);
    public sealed record Enrollment(string Status, string Code);
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    { WriteIndented = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow };
    private readonly string directory;
    private readonly int pendingSeconds;
    private const int MaxPending = 64, MaxEntries = 4096;

    public TransportRegistry(string directory, int pendingSeconds = 3600)
    {
        if (pendingSeconds is < 1 or > 86400) throw new InvalidOperationException("Invalid pending lifetime.");
        this.pendingSeconds = pendingSeconds;
        this.directory = Path.GetFullPath(directory);
        CheckParents(this.directory);
        Directory.CreateDirectory(this.directory);
        if (!OperatingSystem.IsWindows())
        {
            if ((File.GetUnixFileMode(this.directory) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite |
                UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0)
            {
                // A caller must prepare an existing private directory; do not silently change its permissions.
                if (Directory.EnumerateFileSystemEntries(this.directory).Any())
                    throw new InvalidOperationException("Transport registry directory must be private.");
                File.SetUnixFileMode(this.directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            }
        }
    }

    public static string? HashBearer(string authorization)
    {
        if (!authorization.StartsWith("Bearer ", StringComparison.Ordinal)) return null;
        string token = authorization[7..];
        if (!Regex.IsMatch(token, "^[A-Za-z0-9_-]{43}$", RegexOptions.CultureInvariant)) return null;
        byte[] bytes;
        try { bytes = Convert.FromBase64String(token.Replace('-', '+').Replace('_', '/') + "="); }
        catch (FormatException) { return null; }
        try
        {
            string canonical = Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
            return bytes.Length == 32 && canonical == token ? Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() : null;
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }

    public Enrollment Enroll(string hash, string sourceHash) => Locked(doc =>
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var entry = doc.Entries.SingleOrDefault(e => e.TokenHash == hash);
        if (entry is not null && !(entry.Status == "pending" && entry.PendingUntil <= now))
            return (doc, new Enrollment(EffectiveStatus(entry, now), entry.Code));
        if (doc.EnrollmentUntil <= now || doc.EnrollmentRemaining == 0)
            return (doc, new Enrollment("closed", ""));
        var retained = doc.Entries.Where(e => e.Status != "pending" || e.PendingUntil > now).ToList();
        if (retained.Count >= MaxEntries || retained.Count(e => e.Status == "pending") >= MaxPending ||
            retained.Count(e => e.Status == "pending" && e.SourceHash == sourceHash) >= 4)
            throw new RegistryCapacityException();
        string code;
        do
        {
            string random = Convert.ToHexString(RandomNumberGenerator.GetBytes(4));
            code = random[..4] + "-" + random[4..];
        } while (retained.Any(e => e.Code == code));
        retained.Add(new(hash, code, "pending", null, now, now + pendingSeconds, 0, sourceHash));
        return (doc with { Revision = doc.Revision + 1, Entries = retained,
            EnrollmentRemaining = doc.EnrollmentRemaining - 1 }, new Enrollment("pending", code));
    });

    public Entry? Approved(string hash) => Locked(doc =>
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        return (doc, doc.Entries.SingleOrDefault(e => e.TokenHash == hash && EffectiveStatus(e, now) == "approved"));
    });

    public object[] List() => Locked(doc => (doc, doc.Entries.Select(e => (object)new
    {
        e.Code, Status = EffectiveStatus(e, DateTimeOffset.UtcNow.ToUnixTimeSeconds()), e.Profile,
        e.CreatedAt, e.PendingUntil, e.ExpiresAt,
    }).ToArray()));

    public Entry Approve(string code, string profileDirectory, string? existingProfile, bool newProfile, int ttlSeconds)
    {
        if (newProfile == (existingProfile is not null) || ttlSeconds is < 1 or > 31536000)
            throw new InvalidOperationException("Choose exactly one profile binding and a bounded lifetime.");
        string profiles = Path.GetFullPath(profileDirectory);
        CheckParents(profiles);
        if (!Directory.Exists(profiles)) throw new InvalidOperationException("Player directory is unavailable.");
        return Locked(doc =>
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            var entry = doc.Entries.SingleOrDefault(e => e.Code == code);
            if (entry is null || entry.Status != "pending" || entry.PendingUntil <= now)
                throw new InvalidOperationException("An unexpired pending invitation is required.");
            string profile;
            if (existingProfile is not null)
            {
                LocalProfileStore.CheckProfileId(existingProfile);
                profile = existingProfile;
                CheckRegular(Path.Combine(profiles, profile + ".json"), privateFile: true);
            }
            else
            {
                do { profile = "p" + Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant()[..31]; }
                while (File.Exists(Path.Combine(profiles, profile + ".json")) || doc.Entries.Any(e => e.Profile == profile));
            }
            var approved = entry with { Status = "approved", Profile = profile, ExpiresAt = now + ttlSeconds };
            var rows = doc.Entries.Select(e => e.Code == code ? approved : e).ToList();
            return (doc with { Revision = doc.Revision + 1, Entries = rows }, approved);
        });
    }

    public Entry Revoke(string code) => Locked(doc =>
    {
        var entry = doc.Entries.SingleOrDefault(e => e.Code == code) ?? throw new InvalidOperationException("Unknown invitation.");
        var revoked = entry with { Status = "revoked" };
        return (entry.Status == "revoked" ? doc : doc with
        { Revision = doc.Revision + 1, Entries = doc.Entries.Select(e => e.Code == code ? revoked : e).ToList() }, revoked);
    });

    public Entry Renew(string code, int ttlSeconds) => Locked(doc =>
    {
        if (ttlSeconds is < 1 or > 31536000) throw new InvalidOperationException("Invalid approval lifetime.");
        var entry = doc.Entries.SingleOrDefault(e => e.Code == code);
        if (entry is null || entry.Status != "approved" || entry.Profile is null)
            throw new InvalidOperationException("Only an existing approval can be renewed without changing its binding.");
        var renewed = entry with { ExpiresAt = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ttlSeconds };
        return (doc with { Revision = doc.Revision + 1,
            Entries = doc.Entries.Select(e => e.Code == code ? renewed : e).ToList() }, renewed);
    });

    public object OpenEnrollment(int seconds, int slots) => Locked(doc =>
    {
        if (seconds is < 1 or > 600 || slots is < 1 or > 16)
            throw new InvalidOperationException("Enrollment windows allow at most ten minutes and sixteen new installations.");
        long until = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + seconds;
        return (doc with { Revision = doc.Revision + 1, EnrollmentUntil = until, EnrollmentRemaining = slots },
            (object)new { status = "open", enrollmentUntil = until, enrollmentRemaining = slots });
    });

    public object CloseEnrollment() => Locked(doc => (doc with
    { Revision = doc.Revision + 1, EnrollmentUntil = 0, EnrollmentRemaining = 0 }, (object)new { status = "closed" }));

    private static string EffectiveStatus(Entry e, long now) => e.Status switch
    {
        "pending" when e.PendingUntil > now => "pending",
        "approved" when e.ExpiresAt > now => "approved",
        _ => "revoked",
    };

    private T Locked<T>(Func<Document, (Document Document, T Result)> action)
    {
        string path = Path.Combine(directory, "registry.json"), lockPath = Path.Combine(directory, "registry.lock");
        CheckParents(directory);
        if (File.Exists(lockPath)) CheckRegular(lockPath, privateFile: true);
        using var held = OpenLock(lockPath);
        Document doc;
        if (File.Exists(path))
        {
            CheckRegular(path, privateFile: true);
            if (new FileInfo(path).Length > 2 * 1024 * 1024) throw new InvalidDataException("Registry exceeds its bound.");
            doc = JsonSerializer.Deserialize<Document>(File.ReadAllBytes(path), Json) ?? throw new InvalidDataException("Missing registry.");
            Validate(doc);
        }
        else doc = new(1, 0, []);
        var result = action(doc);
        if (result.Document != doc)
        {
            Validate(result.Document);
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".pending";
            try
            {
                using (var output = new FileStream(temporary, PrivateOptions(FileMode.CreateNew)))
                { JsonSerializer.Serialize(output, result.Document, Json); output.Flush(flushToDisk: true); }
                File.Move(temporary, path, overwrite: true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        return result.Result;
    }

    private static FileStreamOptions PrivateOptions(FileMode mode)
    {
        var options = new FileStreamOptions { Mode = mode, Access = FileAccess.ReadWrite, Share = FileShare.None };
        if (!OperatingSystem.IsWindows()) options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        return options;
    }

    private static FileStream OpenLock(string path)
    {
        for (int attempt = 0; ; attempt++)
        {
            try { return new FileStream(path, PrivateOptions(FileMode.OpenOrCreate)); }
            catch (IOException) when (attempt < 100) { Thread.Sleep(10); }
        }
    }

    private static void Validate(Document d)
    {
        if (d.SchemaVersion != 1 || d.Revision < 0 || d.EnrollmentUntil < 0 || d.EnrollmentRemaining is < 0 or > 16 ||
            d.Entries is null || d.Entries.Count > MaxEntries ||
            d.Entries.Any(e => e is null || !Regex.IsMatch(e.TokenHash ?? "", "^[a-f0-9]{64}$") ||
                !Regex.IsMatch(e.SourceHash ?? "", "^[a-f0-9]{64}$") ||
                !Regex.IsMatch(e.Code ?? "", "^[A-F0-9]{4}-[A-F0-9]{4}$") ||
                e.Status is not ("pending" or "approved" or "revoked") || e.BindingRevision < 0 || e.CreatedAt <= 0 || e.PendingUntil <= e.CreatedAt ||
                (e.Status == "approved" && (e.Profile is null || e.ExpiresAt <= e.CreatedAt))) ||
            d.Entries.Select(e => e.TokenHash).Distinct().Count() != d.Entries.Count ||
            d.Entries.Select(e => e.Code).Distinct().Count() != d.Entries.Count)
            throw new InvalidDataException("Invalid transport registry.");
        foreach (var e in d.Entries) if (e.Profile is not null) LocalProfileStore.CheckProfileId(e.Profile);
    }

    public static void CheckParents(string path)
    {
        for (var current = new DirectoryInfo(path); current is not null; current = current.Parent)
            if (current.LinkTarget is not null) throw new InvalidOperationException("Symlink transport directory refused.");
    }

    public static void CheckRegular(string path, bool privateFile)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.LinkTarget is not null || (info.Attributes & FileAttributes.Directory) != 0)
            throw new InvalidOperationException("A regular transport input is required.");
        if (privateFile && !OperatingSystem.IsWindows() &&
            (File.GetUnixFileMode(path) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute |
             UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0)
            throw new InvalidOperationException("Transport input must be private.");
    }
}

public sealed class RegistryCapacityException : Exception;
