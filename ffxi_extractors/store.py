"""ClickHouse, which holds what the extractors and derived facts make of captures: events and facts, never raw
packets. The captures are the only permanent copy; these tables can be rebuilt from them.

A unit's write for one capture is an idempotent replace: it records an attempt in runs, deletes the
capture's rows from its tables only when an earlier attempt exists, inserts, then records done. A crash or a
lost acknowledgement leaves the attempt, so the planner runs the unit again and the delete keeps counts
single, while a first ingest sends no DELETE."""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import clickhouse_connect
import pyarrow as pa

LENS = "https://lens.sruon.dev/c/"
LOCAL = "http://ffxi:ffxi@127.0.0.1:8123/ffxi"  # compose.yaml's
TYPES = {
    pa.string(): "String", pa.int32(): "Int32", pa.int64(): "Int64", pa.bool_(): "Bool",
    pa.float32(): "Float32", pa.float64(): "Float64",
}  # fmt: skip
# Every extractor row's leading columns, never empty.
COMMON = "capture_id String, idx Int64, ts_ms Int64, client_version LowCardinality(String)"

# The decoder's tables and the run records; a caller may add its own. Each is (columns, ORDER BY, engine).
BASE = {
    "captures": (
        "capture_id String, client_version String, release Nullable(String), character Nullable(String),"
        " character_id Nullable(Int64), retail Bool, start_ms Nullable(Int64), end_ms Nullable(Int64),"
        " packets Int64, world Nullable(String), uploader Nullable(String), format Nullable(String),"
        " source Nullable(String)",
        "capture_id",
        "MergeTree",
    ),
    "sessions": (
        "capture_id String, name Nullable(String), start_idx Nullable(Int64), end_idx Nullable(Int64),"
        " start_ms Nullable(Int64), end_ms Nullable(Int64), cut_short Bool",
        "capture_id",
        "MergeTree",
    ),
    "sizes": (
        "capture_id String, client_version String, direction LowCardinality(String), opcode Int32,"
        " size Int32, packets Int64",
        "direction, opcode, capture_id",
        "MergeTree",
    ),
    "zone_visits": (
        "capture_id String, idx Int64, start_ms Int64, end_idx Int64, end_ms Int64, zone_id Int32,"
        " zoned_in Bool",
        "zone_id, capture_id, start_ms",
        "MergeTree",
    ),
    "activity": ("capture_id String, t Int64, n Int64", "capture_id, t", "MergeTree"),
    "runs": (
        "capture_id String, unit String, version String, decoder_version String,"
        " state LowCardinality(String), error Nullable(String), started_ms Int64,"
        " finished_ms Nullable(Int64), rows Nullable(Int64), at UInt64",
        "capture_id, unit",
        "ReplacingMergeTree(at)",
    ),
    "capture_trust": (
        "capture_id String, trust Nullable(String), at UInt64",
        "capture_id",
        "ReplacingMergeTree(at)",
    ),
    "names": (
        "release LowCardinality(String), kind LowCardinality(String), log_id Int64, id Int64,"
        " name Nullable(String), name_passive Nullable(String), log Nullable(String)",
        "release, kind, log_id, id",
        "MergeTree",
    ),
}
DECODE = ("captures", "sessions", "sizes", "zone_visits", "activity")
# The tables of units that are not extractors or derived facts: the decoder, and any a caller adds.
UNITS = {"decode": DECODE}
# An extractor table sorted other than by capture and packet (design 2).
ORDER = {"entity_changes": "entity_id, capture_id, idx"}
# Indexes that skip the blocks without a value: a move among every capture's actions; and in bestiary_fights,
# which is sorted by mob for the mob pages, one capture's fights and the copies of a fight.
INDEXES = {
    "actions": ("action action_id TYPE bloom_filter GRANULARITY 1",),
    "bestiary_fights": (
        "capture capture_id TYPE bloom_filter GRANULARITY 1",
        "fight fight_key TYPE bloom_filter GRANULARITY 1",
    ),
}
SQL = Path(__file__).parent / "sql"


def connect(url: str | None = None, create: bool = False):
    """A client for url, else FFXI_CLICKHOUSE, else the compose file's ClickHouse
    (http://user:password@host:8123/database), safe across threads; with create, the database is made first
    if missing."""
    url = url or os.environ.get("FFXI_CLICKHOUSE", LOCAL)
    if create:
        parts = urlsplit(url)
        server = clickhouse_connect.get_client(dsn=urlunsplit(parts._replace(path="/default")))
        server.command(f"CREATE DATABASE IF NOT EXISTS `{parts.path.strip('/')}`")
        server.close()
    con = clickhouse_connect.get_client(
        dsn=url, autogenerate_session_id=False, connect_timeout=30, send_receive_timeout=3600
    )
    con.dsn = url  # for workers, which connect on their own
    return con


def rows(con, sql: str, params: dict | None = None) -> list[tuple]:
    return con.query(sql, parameters=params).result_rows


def one(con, sql: str, params: dict | None = None):
    r = rows(con, sql, params)
    return r[0] if r else None


