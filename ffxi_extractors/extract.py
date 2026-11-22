"""The extractor contract. An extractor is one analysis: it reads one capture's packets in order, with
the world so far, and writes rows to its own tables. Its version changes whenever its output would, so
a runner such as Scholar re-runs it over the archive. Its code is Rust's (rust/extractors), its declaration
here: name, version, reads, sparse, and tables, which extractors_rs's are checked against."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyarrow as pa


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


class Extractor:
    name: str
    version: int
    doc: str
    reads: frozenset[tuple[int, int]]  # (direction, opcode): 0 is to the client, 1 from it
    tables: tuple[Table, ...]
    # Its rows come only from its reads outside the world's: a capture holding none of them gives it no rows,
    # so a re-run may pass that capture by. False for one that also writes from the world's packets it reads.
    sparse = True


# One capture's rows of a table, or every capture's when {capture:String} is ''.
ONE = "(capture_id = {capture:String} OR {capture:String} = '')"

# Ends the SQL of a fact with a CTE AS MATERIALIZED: ClickHouse plans and runs a CTE again at each reference,
# and planning is most of a fact's time on one capture; a materialized one runs once. The rows are the same.
# Only CTEs small over every capture, as a rebuild runs them: a large one held in memory costs it more than
# the plans it saves.
MATERIALIZE = "SETTINGS enable_materialized_cte = 1"

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
