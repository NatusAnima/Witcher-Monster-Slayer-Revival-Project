# Wire Protocol & API Reference

This document outlines the reverse-engineered TCP wire protocol and API structures used by the game client (ThreadedClient).

## 1. Socket Framing
The game uses a raw TCP socket with big-endian binary framing.

### Client to Server
Every message sent by the client prepends a 4-byte magic sequence:
```
[4 bytes : Magic]    0x9043284A (SECRET_BYTES)
[1 byte  : Type ]    Channel selector (see §2)
[4 bytes : Size ]    Big-endian int32, length of the payload
[N bytes : Data ]    Payload (ByteBuffer), N == Size
```

### Server to Client
The server responds **without** the magic bytes:
```
[1 byte  : Type ]    Channel selector
[4 bytes : Size ]    Big-endian int32, length of the payload
[N bytes : Data ]    Payload
```

### ByteBuffer Codec
All primitives are big-endian.
- `bool`: 1 byte
- `int`: 4 bytes
- `long`: 8 bytes
- `string`: `[int32 len][utf8 bytes]`
- `List<T>`: `[int32 count][elem * count]`
- `Dictionary<K,V>`: `[int32 count][(K,V) * count]`

## 2. Channels (Outer `Type` Byte)
| ID | Channel | Description |
|---|---|---|
| 1 | `Api` | Gameplay RPCs and player actions. |
| 2 | `Logging` | Client log uploads (ignored by server). |
| 3 | `Authentication` | Login handshake. |
| 4 | `StaticGameData` | Fetch static content (GZip JSON). |

## 3. Authentication (Channel 3)
- **Request:** `[int MethodId=1][int apiVersion][long clientVersion][string deviceId][string accountId]`
- **Response:** `[int MethodId=1][byte code]` (Code `0` = Success)

## 4. API Envelope (Channel 1)
Gameplay messages (`MethodMessage<T>`) are wrapped inside the Api channel.
`[1B MsgType][1B unused][int rcvCount][long*rcvCount Received][long Id][int MethodId][method payload]`

### Key Boot-time API Methods
| ID | Name | Payload Structure / Server Response |
|---|---|---|
| 3 | `GetPlayerInfo` | `[byte Success][string Name][int Gold][int Exp][int Head][byte TutorialFinished][byte Gender]` |
| 5 | `GetInventory` | 9 empty `Dictionary<int,int>` then `[int BagSize]` |
| 9 | `GetEquipment` | `[int SwordsCount][int*swords][int ArmorsCount][int*armors][int EquippedArmor][int EquippedSword]` |
| 40 | `GetLocationsByCell` | Client sends S2 cell IDs. Used to spawn the tutorial NPC. |
| 57 | `EndBehaviourGraph`| Request = `[long QuestNodeInstanceId][string OutputName][int FactCount][(int Key, int Value)×FactCount]` (decoded byte-exact from a captured 73-byte tutorial payload against `EndBGRequest`, dump.cs 601870). Response: heavily nested; an all-zero (57 bytes) stub works to bypass NREs — real loot/exp needs the response's read order byte-verified (follow-up milestone). Request facts are persisted server-side (see 58/59/78). |
| 58 / 59 | `GetFacts` / `GetAllFacts` | Response (both, identical shape): `[int count][(int key, int value)×count]`, **no** leading Success byte (dump.cs 598697 / 598307). Serves a persisted server-side fact store. |
| 60 | `GetActiveQuestNodeInstances` | Drives the tutorial NPC spawning. |
| 78 | `SetFacts` | Request = `SetFactsRequest` (dump.cs 602571): single `Dictionary<int,int> Facts` field. Captured payloads are 12 bytes = `[int 2][int key][int value]` (one pair); the leading int's exact meaning (count-of-ints vs. other) isn't disassembled from `Serialize()`, so the server parses pairs until the payload is exhausted rather than trusting it. Response: `SetFactsResponse : BooleanResponse` (dump.cs 600187), 1 byte. |
| 88 | `LoadCells` | Subscribe to S2 geo-cells. Returns `[byte 1]` (BooleanResponse(true)). |
| 115| `GetInitialPlayerData`| Batch response hydrating the player. `[int count][for each: int methodId, inline sub-response fields]` |
| 141| `Ping` | Heartbeat. |

## 5. Static Data Container (Channel 4)
The StaticGameData `FETCH` method returns a gzip-compressed JSON containing 82 top-level arrays.
The client deserializes this using `DataContractJsonSerializer`.

> **Note:** To find valid string IDs (`prefab_path`, `slug`) required for the static data, use `grep_search` on the Addressables catalog at `tools/dump/catalog.json`. Sending invalid slugs will crash the game client on model load.

Key DTOs (snake_case JSON keys):
- `achievements`: `id`, `slug`, `contract_id`
- `monsters`: `id`, `family_id`, `name`, `model`, `image`, `trophy`, `slug`
- `skills`: `id`, `slug`, `cost`, `required_level`, `parent_id`
- `swords`: `id`, `slug`, `priority`, `prefab_path`, `sword_type`
- `armors`: `id`, `slug`, `priority`, `prefab_path`
