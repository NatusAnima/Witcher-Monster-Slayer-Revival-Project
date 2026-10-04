# Protocol contract and implementation limits

This is the maintained contract overview for the reconstructed 1.1.116 backend. The [per-method coverage table](contract-1.1.116/RPC_COVERAGE.md) records implemented methods and the [catalogue reference](contract-1.1.116/CATALOG.md) records client data schemas. Layout recovery, synthetic test coverage and Android acceptance are separate evidence classes.

## Current contract sources

| Subsystem | Contract and implementation reference |
| --- | --- |
| Tasks and rewards | [Task engine](../docs/TASKS-20261001.md), [task catalogue](WitcherRevival.Server/tasks/README.md), [reward synchronization](../docs/REFRESH-AND-REWARDS-20261001.md) |
| Alchemy, equipment and skills | [Alchemy and skills](../docs/ALCHEMY-SKILLS-20261002.md), [combat effects](../docs/COMBAT-EFFECTS-20261002.md), [Aura](../docs/WITCHER-AURA-20261002.md) |
| World policy | [Visibility](../docs/SPAWN-VISIBILITY-20261002.md), [rarity](../docs/SPAWN-WEIGHTS-20261002.md), [operator controls](../docs/ADMIN-CONTROLS-AND-DIFFICULTY-20261002.md) |
| Story | [Story engine and data pipeline](../docs/ITERATION-44.md), [relocation](../docs/RELOCATION-20261001.md) |
| Social operations | [Client audit](../docs/CLIENT-AUDIT-20261002.md), [SocialService](WitcherRevival.Server/Net/SocialService.cs) |
| GPS companion extension | [GPS protocol and policy](../docs/GPS-PANEL-20261003.md), [DistanceIntegrity](WitcherRevival.Server/Net/DistanceIntegrity.cs) |
| Operator APIs | [Panel contract](WitcherRevival.Server/Admin/README.md), [resource measurements](../docs/ADMIN-METRICS-20261002.md) |

## Profiles and persistence

[ProfileRegistry](WitcherRevival.Server/Net/ProfileRegistry.cs) selects a profile from the supplied device and account identifiers. A device without an account uses its guest profile; the first account login can take over that guest profile, and an existing account retains its own profile across devices. Identifiers are keyed with HMAC-SHA256 under the server's identity key. The index stores those keyed values and random profile IDs. This local identity mapping does not verify credentials with the original account provider.

Each profile has a [LocalProfileStore](WitcherRevival.Server/Net/LocalProfileStore.cs) and player service. Schema 1 retains legacy fact/stage data. Schema 2 also persists reconstructed player state, including wallet, items, skills, equipment, story progress and the bounded transaction ledger. `LocalProfile:NewProfileMode=reconstructed` starts a new player at the tutorial; the legacy mode retains the earlier demonstration start. Existing files keep their schema. News and driving-warning configuration do not migrate profiles. Enabling `Tasks:Directory` adds optional task state to reconstructed profiles when they are used; the profile schema number remains 2.

Profile locks prevent concurrent use of the same profile file. Validated writes replace a temporary file; invalid stored data is refused without overwriting it. An implemented field or passing persistence test does not establish original balance or complete gameplay compatibility. Keep identity keys, the player index and profiles together when backing up or restoring a deployment.

## Optional task catalogue

With `Tasks:Directory` enabled, the server compiles validated definitions into static data and persists daily slots, progress, hunt stamps, event claims and achievement timestamps with gameplay. See [task contracts and validation](../docs/TASKS-20261001.md) and the [catalogue schema and editing rules](WitcherRevival.Server/tasks/README.md).

RPC 20 contains the native progress arrays. RPC 21 retains unfinished tasks, 22 returns the replacement ID, and 23 the removed ID. RPC 81 returns the wallet total and preserves the daily/timed type on refusal. RPC 24 counts integers in its ID/Unix-second pairs. RPC 94 returns epoch-day stamps and a valid reward ID; RPC 95 always has nine bytes. The client already increments hunt stamps after a won fight, so no duplicate RPC 96 is pushed. RPC 122 uses a successful empty body with event ID −1 to clear an expired event. RPC 123 returns a reward gold delta, and 125 triggers event synchronization. These optional responses replace the historical empty fixtures described below.

The task catalogue manifest and operator definitions belong with profile backups. Existing static IDs are immutable; new IDs require a server/client restart. Disabling Tasks in the new binary retains saved rewards and task state while filtering task-only static references. Android acceptance remains separate from native analysis and synthetic integration tests.

