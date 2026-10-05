# Operator panel

The operator panel inspects delivered game state and applies validated changes
to world policy, weather, news, tasks and saved profiles. Its map workspace adds
local OpenStreetMap geometry, placement diagnostics and next-day placement
controls. See [placement controls and acceptance limits](../../../docs/PLACEMENT-CONTROLS-20261003.md).

The admin API shares the running server's profile registry and validators through [AdminServer](AdminServer.cs), on a separate loopback listener. The active [operator delivery](../../../docs/OPERATOR-PANEL-20261004.md) serves the panel through the independent [gateway](../../OperatorControl/README.md), preserving Engine controls when the game is stopped. Eleven sections cover overview, map, weather, news, tasks, players, testers, game catalogue, operation history, Help and Engine. Ten language packs contain 1,122 entries each. [Tester administration](../../../docs/TESTER-ADMIN-20261004.md) retains its original feature contract and activation record; current source, package, browser and live boundaries belong to the operator delivery record.

The top-bar language selector supports Polish, English, Spanish, French, German, Ukrainian, Hungarian, Czech, Slovenian and Slovak. It preserves drafts and is independent of the news publication language. See [language behavior and verification](../../../docs/ADMIN-LANGUAGES-20261002.md).

## Choose a task

Open the private panel address configured by the operator, for example `https://admin.example.org/panel/`, with the required gateway login or client certificate. The application does not provide its own password form. The public game and APK-download hosts do not expose this interface.

| Section | Use it to |
| --- | --- |
| Overview | Check observed process/host load, uptime, reset time and current service information. |
| Map | Select a profile, inspect delivered encounters and local OSM context, and preview future placement changes. |
| Weather | Inspect automatic lookup provenance or save a temporary global override. |
| News | Choose a publication language, edit the whole feed and manage cover images. |
| Tasks | Edit eligible daily rotation/stamp policy or stage structural definitions for maintenance. |
| Players | Inspect saved progress and perform explicitly confirmed offline maintenance. |
| Testers | Open enrollment, approve a pairing code, change its profile/deadline or revoke access. |
| Game catalogue | Search immutable tables, identifiers and current values. |
| History | Inspect panel receipts, conflicts and applicable private backup metadata. |
| Help | Read operation-specific effects and recovery limits. |
| Engine | Start, stop or restart the fixed game service through the [independent operator gateway](../../OperatorControl/README.md), which remains available while the game is stopped. |

Before changing a value, check its target, observation time and current revision. A language change preserves drafts and performs no save. When a write reports uncertainty, inspect its receipt and refresh current state before trying again.

### Publish a news list

Select the **publication language** independently of the interface language. Each language is a complete JSON document. The full list, including serialized JSON formatting, must fit within 1 MiB. Add or edit entries, select the optional featured entry, review the entire list and publish once. Removing a row from the draft removes it from that language's published list when saved.

```json
{
  "news_list": [
    {
      "id": 101,
      "group_id": "announcement-101",
      "title": "New testing session",
      "short_description": "The next field trial is ready.",
      "date": "04/10/2026",
      "image_url": "",
      "content": "First paragraph.\nSecond paragraph."
    }
  ],
  "featured": 101
}
```

| Field | Meaning and accepted value |
| --- | --- |
| `news_list` | At most 100 entries; an empty list is valid. Publishing replaces the whole selected-language list. |
| `id` | Unique positive integer within the list. Preserve it when correcting an entry. |
| `group_id` | Nonblank read-state key, at most 128 characters, with no semicolon. Retain it for corrections; do not use it as a publication date. |
| `title`, `content` | Required nonblank text. A JSON `\n` inside `content` represents a newline. |
| `short_description` | Text; an empty string is allowed. |
| `date` | A real calendar date written exactly as `dd/MM/yyyy`. This is a display label, not scheduled publication. |
| `image_url` | Empty for `default.png`; otherwise an existing library filename or an absolute HTTP(S) URL. A filename has a 1–64 character base using letters, digits, `_` or `-`, then `.png`, `.jpg` or `.jpeg`. |
| `featured` | An existing entry ID, or `0` for no automatically opened entry. |

Upload a local cover before referring to its filename. Covers must be valid PNG/JPEG, no larger than 4096 × 4096 pixels and 2 MiB. If no custom `default.png` exists, the server supplies a generated cover. An external URL must load on the client: the original UI waits for the cover before showing an entry. The panel's upload operation does not fetch or validate an external site's image.

The server reports structured validation errors with `field` and `code`, including a zero-based entry path such as `news_list[0].date`. It also rejects a missing named library cover. A successful publish saves a backup and receipt, checks the draft's original revision and atomically replaces the file. The next news request sees it; the date does not delay it. A stale revision requires comparing the fresh document with the draft before resubmission.

