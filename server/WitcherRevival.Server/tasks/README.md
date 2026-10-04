# Task catalogue

Set `Tasks:Directory` to a directory containing `daily.json`, `hunt.json`, `timed.json` and `trinkets.json`. Without this option the previous empty task responses remain active. The four files are one validated catalogue, shared by HTTP and TCP static-data responses and every player service. [schema.json](schema.json) describes their structure; `TaskCatalog` additionally checks references, supported conditions, event overlap and the available daily pool.

The supplied daily pool has nine tasks. IDs, draw weights and rewards are authored; localization slugs and contract types come from client 1.1.116. The four-monster target is in its text. Gold payouts of 50, or 100 for a nemeton, are LAB balance rather than recovered historical amounts. The pool excludes distance and time-of-day objectives until the server has the corresponding validated input.

The ten supplied trinkets cover draconids, leshens, nemeta and selected season 1 outputs. Monster counts come from the client descriptions. Story-output mappings use this server's authored output IDs; they do not reconstruct an original contract-type-13 value mapping. Saved kills and reached story outputs permit catch-up. The lifetime nemeton counter starts when task tracking is enabled because old profiles do not retain earlier days' clears.

The [assignment audit](../../../docs/ASSIGNMENT-AUDIT-20261002.md) corrects the first-leshen trinket to monster 31. Earlier copies incorrectly referenced both hound species. Existing installations need the guarded offline correction of the active definition and saved catalogue manifest; deleting an award alone would let the incorrect definition award it again.

## Daily tasks

Each profile draws at most three tasks per UTC day, without repeating a drawn ID that day, and may replace one. Drawing uses the profile and day as a deterministic seed. Tasks require their minimum level; removing or claiming a task does not restore its issuance allowance. Unfinished tasks remain across midnight because the client retains those slots. Free slots can then receive that day's allowance.

Contract types supported for tasks are monster kills (1), nemeta (2), owned bombs thrown (4), crafting (6), absolute player level (7), skills (8), finished quests (9), preparation items (10), combat actions (11) and gathering (12). Monster references must resolve in the world bestiary; crafting and preparation use `item_type`, optional item IDs and `target`. Combat tasks use action indices and an optional `fights` window. A zero window accumulates actions; a positive window tracks actions in that many recent fights, including losses and fights with no matching actions. Completion stays latched.

Progress and reward receipts are saved in the same profile transaction as the underlying action. Tutorial fact 3 gates progress as in the client. The last observed task time prevents clock rollback from reopening old days. The optional `Tasks:FixedUnixTime` setting is for isolated synthetic tests and must remain unset during play.

## Timed events and rewards

The supplied [first LAB event](../../../docs/TIMED-EVENT-20261001.md) has three general objectives and runs from 1–8 October 2026. An operator can append events with unique positive IDs, inclusive Unix-second `start` and `end`, `gold`, `tasks` and `rewards`. Intervals must not overlap. Timed task IDs are distinct from daily and trinket IDs. Use existing client localization slugs; arbitrary text keys will not acquire translations. A timed subtask supports one item reward. The native slot displays gold when positive, otherwise the item; use one reward form per subtask so its preview matches its payout. Event rewards may contain several supported item types.

Each task and event can be claimed once. An event's final reward requires its subtask rewards to have been claimed before expiry. Expired events return the verified empty-event response so the client clears its old panel. There is no claim grace period in this authored policy.

The five-stamp reward is an owned basic summoning scroll, item type 16 / ID 2. ID 1 remains the free tutorial scroll. Using ID 2 atomically spends one item and saves its group plus modifier 13 for 500 seconds. The catalogue includes the scroll, modifier and linking rows required by the client. Its original GUI hides modifier 13. The supplied group contains four common monsters and one rare monster; species selection and the guaranteed rare slot are authored.

## Editing and recovery

The loader checks for edits once per second and retains the last valid catalogue after a failed reload. Daily draw weights, level gates and the missed-day policy may change live. IDs, slugs, targets, rewards and event schedules form the client static catalogue. Existing definitions cannot be removed or redefined, including after restart: the profile directory's `tasks-catalogue.json` records them under an exclusive lock. To introduce different targets or rewards, append new IDs, retain old rows, and set obsolete daily weights to zero. New static rows require a coordinated server and client restart. A running client does not fetch those rows again through event synchronization.

Back up profiles, the manifest and the four definitions together. Preserve issued task definitions and receipt records during recovery. Disabling the option in this binary stops task progression and hides task-only achievements, scrolls, modifiers and summoned groups while retaining their saved state and previously paid gold. Restart the client when disabling or re-enabling it. Do not blindly downgrade to a binary predating these compatibility guards: it lacks the new static rows. Device acceptance and the release gate are tracked in the [roadmap](../../../docs/ROADMAP.md).

Unrestricted combat-action rows use `value4=-1`; zero means steel swords in the native client. [The correction record](../../../docs/MAP-AND-TASKS-20261001.md) explains the silver-sword progress mismatch and static-data reload requirement.
