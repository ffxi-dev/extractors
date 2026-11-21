# extractors

Turns FFXI captures into ClickHouse tables and findings. **Extractors** read one capture's packets in order and write rows: every action, each mob's HP, effects, spawns, weather, drops, and more. **Derived facts** are ClickHouse SQL over those rows: the bestiary, melee rounds, TP moves, aggro, steals, NPC events, trades, and shops.

[Scholar](https://scholar.sruon.dev) runs this library over every capture [Mogsafe](https://mogsafe.sruon.dev) keeps, and its mob pages show the results. A change merged here reaches Scholar in the next release.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Docker, and a C++20 compiler with CMake and zstd, which xicap's reader builds with.

```bash
uv sync
docker compose up -d --wait                          # ClickHouse on 127.0.0.1:8123, user ffxi, password ffxi
uv run pytest                                        # every test and pin
uv run ffxi-extractors index tests/data/*.xicap      # the fixtures, with names
docker compose exec clickhouse clickhouse-client --user ffxi --password ffxi -d ffxi
```

`ffxi-extractors index` downloads [retail-resources](https://github.com/ffxi-dev/retail-resources)' names into `var/names` the first time; `--no-names` skips them.

## Captures

- `tests/data/` holds two public Mogsafe captures, a Memoria recording and a converted captain log.
- Any capture Mogsafe keeps downloads from `https://mogsafe.sruon.dev/c/<id>`, no sign-in needed. The id is the last part of the capture's page address.
- Your own recordings from [Memoria](https://github.com/ffxi-dev/memoria) or captain index the same way.

Only retail captures are read.

## Layout

- `ffxi_extractors/capture.py` reads a xicap capture, a batch at a time.
- `decode.py` decodes a batch's packets with [packets](https://github.com/ffxi-dev/packets), only the opcodes a run reads.
- `world.py` keeps what the packets say so far: the zone, the character, its party, its inventory, and the entities around it.
- `extract.py` is the contract: `Extractor`, `Derived`, `Table`, and `Column`.
- `extractors/` holds one module per extractor or derived fact, all listed in `extractors/__init__.py`.
- `index.py` walks a capture once with every extractor, then runs the derived facts.
- `store.py` owns the ClickHouse tables and each unit's write.
- `sql/setup.sql` holds the SQL functions and views the facts share.
- `resources.py` mirrors and loads the names.
- `tests/expected/` pins each unit's output on the fixtures to its version.

The specs are in `openspec/specs/`; the specs of most analyses are still in Scholar, beside the mob pages that show them, and follow later. CONTRIBUTING.md says how to add or change an analysis.

## Licence

GPL-3.0 (LICENSE). The extractors began as ports of [captain](https://github.com/sruon/captain)'s addons. The packet layouts are [atom0s's XiPackets](https://github.com/atom0s/XiPackets), by way of packets.
