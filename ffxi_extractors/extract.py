"""The extractor contract. An extractor is one analysis: it reads one capture's packets in order, with
the world so far, and writes rows to its own tables. Its version changes whenever its output would, so
a runner such as Scholar re-runs it over the archive."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from ffxi_extractors.capture import Fields, Packet
from ffxi_extractors.world import World


@dataclass(frozen=True)
class Column:
    name: str
    type: pa.DataType | None  # None in a derived unit's table, whose SQL sets the types
    doc: str
    null: bool = True  # whether a row may have no value
    low: bool = False  # few distinct values, which ClickHouse keeps as a dictionary (LowCardinality)
    ch: str | None = None  # the ClickHouse type as written, for one pyarrow has no match for


@dataclass(frozen=True)
class Table:
    name: str
    doc: str
    columns: tuple[Column, ...]
    order: str = "capture_id, idx"  # an extractor table's ORDER BY; a derived table takes Derived.order
    indexes: tuple[str, ...] = ()  # skip indexes, as ClickHouse's ADD INDEX takes them
    engine: str = "MergeTree"


# Where Lens opens a capture: append the capture id, then "#packet=" and the packet's idx.
LENS = "https://lens.sruon.dev/c/"

# Every extractor row carries these, before its own columns.
COMMON = (
    Column("capture_id", pa.string(), "The Mogsafe capture the row came from.", null=False),
    Column(
        "idx",
        pa.int64(),
        "The packet the row came from: its position in the capture, as Lens's #packet= counts.",
        null=False,
    ),
    Column("ts_ms", pa.int64(), "That packet's time, Unix milliseconds UTC.", null=False),
    Column(
        "client_version",
        pa.string(),
        "The capture's client version; ids are as that version numbers them.",
        null=False,
        low=True,
    ),
)


def arrow(table: Table, values: dict[str, Any]) -> pa.Table:
    """A table's rows from a list per column, each typed as the table declares it."""
    return pa.table({c.name: pa.array(values[c.name], c.type) for c in table.columns})


Emit = Callable[..., dict]  # emit(table, packet, **values) -> the row


class Extractor:
    name: str
    version: int
    doc: str
    reads: frozenset[tuple[int, int]]  # (direction, opcode): 0 is to the client, 1 from it
    tables: tuple[Table, ...]

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        raise NotImplementedError

    def finish(self, world: World, emit: Emit) -> None:
        pass


FLUSH = 100_000  # rows a table holds before the sink writes them


class Sink:
    """Collects one extractor's rows for one capture. With write, flush() writes a table's rows once it holds
    FLUSH, all but those the extractor still holds to fill in."""

    def __init__(self, x: Extractor, capture_id: str, client_version: str, write=None):
        self.tables = {t.name: t for t in x.tables}
        self.rows: dict[str, list[dict]] = {t.name: [] for t in x.tables}
        self.base = {"capture_id": capture_id, "client_version": client_version}
        self.write = write  # write(table, arrow)
        self.written = 0

    def emit(self, table: str, p: Packet | None, **values) -> dict:
        """Add a row; it is returned so an extractor can fill in a value a later packet gives. A row the
        extractor still holds is written at the end, or once it lets go; one it holds to the end is never
        written early, so FLUSH bounds only the rows it is done with."""
        row = dict(self.base, idx=p.idx if p else None, ts_ms=p.ts_ms if p else None)
        row.update(values)
        self.rows[table].append(row)
        return row

    def _arrow(self, name: str, rows: list[dict]) -> pa.Table:
        cols = COMMON + self.tables[name].columns
        if extra := set().union(*rows) - {c.name for c in cols}:  # a typo would drop a column unseen
            raise KeyError(f"{name} has no column {sorted(extra)}")
        return pa.table({c.name: pa.array([r.get(c.name) for r in rows], c.type) for c in cols})

    def arrow(self) -> dict[str, pa.Table]:
        return {name: self._arrow(name, rows) for name, rows in self.rows.items()}

    def flush(self, everything: bool = False) -> None:
        for name, rows in self.rows.items():
            if not rows or (len(rows) < FLUSH and not everything):
                continue
            # A row only this list, the loop, and getrefcount refer to is finished.
            held = [] if everything else [r for r in rows if sys.getrefcount(r) > 3]
            done = rows if everything else [r for r in rows if sys.getrefcount(r) <= 3]
            self.write(name, self._arrow(name, done))
            self.written += len(done)
            self.rows[name] = held


# One capture's rows of a table, or every capture's when {capture:String} is ''.
ONE = "(capture_id = {capture:String} OR {capture:String} = '')"

# Each entity's name and model as the packets up to each one left them, for an ASOF join on idx.
NAMES = (
    "(SELECT capture_id, entity_id, idx, entity_name, model_id"
    " FROM capture_entities(capture = {capture:String}) WHERE entity_name IS NOT NULL)"
)
# Each NPC's name in a capture, one per entity.
NPC_NAMES = (
    "(SELECT capture_id, entity_id, any(entity_name) AS name"
    " FROM capture_entities(capture = {capture:String}) WHERE entity_name IS NOT NULL"
    " GROUP BY capture_id, entity_id)"
)

# Each capture's coarse flag: whether every action packet came on a whole second, as in a PacketViewer log or
# a captain log before 1.7. A capture with millisecond times puts about 1 in 1000 there.
COARSE = (
    f"(SELECT capture_id, countIf(ts_ms % 1000 != 0) = 0 AS coarse FROM actions WHERE {ONE}"
    " GROUP BY capture_id)"
)


def ordered(value: str, key: str, cond: str | None = None) -> str:
    """value's list over the group, ordered by key; only rows where cond holds, when given."""
    agg = f"groupArrayIf(({value}, {key}), {cond})" if cond else f"groupArray(({value}, {key}))"
    return f"arrayMap(t -> t.1, arraySort(t -> t.2, {agg}))"


class Derived:
    """A fact over other units' rows: ClickHouse SQL over their tables. For one capture it runs after them in
    the same job; a rebuild, such as `scholar rebuild`, runs it over every capture at once. The SQL reads one
    capture where {capture:String} names it, every capture where it is ''. Its version joins its own number
    with its inputs', so a new version of any input re-runs it."""

    name: str
    version: int
    doc: str
    reads: frozenset[str]  # the units whose tables the SQL reads
    tables: tuple[Table, ...]  # one: the SQL's result
    order: str  # its table's ORDER BY
    sql: str
    engine = "MergeTree"

    @classmethod
    def full_version(cls, units: dict[str, str]) -> str:
        return f"{cls.version}:" + ",".join(f"{u}{units[u]}" for u in sorted(cls.reads))
