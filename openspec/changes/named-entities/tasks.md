# Tasks

- [x] 1.1 `named_entities` keeps `capture_entities`' rows. Verify `tests/facts/test_named_entities.py`, `tests/test_expected.py`
- [x] 1.2 On prod (2026-11-23, Scholar at extractors v2.1.0, scholar#309): `named_entities` built for all 2,200 captures in 4.1 min of the indexer; its rows, hashed per capture over every column the view gives, equal `capture_entities(capture)`'s on all 2,200 (1,461,818 rows)
