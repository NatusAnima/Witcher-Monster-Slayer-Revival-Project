# TWMS Boot Protocol Map (Phase 1)

Reverse-engineered from the IL2CPP dump (`dump/x86_64/dump.cs`, metadata v24.4 / Unity 2019.4.x).
Client backend code lives under namespace **`WitcherWorld.WebstuffClient.*`** ("Webstuff" = Spokko's
backend codename). This document covers **only the boot path** needed for proof-of-life (past the title
screen). Legend: **[C]** = confirmed from dump structure, **[I]** = inferred (verify at runtime in Phase 2).

## 1. Architecture

Two transports, in sequence:

1. **Gatekeeper** — an HTTPS endpoint. Gates the session (maintenance / version) and returns the
   **game server address** + the player's **WitcherId**. `[C]`
2. **Webstuff game server** — a **raw TCP socket** (`System.Net.Sockets.Socket`, `AsyncClient`/
   `ThreadedClient`), **big-endian binary** framing (no JSON, no WebSocket). Default port **`4253`**
   (`ClientWorker.GAMESERVER_PORT`). Carries auth, static-game-data, and all gameplay RPCs. `[C]`

Key classes: `ClientWorker` (orchestrator), `SocketMessageFactory` (framing), `ByteBuffer` (payload
codec), `ApiBuilder` (channel/handler wiring), `AuthenticationModule`, `Handler<Message,Message,byte>`.
DI is Zenject (`WebstuffClientInstaller : ScriptableObjectInstaller`).

## 2. Config — `ClientSettings : ScriptableObject`

Per-environment fields (values live in a Unity asset bundle, not the dump — recover in Phase 2):

| Field (per Dev/Test/Prod) | Type | Meaning |
|---|---|---|
| `UseGatekeeper{Env}` | bool | if true, discover server via gatekeeper; else connect directly |
| `GatekeeperUrl{Env}` | string | gatekeeper HTTPS base |
| `WebstuffServerIp{Env}` | string | direct server IP (used when `UseGatekeeper=false`) |
| `WebstuffServerDefaultPort{Env}` | int | direct server port |
| `RetryIntervalSeconds{Env}` | int | reconnect backoff |

Known prod gatekeeper host (from string table): `gatekeeper.cloud.thewitchermonsterslayer.com`
(non-prod: `gatekeeper.{beta,test}.dev.spokko.com`).

**Redirect strategy:** stand up our own gatekeeper that returns `Address = <our TCP server>` and
`Type = OK`. Works regardless of the `UseGatekeeper` flag as long as prod uses it. Fallback: Frida-hook
`ClientSettings.get_UseGatekeeper`/`get_WebstuffServerIp` to point directly at us.

## 3. Gatekeeper HTTP — `GatekeeperResponse` (DataContract JSON)

`ClientWorker.SetupServerAddress(gatekeeperUrl, deviceId, accountId)` calls the gatekeeper with the
device + account identity. `[C]` Exact request shape (path/query/body) → **confirm in Phase 2**. `[I]`

Response JSON (`[DataMember]` props): `[C]`
```json
{ "Type": 0, "Message": 0, "EndTime": "", "Address": "host:port", "WitcherId": 123456789 }
```
- `Type` (int) — status; OK vs maintenance/update. Exact OK value **TBD** `[I]`.
- `Message` (int) — message code (localized client-side).
- `EndTime` (string) — maintenance end time.
- `Address` (string) — **the TCP game server to connect to** (format `host:port` inferred). `[I]`
- `WitcherId` (long) — server-side player id.

## 4. Socket framing — `SocketMessageFactory` (`HEADER_SIZE = 5`)

Wire frame `[C]`:
```
[1 byte  : Type ]      channel selector (see §5)
[4 bytes : Size ]      big-endian int32, length of payload
[N bytes : Data ]      payload (ByteBuffer), N == Size
```
`Message { byte Type; int Size; ByteBuffer Data }`. `SocketMessageFactory.Serialize(Message)->ByteBuffer`
and `TryDeserialize(ByteBuffer, out Message)`.

