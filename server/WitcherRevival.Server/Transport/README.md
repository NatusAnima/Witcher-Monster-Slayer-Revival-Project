# Approved installation transport

This optional listener carries the native game protocol over WebSocket behind a dedicated TLS reverse proxy. An operator approves each installation and selects its profile. The legacy TCP listener and its identity resolution remain unchanged for private clients.

The listener is disabled unless `Transport:Port` is configured. Source tests use synthetic credentials, loopback connections and temporary profiles. They do not establish Android, certificate, router or public-network acceptance.

## Identity and framing

The application generates 32 random bytes per installation, stores them outside Android backup, and sends their canonical base64url encoding without padding in `Authorization: Bearer …`. The APK contains no installation credential. The registry stores SHA-256 of the decoded bytes, never the bearer itself. Public pairing codes identify requests for operator approval; they cannot authenticate a game connection.

`POST /transport/enroll` requires an empty body and returns `status` and `code`. A new installation receives `closed` with an empty code until the operator opens enrollment. An accepted request receives `pending` and a code such as `ABCD-EF01`. Existing requests retain their code and expiry when polled; polling does not write the registry or consume another enrollment slot. Expired pending requests can request a fresh code during an open window. Approved credentials report `approved`; explicitly revoked or expired approvals report `revoked`.

`GET /transport/game` upgrades an approved installation to WebSocket. Each binary message must contain exactly one outgoing native frame: four marker bytes, one channel byte, a four-byte big-endian body length, and that body. WebSocket fragmentation is accepted; multiple native frames in one WebSocket message are rejected. Each response message contains one complete native response frame without the client marker. No WebSocket subprotocol is required.

The first message must be the native authentication frame. Its version and layout are validated, but its device/account identifiers cannot select a profile on this listener. Every authentication and reauthentication uses the profile already bound to the installation. The public static-data URL is selected independently of the private TCP URL. Existing profiles require explicit operator selection; new-profile approval reserves a new server-generated profile ID without copying another player's data.

The Android loopback relay must authenticate its own native caller before using the installation bearer. Loopback TCP alone does not establish the caller's app identity. A per-process cookie checked before any remote action is part of the client integration contract, separate from the server's bearer.

## Listener and proxy configuration

The listener always binds IPv4 loopback on a separate port. The TLS frontend must overwrite the following upstream headers and must never log their credential values:

| Header | Required value |
| --- | --- |
| `Host` | Configured `Transport:PublicHost` |
| `X-Forwarded-Proto` | `https` |
| `X-Monster-Transport-Key` | Private frontend credential read from the configured file |
| `X-Monster-Client-IP` | Frontend-observed client address; required for enrollment |

Requests with an `Origin` header or query string are refused. This transport is intended for the native application. Do not forward arbitrary public paths to the main game HTTP port: that listener also contains private `/prototype/` inspection and mutation endpoints. Expose only the individually reviewed game-content routes needed by the client. The transport listener has no HTTP profile or operator routes.

| Configuration | Behavior |
| --- | --- |
| `Transport:Port` | Default `0`, disabled; otherwise a separate loopback port |
| `Transport:PublicHost` | Required public HTTPS authority |
| `Transport:ProxyKeyFile` | Required private regular file containing 32–128 printable ASCII characters |
| `Transport:RegistryDirectory` | Required private directory, separate from player storage |
| `Transport:StaticDataUrl` | Defaults to `https://PUBLIC_HOST/staticdata`; overrides must use that same authority and path |
| `Transport:PendingSeconds` | Pending invitation lifetime; default 3600, range 1–86400 |
| `Transport:FirstFrameSeconds` | First game message deadline; default 10, range 1–30 |
| `Transport:FragmentSeconds` | Incomplete message deadline after its first fragment; default 10, range 1–30 |
| `Transport:IdleSeconds` | Time without a complete game message; default 300, range 30–3600 |
| `Transport:SessionSeconds` | Maximum connection lifetime; default 14400, range 1–86400 |
| `Transport:DiagnosticsDirectory` | Optional private directory for bounded test diagnostics; unset or empty disables collection |

Normal environment configuration uses double underscores, for example `Transport__Port`. Keep the frontend credential in private files prepared by the deployment workflow. No credential belongs in a command-line argument, repository file, URL or diagnostic report.

## Operator workflow

