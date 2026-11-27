# extractors

Turns FFXI captures into ClickHouse tables and findings. **Extractors** read one capture's packets in order and write rows: every action, each mob's HP, effects, spawns, weather, drops, and more. **Derived facts** are ClickHouse SQL over those rows: the bestiary, melee rounds, TP moves, aggro, steals, NPC events, trades, shops, and recipes.

[Scholar](https://scholar.sruon.dev) runs this library over every capture [Mogsafe](https://mogsafe.sruon.dev) keeps, and its mob pages show the results. A change merged here reaches Scholar in the next release.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Docker, [Rust](https://rustup.rs), git, and gcc 14 or newer with CMake and zstd, which xicap's reader builds with. The extractors are Rust (`extractors_rs`); `uv sync` builds them into the package.

```bash
uv sync
docker compose up -d --wait                          # ClickHouse on 127.0.0.1:8123, user ffxi, password ffxi
uv run pytest                                        # every test and pin
uv run ffxi-extractors index tests/data/*.xicap      # the fixtures, with names
docker compose exec clickhouse clickhouse-client --user ffxi --password ffxi -d ffxi
```

`ffxi-extractors index` downloads [retail-resources](https://github.com/ffxi-dev/retail-resources)' names into `var/names` the first time; `--no-names` skips them. It writes to `FFXI_CLICKHOUSE` (`http://user:password@host:8123/database`), else to compose's ClickHouse, database `ffxi`. A capture's id is its file name, so save a Mogsafe capture as `<id>.xicap` for its Lens links to work.

## Captures

- `tests/data/` holds public Mogsafe captures: a Memoria recording, a converted captain log, and, named by id, the small captures that give every pinned table rows (`tests/test_expected.py`).
- Any capture Mogsafe keeps downloads from `https://mogsafe.sruon.dev/c/<id>`, no sign-in needed. The id is the last part of the capture's page address.
- Your own recordings from [Memoria](https://github.com/ffxi-dev/memoria) or captain index the same way.

Only retail captures are read.

## Layout

```
ffxi_extractors/
  capture.py     a xicap capture's header, and which captures are read
  decode.py      the decode unit's tables: what the decoder counts of every packet
  world.py       the packets the world reads: zone, character, party, inventory, entities
  extract.py     the contract: Extractor, Derived, Table, Column, and SQL fragments facts share
  index.py       walks a capture once in Rust with every extractor, then runs the derived facts
  store.py       the ClickHouse tables and each unit's write
  resources.py   mirrors and loads retail-resources' names
  cli.py         ffxi-extractors index
  link.py        the packets an event is made of
  sql/setup.sql  SQL functions and views the facts share
  extractors/    each extractor's declaration: name, version, reads, tables; listed in extractors/__init__.py (ALL)
    battle/      actions, HP, delay, immunity, fights, effects, engages, defeats, kills, ...
    items/       drops, obtained, holdings, trades, shops, synths, digs, fishing
    world/       zones, entities, spawns, levels, looks, weather, conquest, party, character, ...
    progress/    events, key items, battlefields, experience
  facts/         derived facts, ClickHouse SQL, listed in facts/__init__.py (DERIVED)
rust/
  xc-decode/     packets' layouts, decoded as packets does, from its schemas
  xc-core/       the capture reader (xicap's C API), the world, the extractor contract, and the runner
  extractors/    one crate an extractor, the code of each declaration above
  xc-all/        every Rust extractor by name
  xc-py/         extractors_rs, the Python module index.py calls
  parity/        the Rust rows against the Python extractors' last release on real captures
tests/           the same domains; tests/expected/ pins each unit's output on the fixtures
```

The specs are in `openspec/specs/`; the specs of most analyses are still in Scholar, beside the mob pages that show them, and follow later. CONTRIBUTING.md says how to add or change an analysis.

## Licence

GPL-3.0 (LICENSE). The extractors began as ports of [captain](https://github.com/sruon/captain)'s addons. The packet layouts are [atom0s's XiPackets](https://github.com/atom0s/XiPackets), by way of packets.
