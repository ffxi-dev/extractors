# Proposal

## Why

A re-run of the archive took about two hours, ClickHouse at its 8 cores and the indexer near 40%. `entity_changes` was sorted by entity first, so every read of one capture's entities read the whole table (1.77M rows), and `capture_entities` reads it three times a call: 7.35M rows and 190 ms each, in every derived fact and capture page part that names an entity. The capture page's mobs part read 103M rows, bestiary 33M.

## What Changes

- `entity_changes` is sorted by capture first: every reader takes one capture.
- `setup` copies a table made under another ORDER BY into one sorted as the code says, rows and all, and swaps it in once.

## Impact

- `ffxi_extractors/store.py`, `extractors/world/entity_changes.py`, `tests/test_index.py`. No output changes, so no version moves.
