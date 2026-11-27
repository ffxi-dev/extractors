# Tasks

- [x] 1.1 Nine public captures fill every table the two fixtures leave empty; every pin holds them. Verify `tests/test_expected.py` (CI run 46066259206: every m/ and c/ hash as before)
- [x] 1.2 A pin with a table empty on every capture fails. Verify `test_every_table_has_rows_in_its_pin`
- [x] 2.1 `parity --against <tag>` compares this checkout's rows with a release's on the sample, each capture read at its pinned sha256. Verify on lsb 2026-11-27: `parity zones fishing --against v2.15.0` identical on 58/58; `uv run pytest rust/parity`
- [x] 2.2 A unit whose rows differ from the last release with the same version fails the release check. Verify on lsb 2026-11-27: zones' zone_id + 1 failed on 26/58 captures, exit 1; with zones v4, changed and exit 0
- [x] 3.1 rust-extractors 1.4 closed with a recorded comparison, on the mirror by the owner's decision: every capture, no table differs. Verify `openspec/changes/rust-extractors/tasks.md` 1.4
