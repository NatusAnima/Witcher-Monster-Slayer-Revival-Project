using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace WitcherRevival.Server.Admin;

/// <summary>Read-only, bounded process/procfs samples. No dependencies are probed and no commands are run.
/// Host values describe the procfs view, which need not match this process's cgroup limits.</summary>
public sealed class ServerMetrics
{
    public const int SampleIntervalSeconds = 2;
    private readonly object gate = new();
    private readonly TimeProvider clock;
    private readonly Func<ProcessCounters> readProcess;
    private readonly Func<string, string?> readProc;
    private readonly bool linux;
    private Snapshot? cached;
    private long previousAt;
    private ProcessCounters? previousProcess;
    private CpuCounters? previousCpu;

    public sealed record Cpu(bool Available, string Status, double? Percent, double? WindowSeconds,
        string Normalization, int? LogicalCpuCount);
    public sealed record Memory(bool Available, string Status, long? TotalBytes, long? AvailableBytes,
        long? UsedBytes, double? UsedPercent);
    public sealed record Load(bool Available, string Status, double? One, double? Five, double? Fifteen);
    public sealed record ProcessMetrics(bool Available, string Status, double? UptimeSeconds,
        long? ResidentMemoryBytes, double? TotalCpuSeconds, Cpu Cpu);
    public sealed record HostMetrics(bool Available, string Status, string Scope, double? UptimeSeconds,
        int? LogicalCpuCount, Cpu Cpu, Memory Memory, Load Load);
    public sealed record Readiness(string AdminApi, string GameAndDependencies);
    public sealed record Snapshot(DateTimeOffset SampledAt, int SampleIntervalSeconds, string SampleMode,
        string Status, string Scope, Readiness Readiness, ProcessMetrics Process, HostMetrics Host);
    internal sealed record ProcessCounters(double? Uptime, long? Memory, double? CpuSeconds);
    internal sealed record CpuCounters(ulong[] Times, int? Count);

    public ServerMetrics() : this(TimeProvider.System, ReadProcess, ReadProc, OperatingSystem.IsLinux()) { }

    // Injection is internal and used by the source-level fixture tests, never by HTTP/configuration.
    internal ServerMetrics(TimeProvider clock, Func<ProcessCounters> readProcess,
        Func<string, string?> readProc, bool linux)
    { this.clock = clock; this.readProcess = readProcess; this.readProc = readProc; this.linux = linux; }

    public Snapshot Read()
    {
        lock (gate)
        {
            long at = clock.GetTimestamp();
            double window = cached is null ? 0 : clock.GetElapsedTime(previousAt, at).TotalSeconds;
            if (cached is not null && window >= 0 && window < SampleIntervalSeconds) return cached;
            var process = readProcess();
            var cpu = linux ? ParseCpu(readProc("stat")) : null;
            var memory = linux ? ParseMemory(readProc("meminfo")) : EmptyMemory("unsupported");
            var load = linux ? ParseLoad(readProc("loadavg")) : EmptyLoad("unsupported");
            double? uptime = linux ? ParseUptime(readProc("uptime")) : null;
            string processState = Availability(process.Uptime is not null, process.Memory is not null, process.CpuSeconds is not null);
            string hostState = linux ? Availability(cpu is not null, cpu?.Count is not null,
                uptime is not null, memory.Available, load.Available) : "unsupported";
            cached = new(clock.GetUtcNow().ToUniversalTime(), SampleIntervalSeconds, "on-demand-cached", "responding",
                "backend-process-and-linux-host", new("responding", "not-probed"),
                new(processState != "unavailable", processState, process.Uptime, process.Memory, process.CpuSeconds,
                    ProcessCpu(process.CpuSeconds, previousProcess?.CpuSeconds, window)),
                new(linux && hostState != "unavailable", hostState, "procfs-host-not-cgroup", uptime, cpu?.Count,
                    linux ? HostCpu(cpu, previousCpu, window) : EmptyCpu("unsupported", "all-host-logical-cpus", null), memory, load));
            previousProcess = process;
            previousCpu = cpu;
            previousAt = at;
            return cached;
        }
    }

    private static string Availability(params bool[] values) => values.All(v => v) ? "available" :
        values.Any(v => v) ? "partial" : "unavailable";
    private static Cpu EmptyCpu(string status, string normalization, int? count) => new(false, status, null, null, normalization, count);
    private static Memory EmptyMemory(string status = "unavailable") => new(false, status, null, null, null, null);
    private static Load EmptyLoad(string status = "unavailable") => new(false, status, null, null, null);

    private static Cpu ProcessCpu(double? current, double? previous, double window)
    {
        const string basis = "one-logical-cpu";
        if (current is null) return EmptyCpu("unavailable", basis, null);
        if (previous is null) return EmptyCpu("warming-up", basis, null);
        if (current < previous || window <= 0) return EmptyCpu("counter-reset", basis, null);
        double percent = (current.Value - previous.Value) / window * 100;
        return double.IsFinite(percent) ? new(true, "available", percent, window, basis, null) : EmptyCpu("unavailable", basis, null);
    }