def now() -> int:
    """A version for ReplacingMergeTree rows: the newest write wins."""
    return time.time_ns()


def _create(con, name: str, cols: str, order: str, engine: str = "MergeTree") -> None:
    con.command(
        f"CREATE TABLE IF NOT EXISTS {name} ({cols}) ENGINE = {engine} ORDER BY ({order})"
        " SETTINGS allow_nullable_key = 1"
    )


def _type(t: pa.DataType) -> str:
    """An extractor column's ClickHouse type: nullable, or a list of nullable values."""
    if pa.types.is_list(t):
        return f"Array(Nullable({TYPES[t.value_type]}))"
    return f"Nullable({TYPES[t]})"


def setup(con) -> None:
    """Make every table, view, function, and dictionary the units need, and add the columns a new extractor
    version brings. Derived tables come from their SQL."""
    from .extractors import ALL, DERIVED

    for name, (cols, order, engine) in BASE.items():
        _create(con, name, cols, order, engine)
    have = set(rows(con, "SELECT table, name FROM system.columns WHERE database = currentDatabase()"))
    lens = f", lens_url String ALIAS concat('{LENS}', capture_id, '#packet=', toString(idx))"
    for x in ALL:
        for t in x.tables:
            cols = [(c.name, _type(c.type)) for c in t.columns]
            order = ORDER.get(t.name, "capture_id, idx")
            _create(con, t.name, COMMON + "".join(f", `{c}` {typ}" for c, typ in cols) + lens, order)
            for c, typ in cols:
                if (t.name, c) not in have:
                    con.command(f"ALTER TABLE {t.name} ADD COLUMN IF NOT EXISTS `{c}` {typ}")
            for index in INDEXES.get(t.name, ()):
                con.command(f"ALTER TABLE {t.name} ADD INDEX IF NOT EXISTS {index}")
    script(con, "setup.sql")
    for d in DERIVED:
        create_derived(con, d, d.tables[0].name)
    views(con)


def views(con) -> None:
    """The bestiary's views, made again from this code, so a changed definition or table takes effect."""
    from .extractors.bestiary_mobs import VIEWS

    # bestiary_copies and bestiary_recount were the hourly party-copy merge that fight_key replaced.
    for view in ("bestiary_list", "bestiary", "bestiary_recount", "bestiary_copies"):
        con.command(f"DROP VIEW IF EXISTS {view} SYNC")
    for statement in VIEWS:
        con.command(statement)


def script(con, name: str) -> None:
    """Run each statement of one of sql/'s files."""
    text = "\n".join(line for line in (SQL / name).read_text().splitlines() if not line.startswith("--"))
    for statement in text.split(";\n"):
        if statement.strip():
            con.command(statement)


def create_derived(con, d, name: str) -> None:
    """A derived unit's table, typed by its SQL. A table of another engine, or with a column the SQL dropped
    or retyped, is made again, empty: that change comes with a new version, which writes every capture's rows
    again. A column the SQL gained is added, so the next runs can write it. Units go in
    the order of DERIVED, so one over another reads its new columns."""
    sql = "SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = {t:String}"
    engine = one(con, sql, {"t": name})
    if engine and engine[0] != d.engine.split("(")[0]:
        con.command(f"DROP TABLE {name} SYNC")
    elif engine:
        # DESCRIBE spells a named tuple over several lines, system.columns on one: compare without spaces.
        flat = "".join
        want = {c: flat(typ.split()) for c, typ, *_ in rows(con, f"DESCRIBE ({d.sql})", {"capture": ""})}
        held = rows(con, "SELECT name, type FROM system.columns WHERE database = currentDatabase()"
                         " AND table = {t:String}", {"t": name})  # fmt: skip
        if any(want.get(c) != flat(typ.split()) for c, typ in held):
            con.command(f"DROP TABLE {name} SYNC")
    con.command(
        f"CREATE TABLE IF NOT EXISTS {name} ENGINE = {d.engine} ORDER BY ({d.order})"
        f" SETTINGS allow_nullable_key = 1 EMPTY AS {d.sql}",
        parameters={"capture": ""},
    )
    have = {c for (c,) in rows(con, "SELECT name FROM system.columns WHERE database = currentDatabase()"
                                    " AND table = {t:String}", {"t": name})}  # fmt: skip
    after = "FIRST"  # INSERT ... SELECT fills columns in order: a new one goes where the SQL has it
    for c, typ, *_ in rows(con, f"DESCRIBE ({d.sql})", {"capture": ""}):
        if c not in have:
            con.command(f"ALTER TABLE {name} ADD COLUMN `{c}` {typ} {after}")
        after = f"AFTER `{c}`"
    for index in INDEXES.get(d.tables[0].name, ()):
        con.command(f"ALTER TABLE {name} ADD INDEX IF NOT EXISTS {index}")


def tables_of(unit: str) -> tuple[str, ...]:
    from .extractors import ALL, DERIVED

    if unit in UNITS:
        return UNITS[unit]
    for x in (*ALL, *DERIVED):
        if x.name == unit:
            return tuple(t.name for t in x.tables)
    raise KeyError(unit)


