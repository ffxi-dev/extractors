# Proposal

## Why

Scholar indexes ~2,200 captures at ~11 us a packet in Python, most of it handing each packet to Python. The owner chose to move the extractors to Rust: no backport, no second path. Rows stay the same, table for table.

## What Changes

- The walk is Rust: `extractors_rs.run(path, capture_id, units)` reads the capture through xicap's C API, decodes through rust/xc-decode (packets' schemas at v2.2.0), keeps the world, and runs every extractor and the decode unit in one pass, returning pyarrow tables typed as the Python Sink made them. `index.run` calls it; its contract, Skipped, and the store's writes are as before.
- Each Python extractor keeps only its declaration (name, version, doc, reads, sparse, tables). Its code is a crate under `rust/extractors/`; `tests/test_rust.py` checks every crate declares what its class does.
- The Python World, Sink, decoder walk, combat, and vana modules are gone; conftest's `drive` and `raw` run the Rust ones (`extractors_rs.drive`, `extractors_rs.raw`), so the tests and pins stand as they were.
- The package builds with maturin: one wheel holds `ffxi_extractors` and `extractors_rs`. It no longer depends on ffxi-packets or numpy. `DECODER_VERSION` stays `2.2.0+world2`.

## Impact

- No unit's output changes, so no version changes and no re-index for correctness. `rust/parity` showed every unit identical to Python on 58 sample captures (17.1M packets), 17-32x faster each; all units in one pass, 16.5x (11.34 to 0.69 us a packet).
- Building the package needs Rust, gcc 14 or newer, git, and zstd's headers: Scholar's image adds the Rust toolchain (Scholar's change).
