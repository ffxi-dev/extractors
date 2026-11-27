# extractors repository rules

These rules apply to every contributor, human or agent. `CLAUDE.md` imports this file. README.md describes the library and its layout; CONTRIBUTING.md has the workflow and two worked examples.

## Commands

```bash
uv sync
docker compose up -d --wait
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
BLESS=1 uv run pytest tests/test_expected.py     # after a version bump
uv run ffxi-extractors index <capture.xicap>...
docker build .                                   # what CI runs
cargo fmt --check && cargo clippy --workspace --tests -- -D warnings && cargo test --workspace
rust/parity/parity <unit>...                     # the Rust rows against Python's on lsb's captures
```

The tests use the compose file's ClickHouse; `FFXI_TEST_CLICKHOUSE` names another (`http://user:password@host:8123`). A session sets up its database once and empties it before each test.

## Rules

- Packets are decoded only through rust/xc-decode, from `ffxi-dev/packets`' schemas copied at a tag (`decode.PACKETS`). Never write a layout by hand; fix it in packets and copy the new tag. `tests/test_rust.py` checks the copy byte for byte against the `ffxi-packets` pyproject.toml pins.
- Captures are read only through xicap (its C API in Rust, its Python reader for the header), at the tag pyproject.toml pins, and never changed.
- An extractor is a Python declaration (name, version, reads, sparse, tables, docs) and a Rust crate that matches it; `tests/test_rust.py` checks they agree. Its rows match Python's arithmetic to the bit: `xc_core::py`.
- A unit's `version` changes whenever its output would: `tests/test_expected.py` fails otherwise. After a bump, bless and commit the new pin. A change to what the world keeps bumps `WORLD_VERSION`, which re-runs every unit.
- A capture's rows for a unit change only through `store.begin`, `store.insert`, and `store.done`.
- Ids stay ids. Names come from retail-resources by client version, through the capture's `release` and the `*_names` views, or from the packet that carries them.
- ClickHouse is pinned exactly, at the version Scholar runs, in `compose.yaml` and the Dockerfile's two `COPY --from` lines: bump all three. The default profile in `clickhouse/users.xml` is part of what the SQL means (`store.SETTINGS` checks it), and Scholar's server keeps the same one: change both at once.
- Fixtures and test cases come only from public Mogsafe captures. Keep them few and small.
- Specs live in `openspec/`: a change in behaviour updates its spec in the same commit.
- A helper two units share lives once: in rust/xc-core (`combat`, `vana`, `positions`, `py`) when domains share it, or in a crate of its own beside them (`rust/extractors/link`, `rust/extractors/gathering`) when one domain does; a declaration two classes share, in a module beside them (`link.py`, `battle/positions.py`, `items/gathering.py`). Python imports are absolute.

## Writing

Docs, column notes, commit messages: short plain words, active voice, no filler. Every bug fix adds a test that fails without it. Commits are small and say why.