def runs(con, capture_id: str | None = None) -> dict[tuple[str, str], tuple[str, str, str]]:
    """(capture, unit) -> (version, decoder version, state) of its latest run: attempting, done, or failed."""
    where = "WHERE capture_id = {c:String}" if capture_id else ""
    got = rows(con, f"SELECT capture_id, unit, version, decoder_version, state FROM runs FINAL {where}",
               {"c": capture_id} if capture_id else None)  # fmt: skip
    return {(c, u): (v, d, s) for c, u, v, d, s in got}


RUNS = [
    "capture_id",
    "unit",
    "version",
    "decoder_version",
    "state",
    "error",
    "started_ms",
    "finished_ms",
    "rows",
    "at",
]


def _runs(con, capture_id: str, units: dict[str, tuple], decoder: str, state: str, started: int) -> None:
    """One runs row per unit: units maps each to (version, rows, error)."""
    finished = int(time.time() * 1000) if state != "attempting" else None
    con.insert("runs", [[capture_id, u, v, decoder, state, e, started, finished, n, now()]
                        for u, (v, n, e) in units.items()], column_names=RUNS)  # fmt: skip


def delete(con, table: str, capture_id: str) -> None:
    """Delete a capture's rows from a table, again until none are left. ClickHouse 26.8 can lose one of two
    DELETEs that land on a table at once, when it applies both mutations in one step."""
    sql = f"SELECT count() FROM `{table}` WHERE capture_id = {{c:String}}"
    for _ in range(5):
        con.command(f"DELETE FROM `{table}` WHERE capture_id = {{c:String}}", parameters={"c": capture_id})
        if not one(con, sql, {"c": capture_id})[0]:
            return
    raise RuntimeError(f"{table} kept rows of {capture_id} after five deletes")


def _clear(con, capture_id: str, units) -> None:
    for unit in units:
        for t in tables_of(unit):
            delete(con, t, capture_id)


def begin(con, capture_id: str, versions: dict[str, str], decoder: str, started: int) -> None:
    """Record an attempt at these units, and clear what an earlier attempt wrote."""
    before = {u for (_, u) in runs(con, capture_id)}
    _runs(con, capture_id, {u: (v, None, None) for u, v in versions.items()}, decoder, "attempting", started)
    _clear(con, capture_id, [u for u in versions if u in before])


def insert(con, table: str, data: pa.Table) -> None:
    if data.num_rows:
        con.insert_arrow(table, data)


def done(con, capture_id: str, units: dict[str, tuple[str, int]], decoder: str, started: int) -> None:
    """Record these units' runs done: units maps each to (version, rows)."""
    _runs(con, capture_id, {u: (v, n, None) for u, (v, n) in units.items()}, decoder, "done", started)


def fail(con, capture_id: str, versions: dict[str, str], decoder: str, error: str, started: int = 0) -> None:
    """Record that these units failed on a capture. A unit that failed partway keeps no rows of it; one that
    failed before writing keeps the rows of its last good run."""
    last = runs(con, capture_id)
    _clear(
        con,
        capture_id,
        [u for u in versions if last.get((capture_id, u), (None, None, None))[2] == "attempting"],
    )
    _runs(
        con, capture_id, {u: (v, None, error[:2000]) for u, v in versions.items()}, decoder, "failed", started
    )


def drop(con, capture_id: str) -> None:
    """Remove every row of a capture: its runs, trust, and share of the mob pages with it. A fight it
    held a copy of counts in another capture's copy."""
    from .extractors.bestiary_mobs import partners, reroll

    others = partners(con, [capture_id])
    for (t,) in rows(
        con,
        "SELECT DISTINCT table FROM system.columns c JOIN system.tables t ON t.database = c.database"
        " AND t.name = c.table WHERE c.database = currentDatabase() AND c.name = 'capture_id'"
        " AND t.engine LIKE '%MergeTree' AND NOT startsWith(t.name, '.inner')",
    ):
        delete(con, t, capture_id)
    reroll(con, others)


def trust(con, levels: list[tuple[str, str | None]]) -> None:
    """Mogsafe's trust level for each (capture, level), in one insert: gold, silver, bronze, plain or flagged;
    None forgets it. A mob page leaves out Flagged captures at once. A capture flagged or no longer
    flagged writes again its mob roll-up and its partners', whose copies it stops or starts counting."""
    from .extractors.bestiary_mobs import partners, reroll

    if levels:
        sql = "SELECT capture_id, trust FROM capture_trust FINAL WHERE capture_id IN {c:Array(String)}"
        before = dict(rows(con, sql, {"c": [c for c, _ in levels]}))
        at = now()
        con.insert(
            "capture_trust", [[c, v, at] for c, v in levels], column_names=["capture_id", "trust", "at"]
        )
        changed = [c for c, v in levels if (before.get(c) == "flagged") != (v == "flagged")]
        reroll(con, changed + partners(con, changed))


def levels(con) -> dict[str, str]:
    return dict(rows(con, "SELECT capture_id, trust FROM capture_trust FINAL WHERE trust IS NOT NULL"))