Run the following from `server/` after building. Replace `TRANSPORT_DIRECTORY`, `PLAYER_DIRECTORY`, `PAIRING_CODE` and `PROFILE_ID` with the deployment's paths and selected public identifiers. These commands operate only on the private transport registry; they do not start a listener or rewrite player progress.

```sh
python -B dev.py run --transport-admin open --registry TRANSPORT_DIRECTORY --ttl-seconds 600 --slots 16
python -B dev.py run --transport-admin list --registry TRANSPORT_DIRECTORY
python -B dev.py run --transport-admin approve --registry TRANSPORT_DIRECTORY --profiles PLAYER_DIRECTORY --code PAIRING_CODE --profile PROFILE_ID
python -B dev.py run --transport-admin close --registry TRANSPORT_DIRECTORY
```

Compare the code shown by the intended device before approval. To give a new player a separate profile, replace `--profile PROFILE_ID` with `--new-profile`. Approval requires an unexpired pending request. The active [operator controls](../../../docs/TESTER-ADMIN-20261004.md) add explicit reassignment to another existing or new profile while preserving saved progress and the access deadline; those controls remain deployed in the current [operator release](../../../docs/OPERATOR-PANEL-20261004.md). Approval lasts 30 days by default; `--ttl-seconds` selects a lifetime from one second through 365 days.

An enrollment window lasts at most ten minutes and accepts at most sixteen new installations. Explicitly opening another window replaces its deadline and remaining count. Closing it stops new requests while existing pending requests remain available for approval. The registry transaction covers both the window counter and new entry, including concurrent operator commands.

```sh
python -B dev.py run --transport-admin renew --registry TRANSPORT_DIRECTORY --code PAIRING_CODE
python -B dev.py run --transport-admin revoke --registry TRANSPORT_DIRECTORY --code PAIRING_CODE
```

`renew` sets an approved or expired approval's deadline to the current server time plus the requested duration, for the same profile. This can shorten existing access; it does not add time to the previous deadline. An explicitly revoked credential cannot be renewed or approved again; reopening enrollment or restarting LAB does not clear its revoked state. Revocation, expiry, registry failure or a changed profile binding cancels an active connection on the next one-second registry check. Registry lock contention is bounded to about one additional second. Reinstalls that lose the bearer require a new request and explicit approval.

## Operator management

The Testers section uses authenticated `GET /api/transport` and revision-guarded `POST /api/transport` on the private administration listener. It exposes public pairing codes, profile summaries, access states and enrollment capacity; bearer values and hashes remain private. The [tester contract](../../../docs/TESTER-ADMIN-20261004.md) describes confirmation, readback, session cancellation and the `bindingRevision` rollback boundary. The current [operator delivery](../../../docs/OPERATOR-PANEL-20261004.md) retains these controls; the tester record preserves their original synthetic and live read-only acceptance.

## Test diagnostics API

`POST /transport/diagnostics` collects a small set of client health observations while an operator tests a build. It requires the same trusted frontend and currently approved installation bearer as the game transport. Collection is disabled by default and returns `404` until `Transport:DiagnosticsDirectory` selects a separate private directory. The route does not read or change player progress, reconnect a game session, or expose a diagnostic viewer. The implementation remains deployed in the current backend, but diagnostic collection is disabled in configuration. Deployment of the code does not establish client reporting or collection.

Send one JSON object with `Content-Type: application/json` and a fixed `Content-Length` of at most 8192 bytes. Chunked or compressed bodies, unknown or duplicate fields, missing fields, nested values and incorrect types are rejected. Every field below is required; ages use `-1` when the client has no observation.

| Field | Accepted value |
| --- | --- |
| `schemaVersion` | Integer `1` |
| `event` | One of the 16 codes listed below |
| `uptimeMs` | Monotonic elapsed time since this reporter started, integer 0–2592000000 (30 days) |
| `clientBuild` | Integer 1–999999; use a documented build identifier such as `290013` for LAB 29 build 13 |
| `foreground` | JSON boolean |
| `nativeHeartbeatAgeMs` | Integer -1–2592000000 |
| `gpsSampleAgeMs` | Integer -1–2592000000 |
| `gpsAckAgeMs` | Integer -1–2592000000 |
| `retryState` | `idle`, `waiting`, `ready`, `running`, `blocked` or `unavailable` |
| `sessionGeneration` | Integer 0–2147483647 |

