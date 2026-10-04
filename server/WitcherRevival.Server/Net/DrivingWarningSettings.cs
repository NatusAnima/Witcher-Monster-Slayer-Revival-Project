using System.Globalization;
using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Optional client driving-warning overrides. Missing values leave the client's native defaults in use.
/// Read once at startup so the HTTP and socket preloaders publish the same configuration.
/// </summary>
public sealed class DrivingWarningSettings
{
    public IReadOnlyList<string> Rows { get; }

    private DrivingWarningSettings(string[] rows) => Rows = Array.AsReadOnly(rows);

    public static DrivingWarningSettings FromConfiguration(IConfiguration configuration)
    {
        var rows = new List<string>();
        // The native configuration exposes this legacy value, but its runtime use and units are unverified.
        Add("Client:DrivingWarningCooldown", "drivingWarningCooldown", 1001, 1);
        Add("Client:DrivingWarningMinSamples", "drivingWarningMinSamples", 1002, 2);
        Add("Client:DrivingWarningMinSpeedKmh", "drivingWarningMinSpeed", 1003, 1);
        return new DrivingWarningSettings(rows.ToArray());

        void Add(string key, string name, int id, int minimum)
        {
            string? configured = configuration[key];
            if (configured is null) return;
            if (!int.TryParse(configured, NumberStyles.None, CultureInfo.InvariantCulture, out int value)
                || value < minimum)
                throw new InvalidOperationException($"{key} must be an integer in {minimum}..{int.MaxValue}.");
            rows.Add(JsonSerializer.Serialize(new
            {
                id, param_name = name, param_value = value.ToString(CultureInfo.InvariantCulture)
            }));
        }
    }
}
