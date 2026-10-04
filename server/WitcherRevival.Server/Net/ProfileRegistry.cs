using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The server's players and which profile each one plays.
///
/// Client: ClientWorker.Run (0x19311C4) authenticates with AuthenticationModule._deviceId, which is
/// SystemInfo.deviceUniqueIdentifier (InitializeModule 0x17AD17C), and with AuthenticationData.AccountID, set by a
/// Device, Apple or Google login (LoginMethod), kept in the game's saved data and cleared on logout. The client's
/// own player id is the account when there is one, otherwise the device (GetPlayerId 0x17AD66C).
///
/// The server follows the same rule:
///   - a device without an account plays the device's guest profile, created on its first visit;
///   - the first time an account logs in, it takes over the guest profile of the device it logs in on, and from then
///     on the profile belongs to the account and follows it to any device; that device is then only recorded as one
///     of the account's devices, and it has no guest profile until it plays without an account again;
///   - an account that already has a profile plays it on every device, and a guest profile on that device stays the
///     device's (nothing is merged);
///   - logging out leaves the account's profile to the account: the device goes on as a guest with a new profile,
///     and another account that then logs in for the first time takes over that guest profile, never the first
///     account's.
///
/// Identifiers are never stored, logged or returned: players.json (readable by the owner only) keys devices and
/// accounts by an HMAC-SHA256 of the identifier under a secret the server generates on its first start
/// (identity.key). Profile ids are random ("p" and 31 hex digits), since a profile can pass from a device to an
/// account. Every profile has its own store (file and lock) and its own PlayerService, which holds that player's game
/// state and answers their requests; two connections of one player share them.
/// </summary>
public sealed class ProfileRegistry : IDisposable
{
    /// <summary>A device: its guest profile (none after an account took it over) and when it was last seen.</summary>
    public sealed record DeviceEntry(string? Profile, long LastSeen);

    /// <summary>An account: its profile, the devices it logged in on, and when it was last seen.</summary>
    public sealed record AccountEntry(string Profile, List<string> Devices, long LastSeen);

    /// <summary>The identity index saved as players.json.</summary>
    public sealed record Index(Dictionary<string, DeviceEntry> Devices, Dictionary<string, AccountEntry> Accounts);

    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    private readonly ILoggerFactory _loggers;
    private readonly IConfiguration _cfg;
    private readonly WorldWeather _weather;
    private readonly WorldPolicy _world;
    private readonly TaskEngine _tasks;
    private readonly SocialService _social;
    private readonly ILogger<ProfileRegistry> _log;
    private readonly string _directory;
    private readonly string? _newProfileMode;
    private readonly byte[] _key;
    private readonly string _indexPath;
    private readonly Index _index;
    private readonly object _gate = new();
    private readonly Dictionary<string, (LocalProfileStore Store, PlayerService Player)> _open = new();

    public ProfileRegistry(IConfiguration cfg, ILoggerFactory loggers, WorldWeather weather, TaskEngine tasks, WorldPolicy world)
    {
        _cfg = cfg;
        _loggers = loggers;
        _weather = weather;
        _world = world;
        _tasks = tasks;
        _log = loggers.CreateLogger<ProfileRegistry>();
        _newProfileMode = cfg["LocalProfile:NewProfileMode"];
        _directory = LocalProfileStore.PrepareDirectory(cfg["LocalProfile:DataDirectory"] ?? "data/profiles");
        _key = LoadOrCreateKey(Path.Combine(_directory, "identity.key"));
        _indexPath = Path.Combine(_directory, "players.json");
        _index = File.Exists(_indexPath)
            ? JsonSerializer.Deserialize<Index>(File.ReadAllBytes(_indexPath)) ?? throw new InvalidDataException("Empty players index.")
            : new Index(new(), new());
        _social = new SocialService(cfg, _directory, OpenSocialStore);
    }

