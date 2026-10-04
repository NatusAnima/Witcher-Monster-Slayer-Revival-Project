using System.Buffers.Binary;
using System.Diagnostics;
using System.Net.WebSockets;
using WitcherRevival.Server.Net;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Transport;

/// <summary>One complete native frame per binary WebSocket message. No unbounded receive queue.</summary>
public sealed class GameWebSocketStream(WebSocket socket, int firstFrameSeconds, int fragmentSeconds, int idleSeconds) : Stream
{
    public const int MaxIncoming = 65536;
    private readonly byte[] incoming = new byte[MaxIncoming];
    private readonly MemoryStream outgoing = new();
    private int position, length;
    private bool first = true;
    private long window = Stopwatch.GetTimestamp();
    private int frames, bytes;

    public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
    {
        if (buffer.IsEmpty) return 0;
        if (position == length)
        {
            position = length = 0;
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            deadline.CancelAfter(TimeSpan.FromSeconds(first ? firstFrameSeconds : idleSeconds));
            bool fragmentStarted = false;
            while (true)
            {
                var part = await socket.ReceiveAsync(incoming.AsMemory(length), deadline.Token);
                if (part.MessageType == WebSocketMessageType.Close) return 0;
                if (part.MessageType != WebSocketMessageType.Binary) throw new InvalidDataException("Binary game frames required.");
                length += part.Count;
                if (part.EndOfMessage) break;
                if (length == MaxIncoming) throw new InvalidDataException("Game frame exceeds bound.");
                if (!fragmentStarted)
                {
                    // The initial authentication deadline covers the entire message.
                    if (!first) deadline.CancelAfter(TimeSpan.FromSeconds(fragmentSeconds));
                    fragmentStarted = true;
                }
            }
            if (length < 9 || !incoming.AsSpan(0, 4).SequenceEqual(PreloaderStaticData.Magic) ||
                BinaryPrimitives.ReadInt32BigEndian(incoming.AsSpan(5, 4)) != length - 9 ||
                incoming[4] is < 1 or > 4 || first && incoming[4] != 3)
                throw new InvalidDataException("Invalid game frame envelope.");
            if (Stopwatch.GetElapsedTime(window).TotalSeconds >= 10)
            { window = Stopwatch.GetTimestamp(); frames = bytes = 0; }
            if (++frames > 256 || (bytes += length) > 8 * 1024 * 1024)
                throw new InvalidDataException("Game input rate exceeded.");
            first = false;
        }
        int count = Math.Min(buffer.Length, length - position);
        incoming.AsMemory(position, count).CopyTo(buffer);
        position += count;
        return count;
    }

    public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (outgoing.Length + buffer.Length > 8 * 1024 * 1024 + 5)
            throw new InvalidDataException("Game response exceeds bound.");
        outgoing.Write(buffer.Span);
        return ValueTask.CompletedTask;
    }

    public override async Task FlushAsync(CancellationToken cancellationToken)
    {
        if (outgoing.Length == 0) return;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await socket.SendAsync(outgoing.GetBuffer().AsMemory(0, checked((int)outgoing.Length)),
            WebSocketMessageType.Binary, true, deadline.Token);
        outgoing.SetLength(0);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { Array.Clear(incoming); outgoing.Dispose(); }
        base.Dispose(disposing);
    }
    public override bool CanRead => true;
    public override bool CanWrite => true;
    public override bool CanSeek => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    public override void Flush() => throw new NotSupportedException();
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
}
