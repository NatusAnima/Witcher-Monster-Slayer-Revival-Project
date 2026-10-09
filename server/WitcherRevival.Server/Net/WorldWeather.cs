using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Real weather for GetWeather (67) and the world's monsters.
///
/// Client: RealWeatherProvider.UpdateWeather asks every 300 s (WeatherSettings._weatherConditionsRefreshRate) with
/// GetWeatherRequest [float lat][float lng] and reads GetWeatherResponse [int WeatherCode]: None 0, Thunderstorm 1,
/// Drizzle 2, Rain 3, Snow 4, Atmosphere 5, Clear 6, Clouds 7, the main groups of the OpenWeatherMap API. The
/// client computes the time of day and moon phase itself. ImprovePlayerOverallDamageWhenRaining (the Squall
/// potion) holds for Thunderstorm, Drizzle, Rain and Snow.
///
/// Source: the Open-Meteo forecast API (no key), asked with the position rounded to 0.1° (about 11 km), at most once
/// per cell and cache period. Positions are never logged. Without a configured URL every answer is Clear.
/// </summary>
public sealed class WorldWeather
{
    public const int None = 0, Thunderstorm = 1, Drizzle = 2, Rain = 3, Snow = 4, Atmosphere = 5, Clear = 6, Clouds = 7;

