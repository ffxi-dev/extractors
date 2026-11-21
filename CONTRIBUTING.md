# Contributing

Set up as the README's quick start says. Then:

1. Make the change, with a test. A bug fix needs a test that fails without it.
2. If any unit's output changes, bump its `version`, then write its new pin: `BLESS=1 uv run pytest tests/test_expected.py`. Commit the new `tests/expected/<unit>-v<version>.json` and delete the old one.
3. `uv run ruff check . && uv run ruff format --check . && uv run pytest` passes.
4. Open a pull request saying what retail does and how a capture shows it: a capture id and packet index (Lens opens `https://lens.sruon.dev/c/<id>#packet=<index>`).

A version is how Scholar knows to re-run a unit over the archive. Change a unit's output without bumping it and CI fails, naming the unit.

## The rules

- Decode packets only through `packets`. If a field is wrong or missing there, fix it in packets first.
- Ids stay ids. Names come from the `*_names` views at query time, or from the packet that carries them.
- Fixtures and test cases come only from public Mogsafe captures.
- A column's doc says what the value is and where it comes from, in short plain words.

## A new extractor

An extractor reads the packets it names in `reads`, in order, with the world so far, and emits rows to its own tables. Every row also gets `capture_id`, `idx` (the packet's index, as Lens counts it), `ts_ms`, and `client_version`.

```python
# ffxi_extractors/extractors/music.py
import pyarrow as pa

from ..extract import Column, Extractor, Table


class Music(Extractor):
    name = "music"
    version = 1
    doc = "Each music change the server sends."
    reads = frozenset({(0, 0x05F)})  # (direction, opcode): 0 is to the client
    tables = (
        Table(
            "music",
            "One row per music packet (0x05F).",
            (
                Column("zone_id", pa.int32(), "The zone."),
                Column("slot", pa.int32(), "Which music it sets: Slot, as sent."),
                Column("track", pa.int32(), "The track: MusicNum, as sent."),
            ),
        ),
    )

    def packet(self, p, f, world, emit):
        emit("music", p, zone_id=world.zone, slot=f("Slot"), track=f("MusicNum"))
```

`f(path)` gives the packet's fields by packets' paths (`UniqueNo`, `SendFlg.Despawn`, `GrapIDTbl[3]`), or None for a field the packet does not hold. An extractor that needs to see a whole fight first keeps state on `self` (Scholar makes a fresh one per capture) and emits in `finish`.

List the class in `ALL` in `extractors/__init__.py`, then test it on hand-built packets with `drive`:

```python
from conftest import drive

from ffxi_extractors.extractors.music import Music


def test_music_changes():
    rows = drive(Music, (0x05F, {"Slot": 0, "MusicNum": 113}))["music"]
    assert [(r["slot"], r["track"]) for r in rows] == [(0, 113)]
```

Bless its first pin, as step 2 says. `store.setup` makes its table from the columns.

## A new derived fact

A derived fact is one SELECT over other units' tables. Its table takes its columns and types from the SQL; its `Column`s carry their docs, with `None` for the type. The SQL reads one capture where `{capture:String}` names it, and every capture where it is `''`: `ONE` says that for a table with `capture_id`.

```python
# ffxi_extractors/extractors/tp_move_counts.py
from ..extract import ONE, Column, Derived, Table


class TpMoveCounts(Derived):
    name = "tp_move_counts"
    version = 1
    doc = "How often each mob used each TP move."
    reads = frozenset({"tp_uses"})  # the units it reads: a new version of one re-runs this
    order = "action_id, actor_id"
    sql = f"""
    SELECT capture_id, actor_id, action_id, count() AS uses
    FROM tp_uses WHERE {ONE} GROUP BY capture_id, actor_id, action_id
    """
    tables = (
        Table(
            "tp_move_counts",
            "One row per capture, mob, and TP move it used.",
            (
                Column("actor_id", None, "The mob."),
                Column("action_id", None, "The move."),
                Column("uses", None, "How many times it was used."),
            ),
        ),
    )
```

List it in `DERIVED`, after every unit it reads. Test it on hand-built rows: `put` them into the tables it reads, run it alone, and read what it wrote.

```python
from conftest import rows
from fill import put

from ffxi_extractors.index import run


def test_uses_count_by_mob(con):
    put(con, "tp_uses", [{"capture_id": "h", "idx": i, "actor_id": 9, "action_id": 7} for i in range(3)])
    run(con, None, "h", units={"tp_move_counts"})
    assert rows(con, "SELECT actor_id, action_id, uses FROM tp_move_counts") == [(9, 7, 3)]
```

A table's columns are in its module in `extractors/`, or `DESCRIBE tp_uses` in the ClickHouse client.

## Releases

The owner merges and tags `v<x.y.z>`. Scholar then installs the tag and re-runs, over every capture, only the units whose versions changed.
