using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Pedestrian-safe points per S2 cell from playable_locations.py (the OSM stand-in for the Google Playable
/// Locations the 1.1.116 client names), and a bounded estimate of the player's current map area.
/// RPC 88 seeds it; RPC 40 supplies newly loaded cells during movement. Positions are never logged.
/// </summary>
public sealed class PlayableLocations
{
    public sealed record Place(string Id, double Lat, double Lng, int[] Biomes, string Kind);

    public sealed record Cell(ulong Id, double Lat, double Lng, IReadOnlyList<Place> Places,
        bool HasNestPlacement = false, string? NestPlaceId = null);

    private readonly string? _url;
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(5) };
    // Shared geometry only. Player area, killed monsters, herb timers and quest choices stay outside this cache.
    private sealed record Cached(IReadOnlyList<Cell> Cells, long Expires, int Points);
    private static readonly object CacheGate = new();
    private static readonly Dictionary<string, (Cached Value, LinkedListNode<string> Node)> Cache = new();
    private static readonly LinkedList<string> CacheOrder = new();
    private static readonly Dictionary<string, TaskCompletionSource<IReadOnlyList<Cell>?>> Pending = new();
    private static int cachedPoints;
    private readonly object _gate = new();
    private ulong[] _area = Array.Empty<ulong>();
    private readonly Dictionary<ulong, (double Lat, double Lng)> _centers = new();

    public PlayableLocations(string? url) => _url = string.IsNullOrWhiteSpace(url) ? null : url.TrimEnd('/');

    public bool Enabled => _url is not null;

    public IReadOnlyList<ulong> Area { get { lock (_gate) return _area; } }

    /// <summary>LoadCells/GetLocationsByCell request: [int count][ulong cellId × count].</summary>
    public static ulong[] ReadCellIds(byte[] data)
    {
        var r = new Protocol.ByteBuffer(data);
        int count = r.ReadInt();
        if (count < 0 || count > 64 || r.RemainingToRead != count * 8) throw new InvalidDataException("Invalid cell list.");
        var cells = new ulong[count];
        for (int i = 0; i < count; i++) cells[i] = r.ReadULong();
        return cells;
    }

    public void SetArea(ulong[] cells)
    {
        if (cells.Length == 0) return;
        var seed = Cells(cells.Distinct().ToArray(), 0);
        lock (_gate)
        {
            _area = cells.Distinct().Order().ToArray();
            foreach (ulong id in _centers.Keys.Where(id => !_area.Contains(id)).ToList()) _centers.Remove(id);
            if (seed is not null)
                foreach (var cell in seed.Where(c => _area.Contains(c.Id))) _centers[cell.Id] = (cell.Lat, cell.Lng);
        }
    }

    // PoiModule.LoadCells (0x1904184) sends only its cache misses in RPC 40, including empty lists.
    // Replacing the area with each delta loses the surrounding cells; accumulating forever keeps
    // the login location after a teleport. Retain nearby observed cells instead. The 2 km bound is
    // an authored estimate for level-14 neighborhoods, not a recovered GPS position or subscription.
    public void ObserveCells(IReadOnlyList<Cell> cells)
    {
        if (cells.Count == 0) return;
        double lat = cells.Average(c => c.Lat), lng = cells.Average(c => c.Lng);
        lock (_gate)
        {
            foreach (var cell in cells) _centers[cell.Id] = (cell.Lat, cell.Lng);
            var nearby = _centers.Where(c => Distance(lat, lng, c.Value.Lat, c.Value.Lng) <= 2000)
                .OrderBy(c => Distance(lat, lng, c.Value.Lat, c.Value.Lng)).Take(64).Select(c => c.Key).ToHashSet();
            foreach (ulong id in _centers.Keys.Where(id => !nearby.Contains(id)).ToList()) _centers.Remove(id);
            _area = nearby.Order().ToArray();
        }
    }

    /// <summary>Cells with their centres and places, or null when the service is off or unreachable.</summary>
    public IReadOnlyList<Cell>? Cells(IReadOnlyCollection<ulong> ids, long epoch)
    {
        if (_url is null || ids.Count == 0) return null;
        if (ids.Count > 64) throw new ArgumentOutOfRangeException(nameof(ids));
        string key = $"{_url}/cells?ids={string.Join(',', ids.Distinct().Order())}&epoch={epoch}";
        // Epoch zero is used to validate a quest destination against current placement data.
        // Keep this transactional lookup fresh; ordinary dated map geometry may be shared briefly.
        if (epoch == 0) return Fetch(key);
        TaskCompletionSource<IReadOnlyList<Cell>?> pending;
        bool owner;
        lock (CacheGate)
        {
            while (true)
            {
                if (Cache.TryGetValue(key, out var cached))
                {
                    CacheOrder.Remove(cached.Node);
                    if (cached.Value.Expires > Environment.TickCount64)
                    {
                        CacheOrder.AddLast(cached.Node);
                        return cached.Value.Cells;
                    }
                    cachedPoints -= cached.Value.Points;
                    Cache.Remove(key);
                }
                if (Pending.TryGetValue(key, out pending!)) { owner = false; break; }
                if (Pending.Count < 16)
                {
                    pending = new(TaskCreationOptions.RunContinuationsAsynchronously);
                    Pending.Add(key, pending); owner = true; break;
                }
                Monitor.Wait(CacheGate);
            }
        }
        if (!owner) return pending.Task.GetAwaiter().GetResult();
        IReadOnlyList<Cell>? result = null;
        try
        {
            result = Fetch(key);
            if (result is not null)
            {
                int points = result.Sum(c => c.Places.Count);
                lock (CacheGate)
                {
                    if (points <= 32768)
                    {
                        Cache.Add(key, (new Cached(result, Environment.TickCount64 + 10000, points), CacheOrder.AddLast(key)));
                        cachedPoints += points;
                        while (Cache.Count > 128 || cachedPoints > 32768)
                        {
                            string old = CacheOrder.First!.Value;
                            cachedPoints -= Cache[old].Value.Points;
                            CacheOrder.RemoveFirst(); Cache.Remove(old);
                        }
                    }
                }
            }
            return result;
        }
        finally
        {
            lock (CacheGate)
            {
                pending.TrySetResult(result);
                Pending.Remove(key);
                Monitor.PulseAll(CacheGate);
            }
        }
    }

    private static IReadOnlyList<Cell>? Fetch(string url)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            using var response = Http.Send(request);
            if (!response.IsSuccessStatusCode) return null;
            using var stream = response.Content.ReadAsStream();
            using var json = JsonDocument.Parse(stream);
            var cells = new List<Cell>();
            foreach (var cell in json.RootElement.EnumerateObject())
            {
                var center = cell.Value.GetProperty("center");
                var places = cell.Value.GetProperty("places").EnumerateArray().Select(p => new Place(
                    p.GetProperty("id").GetString()!, p.GetProperty("lat").GetDouble(), p.GetProperty("lng").GetDouble(),
                    p.GetProperty("biomes").EnumerateArray().Select(b => b.GetInt32()).ToArray(),
                    p.GetProperty("kind").GetString()!)).ToList();
                bool hasNest = cell.Value.TryGetProperty("nest_place_id", out var nest);
                string? nestId = hasNest && nest.ValueKind != JsonValueKind.Null ? nest.GetString() : null;
                if (nestId is not null && !places.Any(p => p.Id == nestId))
                    throw new InvalidDataException("Nemeton placement is outside the supplied cell places.");
                cells.Add(new Cell(ulong.Parse(cell.Name), center[0].GetDouble(), center[1].GetDouble(), places,
                    hasNest, nestId));
            }
            return cells;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or
                                  KeyNotFoundException or InvalidOperationException or FormatException or InvalidDataException)
        {
            return null;
        }
    }

    /// <summary>Metres between two points (equirectangular; exact enough within a few kilometres).</summary>
    public static double Distance(double lat1, double lng1, double lat2, double lng2)
    {
        double kx = 111_320.0 * Math.Cos((lat1 + lat2) / 2 * Math.PI / 180);
        return Math.Sqrt(Math.Pow((lng2 - lng1) * kx, 2) + Math.Pow((lat2 - lat1) * 110_540.0, 2));
    }
}