### Inspect player progress

Choose the intended saved profile in **Players** and check its revision. The `/api/profiles/{id}/progress` projection separates season-one story, daily tasks, timed events, trinkets, hunt stamps and credited distance. It reads one saved snapshot; opening the view does not issue tasks, reconcile elapsed windows, unlock trinkets or claim rewards.

An entry can be complete but still awaiting a gameplay refresh or a player reward claim. Missing saved data is shown separately from zero progress. Claimed daily tasks disappear from the save, so this view cannot supply a complete daily-task history. Story branch outputs are not a completion percentage, and names can be catalogue identifiers or embedded English names rather than the client's localized labels. Credited distance may include older unverified reports or offline operator changes; it is not proof of real-world travel.

### Approve a tester and inspect a map

Open a bounded enrollment window in **Testers**, compare the installation's pairing code and expiry with the device, then explicitly choose a new or existing profile. Selecting an existing profile gives that installation access to its progress. Review profile, duration and impact before confirming. Revocation permanently rejects that installation's code/credential; restarting the same application does not create a new approved identity. The [tester contract](../../../docs/TESTER-ADMIN-20261004.md) covers renewal, reassignment and recovery.

After the client requests its map, select that profile in **Map**. The atlas and listing show the same retained delivered response. Check its age before interpreting missing or defeated monsters. Layer filters change the inspection view, not the game's world. Preview placement changes before saving; scheduled geography activates on the next UTC placement day, while existing encounters retain their original generation. Use **Weather** for current policy and expiry, and **History** for the saved receipt.

## Enable behind an authenticated proxy

`Admin:Port` defaults to `0`, which disables the listener. The independent-gateway example uses backend admin port 18092 and gateway port 18090; follow the [gateway configuration](../../OperatorControl/README.md) before assigning these ports. Configure the backend values through the service’s private configuration:

| Setting | Meaning |
| --- | --- |
| `Admin:Port` | A free loopback port distinct from the game TCP and HTTP ports. |
| `Admin:Origin` | The browser's exact HTTPS origin, without a path. HTTP is accepted only for loopback fixtures. |
| `Admin:KeyFile` | Owner-readable file containing a 32–256 byte printable ASCII proxy credential. Keep it out of arguments, logs and source control. |
| `Admin:DataDirectory` | Private storage for receipts, backups and staged catalogues. |
| `News:Directory` | The active game news directory. |
| `Tasks:Directory` | The active external task catalogue. |
| `World:SpawnBalanceFromUnixSeconds` | Absolute activation time for the [88:18:3 rarity lottery](../../../docs/SPAWN-WEIGHTS-20261002.md), read at startup. Default `0` for fresh installations; retain the configured timestamp across upgrade restarts. Read-only in the panel. |
| `World:Directory` | Directory containing a valid `world.json`, optional `weather.json`, generation history `spawn-balance.json` and versioned `placement-policy.json`; see [WorldPolicy](../Net/WorldPolicy.cs), [WorldWeather](../Net/WorldWeather.cs) and [placement controls](../../../docs/PLACEMENT-CONTROLS-20261003.md). |

The reverse proxy must authenticate the operator, strip incoming `X-Monster-Admin-Key` and inject its own value from protected configuration. In the active topology it forwards to the independent gateway, which serves the UI and proxies game-dependent API requests to the backend admin listener. The shared header authenticates the proxy, not a person. Use the deployment's existing mTLS or authenticated gateway and retain its access logs for human attribution. Do not expose the loopback listener through an unauthenticated forwarder. The phone companion app has no proxy: its in-app browser presents the key as the `monster-admin-key` cookie, which the listener accepts when the header is absent.

Assets and API calls use relative URLs. A proxy can mount the panel under a prefix such as `/panel/` by stripping that prefix upstream and redirecting the path without a trailing slash. `Admin:Origin` remains the origin, for example `https://lab.example.com`.

Every API request requires the proxy credential. Mutations also require the configured `Origin` and the panel's request marker. Responses prohibit caching and framing. The game listener has no admin routes. Keep its separate diagnostic `/prototype` endpoints out of any game-facing proxy allowlist.

## Operations and visibility