    private readonly string? _url;
    private readonly TimeSpan _ttl;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(4) };
    private readonly object _gate = new();
    private sealed record CachedWeather(DateTimeOffset AttemptedAt, int Code, DateTimeOffset? DataAt, bool FetchSucceeded);
    public sealed record Answer(int Code, string Source, DateTimeOffset At, string ValueStatus, DateTimeOffset? DataAt);
    private readonly Dictionary<(int Lat, int Lng), CachedWeather> _cells = new();
    private readonly HashSet<(int, int)> _refreshing = new();
    private int _current = Clear;
    private readonly string? _overridePath;
    private OverrideSettings _override = new();
    private long _nextPolicyRead;
    private DateTimeOffset? _lastFetchAt;
    private Answer? _lastAnswered;
    private string _lastFetchOutcome = "not-requested", _policyStatus = "automatic";

    public sealed record OverrideSettings(int SchemaVersion = 1, string Mode = "automatic", int? Code = null,
        DateTimeOffset? ExpiresAt = null);
    public static readonly JsonSerializerOptions PolicyJson = new(JsonSerializerDefaults.Web)
    { WriteIndented = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow };

    public static void ValidateOverride(OverrideSettings settings, bool requireFuture = true)
    {
        if (settings.SchemaVersion != 1 || settings.Mode is not ("automatic" or "manual"))
            throw new InvalidDataException("Invalid weather policy schema or mode.");
        if (settings.Mode == "automatic")
        {
            if (settings.Code is not null || settings.ExpiresAt is not null)
                throw new InvalidDataException("Automatic weather cannot carry a manual code or expiration.");
        }
        else if (settings.Code is null or < 1 or > 7 || settings.ExpiresAt is null ||
            settings.ExpiresAt > DateTimeOffset.UtcNow.AddHours(24) || requireFuture && settings.ExpiresAt <= DateTimeOffset.UtcNow)
            throw new InvalidDataException("Manual weather requires code 1–7 and a future expiration within 24 hours.");
    }

    public WorldWeather(string? url, TimeSpan ttl, string? overrideDirectory = null)
    {
        _url = string.IsNullOrWhiteSpace(url) ? null : url.Trim();
        _ttl = ttl;
        if (!string.IsNullOrWhiteSpace(overrideDirectory))
            _overridePath = Path.Combine(Path.GetFullPath(overrideDirectory), "weather.json");
    }

    public bool Enabled => _url is not null;

    /// <summary>The active override, otherwise the last automatic lookup in this process (Clear initially).
    /// Lookups also occur during map generation; this is not per-player weather telemetry.</summary>
    public int Current { get { lock (_gate) return ActiveOverride()?.Code ?? _current; } }

    // Called under _gate. A replacement never clears provider caches or living monster generations.
    private OverrideSettings? ActiveOverride()
    {
        if (_overridePath is not null && Environment.TickCount64 >= _nextPolicyRead)
        {
            _nextPolicyRead = Environment.TickCount64 + 1000;
            try
            {
                if (!File.Exists(_overridePath)) { _override = new(); _policyStatus = "automatic"; }
                else
                {
                    using var file = new FileStream(_overridePath, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
                    if (file.Length > 4096) throw new InvalidDataException();
                    var settings = JsonSerializer.Deserialize<OverrideSettings>(file, PolicyJson) ?? throw new InvalidDataException();
                    ValidateOverride(settings, requireFuture: false);
                    _override = settings; _policyStatus = "valid";
                }
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            { _policyStatus = "invalid-kept-last-valid"; }
        }
        return _override.Mode == "manual" && _override.ExpiresAt > DateTimeOffset.UtcNow ? _override : null;
    }

    public object Status()
    {
        lock (_gate)
        {
            var active = ActiveOverride();
            return new { mode = active is null ? "automatic" : "manual", code = active?.Code ?? (Enabled ? (int?)null : Clear),
                source = active is not null ? "manual" : Enabled ? "open-meteo" : "clear-fallback",
                overrideActive = active is not null, expiresAt = active?.ExpiresAt,
                observedAt = (DateTimeOffset?)null, lastAnswered = _lastAnswered, providerConfigured = Enabled, cachedCells = _cells.Count,
                generations = _generations.Count, cacheSeconds = _ttl.TotalSeconds,
                lastFetchAt = _lastFetchAt, lastFetchOutcome = _lastFetchOutcome, policyStatus = _policyStatus,
                valueStatus = active is not null ? "override" : Enabled ? "location-dependent" : "fallback" };
        }
    }

    /// <summary>The weather at a position: the cached value of its 0.1° cell, fetched now when the cell is unknown,
    /// refreshed in the background when it is older than the cache period.</summary>
    public int Code(double lat, double lng)
    {
        lock (_gate)
            if (ActiveOverride() is { Code: { } code }) return Remember(code, "manual", "override", null);
        if (_url is null || WorldTuning.Current.Get(WorldTuning.RealWeather) == 0 || !double.IsFinite(lat) || !double.IsFinite(lng) || Math.Abs(lat) > 90 || Math.Abs(lng) > 180)
            return Remember(Clear, "clear-fallback", "fallback", null);
        var cell = ((int)Math.Round(lat * 10), (int)Math.Round(lng * 10));
        CachedWeather? known;
        bool have;
        lock (_gate) have = _cells.TryGetValue(cell, out known);
        if (!have) return Remember(Fetch(cell), cached: false);
        if (DateTimeOffset.UtcNow - known!.AttemptedAt >= _ttl)
        {
            bool start;
            lock (_gate) start = _refreshing.Add(cell);
            if (start) _ = Task.Run(() => { try { Fetch(cell); } finally { lock (_gate) _refreshing.Remove(cell); } });
        }
        return Remember(known, cached: true);
    }

    // The weather each monster generation of a cell was drawn under: one value for every player, kept for the
    // generation's life so its monster stays the same whoever asks and whenever.
    private readonly Dictionary<(ulong Cell, long Generation), int> _generations = new();

    /// <summary>The weather a cell's monster generation is drawn under, fixed on first use (Clear when off).</summary>
    public int ForGeneration(ulong cellId, double lat, double lng, long generation)
    {
        lock (_gate)
            if (_generations.TryGetValue((cellId, generation), out int known)) return known;
        int code = Code(lat, lng);
        lock (_gate)
        {
            if (_generations.Count > 16384) _generations.Clear();
            return _generations.TryAdd((cellId, generation), code) ? code : _generations[(cellId, generation)];
        }
    }

    private int Remember(CachedWeather value, bool cached) => Remember(value.Code,
        value.DataAt is null ? "clear-fallback" : cached || !value.FetchSucceeded ? "open-meteo-cache" : "open-meteo",
        value.DataAt is null ? "fallback" : !value.FetchSucceeded || DateTimeOffset.UtcNow - value.DataAt > _ttl ? "stale-cache" : cached ? "cached" : "observed",
        value.DataAt);

    private int Remember(int code, string source, string valueStatus, DateTimeOffset? dataAt)
    {
        lock (_gate)
        {
            if (source != "manual") _current = code;
            _lastAnswered = new(code, source, DateTimeOffset.UtcNow, valueStatus, dataAt);
        }
        return code;
    }

    private CachedWeather Fetch((int Lat, int Lng) cell)
    {
        int? code = null;
        try
        {
            string lat = (cell.Lat / 10.0).ToString("0.0", CultureInfo.InvariantCulture);
            string lng = (cell.Lng / 10.0).ToString("0.0", CultureInfo.InvariantCulture);
            using var response = _http.Send(new HttpRequestMessage(HttpMethod.Get,
                $"{_url}?latitude={lat}&longitude={lng}&current=weather_code"));
            if (response.IsSuccessStatusCode)
            {
                using var json = JsonDocument.Parse(response.Content.ReadAsStream());
                code = FromWmo(json.RootElement.GetProperty("current").GetProperty("weather_code").GetInt32());
            }
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or KeyNotFoundException
                                     or InvalidOperationException) { }
        // A failed request keeps the cell's last value (or Clear) until the next period.
        lock (_gate)
        {
            _lastFetchAt = DateTimeOffset.UtcNow;
            _cells.TryGetValue(cell, out var old);
            _lastFetchOutcome = code is not null ? "success" : old?.DataAt is not null ? "failed-kept-cache" : "failed-clear-fallback";
            var value = new CachedWeather(DateTimeOffset.UtcNow, code ?? old?.Code ?? Clear,
                code is not null ? DateTimeOffset.UtcNow : old?.DataAt, code is not null);
            _cells[cell] = value;
            return value;
        }
    }

    /// <summary>WMO weather interpretation codes (Open-Meteo) to the client's OpenWeatherMap groups.</summary>
    public static int FromWmo(int wmo) => wmo switch
    {
        0 or 1 => Clear,
        2 or 3 => Clouds,
        45 or 48 => Atmosphere,
        >= 51 and <= 57 => Drizzle,
        (>= 61 and <= 67) or (>= 80 and <= 82) => Rain,
        (>= 71 and <= 77) or 85 or 86 => Snow,
        >= 95 and <= 99 => Thunderstorm,
        _ => Clouds,
    };

    /// <summary>Precipitation as the client counts it for ImprovePlayerOverallDamageWhenRaining.</summary>
    public static bool IsRaining(int code) => code is Thunderstorm or Drizzle or Rain or Snow;

    public static bool IsFoggy(int code) => code == Atmosphere;
}
