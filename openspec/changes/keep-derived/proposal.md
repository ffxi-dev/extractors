# Proposal

## Why

`setup` drops a derived table whose engine or column types no longer match its SQL, and makes it again, empty. Scholar runs setup as its indexer starts, so after such a release every mob page and query over that table sees no rows until Scholar's rebuild fills it; if the rebuild fails, the table stays empty. Scholar's rebuild already builds a new table beside the live one and swaps them, so the drop only opens that gap. Step 1 of vault's `release-schema` change.

## What Changes

- `store.pending(con)` lists the derived units whose table is of another engine, or holds a column the SQL dropped or retyped.
- `setup(con, keep=True)` leaves those tables as they are, rows and all, for Scholar's rebuild to replace. `setup(con)` still makes them again, empty, for a caller with no rebuild (this library's own `index` command).

## Impact

- `ffxi_extractors/store.py`, `tests/facts/test_bestiary.py`. No unit's output changes; no version bump.
- Scholar passes `keep=True` and rebuilds the units `pending` lists, in the release that moves its tag.