| Operation | Validation and effect |
| --- | --- |
| Server resources | Read-only process CPU/RSS/uptime and Linux host CPU/RAM/load/uptime. Actual CPU averaging windows and stale/unavailable states are explicit. See [metrics contract](../../../docs/ADMIN-METRICS-20261002.md). |
| Map inspection | Select a saved profile to inspect its last retained nonempty RPC 40 response alongside local OSM geometry and bounded placement diagnostics. Layers, point details and the paginated text listing share the same delivered snapshot. Read-only; does not generate encounters. |
| Future placement policy | Preview and save global point caps, spacing, exclusion circles and preferred points. Revision guards, OSM validation, backup and receipts apply. Changes activate on the next UTC placement day and preserve historical epochs and existing encounters. See [placement contract](../../../docs/PLACEMENT-CONTROLS-20261003.md). |
| Weather | Automatic mode or a temporary global override for up to 24 hours, with validation, revision, backup and receipt. The next-request policy and last server lookup have separate provenance. |
| Player inspection | Inventory, equipment, skills, bestiary, story, tasks, distance, crafting and aggregate social state from saved snapshots. No rewards or gift reconciliation on reads. |
| Tester installations | List pairing codes, states, selected profiles and deadlines; open/close enrollment, approve a pending code for a new or existing profile, set duration from now, rebind while preserving the deadline, or revoke access. Revision checks and receipts apply; no credentials are exposed. See the [contract and recovery limits](../../../docs/TESTER-ADMIN-20261004.md). |
| GPS and distance policy | Displays short-lived fixes, negotiated capability, credited totals and coordinate-free decisions. Observation or protected policy takes effect at a fresh capable handshake; existing protection stays latched. See [GPS controls and retention limits](../../../docs/GPS-PANEL-20261003.md). |
| Game catalogue | Search the active immutable tables and bestiary. Read-only; editing balance remains a maintenance operation. |
| News | Uses the game's `NewsFeed.Validate`, a SHA-256 revision guard, private backup and atomic replacement. Visible on the next feed request. |
| Covers | PNG/JPEG signatures and dimensions, safe filenames and a 2 MiB limit. The interface adds new filenames; the API requires a matching revision to replace an existing file. |
| Daily rotation | Only `weight` and `min_level` may change live. Existing IDs, conditions and rewards remain immutable. New draws use the new policy. |
| Stamp policy | Only the missed-day `streak` setting changes live. |
| Full task catalogue | Uses `TaskCatalog.Validate`, retains existing persisted definitions and stages new IDs for maintenance. It does not replace the active catalogue during gameplay. |
| Rarity and species policy | Edit category weights and species multipliers, disable individual species, inspect normalized chances and transition times. Revision guards, backups, receipts and forward-only restoration preserve living generations. See [live controls](../../../docs/ADMIN-CONTROLS-AND-DIFFICULTY-20261002.md). |
| Monster density | Uses `WorldPolicy.Validate`; the server reads changes within one second. Already loaded client cells may await their next map refresh. |
| Reset, copy, story clock, restore | Requires closed game sessions, current profile revisions and typed target confirmation. Writes a private backup before replacing the profile. |

Rebinding a tester installation changes which profile that installation can use; it preserves both saved profiles and the access deadline, and ends the installation's existing transport sessions. Selecting an existing profile grants access to its existing progress. It does not copy progress. Revoked access cannot be approved or renewed with the same code or credential. Enrollment controls only new requests, independently of existing approvals.

Copying progress overwrites the destination's saved progress and leaves the source unchanged. Each device retains its existing identity binding, and the two profiles then develop independently. It does not merge inventories or provide account login. The source must also be offline, and its revision is checked.

The `Reconstruction:*` balance settings described in the [alchemy and skills packet](../../../docs/ALCHEMY-SKILLS-20261002.md) and [Witcher Aura contract](../../../docs/WITCHER-AURA-20261002.md) belong to service configuration. They require a server and client reload and are not live panel edits.

Story-clock changes affect the selected profile's story offset only. Daily stamps remain on the UTC boundary. The overview converts the next UTC reset to the browser's timezone without changing the server clock.

A restored profile receives a new revision. Restoration also backs up the current state. The history view offers restoration only for applied profile operations; the server binds the backup to its original target and repeats the offline and revision checks. The panel does not return raw profiles, identity bindings or identity keys. Its map endpoint returns encounter coordinates from the selected profile's delivered response, with an explicit source and age. The separate GPS view can show the latest client fix for up to 120 seconds; it does not store or reconstruct a route.

## Map and weather limits

The map combines one delivered response with locally retained OSM roads,
buildings and water. Geometry comes from authenticated same-origin endpoints;
the browser requests no external tiles or device location. The response remains
an observation, not the player's current screen. Cell centres do not represent
boundaries. Responses retain at most 64 cells and 4,096 points for each of 32
profiles. They become stale after two minutes and expire after an hour; server
restart clears them. Empty deltas do not erase the last nonempty response.
Defeated or expired encounters may remain in that snapshot, while successor
responses and personal summons are outside it. The interface can open the area
in an external map only on an explicit operator action.