### Payload codec — `ByteBuffer`
Big-endian primitives (`EndiannessConverter` toggles to network order). Methods `[C]`:
`WriteByte/Int/UInt/Long/ULong/Float/Double/String` (+ `Read*`). `INT_SIZE=4`, `LONG_SIZE=8`.
**`WriteString` framing is the one detail not in the dump** (bodies aren't decompiled). Hypothesis
`[I]`: `[BE int32 length][UTF-8 bytes]` — **confirm byte-for-byte in Phase 2** (this blocks the codec).

## 5. Channels (outer `Type` byte)

`ApiBuilder` wires four channels. The concrete `Type` byte value for each is set in code Il2CppDumper
doesn't decompile → **recover in Phase 2 (runtime/Ghidra):** `[I]`
- **Authentication** (`CreateAuthenticationHandler`) — login handshake.
- **Api** (`CreateApiHandler` → `CreateApiTypeHandler`) — `Method`-keyed gameplay RPCs.
- **StaticGameData** (`CreateStaticGameDataHandler`) — fetch static content.
- **Logging** — client log upload.

## 6. Authentication handshake (Authentication channel)

Request built by `ClientWorker.WriteAuthenticationRequest(int apiVersion, long clientVersion,
byte[] deviceId, byte[] accountId)` → payload order (inferred from signature) `[I]`:
`WriteInt(apiVersion); WriteLong(clientVersion); WriteBytes(deviceId); WriteBytes(accountId)`.

Response — `AuthenticationResponse { bool Success; byte ErrCode }` `[C]`:
- `ErrCode` consts: `ERROR_LOGIN_FAILED=1`, `ERROR_VERSION_MISMATCH=2`, `ERROR_VERSION_NEWER=3`.
- **Version gating lives here** — the emulator must accept the client's `clientVersion`/`apiVersion`
  (echo success). For proof-of-life, accept any identity → `Success=true, ErrCode=0`.

## 7. API envelope (Api channel)

`MethodMessage<T> { long Id; int MethodId; T Data }` `[C]`:
- `Id` (long) — correlation id (client generates; response echoes; `ApiResponseReceived{MessageId}` acks).
- `MethodId` (int) — value from the **`Method`** enum.
- `Data` — typed request/response payload; each `*Request` implements `ByteBuffer Serialize()`, each
  `*Response` has `.ctor(ByteBuffer)`.

### Boot-relevant `Method` ids `[C]`
| Method | id | role at boot |
|---|---|---|
| `GetPlayerInfo` | 3 | basic profile |
| `GetInventory` | 5 | inventory |
| `GetLocationsByCell` | 40 | map POIs for a geo-cell |
| `LoadCells` | 88 | subscribe S2 geo-cells (`WriteLoadCells(List<ulong>)`) |
| **`GetInitialPlayerData`** | **115** | **batch player hydration (see §8)** |
| `Ping` | 141 | heartbeat (`HeartbeatLogic`, `SendPingRequest`) |

(Full enum spans 2..≥141; complete catalog in `dump.cs` `enum Method`.)

## 8. `GetInitialPlayerData` (id 115) — the boot payload

`GetInitialPlayerDataRequest` has **no fields** (empty `Serialize()`). `[C]`
`GetInitialPlayerDataResponse { Dictionary<int, IMethodMessageResponse> responses }` — a **batch** whose
keys are `Method` ids and values are the corresponding sub-responses (inventory, equipment, skills,
facts, quests, etc.). `[C]` This single response hydrates the player after auth. The minimum set of
sub-responses the client tolerates for boot → **determine in Phase 2** (send empty/defaults, add until
it proceeds). `[I]`

## 9. Boot sequence (inferred order) `[I]`

1. HTTPS → **Gatekeeper**(deviceId, accountId) ⇒ `{Type=OK, Address, WitcherId}`.
2. TCP connect to `Address` (default port 4253).
3. **Auth** channel: send `WriteAuthenticationRequest(...)` ⇒ `AuthenticationResponse{Success=true}`.
4. **StaticGameData**: `GetStaticDataUrl` ⇒ `StaticDataUrl`; then `FetchStaticGameData` (or client
   downloads from URL). Client needs valid static data to build its data model.
5. **Api**: `GetInitialPlayerData`(115) ⇒ batch ⇒ player hydrated.
6. `LoadCells`(88) / `GetLocationsByCell`(40) for the initial map; `Ping`(141) heartbeat begins.
7. Title screen dismisses → in-game.

Proof-of-life likely needs steps 1–5 (maybe 6). Exact minimum is a Phase-2 empirical question.

## 9b. OnetimeWebstuffPreloader — the boot-time static-data fetch `[C]` (decoded from arm64 v1.0.43)

Before the main `AsyncClient`/gatekeeper flow, a **synchronous** `ISynchronousPreloader`
(`WitcherWorld.Modules.DataManager.StaticData.OnetimeWebstuffPreloader`) runs at boot and blocks the
title screen ("Waiting on server response") until it fetches the static-game-data `Container`. Fully
disassembled from `tools/patch/libil2cpp.so` (offsets == dump RVAs). Use `tools/disasm.py`.

**Fields** (injected via Zenject from `ClientSettings`): `Host` (0x10), `Port` (0x18),
`UseGatekeeper` (0x1C), `GatekeeperUrl` (0x20). `SECRET_BYTES = -1874646966 = 0x9043284A`. `FAKE_USER_ID = "bob"`.

**`Connect()`** (RVA 0x18A62B8):
- if `UseGatekeeper`: `addr = GetServerAddress("bob")`; else `addr = Host`.
- `GetServerAddress(uid)` = HTTP **GET** `{GatekeeperUrl}/{uid}` (i.e. `{GatekeeperUrl}/bob`); the
  **response body is a bare hostname/IP string** (no port).
- `Dns.GetHostEntry(addr)` → for each resolved IP: `Socket(InterNetwork, Stream, Tcp)` → `Connect(ip, Port)`.
  **Port always comes from the `Port` field**, never from the address string. Sets Recv/Send timeout = 2000 ms.

**Wire protocol** (its own framing, big-endian `ByteBuffer` — NOT `SocketMessageFactory`, though the
5-byte header is the same shape):

*Request the client sends* (`CreateRequestPayload`, exactly 17 bytes):
```
90 43 28 4A            WriteInt(SECRET_BYTES = 0x9043284A)   ; magic, identifies a preloader conn
04                     WriteByte(0x04)                        ; message/channel type
00 00 00 08            WriteInt(8)
00 00 00 01            WriteInt(1)
00 00 00 00            WriteInt(0)
```

*Response the client expects* (`GetMessageSize` + `ReceiveStaticGameDataJson`):
```
04                     byte, must == 0x04 (else client treats size as -1 and bails)
<BE int32 size>        size = 8 + len(gzip)
<8 bytes>              ignored by client (Array.Copy starts at offset 8)
<gzip bytes>           GZipStream(Decompress) → DataContractJsonSerializer(Container)  ; size-8 bytes
```
So total on the wire = `04` + `BE32(8+gzipLen)` + 8 filler bytes + `gzip(json)`.
Read as: first `ReceiveBytes(5)` → `[04][size]`; then `ReceiveBytes(size)` → skip 8 → gzip payload.

**`Container`** (`dump.cs` line ~692933) = the full static catalog: 82 top-level `[DataMember]`
arrays (Monsters, Quests, Items, Recipes, Shops…). Empty/absent members deserialize to null.
Proof-of-life: try `{}` first, then all-empty-arrays if the client NPEs iterating a null array.

**Endianness confirmed:** `ByteBuffer.WriteInt` stores MSB-first (big-endian) — verified in disasm.

## 9c. CONFIRMED at runtime (Phase 2 capture, v1.0.43) — the boot IS the ThreadedClient path

The active boot client is **`WitcherWorld.WebstuffClient.Network.ThreadedClient`**, driven by
`ClientWorker.Run` on a worker thread. **`OnetimeWebstuffPreloader` does NOT run during boot** (its
hooks never fired) — §9b was a dead end for the current blocker; keep it only as reference.

The dead prod DNS still resolves: `gatekeeper.cloud.thewitchermonsterslayer.com` and
`game-server.cloud.thewitchermonsterslayer.com` both → **34.107.152.195** (GCP, dead). The client
connects to **`game-server...:80`** (raw TCP, retries every ~7 s = the "Waiting on server response"
loop). We redirect that connect at the libc `connect()` level to `127.0.0.1:4253` (tunnelled to the
PC via `adb reverse tcp:4253`). See `tools/patch/hook.js` (`REDIRECT`, `DEAD_IP`).

### Wire framing — CONFIRMED
- **Client → server**: every message = `[4B magic 0x9043284A][1B type][4B BE size][payload]`. The magic
  (`SECRET_BYTES = -1874646966`) is prepended to **every** outgoing message by
  `ThreadedClient.prependSecretBytes`, NOT once per connection.
- **Server → client**: `[1B type][4B BE size][payload]` — **no magic** (client `TryDeserialize` /
  `SocketMessageFactory` HEADER_SIZE=5 = `[type][size]`, reads magic-free).
- `ByteBuffer`: big-endian ints/longs (`WriteInt` MSB-first, verified). `WriteString` **and** `byte[]`
  framing = **`[BE int32 length][raw bytes]`** (confirmed on the wire: deviceId len=32 + 32 ASCII bytes).

### Channel outer type bytes — CONFIRMED (`ApiBuilder.CreateHandler` key map)
**1 = Api, 2 = Logging, 3 = Authentication, 4 = StaticGameData.**

### Authentication (channel 3) — CONFIRMED
Request payload (`BuildAuthenticationRequest` → `SocketMessageFactory.Create(type=3)`):
`WriteInt(MethodId=1 AUTHENTICATE); WriteInt(apiVersion); WriteLong(clientVersion);
WriteInt(deviceId.len)+deviceId; WriteInt(accountId.len)+accountId`.
Captured: apiVersion=**15**, clientVersion=**281474976710699** (0x000100000000002B),
deviceId=`"1babc850a7236d43bf1458731f1cf6e7"`, accountId empty (first launch, no account).
Response (server → client, channel 3): inner `[int MethodId=1][byte code]`; `code==0 ⇒ Success=true`
(`AuthenticationHandler.HandleAuthenticateResponse` reads exactly one byte). So reply bytes =
`03  00 00 00 05  00 00 00 01  00`. **This works — client authenticates and proceeds.**

### Api (channel 1) — envelope decoded
Two nested serializers:
- `Api.Message.Factory.Serialize`: `WriteByte(b1); WriteByte(b2); WriteInt(x)` then the TypeMessage bytes.
  (Captured request header = `01 01  00 00 00 00`; meaning of the two bytes + int TBD — decode
  `Api.Message.Factory.Deserialize` to build responses.)
- `TypeMessage.Factory.Serialize`: `WriteLong(Id); WriteInt(Method); Write(Data)`. `Id` = `RandomLong.Get()`.
Captured first Api request after auth = **`LoadCells` (Method 88)** with 9 ulong S2 cell ids.
`GetInitialPlayerData` = Method 115. Responses expected keyed by the same `Id`; `ApiResponseReceived{Id}` acks.

### Current status
Auth succeeds; loading bar advances to **52%**; client sends `LoadCells(88)` then **times out**
("Server connection timed out") waiting for Api responses. Next: implement Api response envelope +
`LoadCells`/`GetInitialPlayerData` replies to push past the title screen.

## 10. Open items — remaining
1. ~~ByteBuffer.WriteString framing~~ **CONFIRMED** `[BE32 len][bytes]`.
2. ~~Channel Type bytes~~ **CONFIRMED** 1=Api 2=Logging 3=Auth 4=StaticGameData.
3. Gatekeeper HTTP request shape — N/A for boot (client uses direct game-server:80, not gatekeeper).
4. ~~`Address` format~~ — N/A (DNS-based, port 80 hardcoded on the game-server host).
5. ~~Auth payload byte layout~~ **CONFIRMED** (see §9c).
6. **Api `Message.Factory` header** (2 bytes + int) — decode the deserialize side to build responses.
7. **Minimum Api responses** (LoadCells / GetInitialPlayerData / StaticGameData / Ping) to leave the title screen.

## Source references
- `dump/x86_64/dump.cs` — namespaces `WitcherWorld.WebstuffClient.*`, `WitcherWorld.Modules.Authentication`.
- DTOs reusable in the C# emulator: `dump/x86_64/DummyDll/Game.dll`, `Assembly-CSharp.dll` (the
  `*Request`/`*Response` types + `GatekeeperResponse` carry `[DataMember]`/field layouts).
