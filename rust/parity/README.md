# parity

Checks the Rust extractors against the Python ones on real captures, and times both. A port is done when
`parity <its extractor>` says identical on the sample.

```bash
rust/parity/parity actions                          # the sample, 58 captures
rust/parity/parity actions fights --captures all    # every capture in Scholar's mirror
rust/parity/parity actions --captures 2Se_XXHspf9M,vqD1IGCt36hk --rows 20
```

```
actions: identical on 58/58 captures (0 skipped), 17,128,799 packets; python 812.31 s, rust 20.12 s, 40.4x
```

A mismatch prints, for each capture and table that differs, the row counts, the schemas when they differ, and
the first `--rows` rows (default 5) only Python has (`-`) and only Rust has (`+`); the command then exits 1.

A unit is an extractor's name, `decode` (the decoder's tables: captures, sessions, sizes, zone_visits,
activity), `world` (the walk alone, no rows: its time), or `all`.

## What it does

`parity` runs on lsb (`PARITY_HOST`, default `sruon@192.168.1.218`). It copies this checkout's files as they
are, committed or not (`git ls-files -co --exclude-standard`), to a `/tmp` folder there, builds
`rust/parity/Dockerfile` from them, runs `parity.py` in it with the mirror read-only, and removes the folder
and the image after.

For each capture and unit:

- **Python**: a walk with that unit alone, as `index.walk` does it, then its sink's tables. Its rows and time
  are cached in `/home/sruon/scholar-data/parity-ref/<capture>/<unit>.json` and `<unit>.<table>.jsonl.gz`, and
  made again when the unit's version or `DECODER_VERSION` changes. The first check of a unit on a capture makes
  them.
- **Rust**: `extractors_rs.run(path, capture_id, [unit])`, which returns `{table: pyarrow.Table}`; its time.
  The image builds every maturin crate under `rust/` into its environment.
- **Canonical rows**: each row a JSON list of its values in column order (floats as Python's `repr`), the rows
  sorted, so the order they come in does not count, as it does not in ClickHouse. A table is identical when
  its md5 over those rows and its column names and types are.

The speedup is Python's seconds over Rust's, summed over the captures, each the whole walk: read, decode,
world, and the unit. Both run one process a capture, `-j` (default 4) at once. lsb also runs Scholar, whose
indexer can take 14 cores: times are a guide, rows are exact.

`PARITY_RUST=python rust/parity/parity zones` runs Python in Rust's place: every unit identical, about 1x.
`uv run pytest rust/parity` checks the diff.

`parity ref <unit>...` makes Python's cache without Rust; `parity baseline <unit>...` prints Python's
seconds per unit from it.

## The sample

`sample.txt`: for each extractor table, the smallest capture with rows in it and, unless one picked already
has a quarter as many, one of at most 700k packets with the most; PacketViewer, Memoria, and every client
version; and the spike's two large captures. 58 captures, 17.1M packets.