Placement previews report safe candidates and rejection counts for retained
cells. They do not promise encounters at every preferred point. OSM walkable or
open ground and fixed road, building and water clearances remain mandatory.
Policy limits are 8–64 points per cell, 35–120 metre spacing, 32 exclusion circles
with 10–1,000 metre radii, and 64 preferred points. Missing policy keeps the
existing 24-point, 50-metre defaults. Exact routes, validation, scheduling and
history bounds are documented in [placement controls](../../../docs/PLACEMENT-CONTROLS-20261003.md).

Automatic weather depends on the requested location. The last lookup belongs to the process and can also come from world generation; it does not prove what a particular player sees. Provider/cache/fallback sources and lookup/data-fetch timestamps remain distinct. Manual overrides affect all players, expire within 24 hours and reload within one second. Existing retained monster generations keep their weather; generation-cache eviction and restart remain continuity limits. The native client normally requests weather about every five minutes.

## Apply a staged catalogue

The game client caches static task definitions. Apply a staged catalogue during maintenance, with the game service stopped and players ready to restart LAB. From this directory:

```sh
python apply_staged_tasks.py \
  --admin-directory "$LAB_ADMIN_DIRECTORY" \
  --tasks-directory "$LAB_TASKS_DIRECTORY" \
  --profiles-directory "$LAB_PROFILES_DIRECTORY" \
  --operation-id "$LAB_STAGED_OPERATION"
```

Set these variables to the same private directories as the running service and the receipt ID shown by the panel. The Linux tool acquires the catalogue lock used by the game process, verifies the staged hash and all four reviewed input-file hashes, and backs up the previous files. It replaces the files while holding the lock and updates the receipt. A running service, changed inputs or repeated application is refused. A write failure restores files already replaced by that invocation.

Start the service and check its health and task catalogue before reopening LAB. If startup fails, retain the failed candidate and restore the four files from that operation's private task backup while the service remains stopped. Once the new catalogue has been loaded and its IDs persisted, keep those IDs in later catalogues rather than deleting them during rollback.

## Receipts and recovery

Document writes use their original SHA-256 revision; repeated or stale requests return a conflict. Profile writes use saved revisions and active-session leases. Each accepted mutation records its action, target, time, state and before/after revision or digest. Receipt IDs identify private backups. Transport receipts retain only non-secret before/after summaries; they do not offer an automatic registry restore. After an uncertain transport response, inspect history and refresh the installation state before another action. The history view can inspect previous news, world, weather, rotation and stamp-policy documents. It does not export profile backups. Restoring configuration requires reviewing the previous document and saving it against the current revision; expired weather overrides require a new valid expiration.

Receipts cover this panel only. They do not attribute an individual human or record manual filesystem edits. The gateway's authentication logs provide the operator identity. An interrupted request may have reached disk before the browser saw a reply: inspect the receipt and current state before retrying. A bounded browser timeout restores controls and explains this uncertainty.

Resource metrics refresh about every five seconds only on a visible overview. This independent read does not reload forms or prove external dependency health. The other interface data refreshes on navigation or request, preserves edited fields on validation/conflict errors, and prevents switching targets during submission. Saving one task form preserves drafts in the other forms.

## Verification

The [operator integration tests](../../tests/test_admin.py) use temporary directories, synthetic identities and real loopback server processes. They cover authentication/origin/port separation, news validation and backup, image boundaries, world reload, rotation restrictions, catalogue maintenance locks, offline profile guards, copy preservation and backup restoration. Additional cases compare map observations with binary RPC responses, verify catalogue identity and side-effect-free profile/social reads, and exercise weather expiry, restart, invalid writes and per-cell provenance. Run them from the prototype directory after building:

```sh
PYTHONPATH=server:server/tests python -m unittest -v test_admin
```

The current release passes 295 exact-source backend checks and 28 operator checks; the Debian packages pass 109 backend runtime and 28 operator tests without skips. Browser acceptance comprises 58 synthetic journeys, 29 pressure checks and 157 checks across the ten languages. Credentialed reads through the private relay to the configured upstream verify all 17 pinned assets, engine state and proxied API behavior. They do not traverse nginx HTTPS/mTLS. Real stop/start/restart operations pass through the same authenticated API contract, with the gateway available while the game is stopped. These were producer requests, not browser clicks. See the [delivery record](../../../docs/OPERATOR-PANEL-20261004.md) for precise scope; the earlier 79 focused and 41 browser checks remain in the dated [tester record](../../../docs/TESTER-ADMIN-20261004.md). No authenticated live-browser or resulting Android flow is inferred.

Browser acceptance uses a disposable proxy and fixtures, separate from deployment acceptance. Native dialog focus, responsive layouts, draft preservation and conflict recovery were exercised in Chromium; this does not establish coverage for other browsers or assistive technologies.