    private static Cpu HostCpu(CpuCounters? current, CpuCounters? previous, double window)
    {
        const string basis = "all-host-logical-cpus";
        if (current is null) return EmptyCpu("unavailable", basis, null);
        if (previous is null) return EmptyCpu("warming-up", basis, current.Count);
        if (current.Count != previous.Count || window <= 0) return EmptyCpu("counter-reset", basis, current.Count);
        // /proc/stat includes guest in user and guest_nice in nice; count the first eight columns only.
        // Idle and iowait are excluded from busy. Linux can decrease iowait: reject that interval.
        // https://docs.kernel.org/filesystems/proc.html#miscellaneous-kernel-statistics-in-proc-stat
        double total = 0, idle = 0;
        for (int i = 0; i < 8; i++)
        {
            if (current.Times[i] < previous.Times[i]) return EmptyCpu("counter-reset", basis, current.Count);
            ulong delta = current.Times[i] - previous.Times[i];
            total += delta;
            if (i is 3 or 4) idle += delta;
        }
        if (total <= 0) return EmptyCpu("unavailable", basis, current.Count);
        return new(true, "available", Math.Clamp((total - idle) / total * 100, 0, 100), window, basis, current.Count);
    }

    internal static CpuCounters? ParseCpu(string? text)
    {
        if (text is null) return null;
        ulong[]? times = null;
        var cpus = new HashSet<int>();
        foreach (string line in text.Split('\n'))
        {
            if (!line.StartsWith("cpu", StringComparison.Ordinal)) continue;
            var fields = Words(line);
            if (fields.Length == 0) continue;
            if (fields[0] == "cpu")
            {
                if (times is not null || fields.Length < 5) return null;
                times = new ulong[8];
                for (int i = 1; i < Math.Min(fields.Length, 9); i++)
                    if (!ulong.TryParse(fields[i], NumberStyles.None, CultureInfo.InvariantCulture, out times[i - 1])) return null;
            }
            else if (fields[0].StartsWith("cpu", StringComparison.Ordinal) &&
                int.TryParse(fields[0].AsSpan(3), NumberStyles.None, CultureInfo.InvariantCulture, out int id) && fields.Length >= 5)
            { if (!cpus.Add(id)) return null; }
        }
        return times is null ? null : new(times, cpus.Count > 0 ? cpus.Count : null);
    }

    internal static Memory ParseMemory(string? text)
    {
        if (text is null) return EmptyMemory();
        long? total = null, available = null;
        foreach (string line in text.Split('\n'))
        {
            var fields = Words(line);
            if (fields.Length == 0 || fields[0] is not ("MemTotal:" or "MemAvailable:")) continue;
            if (fields.Length != 3 || fields[2] != "kB" ||
                !long.TryParse(fields[1], NumberStyles.None, CultureInfo.InvariantCulture, out long kb) || kb > long.MaxValue / 1024)
                return EmptyMemory();
            if (fields[0] == "MemTotal:") { if (total is not null) return EmptyMemory(); total = kb * 1024; }
            else { if (available is not null) return EmptyMemory(); available = kb * 1024; }
        }
        if (total is null or <= 0 || available is null || available > total) return EmptyMemory();
        long used = total.Value - available.Value;
        return new(true, "available", total, available, used, (double)used / total.Value * 100);
    }

    internal static Load ParseLoad(string? text)
    {
        var fields = Words(text ?? "");
        if (fields.Length < 3 || !Nonnegative(fields[0], out var one) || !Nonnegative(fields[1], out var five) ||
            !Nonnegative(fields[2], out var fifteen)) return EmptyLoad();
        return new(true, "available", one, five, fifteen);
    }

    internal static double? ParseUptime(string? text)
    {
        var fields = Words(text ?? "");
        return fields.Length > 0 && Nonnegative(fields[0], out var uptime) ? uptime : null;
    }

    private static bool Nonnegative(string value, out double parsed) =>
        double.TryParse(value, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out parsed) && double.IsFinite(parsed) && parsed >= 0;
    private static string[] Words(string line) => line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);

    private static ProcessCounters ReadProcess()
    {
        double? uptime = null, cpu = null;
        long? memory = null;
        try
        {
            using var process = Process.GetCurrentProcess();
            try { uptime = Math.Max(0, (DateTime.UtcNow - process.StartTime.ToUniversalTime()).TotalSeconds); }
            catch (Exception e) when (Unavailable(e)) { }
            try { long value = process.WorkingSet64; memory = value >= 0 ? value : null; }
            catch (Exception e) when (Unavailable(e)) { }
            try { cpu = process.TotalProcessorTime.TotalSeconds; }
            catch (Exception e) when (Unavailable(e)) { }
        }
        catch (Exception e) when (Unavailable(e)) { }
        return new(uptime, memory, cpu);
    }

    private static bool Unavailable(Exception error) => error is IOException or UnauthorizedAccessException or
        Win32Exception or InvalidOperationException or NotSupportedException;

    private static string? ReadProc(string name)
    {
        // These four names are fixed by Read(), with no configurable path or request input.
        int limit = name == "stat" ? 2 * 1024 * 1024 : name == "meminfo" ? 128 * 1024 : 4096;
        try
        {
            using var reader = new StreamReader("/proc/" + name);
            var result = new StringBuilder();
            var chars = new char[4096];
            int length;
            while ((length = reader.Read(chars, 0, chars.Length)) > 0)
            {
                if (result.Length + length > limit) return null;
                result.Append(chars, 0, length);
            }
            return result.ToString();
        }
        catch (Exception e) when (Unavailable(e)) { return null; }
    }
}