## Transport and handshake

Integers use big-endian encoding. [Frame](WitcherRevival.Server/Protocol/Frame.cs) reads client frames as:

```text
magic 0x9043284A | channel byte | payload length int32 | payload
```

Server responses omit the magic prefix. The payload limit is 8 MiB. Channels are API `1`, discarded client logging `2`, local handshake `3` and static data `4`. API requests require a structurally valid handshake; static data can be fetched before it.

The supported handshake body is:

```text
int32 method=1 | int32 apiVersion=25 | int64 clientVersion
int32 deviceLength | deviceBytes
int32 accountLength | accountBytes
```

Each identifier array is limited to 4096 bytes. Truncated data, unsupported versions and trailing bytes are rejected. The response is `int32 1 | byte 0`. The value 25 and the request layout were checked against the 1.1.116 writer. `clientVersion` is not used to assert compatibility.

The [API envelope](WitcherRevival.Server/Net/ApiProtocol.cs) is:

```text
byte version=1 | byte messageType | int32 acknowledgementCount
int64[] acknowledgements | int64 requestId | int32 method | methodPayload
```

Request type is `1`; response type is `2`. Responses acknowledge and echo the request identifier and method. Unknown methods without a verified refusal body remain unanswered, with the session open and the method number logged. Reviewed failures receive complete method-specific DTOs; there is no catch-all success response. Method 122 uses the current task/event contract described above; its original failed fixture is retained in the historical record.

## Static data and maps

[StaticDataSnapshot](WitcherRevival.Server/Net/StaticDataSnapshot.cs) constructs one immutable catalogue per process and shares its serialized content between HTTP and TCP. It combines the retained base structures with reconstructed gameplay, story and optional task rows. Structural catalogue changes require a server restart and a fresh client load; counts from the original fixture do not describe the current catalogue.

Game data includes client-derived, donor-derived, community-supported and authored values. A valid JSON field or a rendered item does not prove its historical numeric value. The [evidence definitions](../docs/SERVER-RECONSTRUCTION.md#evidence-classes) and subsystem records identify that distinction.

The backend's `/v1/featuretiles/{path}` route is an empty stub. Geographic FeatureTiles come from the separate [OSM sidecar](connection/map-road-fixture-01/OSM-LIVE.md), and encounter placement uses a separate playable-locations service. A server health response does not start or validate either dependency.

## Historical stage-aware fixture

The complete early fixture description has moved to [CONTRACT-HISTORY.md](CONTRACT-HISTORY.md). It retains the exact sample response layouts, zero-reward prologue, authored bomb row and historical map/event limits for comparison. Use the current coverage table for active handler behavior.

## Observability

TCP diagnostics include a process-local session counter, frame stages (`magic`, `header`, `body`), expected/received byte counts and `complete` or `eof`. Empty connections and incomplete frames can therefore be distinguished without logging payloads. Request identifiers are protocol correlation values, not profile or account selectors. I/O exceptions and cancellation do not masquerade as EOF.

[HTTP metadata middleware](WitcherRevival.Server/Net/HttpMetadataMiddleware.cs) records a fixed route label, method category, status, response length and exception type. Framework request logging is disabled because it can include URLs and query strings. The middleware does not record URLs, queries, headers, remote addresses or exception messages. Requests rejected before reaching middleware may have no corresponding event.

Account/device bodies and client log-channel payloads are discarded. [Integration tests](tests/test_prototype.py) use synthetic markers to verify that identifiers and HTTP query/header values are not written to logs or profiles. These checks apply to this server, not to every diagnostic component in a client experiment.

## Client recovery

LAB 27 adds a [client request deadline](../docs/REQUEST-RECOVERY-20261003.md)
for tracked native requests. It can show the existing recovery view after 30
seconds of active waiting, without inventing a server response. The server's
verified refusal contracts remain unchanged. During a real maintenance interruption,
LAB 27 displayed the native timeout view; one Try Again returned to the map and
protected GPS acknowledgements. Other device models and failure branches remain
separate acceptance checks.

## Quest relocation (77)

A long identifies the nearby giver served by RPC 40. The response is a success byte followed by locations, active quest nodes and the expiring-instance dictionary; all three collections are mandatory on refusal. The backend now plans new places and saves them in one revision while preserving progress. Cache identity, supported stages, authored placement rules and remaining device checks are described in [quest relocation](../docs/RELOCATION-20261001.md).
