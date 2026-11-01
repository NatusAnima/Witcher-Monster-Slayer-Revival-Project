# Community server: design

Status: decided on 2026-10-25, nothing built yet. This records what the community server is, why it has this shape, and what
building it involves. The feature ideas it serves are in [feature-ideas.md](feature-ideas.md).

## Decisions

| Question | Decision |
| --- | --- |
| What runs where | Each phone keeps running its whole world as today: the map, monster places, fights, the shop, weather and its own map download. The community server only connects players. |
| Host | **Cloudflare Workers with a D1 database**, on the free plan: €0, no machine to maintain. |
| Trust | **Casual.** Each phone's server is under its player's control, so results are taken on trust and sanity-checked; players can report and the maintainer can ban. |
| Tuning | In community mode the phone uses the community's preset, served by the backend. Solo play keeps personal presets. |

## Why this shape

What the current server does, and whether a shared server must do it:

| Part | Shared? | Load |
| --- | --- | --- |
| Game protocol: profiles, fights, inventory, quests, shop, friends | Only friends, gifts and progress others see | Small messages |
| Monster places (the placement service over the map index) | No (see the trade-offs) | The map index of every area played: about twice the OpenStreetMap download, built once per area |
| Map tiles | No | Drawn on the phone from its own map |
| Weather | No | Each phone asks Open-Meteo through the app's relay |
| Game files, app updates | No | The Internet Archive and GitHub Releases |

The map is the only heavy part. Keeping it on the phones leaves the shared part small: kilobytes per player and light requests.
That fits a free serverless plan. A server that holds maps needs about 4 GB of index for Poland, about 60 GB for Europe, and
index builds that a free virtual machine (Oracle's: 2 cores, 12 GB of RAM, 200 GB) can do per country but not per continent.

## The backend

A small TypeScript Worker over a D1 (SQLite) database. Areas are the game's own level-14 S2 cells
(`server/connection/map-road-fixture-01/s2cells.py`); coordinates are only stored rounded to their cell.

What it holds, by phase:

1. **Accounts and friends**
   - An installation key per player, made on the phone and kept out of Android backups. An optional Discord link helps with
     recovery and moderation.
   - Cloud save: a backup and restore of the profile (the Save Data zip), so one player can use several phones.
   - Friend codes, friend lists and a gift mailbox (packs, and later trades).
   - The event calendar and the community's Tuning preset.
2. **Shared moments**
   - Leaderboards and titles: score submissions, batched.
   - Shared lures: a bait placed in a cell, with an expiry; phones in that cell add its monsters.
   - World hunts: a boss announced at coordinates for a weekend. Each phone places it on its own map; the backend pools
     the damage into one health bar and pays by contribution. The hook sets the fight's starting health.
3. **Community features**
   - Schools: membership, weekly goals, nemeton claims by cell.
   - Taverns: check-ins by cell, with an expiry.
   - Trading through the mailbox, the alchemy "first to find" record, the weekly trial.
- **Throughout:** moderation (names, reports, bans), and Discord announcements through webhooks, so no bot process needs
  hosting.

A sketch of the routes (`/v1/…`): `register`, `save` (PUT and GET), `friends`, `mailbox` and `mailbox/{id}/claim`, `events`,
`scores` (POST, batched) and `boards/{board}`, `lures?cells=`, `hunts/active?cells=` and `hunts/{id}/damage`, `checkins`,
`reports`, `account` (DELETE). Operator routes sit behind a secret the maintainer keeps.

## The phone side

- **Through the app's relay.** The phone's server cannot look host names up (musl reads `/etc/resolv.conf`, which Android
  lacks), so it reaches the backend through the companion app, as the weather already does (`ServerService.startWeatherRelay`).
  The relay gets one more loopback port, limited to the backend's host.
- **Social calls.** `SocialService` (friends, gifts, packs) talks to the backend in community mode instead of local storage.
  The community features add their own calls.
- **Joining.** The dashboard gains a Community page: join, leave, status. A join sends the profile's installation key; leaving
  keeps local play intact.
- **Locked Tuning.** In community mode the Tuning page shows the community preset read-only.

## Load and limits

- An active player makes about 50 to 150 requests a day, with syncs batched every few minutes while playing.
- The Workers free plan is reported (for 2026) at about 100,000 requests a day, with D1 at 5 GB of storage, 5 million rows read
  and 100,000 written a day. That covers roughly a thousand daily players.
- **Check these numbers on Cloudflare's own pages before building**: only the enforcement of the D1 daily limits (from
  2026-09-01) comes from Cloudflare's changelog. Past a limit, requests fail until midnight UTC, so the phone must treat the
  backend as optional: solo play continues.
- The free `workers.dev` address has HTTPS, so no domain is needed.

## Trade-offs, accepted

- **Players don't share the same monsters.** Each phone has its own map download and Tuning. Spawns are deterministic, so
  phones with the same map version and the same Tuning would see the same monsters: a possible later step (a community map
  version).
- **Results are taken on trust.** Leaderboards hide results above plausible rates (kills an hour, damage a fight), reports go
  to the maintainer, and a ban hides a player from the boards and stops their social calls.

## Privacy

The maintainer is in the EU, so the GDPR applies.

- The backend sees coordinates only for lures, check-ins and hunts, rounded to their cell, never a track.
- Short retention: lures and check-ins go when they expire, and the scores of finished events are summarised.
- A privacy notice in the app before joining, and `DELETE /v1/account` removes everything about a player.
- No IP logging beyond what Cloudflare itself keeps.

## Operations

- Deployed with Cloudflare's `wrangler` from the maintainer's PC.
- Backups: D1's own restore (check what the free plan keeps), plus a weekly export to the maintainer's PC.
- Discord webhooks announce events and alert the maintainer about errors.
- The backend holds no game files, so a takedown of the file mirror does not touch it.

## Ruled out

| Option | Why not |
| --- | --- |
| A server that holds maps and decides spawns | Disk and index builds grow with every area; past about Europe plus North America it needs paid hosting |
| An Oracle Always Free virtual machine | A machine to keep updated; Oracle reclaims idle free machines and can close free accounts |
| The maintainer's PC behind a tunnel | The community is down whenever the PC is |
