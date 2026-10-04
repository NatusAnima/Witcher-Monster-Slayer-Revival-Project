using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>Applies only at a fresh companion HELLO. Protection already latched to a profile cannot be undone.</summary>
public sealed class DistancePolicy(string? directory, ILogger log)
{
    public sealed record Settings(string Mode = "shadow");
    private readonly string? path = string.IsNullOrWhiteSpace(directory) ? null : Path.Combine(Path.GetFullPath(directory), "distance-policy.json");
    private readonly object gate = new();
    private Settings current = new();
    private long nextCheck;
    public static Settings Parse(JsonElement document)
    {
        if (document.ValueKind != JsonValueKind.Object || document.EnumerateObject().Count() != 1 ||
            !document.TryGetProperty("mode", out var mode) || mode.ValueKind != JsonValueKind.String ||
            mode.GetString() is not ("shadow" or "protected")) throw new InvalidDataException("Distance policy mode must be shadow or protected.");
        return new(mode.GetString()!);
    }
    public Settings Read(bool refresh = false)
    {
        lock (gate)
        {
            if (path is null || !refresh && Environment.TickCount64 < nextCheck) return current;
            nextCheck = Environment.TickCount64 + 1000;
            try
            {
                if (File.Exists(path))
                {
                    using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
                    if (stream.Length > 4096) throw new InvalidDataException();
                    using var document = JsonDocument.Parse(stream);
                    current = Parse(document.RootElement);
                }
                else current = new();
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
            { log.LogWarning("Distance policy reload refused; keeping last valid policy ({Reason})", ex.GetType().Name); }
            return current;
        }
    }
}
