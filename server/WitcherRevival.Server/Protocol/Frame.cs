using System.Buffers.Binary;

namespace WitcherRevival.Server.Protocol;

/// <summary>
/// One socket message. Wire framing (confirmed from <c>SocketMessageFactory</c>, HEADER_SIZE=5):
/// <c>[1 byte Type][4 byte big-endian length][payload]</c>. <c>Type</c> selects the channel.
/// </summary>
public readonly record struct Frame(byte Type, byte[] Data);

/// <summary>
/// Outer channel selector (the <c>Type</c> byte). <c>ApiBuilder</c> wires four channels, but the
/// IL2CPP dump doesn't expose the concrete byte values.
/// UNCONFIRMED — the enum values below are placeholders; recover the real bytes from the first
/// captured frames (the client's very first frame is the auth handshake).
/// </summary>
public enum Channel : byte
{
    Authentication = 0,
    Api = 1,
    StaticGameData = 2,
    Logging = 3,
}

/// <summary>
/// API RPC ids, from <c>dump.cs</c> <c>enum Method</c> (Api channel). Boot-relevant subset.
/// </summary>
public enum Method
{
    GetLocations = 2,
    GetPlayerInfo = 3,
    GetInventory = 5,
    GetLocationsByCell = 40,
    LoadCells = 88,
    GetInitialPlayerData = 115,
    Ping = 141,
}

/// <summary>Reads/writes length-prefixed frames off a stream.</summary>
public static class FrameCodec
{
    private const int MaxFrame = 8 * 1024 * 1024;

    public static async Task<Frame?> ReadAsync(Stream s, CancellationToken ct)
    {
        var header = await ReadExactAsync(s, 5, ct);
        if (header is null) return null;
        byte type = header[0];
        int len = BinaryPrimitives.ReadInt32BigEndian(header.AsSpan(1, 4));
        if (len is < 0 or > MaxFrame) throw new InvalidDataException($"implausible frame length {len} (type {type}) — framing assumption wrong?");
        var data = len == 0 ? Array.Empty<byte>() : await ReadExactAsync(s, len, ct);
        if (data is null) return null;
        return new Frame(type, data);
    }

    public static async Task WriteAsync(Stream s, byte type, byte[] payload, CancellationToken ct)
    {
        var header = new byte[5];
        header[0] = type;
        BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(1, 4), payload.Length);
        await s.WriteAsync(header, ct);
        if (payload.Length > 0) await s.WriteAsync(payload, ct);
        await s.FlushAsync(ct);
    }

    private static async Task<byte[]?> ReadExactAsync(Stream s, int n, CancellationToken ct)
    {
        var buf = new byte[n];
        int off = 0;
        while (off < n)
        {
            int r = await s.ReadAsync(buf.AsMemory(off, n - off), ct);
            if (r == 0) return null; // peer closed
            off += r;
        }
        return buf;
    }
}
