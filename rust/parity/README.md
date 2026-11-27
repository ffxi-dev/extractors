# parity

Checks the Rust extractors on real captures against a reference, and times both: the Python extractors'
last release (v1.14.4), or, with `--against <tag>`, an earlier Rust release. A port was done when
`parity <its extractor>` said identical on the sample; a release is ready when `parity --against <the last
tag> all` fails no unit.

```bash
rust/parity/parity actions                          # the sample, 58 captures
rust/parity/parity actions fights --captures all    # every capture in Scholar's mirror
rust/parity/parity actions --captures 2Se_XXHspf9M,vqD1IGCt36hk --rows 20
```

```
actions: identical on 58/58 captures (0 skipped), 17,128,799 packets; python 60.20 s, rust 58.60 s, 1.0x
```

(That was Python in Rust's place, `PARITY_RUST=python`.)

A mismatch prints, for each capture and table that differs, the row counts, the schemas when they differ, and
the first `--rows` rows (default 5) only Python has (`-`) and only Rust has (`+`); the command then exits 1.

A unit is an extractor's name, `decode` (the decoder's tables: captures, sessions, sizes, zone_visits,
activity), `world` (the walk alone, no rows: its time), or `all`.

## Against a release

```bash
rust/parity/parity --against v2.15.0 all             # this checkout against v2.15.0, on the sample
rust/parity/parity ref --against v2.15.0 all         # only make v2.15.0's rows
```

```
fishing: identical on 58/58 captures (0 skipped), 17,128,799 packets; v2.15.0 1.91 s, rust 1.88 s, 1.0x
```

With zones' zone_id one higher and its version as it was (2026-11-27, a trial):

```
zones k8NFtuhORJWF: mismatch
  zones: rows v2.15.0 1, rust 1
    columns: capture_id, idx, ts_ms, client_version, zone_id, server
    - ["k8NFtuhORJWF", 25, 1760673669000, "Version 18:48:06 Oct  2 2025", 256, null]
    + ["k8NFtuhORJWF", 25, 1760673669000, "Version 18:48:06 Oct  2 2025", 257, null]
...
zones: rows changed since v2.15.0 with the version as it was: bump it
zones: mismatch on 26/58 captures (0 skipped), 17,128,799 packets; v2.15.0 1.70 s, rust 1.71 s, 1.0x
```

and with its version bumped, exit 0:

```
zones k8NFtuhORJWF: changed with the version, 3/2.3.0+world2 to 4/2.3.0+world2
...
zones: changed on 26/58 captures (0 skipped), 17,128,799 packets; v2.15.0 1.70 s, rust 1.70 s, 1.0x
```

The release's rows are made once, in an image of the tag built without the shared target cache (the tag's
files carry its commit's times, which cargo would take as older than any build there), by this checkout's
`parity.py`, and kept in `/home/sruon/parity-release/<tag>/` (`PARITY_RELEASES`): a tag never changes. Then
this checkout's rows are compared with them. A unit whose rows differ and whose version (with the
decoder's) is as it was in the tag is a mismatch, and the command exits 1: Scholar would keep its old rows.
Rows that differ under a new version are shown, as Scholar re-runs the unit for them. A unit the release
lacks, or a capture it passed by, is skipped. Tags from v2.0.0 on.

## What it does

`parity` runs on lsb (`PARITY_HOST`, default `sruon@192.168.1.218`). It copies this checkout's files as they
are, committed or not (`git ls-files -co --exclude-standard`), to a `/tmp` folder there, builds
`rust/parity/Dockerfile` from them, runs `parity.py` in it with the mirror read-only, and removes the folder
and the image after.

For each capture and unit:

- **Python**: a walk with that unit alone, as `index.walk` does it, then its sink's tables. Its rows and time
  are cached in `/home/sruon/scholar-data/parity-ref/<capture>/<unit>.json` and `<unit>.<table>.jsonl.gz`, and
  made again when the unit's version or `DECODER_VERSION` changes. The first check of a unit on a capture makes
  them. The Python walk is gone since the Rust switch: the cache, made at v1.14.4, is the reference, and a
  checkout of v1.14.4 makes it for a capture it lacks (`parity ref`).
- **Rust**: `extractors_rs.run(path, capture_id, [unit])`, which returns `{table: pyarrow.Table}`; its time.
  The image builds the package, extractors_rs in it, into its environment.
