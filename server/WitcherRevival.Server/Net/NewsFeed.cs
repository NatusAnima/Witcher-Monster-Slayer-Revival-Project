using System.Globalization;
using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace WitcherRevival.Server.Net;

// The 1.1.116 GatekeeperNewsLoader appends CurrentLanguageCode to its news base URL and reads the body
// with Newtonsoft into NewsContainer/NewsData. Both are [DataContract] types whose [DataMember] attributes
// set the JSON names (news_list, featured, id, group_id, ...), so feeds use those names, not the C# field names.
//
// Every entry needs a cover image: LazyNewsHubEntry stays in its loading state until RemoteImage reports a
// loaded texture, and RemoteImage.Load returns without a callback for an empty URL. A feed's image_url is an
// absolute HTTP(S) URL, or a file name in <News:Directory>/images served here at /news/images/<name>; an empty
// image_url becomes default.png, generated when the directory does not provide one. File names are resolved
// against the request's own scheme and host, which are the address the client used.
public sealed class NewsFeed
{
    private const int MaxBytes = 1024 * 1024;
    private const int MaxImageBytes = 2 * 1024 * 1024;
    public const string DefaultImage = "default.png";
    private static readonly Regex Language = new("^[a-z]{2,3}(?:-[a-z]{2,4})?$", RegexOptions.CultureInvariant);
    private static readonly Regex ImageName = new(@"^[A-Za-z0-9_-]{1,64}\.(png|jpg|jpeg)$", RegexOptions.CultureInvariant);
    private static readonly Lazy<byte[]> GeneratedDefault = new(DefaultPng);
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = null,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };
    private static readonly byte[] Empty = JsonSerializer.SerializeToUtf8Bytes(new NewsContainer
    {
        NewsList = [], HighlightedId = 0
    }, Json);
    private readonly string directory;
    private readonly string defaultLanguage;
    private readonly ILogger<NewsFeed> logger;
    private readonly object gate = new();
    private readonly Dictionary<string, NewsContainer> lastValid = new();
    private readonly HashSet<string> failed = new();

    public NewsFeed(IConfiguration configuration, ILogger<NewsFeed> logger)
    {
        directory = Path.GetFullPath(configuration["News:Directory"] ?? Path.Combine(AppContext.BaseDirectory, "news"));
        defaultLanguage = (configuration["News:DefaultLanguage"] ?? "pl").ToLowerInvariant();
        if (!Language.IsMatch(defaultLanguage)) throw new InvalidOperationException("Invalid News:DefaultLanguage.");
        this.logger = logger;
    }

    public IResult Response(HttpContext context, string? language)
    {
        string requested = (language ?? defaultLanguage).ToLowerInvariant();
        if (!Language.IsMatch(requested)) return Results.BadRequest();
        // Files are read on each request: an operator can atomically replace a feed without a restart.
        // Missing translations fall back to the base language, then to the configured default.
        lock (gate)
        {
            foreach (string candidate in new[] { requested, requested.Split('-')[0], defaultLanguage }.Distinct())
            {
                NewsContainer? container = Read(candidate);
                if (container is null) continue;
                context.Response.Headers.CacheControl = "no-store";
                context.Response.Headers.ContentLanguage = candidate;
                string images = $"{context.Request.Scheme}://{context.Request.Host}/news/images/";
                NewsContainer served = container with
                {
                    NewsList = container.NewsList.Select(item => item with { ImageUrl = ImageUrlFor(item.ImageUrl, images) }).ToArray()
                };
                return Results.Bytes(JsonSerializer.SerializeToUtf8Bytes(served, Json), "application/json; charset=utf-8");
            }
        }
        // With no valid feed, use the client's existing unavailable/retry UI. Never return null news.
        context.Response.StatusCode = StatusCodes.Status503ServiceUnavailable;
        context.Response.Headers.CacheControl = "no-store";
        return Results.Bytes(Empty, "application/json; charset=utf-8");
    }

    /// <summary>GET /news/images/{name}: an operator image, or the generated default cover.</summary>
    public IResult Image(string name)
    {
        if (!ImageName.IsMatch(name)) return Results.BadRequest();
        string type = name.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ? "image/png" : "image/jpeg";
        try
        {
            var file = new FileInfo(Path.Combine(directory, "images", name));
            if (file.Exists && file.Length <= MaxImageBytes) return Results.Bytes(File.ReadAllBytes(file.FullName), type);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            logger.LogWarning("News image rejected; error_type={ErrorType}", exception.GetType().Name);
        }
        return name == DefaultImage ? Results.Bytes(GeneratedDefault.Value, "image/png") : Results.NotFound();
    }

    private static string ImageUrlFor(string imageUrl, string images) =>
        imageUrl.Length == 0 ? images + DefaultImage : ImageName.IsMatch(imageUrl) ? images + imageUrl : imageUrl;

    private NewsContainer? Read(string language)
    {
        try
        {
            using var stream = new FileStream(Path.Combine(directory, language + ".json"), FileMode.Open,
                FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (stream.Length > MaxBytes) throw new InvalidDataException("News feed exceeds size limit.");
            // Bound the read even if a file grows while it is open.
            byte[] buffer = new byte[MaxBytes + 1];
            int count = 0, read;
            while (count < buffer.Length && (read = stream.Read(buffer, count, buffer.Length - count)) > 0) count += read;
            if (count > MaxBytes) throw new InvalidDataException("News feed exceeds size limit.");
            NewsContainer container = JsonSerializer.Deserialize<NewsContainer>(buffer.AsSpan(0, count), Json)
                ?? throw new InvalidDataException("Null news container.");
            Validate(container);
            lastValid[language] = container;
            failed.Remove(language);
            return container;
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or UnauthorizedAccessException or JsonException)
        {
            // Do not log authored content or configured paths. Repeated failures do not flood the log.
            if (exception is not FileNotFoundException and not DirectoryNotFoundException && failed.Add(language))
                logger.LogWarning("News feed rejected; retaining last valid content; error_type={ErrorType}", exception.GetType().Name);
            return lastValid.GetValueOrDefault(language);
        }
    }

    public static void Validate(NewsContainer container)
    {
        if (ValidationIssues(container).Length != 0) throw new InvalidDataException("Invalid news feed.");
    }

    public sealed record ValidationIssue(string Field, string Code);

    public static ValidationIssue[] ValidationIssues(NewsContainer container)
    {
        var issues = new List<ValidationIssue>();
        if (container.NewsList is null || container.NewsList.Length > 100)
            return [new("news_list", "list_limit")];
        var ids = new HashSet<int>();
        for (int index = 0; index < container.NewsList.Length; index++)
        {
            NewsItem item = container.NewsList[index];
            string path = $"news_list[{index}]";
            void Add(string field, string code) => issues.Add(new(path + "." + field, code));
            if (item is null) { issues.Add(new(path, "item_required")); continue; }
            if (item.Id <= 0 || !ids.Add(item.Id)) Add("id", "unique_positive_id");
            if (string.IsNullOrWhiteSpace(item.GroupId) || item.GroupId.Length > 128 || item.GroupId.Contains(';'))
                Add("group_id", "group_format");
            if (string.IsNullOrWhiteSpace(item.Title)) Add("title", "required_text");
            if (item.ShortDescription is null) Add("short_description", "text_required");
            if (string.IsNullOrWhiteSpace(item.Content)) Add("content", "required_text");
            if (item.Date is null || !Regex.IsMatch(item.Date, @"^\d{2}/\d{2}/\d{4}$", RegexOptions.CultureInvariant)
                || !DateTime.TryParseExact(item.Date, "dd/MM/yyyy", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
                Add("date", "calendar_date");
            if (item.ImageUrl is null) Add("image_url", "text_required");
            else if (item.ImageUrl.Length > 0 && !ImageName.IsMatch(item.ImageUrl)
                && (!Uri.TryCreate(item.ImageUrl, UriKind.Absolute, out Uri? uri) || uri.Scheme is not ("http" or "https")))
                Add("image_url", "image_format");
        }
        if (container.HighlightedId != 0 && !ids.Contains(container.HighlightedId))
            issues.Add(new("featured", "featured_missing"));
        return issues.ToArray();
    }

    /// <summary>A plain 1024x512 cover in the game's dark parchment tones, so a feed works without artwork.</summary>
    private static byte[] DefaultPng()
    {
        const int width = 1024, height = 512;
        var raw = new byte[height * (1 + width * 3)];
        for (int y = 0; y < height; y++)
        {
            int row = y * (1 + width * 3);
            for (int x = 0; x < width; x++)
            {
                // A vertical gradient with a thin lighter band across the middle.
                double t = (double)y / (height - 1);
                bool band = Math.Abs(y - height / 2) < 3 && x > width / 8 && x < width * 7 / 8;
                raw[row + 1 + x * 3] = (byte)(band ? 150 : 28 + 40 * t);
                raw[row + 2 + x * 3] = (byte)(band ? 126 : 26 + 32 * t);
                raw[row + 3 + x * 3] = (byte)(band ? 90 : 23 + 20 * t);
            }
        }
        using var png = new MemoryStream();
        png.Write([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
        var header = new byte[13];
        System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(header, width);
        System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(4), height);
        header[8] = 8; header[9] = 2;   // 8-bit RGB, no interlace
        Chunk(png, "IHDR", header);
        using (var compressed = new MemoryStream())
        {
            using (var zlib = new ZLibStream(compressed, CompressionLevel.Optimal, leaveOpen: true)) zlib.Write(raw);
            Chunk(png, "IDAT", compressed.ToArray());
        }
        Chunk(png, "IEND", []);
        return png.ToArray();
    }

    private static void Chunk(Stream png, string type, byte[] data)
    {
        Span<byte> number = stackalloc byte[4];
        System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(number, data.Length);
        png.Write(number);
        byte[] body = [.. System.Text.Encoding.ASCII.GetBytes(type), .. data];
        png.Write(body);
        uint crc = 0xFFFFFFFF;
        foreach (byte b in body)
        {
            crc ^= b;
            for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320 & (0 - (crc & 1)));
        }
        System.Buffers.Binary.BinaryPrimitives.WriteUInt32BigEndian(number, ~crc);
        png.Write(number);
    }
}

public sealed record NewsContainer
{
    [JsonPropertyName("news_list")] public required NewsItem[] NewsList { get; init; }
    [JsonPropertyName("featured")] public required int HighlightedId { get; init; }
}

public sealed record NewsItem
{
    [JsonPropertyName("id")] public required int Id { get; init; }
    [JsonPropertyName("group_id")] public required string GroupId { get; init; }
    [JsonPropertyName("title")] public required string Title { get; init; }
    [JsonPropertyName("short_description")] public required string ShortDescription { get; init; }
    [JsonPropertyName("date")] public required string Date { get; init; }
    [JsonPropertyName("image_url")] public required string ImageUrl { get; init; }
    [JsonPropertyName("content")] public required string Content { get; init; }
}