    /// <summary>The profile an authenticated player plays (see the class summary).</summary>
    public string Resolve(ReadOnlySpan<byte> deviceId, ReadOnlySpan<byte> accountId)
    {
        string? device = deviceId.Length > 0 ? Key('d', deviceId) : null;
        string? account = accountId.Length > 0 ? Key('a', accountId) : null;
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        lock (_gate)
        {
            string profile, how;
            if (account is not null)
            {
                if (_index.Accounts.TryGetValue(account, out var known))
                {
                    profile = known.Profile;
                    how = "account";
                    var devices = known.Devices.ToList();
                    if (device is not null && !devices.Contains(device)) devices.Add(device);
                    _index.Accounts[account] = known with { Devices = devices, LastSeen = now };
                }
                else if (device is not null && _index.Devices.GetValueOrDefault(device)?.Profile is { } guest)
                {
                    profile = guest;
                    how = "account-took-guest";
                    _index.Accounts[account] = new AccountEntry(guest, [device], now);
                    _index.Devices[device] = new DeviceEntry(null, now);
                }
                else
                {
                    profile = NewProfileId();
                    how = "account-new";
                    _index.Accounts[account] = new AccountEntry(profile, device is null ? [] : [device], now);
                }
                if (device is not null && !_index.Devices.ContainsKey(device)) _index.Devices[device] = new DeviceEntry(null, now);
            }
            else if (device is not null)
            {
                var entry = _index.Devices.GetValueOrDefault(device);
                if (entry?.Profile is { } guest) { profile = guest; how = "guest"; }
                else { profile = NewProfileId(); how = "guest-new"; }
                _index.Devices[device] = new DeviceEntry(profile, now);
            }
            else throw new InvalidDataException("No player identifier.");
            SaveIndex();
            _log.LogInformation("Player resolved profile={Profile} via={How}", profile, how);
            return profile;
        }
    }

    private readonly Dictionary<string, int> _sessions = new();

    /// <summary>Acquire a session and its current PlayerService under the same gate as administration.</summary>
    public (PlayerService Player, IDisposable Lease) Connect(string profileId)
    {
        lock (_gate)
        {
            var player = Open(profileId).Player;
            _sessions[profileId] = _sessions.GetValueOrDefault(profileId) + 1;
            return (player, new SessionLease(this, profileId));
        }
    }

    private sealed class SessionLease(ProfileRegistry registry, string id) : IDisposable
    {
        private bool disposed;
        public void Dispose()
        {
            lock (registry._gate)
            {
                if (disposed) return;
                disposed = true;
                int count = registry._sessions.GetValueOrDefault(id) - 1;
                if (count <= 0) registry._sessions.Remove(id); else registry._sessions[id] = count;
            }
        }
    }

    public int ActiveSessions(string id) { lock (_gate) return _sessions.GetValueOrDefault(id); }

    public sealed record IdentitySummary(string IdentityKind, int DeviceCount);

    /// <summary>Operator metadata only: never expose identity keys, identifiers, or authentication bodies.</summary>
    public IdentitySummary DescribeIdentity(string profileId)
    {
        lock (_gate)
        {
            var accounts = _index.Accounts.Values.Where(a => a.Profile == profileId).ToArray();
            if (accounts.Length > 0)
                return new("account", accounts.SelectMany(a => a.Devices).Distinct().Count());
            int guests = _index.Devices.Values.Count(d => d.Profile == profileId);
            return new(guests > 0 ? "guest" : "unbound", guests);
        }
    }

    /// <summary>Reset, copy progress, or advance a story clock only while all affected profiles are offline.
    /// Identity bindings and the source remain unchanged. Revision checks reject stale operator review.</summary>
    public LocalProfileStore.Profile AdminChange(string target, long expectedRevision, string action,
        string? source, long? sourceRevision, long seconds, Action<LocalProfileStore.Profile> backup,
        LocalProfileStore.Profile? restore = null)
    {
        return _social.WithProfileAdministration(() =>
        {
        lock (_gate)
        {
            var saved = Saved();
            if (!saved.Contains(target) || source is not null && !saved.Contains(source))
                throw new InvalidOperationException("Saved profile no longer exists.");
            if (_sessions.GetValueOrDefault(target) > 0 || source is not null && _sessions.GetValueOrDefault(source) > 0)
                throw new InvalidOperationException("Close LAB on both affected devices before changing progress.");
            var entry = Open(target);
            var current = entry.Store.Snapshot();
            if (current.Revision != expectedRevision || current.Player is null)
                throw new InvalidOperationException("Profile changed or uses a legacy format; refresh before retrying.");
            var template = current;
            if (action == "reset")
                template = new LocalProfileStore.Profile(2, target, current.Revision, new(), Reconstruction.TutorialGhoul, Reconstruction.StartState());
            else if (action == "copy")
            {
                if (source is null || source == target || sourceRevision is null)
                    throw new InvalidOperationException("Choose a different saved source profile.");
                template = Open(source).Store.Snapshot();
                if (template.Revision != sourceRevision || template.Player is null)
                    throw new InvalidOperationException("Source changed or uses a legacy format; refresh before retrying.");
            }
            else if (action == "restore")
            {
                if (restore is null || restore.ProfileId != target) throw new InvalidOperationException("The backup belongs to another profile.");
                template = restore;
            }
            else if (action == "clock")
            {
                if (seconds < 1 || seconds > 30L * 86400) throw new InvalidOperationException("Clock advance must be within 1 second and 30 days.");
                var story = current.Player.Story ?? LocalProfileStore.StoryProgress.Empty;
                template = current with { Player = current.Player with { Story = story with { Clock = checked(story.Clock + seconds) } } };
            }
            else throw new InvalidOperationException("Unsupported profile operation.");
            var result = entry.Store.AdminReplace(expectedRevision, template, backup, rebaseMovement: action is "reset" or "copy" or "restore");
            // No connected session may retain request caches or map state from the replaced profile.
            _open[target] = (entry.Store, new PlayerService(_loggers.CreateLogger<PlayerService>(), _cfg, entry.Store, _weather, _tasks, _world, _social));
            return result;
        }
        });
    }

