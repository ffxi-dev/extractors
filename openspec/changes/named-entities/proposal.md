# Proposal

## Why

Scholar's capture page names entities through `capture_entities(capture)`, a view that plans and runs its names lookups again in every query that reads it: about 25 ms on one capture, nearly all of it planning and reading a release's entity names. Eleven of the page's 34 parts read it, so it costs about 275 ms of the 800 a page takes. ClickHouse cannot share it between queries.

## What Changes

- New derived fact `named_entities`: `capture_entities`' rows for one capture, kept in a table sorted as `entity_changes` is (`capture_id, entity_id, idx`), with the capture's `client_version`. A query reads a capture's rows by `capture_id`.
- `capture_entities` stays as it is, for queries across every capture and for the facts that read it.

## Impact

- `facts/named_entities.py`, `facts/__init__.py`; its first pin, `tests/expected/named_entities-v1.json`.
- Scholar runs it over the archive once on the release that brings it, and again on a names reload, as for any fact that reads `capture_entities`.
