using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Api channel (outer type 1) envelope, decoded from the IL2CPP dump (v1.0.43):
///   Api.Message  = [byte API_VERSION=1][byte MsgType][int Received.count][long*count Received][Data]
///   TypeMessage  = [long Id][int Method][method payload]        (Data of an Api.Message)
///   MsgType: REQUEST=1, RESPONSE=2.
/// Responses echo the request Id + Method; the method payload is the *Response serialization.
/// See docs/protocol-boot.md §9c.
/// </summary>
public static class ApiProtocol
{
    public const byte ApiVersion = 1;
    public const byte MsgRequest = 1;
    public const byte MsgResponse = 2;

    public readonly record struct ApiRequest(byte MsgType, long[] Received, long Id, int Method, byte[] Data);

    public static ApiRequest Parse(byte[] payload)
    {
        var b = new ByteBuffer(payload);
        b.ReadByte();                          // API_VERSION
        byte msgType = b.ReadByte();
        int rcvCount = b.ReadInt();
        var received = new long[rcvCount];
        for (int i = 0; i < rcvCount; i++) received[i] = b.ReadLong();
        long id = b.ReadLong();
        int method = b.ReadInt();
        byte[] data = b.ReadRemaining();
        return new ApiRequest(msgType, received, id, method, data);
    }

    /// <summary>Build the Api.Message payload for a response to (id, method) with the given method payload.</summary>
    public static byte[] BuildResponse(long id, int method, byte[] methodPayload, long[]? ack = null)
    {
        var outer = new ByteBuffer();
        outer.WriteByte(ApiVersion);
        outer.WriteByte(MsgResponse);
        ack ??= new[] { id };                  // ack the request id via the Received array
        outer.WriteInt(ack.Length);
        foreach (var a in ack) outer.WriteLong(a);
        // TypeMessage
        outer.WriteLong(id);
        outer.WriteInt(method);
        outer.WriteBytes(methodPayload);
        return outer.ToArray();
    }

    /// <summary>A BooleanResponse payload (LoadCells, and other bool RPCs): a single byte.</summary>
    public static byte[] Boolean(bool value) => new[] { (byte)(value ? 1 : 0) };
}