    /// <summary>The saved profiles.</summary>
    public IReadOnlyList<string> Saved() => Directory.EnumerateFiles(_directory, "p*.json")
        .Select(path => Path.GetFileNameWithoutExtension(path)!).Where(name => name != "players").Order().ToList();

    /// <summary>The store of a profile, opened on first use (a new profile is created in memory and saved with its
    /// first change).</summary>
    public LocalProfileStore Store(string profileId) => Open(profileId).Store;

    public object SocialSummary(string profileId) => _social.OperatorSummary(profileId);

    /// <summary>The game service of a profile.</summary>
    public PlayerService Player(string profileId) => Open(profileId).Player;

    private LocalProfileStore OpenSocialStore(string profileId)
    {
        LocalProfileStore.CheckProfileId(profileId);
        lock (_gate)
        {
            if (_open.TryGetValue(profileId, out var live)) return live.Store;
            // A social reference cannot recreate a deleted player's inventory or identity.
            if (!File.Exists(Path.Combine(_directory, profileId + ".json")))
                throw new InvalidOperationException("Referenced social profile is unavailable.");
            return Open(profileId).Store;
        }
    }

    private (LocalProfileStore Store, PlayerService Player) Open(string profileId)
    {
        lock (_gate)
        {
            if (_open.TryGetValue(profileId, out var open)) return open;
            var store = new LocalProfileStore(_directory, profileId, _newProfileMode, _tasks);
            var player = new PlayerService(_loggers.CreateLogger<PlayerService>(), _cfg, store, _weather, _tasks, _world, _social);
            _open[profileId] = (store, player);
            return (store, player);
        }
    }

    private static string NewProfileId() => "p" + Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant()[..31];

    private string Key(char kind, ReadOnlySpan<byte> identifier)
    {
        byte[] message = new byte[identifier.Length + 1];
        message[0] = (byte)kind;
        identifier.CopyTo(message.AsSpan(1));
        try { return Convert.ToHexString(HMACSHA256.HashData(_key, message)).ToLowerInvariant(); }
        finally { CryptographicOperations.ZeroMemory(message); }
    }

    private void SaveIndex() => WritePrivate(_indexPath, JsonSerializer.SerializeToUtf8Bytes(_index, Json));

    private static byte[] LoadOrCreateKey(string path)
    {
        if (File.Exists(path)) return Convert.FromHexString(File.ReadAllText(path).Trim());
        byte[] key = RandomNumberGenerator.GetBytes(32);
        WritePrivate(path, Encoding.ASCII.GetBytes(Convert.ToHexString(key)));
        return key;
    }

    private static void WritePrivate(string path, byte[] contents)
    {
        string pending = path + ".pending";
        try
        {
            File.WriteAllBytes(pending, contents);
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(pending, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            File.Move(pending, path, overwrite: true);
        }
        finally { if (File.Exists(pending)) File.Delete(pending); }
    }

    public void Dispose()
    {
        _social.Dispose();
        lock (_gate) foreach (var (store, _) in _open.Values) store.Dispose();
    }
}