The event codes are `client-start`, `heartbeat`, `foreground`, `background`, `transport-lost`, `transport-authenticated`, `retry-requested`, `retry-ready`, `retry-failed`, `native-stale`, `native-recovered`, `gps-stale`, `gps-recovered`, `gps-ack-stale`, `gps-ack-recovered` and `client-stop`. They carry no free-form message, exception, stack, coordinates, game payload, device identifier, profile identifier or credential. These are client observations: a heartbeat does not prove that a screen rendered correctly, and a missing report alone cannot distinguish lost connectivity from a stopped process.

```json
{"schemaVersion":1,"event":"heartbeat","uptimeMs":12000,"clientBuild":290013,"foreground":true,"nativeHeartbeatAgeMs":20,"gpsSampleAgeMs":300,"gpsAckAgeMs":-1,"retryState":"idle","sessionGeneration":0}
```

Success is an empty `204` response. Refusals use `400` for schema/framing, `401` for an invalid bearer, `403` for an unapproved installation or frontend, `408` for the absolute three-second body deadline, `413` for size, `415` for content type/encoding, and `429` for limits. `429` includes `Retry-After: 5`; clients should discard stale health observations and avoid accumulating a replay queue. Storage or registry failure refuses the request without returning internal exception text. Approval is checked again after the body has arrived, so revocation during a slow request prevents persistence.

The server allows 12 requests per minute per installation with a burst of four, four per second globally with a burst of sixteen, and at most four concurrent body reads. Invalid schema requests consume the same allowance. The proxy template adds a separate per-address limit on this exact route. Other transport routes retain their zero-body limit.

Only normalized events are appended to `diagnostics-current.ndjson`. On reaching 256 KiB, it replaces `diagnostics-previous.ndjson`; both files together stay at or below 512 KiB. The directory is private (`0700`) and files use `0600` on Unix. A process lock prevents two collectors from writing the same directory. Existing symlinks, non-private files and oversized files are refused. Each record adds a server receipt time and a domain-separated HMAC pseudonym for installation correlation; bearer hashes, pairing codes, profiles and source addresses are not stored in these files. Operational logs contain only aggregate accepted/refused counts at shutdown.

Retention is bounded by size, not by age: records remain until rotation or explicit deletion by the operator. Unset `Transport:DiagnosticsDirectory` and remove the exact proxy location to stop collection, then remove the two diagnostic data files when the test evidence is no longer needed. Keep these records local and outside published source. Neither enabling nor removing diagnostics requires restoring player data.

## Bounds and recovery

There are at most 32 active game connections and two per installation. Input messages are limited to 65,536 bytes including the native envelope, 256 messages per ten-second window, and 8 MiB per window. A response is limited to 8 MiB plus its header and has a 15-second send deadline. The listener uses WebSocket keepalive every 20 seconds.

Enrollment has a global one-request-per-second token bucket with an initial burst of 64, at most 64 pending records, and at most four live pending records per IPv4 address or IPv6 /64. Only a domain-separated HMAC of the source grouping is retained. The frontend should also rate-limit enrollment from its observed client address. Existing approval polling does not consume window slots, though request rate limits still apply. Total retained registry entries are bounded to 4096; explicitly revoked records remain as tombstones.

These controls bound application work and invitation admission. Distributed clients can still consume an open window, and application limits cannot protect a saturated Internet uplink. Keep enrollment windows short and compare device codes before selecting profiles.

To withdraw public game access, close enrollment and disable the dedicated frontend/listener. Retain the registry for later recovery; never restore an old profile backup to undo a transport change. The existing private TCP route remains subject to its original network isolation requirements.

Build and run the focused checks from `server/`:

```sh
python -B dev.py build --no-restore
python -B -m unittest discover -s tests -p test_transport.py -v
python -B -m unittest discover -s tests -p test_transport_diagnostics.py -v
python -B -m unittest discover -s tests -p test_admin_transport.py -v
```

The tests exercise bearer/frontdoor checks, enrollment state, explicit profile binding and reassignment, duration changes, revocation, framing, diagnostic schema and retention limits against temporary servers. The new management tests also cover stale and concurrent writes, rapid A→B→A reassignment, saved-profile preservation and legacy registries. Public TLS and native-client behavior need their own acceptance checks.
