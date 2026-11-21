# extractors repository rules

These rules apply to every contributor, human or agent. `CLAUDE.md` imports this file. README.md describes the library and its layout; CONTRIBUTING.md has the workflow and two worked examples.

## Commands

```bash
uv sync
docker compose up -d --wait
uv run ruff check . && uv run ruff format --check . && uv run pytest
BLESS=1 uv run pytest tests/test_expected.py     # after a version bump
uv run ffxi-extractors index <capture.xicap>...
docker build .                                   # what CI runs
```

The tests use the compose file's ClickHouse; `FFXI_TEST_CLICKHOUSE` names another (`http://user:password@host:8123`). A session sets up its database once and empties it before each test.

## Rules

- Packets are decoded only through `ffxi_packets`, pinned by tag. Never decode a layout here; fix it in `ffxi-dev/packets` and bump the pin.
- Captures are read only through xicap's Python reader, and never changed.
- A unit's `version` changes whenever its output would: `tests/test_expected.py` fails otherwise. After a bump, bless and commit the new pin. A change to what the world keeps bumps `WORLD_VERSION`, which re-runs every unit.
- A capture's rows for a unit change only through `store.begin`, `store.insert`, and `store.done`.
- Ids stay ids. Names come from retail-resources by client version, through the capture's `release` and the `*_names` views, or from the packet that carries them.
- ClickHouse is pinned exactly, at the version Scholar runs, in `compose.yaml` and the Dockerfile's two `COPY --from` lines: bump all three. The default profile in `clickhouse/users.xml` is part of what the SQL means (`store.SETTINGS` checks it), and Scholar's server keeps the same one: change both at once.
- Fixtures and test cases come only from public Mogsafe captures. Keep them few and small.
- Specs live in `openspec/`: a change in behaviour updates its spec in the same commit.

## Writing

Docs, column notes, commit messages: short plain words, active voice, no filler. Every bug fix adds a test that fails without it. Commits are small and say why.
