# Proposal

## Why

A release that re-runs one extractor walks every capture, though most hold none of the packets it reads: synthesis packets are in 130 of 2,182 captures, conquest's and influence's in under half. The owner approved passing those captures by.

## What Changes

- `Extractor.sparse`, True unless set: the extractor's rows come only from its reads outside the world's, so a capture holding none of them gives it no rows. False for zones, entity_changes, and engages, which also write from the world's packets they read, and for party, holdings, weather, and looks, which read only the world's.
- A test walks the fixtures once per sparse extractor with its own packets left out and asserts no rows.
- Scholar passes by such a capture on a re-run (Scholar's change).

## Impact

- `ffxi_extractors/extract.py`, the seven extractors above, `tests/test_sparse.py`. No output changes, so no version changes.