- **Canonical rows**: each row a JSON list of its values in column order (floats as Python's `repr`), the rows
  sorted, so the order they come in does not count, as it does not in ClickHouse. A table is identical when
  its md5 over those rows and its column names and types are.

The speedup is Python's seconds over Rust's, summed over the captures, each the whole walk: read, decode,
world, and the unit. Both run one process a capture, `-j` (default 4) at once. lsb also runs Scholar, whose
indexer can take 14 cores: times are a guide, rows are exact.

`PARITY_RUST=python rust/parity/parity zones`, from a checkout of v1.14.4, runs Python in Rust's place: every
unit identical, about 1x. `uv run pytest rust/parity` checks the diff.

`parity ref <unit>...` makes Python's cache without Rust; `parity baseline <unit>...` prints Python's
seconds per unit from it.

## The sample

`sample.txt` names each capture by id and by the sha256 of its file, as the mirror names it, so a live
capture that grew since is read as it was; a file the mirror no longer holds stops the run. For each extractor
table, the smallest capture with rows in it and, unless one picked already
has a quarter as many, one of at most 700k packets with the most; PacketViewer, Memoria, and every client
version; and the spike's two large captures. 58 captures, 17.1M packets.

## Baseline

Python on the sample, lsb, 2026-11-22, Scholar idle, `-j 4`: `parity baseline all`. Each unit's walk alone, and
what it adds to the world-only walk. Every table's row count matched Scholar's on every capture.

58 captures, 17,128,799 packets; world-only walk 36.0 s, 2.10 us/packet.

| unit | seconds | over the world-only walk | us/packet |
|---|---|---|---|
| engages | 79.3 | +43.3 | 4.63 |
| looks | 64.6 | +28.7 | 3.77 |
| actions | 60.2 | +24.2 | 3.51 |
| effects | 49.9 | +13.9 | 2.91 |
| hp | 49.3 | +13.3 | 2.88 |
| delay | 48.7 | +12.7 | 2.84 |
| kills | 48.2 | +12.2 | 2.81 |
| fights | 47.6 | +11.6 | 2.78 |
| entity_changes | 47.3 | +11.3 | 2.76 |
| decode | 45.5 | +9.5 | 2.66 |
| immunity | 45.1 | +9.2 | 2.64 |
| mob_messages | 44.8 | +8.8 | 2.62 |
| experience | 40.6 | +4.6 | 2.37 |
| spawns | 40.5 | +4.5 | 2.36 |
| levels | 40.0 | +4.0 | 2.33 |
| obtained | 39.1 | +3.1 | 2.28 |
| character | 38.6 | +2.6 | 2.25 |
| events | 38.3 | +2.3 | 2.23 |
| fishing | 37.8 | +1.9 | 2.21 |
| holdings | 37.8 | +1.8 | 2.21 |
| influence | 37.8 | +1.8 | 2.20 |
| keyitems | 37.6 | +1.7 | 2.20 |
| conquest | 37.5 | +1.5 | 2.19 |
| evasion_skill | 37.4 | +1.4 | 2.18 |
| shops | 37.4 | +1.4 | 2.18 |
| digs | 37.3 | +1.3 | 2.18 |
| drops | 37.2 | +1.3 | 2.17 |
| battlefields | 37.2 | +1.2 | 2.17 |
| trades | 36.9 | +0.9 | 2.15 |
| party | 36.8 | +0.8 | 2.15 |
| zones | 36.8 | +0.8 | 2.15 |
| weather | 36.7 | +0.8 | 2.15 |
| synths | 36.6 | +0.7 | 2.14 |
| defeats | 36.6 | +0.6 | 2.14 |
| world | 36.0 | +0.0 | 2.10 |

## The archive: rust-extractors 1.4

`archive.py` compared v1.14.4's Python with v2.0.0's Rust, the two sides of the switch, on every capture in
the mirror: each (table, capture)'s rows and an order-free hash, the sum mod 2^128 of each canonical row's md5,
with no row kept. Python ran as its `index.run` did, every extractor and the decoder in one walk; Rust as
`extractors_rs.run` with the same units. Each side ran in an image of its tag on lsb, four workers in a
container of 12 GB and 4 CPUs, then one worker for what a killed worker left; the images and work folder were
removed after. The result is in `openspec/changes/rust-extractors/tasks.md`, 1.4.
