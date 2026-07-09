using System.Buffers.Binary;
using System.Text;

namespace WitcherRevival.Server.Protocol;

/// <summary>
/// Big-endian binary codec mirroring <c>WitcherWorld.WebstuffClient.ByteBuffer</c>.
/// Confirmed from the dump: big-endian int/uint/long/ulong/float/double, INT_SIZE=4, LONG_SIZE=8,
/// and an <c>EndiannessConverter</c> that forces network byte order.
///
/// ASSUMPTION (verify against captured bytes): <see cref="WriteString"/>/<see cref="ReadString"/>
/// use a <c>[BE int32 length][UTF-8 bytes]</c> framing. The method bodies aren't in the IL2CPP dump,
/// so this is the leading hypothesis. If the first captured frame doesn't decode, this is the first
/// thing to change (candidates: uint16 length prefix / Java writeUTF style).
/// </summary>
public sealed class ByteBuffer
{
    private readonly MemoryStream _out = new();
    private readonly byte[] _in;
    private int _pos;

    public ByteBuffer() => _in = Array.Empty<byte>();
    public ByteBuffer(byte[] data) => _in = data;

    public int RemainingToRead => _in.Length - _pos;
    public int Length => (int)_out.Length;

    // ---- reads ----
    public byte ReadByte() => _in[_pos++];
    public int ReadInt() { var v = BinaryPrimitives.ReadInt32BigEndian(_in.AsSpan(_pos)); _pos += 4; return v; }
    public uint ReadUInt() { var v = BinaryPrimitives.ReadUInt32BigEndian(_in.AsSpan(_pos)); _pos += 4; return v; }
    public long ReadLong() { var v = BinaryPrimitives.ReadInt64BigEndian(_in.AsSpan(_pos)); _pos += 8; return v; }
    public ulong ReadULong() { var v = BinaryPrimitives.ReadUInt64BigEndian(_in.AsSpan(_pos)); _pos += 8; return v; }
    public float ReadFloat() { var v = BinaryPrimitives.ReadSingleBigEndian(_in.AsSpan(_pos)); _pos += 4; return v; }
    public double ReadDouble() { var v = BinaryPrimitives.ReadDoubleBigEndian(_in.AsSpan(_pos)); _pos += 8; return v; }
    public byte[] ReadBytes(int n) { var b = _in.AsSpan(_pos, n).ToArray(); _pos += n; return b; }
    public byte[] ReadRemaining() { var b = _in.AsSpan(_pos).ToArray(); _pos = _in.Length; return b; }
    public string ReadString() { int len = ReadInt(); var s = Encoding.UTF8.GetString(_in, _pos, len); _pos += len; return s; } // ASSUMPTION

    // ---- writes ----
    public void WriteByte(byte v) => _out.WriteByte(v);
    public void WriteInt(int v) { Span<byte> b = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(b, v); _out.Write(b); }
    public void WriteUInt(uint v) { Span<byte> b = stackalloc byte[4]; BinaryPrimitives.WriteUInt32BigEndian(b, v); _out.Write(b); }
    public void WriteLong(long v) { Span<byte> b = stackalloc byte[8]; BinaryPrimitives.WriteInt64BigEndian(b, v); _out.Write(b); }
    public void WriteULong(ulong v) { Span<byte> b = stackalloc byte[8]; BinaryPrimitives.WriteUInt64BigEndian(b, v); _out.Write(b); }
    public void WriteFloat(float v) { Span<byte> b = stackalloc byte[4]; BinaryPrimitives.WriteSingleBigEndian(b, v); _out.Write(b); }
    public void WriteDouble(double v) { Span<byte> b = stackalloc byte[8]; BinaryPrimitives.WriteDoubleBigEndian(b, v); _out.Write(b); }
    public void WriteBytes(byte[] v) => _out.Write(v, 0, v.Length);
    public void WriteString(string v) { var b = Encoding.UTF8.GetBytes(v); WriteInt(b.Length); WriteBytes(b); } // ASSUMPTION

    public byte[] ToArray() => _out.ToArray();
}
