# Proposal

## Why

Scholar's mob, NPC, weather, and item pages read the derived facts through 24 queries that lived in Scholar's `queries.json`, with the 37 tests that check them. A change to a derived fact here could break what the pages show and only Scholar's suite would see it, on the next release.

## What Changes

- The 24 queries are files in `ffxi_extractors/sql/pages/`, one each, their `{name:Type}` blanks ClickHouse parameters; `store.pages()` reads them by name.
- Their tests move to `tests/pages/`, and `fill.ask` runs one by name.
- Plain queries, not parameterized views: ClickHouse types a view when it is made and refuses the nullable tuples `tp_moves` and `fishing_catalog` give.

## Capabilities

### Modified Capabilities
- `extractor-library`: the library holds the queries a page across captures runs.

## Impact

- New `ffxi_extractors/sql/pages/`, `store.PAGES` and `store.pages()`, `tests/pages/`, `fill.ask`.
- No table's output changes, so no version bumps.
- Scholar reads its page queries from `store.pages()`.
