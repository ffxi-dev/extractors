# Proposal

## Why

A unit's version tells Scholar to re-run it, and `tests/test_expected.py` is what makes a contributor bump it: it pins each unit's output on the fixtures. On the two fixtures, 19 of the 61 pinned tables were empty, so the pins held only the hash of no rows for 14 units (battlefields, defeats, digs, fishing, keyitems, npc_events, npc_shops, npc_trades, obtained, recipes, shops, steals, synths, trades) and for tables of four more (character_params, log_changes, level_changes, registrations). A change to what any of them writes passed CI with no bump, and Scholar kept the old rows. (Codex platform review, 2026-11-27, data #4.)

The release check beyond the pins, `rust/parity`, compares Rust with a cache of Python's rows made at v1.14.4. That proved the migration; it cannot judge a change made since, and the migration's last gate (rust-extractors 1.4, Scholar's full re-index matching its counts and hashes) has no recorded result.

## Target design

- Every pinned table has rows on at least one fixture, and a test fails when one has none. Fixtures stay public Mogsafe captures, few and small: for each table the two leave empty, the smallest capture that fills it, as archived.
- A release is checked against the last release, not against Python: `parity` compares this checkout's rows with the last tag's on the sample, and a unit whose rows differ must have a new version.
- The migration's gate is closed with a recorded result, or revised to say why it is not needed.

## Stages

1. **Pins with rows** (this change's first PR). Nine public captures, 144 KB, 17k packets, join the pin set: captain, PacketViewer, client versions from 2018 to 2026. Every table has rows; `test_every_table_has_rows_in_its_pin` keeps it so. No unit's version changes: the pins gain captures, the output on the old two is the same.
2. **Release against release.** `parity --against <tag>` builds the last release's wheel beside this checkout's and compares their rows on `sample.txt`, with each sample capture's sha256 recorded so the sample cannot drift. A unit whose rows differ and whose version did not change fails. The v1.14.4 Python cache is kept only as the migration's record.
3. **Close the migration gate.** rust-extractors 1.4: run Scholar's per-(table, capture) count and hash comparison once (as recipes 1.4 did), or record the owner's decision that the parity run and the releases since stand for it.

## Impact

- `tests/test_expected.py`, `tests/data/` (nine captures), `tests/expected/*.json` (every pin gains the nine captures' hashes), README.
- No unit's output changes: no version bump, no Scholar re-run.
- CI indexes eleven captures for the pins instead of two: seconds.
