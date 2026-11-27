"""ClickHouse, which holds what the extractors and derived facts make of captures: events and facts, never raw
packets. The captures are the only permanent copy; these tables can be rebuilt from them.

A unit's write for one capture is an idempotent replace: it records an attempt in runs, deletes the
capture's rows from its tables only when an earlier run may have left some, inserts, then records done. A
crash or a lost acknowledgement leaves the attempt, so the next run of the unit does it again and the delete
keeps counts single, while a first ingest, or a unit whose last run wrote no rows, sends no DELETE."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import clickhouse_connect
import pyarrow as pa

from ffxi_extractors.decode import TABLES
from ffxi_extractors.extract import COMMON, LENS, Column, Table
from ffxi_extractors.extractors import ALL
from ffxi_extractors.facts import DERIVED
from ffxi_extractors.facts.bestiary_mobs import partners, reroll
from ffxi_extractors.facts.views import VIEWS

LOCAL = "http://ffxi:ffxi@127.0.0.1:8123/ffxi"  # compose.yaml's
TYPES = {
    pa.string(): "String", pa.int32(): "Int32", pa.int64(): "Int64", pa.uint64(): "UInt64",
    pa.bool_(): "Bool", pa.float32(): "Float32", pa.float64(): "Float64",
}  # fmt: skip

RUNS = Table(
    "runs",
    "Which version of each unit wrote a capture's rows, or failed on it. Read it with FINAL.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column(
            "unit",
            pa.string(),
            "decode, an extractor's name, a derived fact's, or one a caller adds.",
            null=False,
        ),
        Column("version", pa.string(), "The unit's version.", null=False),
        Column(
            "decoder_version",
            pa.string(),
            "The packets release and world version that decoded the capture.",
            null=False,
        ),
        Column(
            "state",
            pa.string(),
            "attempting, done, or failed: a unit that fails keeps the rows of its last good run, "
            "unless it failed partway.",
            null=False,
            low=True,
        ),
        Column("error", pa.string(), "Why it failed."),
        Column("started_ms", pa.int64(), "When the run began.", null=False),
        Column("finished_ms", pa.int64(), "When it ended."),
        Column("rows", pa.int64(), "Rows written."),
        Column("at", pa.uint64(), "The write's version: the newest wins.", null=False),
    ),
    order="capture_id, unit",
    engine="ReplacingMergeTree(at)",
)
TRUST = Table(
    "capture_trust",
    "Mogsafe's trust level for each capture; read it with FINAL.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column(
            "trust",
            pa.string(),
            "gold, silver, bronze, plain or flagged: figures across captures leave out flagged.",
        ),
        Column("at", pa.uint64(), "The write's version: the newest wins.", null=False),
    ),
    order="capture_id",
    engine="ReplacingMergeTree(at)",
)
NAMES_TABLE = Table(
    "names",
    "Every name, by release, kind, and id: the *_names views read it.",
    (
        Column("release", pa.string(), "The retail-resources release.", null=False, low=True),
        Column(
            "kind",
            pa.string(),
            "zone, entity, item, spell, and so on: what the id names.",
            null=False,
            low=True,
        ),
        Column("log_id", pa.int64(), "The quest or mission log, for those; 0 otherwise.", null=False),
        Column("id", pa.int64(), "The id, as packets send it.", null=False),
        Column("name", pa.string(), "The name."),
        Column("name_passive", pa.string(), "A status effect's passive name."),
        Column("log", pa.string(), "The log's name, for quests and missions."),
    ),
    order="release, kind, log_id, id",
)
NAMES_ONE = Table(
    "names_one",
    "One row per release, kind, log_id, and id of names, which pick_names builds from it: the *_names views"
    " read it, so no query groups names.",
    (
        *NAMES_TABLE.columns[:4],
        Column("name", pa.string(), "The least of the key's names: a release may list an id twice."),
        Column("name_passive", pa.string(), "The least passive name."),
        Column("log", pa.string(), "The least log name."),
        Column("names", None, "Every name of the key, sorted, once each.", ch="Array(String)"),
    ),
    order=NAMES_TABLE.order,
)
# Every table that is not a unit's: the decoder's, the run records, and any a caller adds.
BASE = {t.name: t for t in (*TABLES, RUNS, TRUST, NAMES_TABLE, NAMES_ONE)}
DECODE = tuple(t.name for t in TABLES)
# The tables of units that are not extractors or derived facts: the decoder, and any a caller adds.
UNITS = {"decode": DECODE}
SQL = Path(__file__).parent / "sql"
# The figures across captures that pages show: one query a file, its {name:Type} blanks ClickHouse
# parameters. A caller runs them as they are, as Scholar's mob, NPC, weather, and item pages do.
PAGES = SQL / "pages"


def pages() -> dict[str, str]:
    """Each page query by its file's name."""
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(PAGES.glob("*.sql"))}


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
    # The URL it connected to, for workers that connect on their own (Scholar's indexer passes it on).
    con.dsn = url  # type: ignore[attr-defined]
    return con


def rows(con, sql: str, params: dict | None = None) -> list[tuple]:
    return con.query(sql, parameters=params).result_rows


def one(con, sql: str, params: dict | None = None):
    r = rows(con, sql, params)
    return r[0] if r else None


def now() -> int:
    """A version for ReplacingMergeTree rows: the newest write wins."""
    return time.time_ns()


def _create(con, name: str, cols: str, order: str, engine: str = "MergeTree", keep: bool = False) -> None:
    """A table, made if missing. One made under another ORDER BY is copied into a new one sorted by order,
    and swapped in: the same rows, read by the new key; keep leaves it for the caller (sorts()). Each process
    copies under its own name and checks again before the swap, so two setting up at once (a deploy's
    indexer and its rebuild) do not undo each other."""
    con.command(
        f"CREATE TABLE IF NOT EXISTS {name} ({cols}) ENGINE = {engine} ORDER BY ({order})"
        " SETTINGS allow_nullable_key = 1"
    )
    if keep or _sorting_key(con, name) == _key(order):
        return
    tmp = f"{name}_sorted_{os.getpid()}"
    copy_sorted(con, name, tmp, order, engine)
    if _sorting_key(con, name) != _key(order):
        con.command(f"EXCHANGE TABLES {name} AND {tmp}")
    con.command(f"DROP TABLE {tmp} SYNC")


def copy_sorted(con, name: str, into: str, order: str, engine: str) -> None:
    """Copy the table name into a new table into, under ORDER BY order: the same rows, read by the new key."""
    con.command(f"DROP TABLE IF EXISTS {into} SYNC")
    con.command(
        f"CREATE TABLE {into} AS {name} ENGINE = {engine} ORDER BY ({order}) SETTINGS allow_nullable_key = 1"
    )
    con.command(f"INSERT INTO {into} SELECT * FROM {name}")


def sorts(con) -> dict[str, tuple[str, str]]:
    """The tables of capture rows (the decoder's and the extractors') made under another ORDER BY than this
    code's, each with its ORDER BY and engine: setup(keep=True) leaves them, for a caller to copy_sorted()
    and swap in under its own lock. The bookkeeping tables are re-sorted by setup still."""
    want = {t.name: (t.order, t.engine) for t in TABLES} | {
        t.name: (t.order, "MergeTree") for x in ALL for t in x.tables
    }
    held = dict(rows(con, "SELECT name, sorting_key FROM system.tables WHERE database = currentDatabase()"
                          " AND name IN {n:Array(String)}", {"n": list(want)}))  # fmt: skip
    return {n: oe for n, oe in want.items() if n in held and _key(held[n]) != _key(oe[0])}


def _key(order: str) -> str:
    return order.replace(" ", "").replace("`", "").strip("()")


def _sorting_key(con, name: str) -> str:
    sql = "SELECT sorting_key FROM system.tables WHERE database = currentDatabase() AND name = {t:String}"
    return _key(one(con, sql, {"t": name})[0])


def ch_type(c: Column) -> str:
    """A column's ClickHouse type: ch as written, else pyarrow's, Nullable unless null is False and
    LowCardinality when low. A list holds nullable values."""
    if c.ch:
        return c.ch
    assert c.type is not None, f"{c.name}: a derived table's column takes its type from the SQL"
    if pa.types.is_list(c.type):
        return f"Array(Nullable({TYPES[c.type.value_type]}))"
    t = f"Nullable({TYPES[c.type]})" if c.null else TYPES[c.type]
    return f"LowCardinality({t})" if c.low else t


def columns(cs) -> str:
    """Columns as CREATE TABLE lists them."""
    return ", ".join(f"{c.name} {ch_type(c)}" for c in cs)


# Settings that change what the SQL means, as clickhouse/users.xml's default profile sets them.
SETTINGS = {
    "join_use_nulls": 1,
    "prefer_column_name_to_alias": 1,
    "aggregate_functions_null_for_empty": 1,
    "enable_named_columns_in_function_tuple": 1,
}


def setup(con, keep: bool = False) -> None:
    """Make every table, view, function, and dictionary the units need, and add the columns a new extractor
    version brings. Derived tables come from their SQL. keep leaves each derived table pending() lists as it
    is, rows and all, and the views as they are while any is, for a caller that rebuilds them beside the live
    ones, swaps them, and makes the views again (Scholar's rebuild); without it, such a table is made again,
    empty. keep also leaves each table sorts() lists under its old ORDER BY, for that caller to re-sort."""
    got = one(con, "SELECT " + ", ".join(f"toInt64(getSetting('{s}'))" for s in SETTINGS))
    if list(got) != list(SETTINGS.values()):
        raise RuntimeError(f"ClickHouse runs these settings otherwise: {SETTINGS}; see clickhouse/users.xml")
    for t in BASE.values():
        _create(con, t.name, columns(t.columns), t.order, t.engine, keep and t.name in DECODE)
    have = set(rows(con, "SELECT table, name FROM system.columns WHERE database = currentDatabase()"))
    lens = f", lens_url String ALIAS concat('{LENS}', capture_id, '#packet=', toString(idx))"
    for x in ALL:
        for t in x.tables:
            cols = [(c.name, ch_type(c)) for c in t.columns]
            _create(
                con,
                t.name,
                columns(COMMON) + "".join(f", `{c}` {typ}" for c, typ in cols) + lens,
                t.order,
                keep=keep,
            )
            for c, typ in cols:
                if (t.name, c) not in have:
                    con.command(f"ALTER TABLE {t.name} ADD COLUMN IF NOT EXISTS `{c}` {typ}")
            for index in t.indexes:
                con.command(f"ALTER TABLE {t.name} ADD INDEX IF NOT EXISTS {index}")
    if not one(con, "SELECT 1 FROM names_one LIMIT 1"):
        pick_names(con)
    script(con, "setup.sql")
    # A fact over a kept table may read a column it lacks, so it waits for the rebuild too, unread.
    kept = set(pending(con)) if keep else set()
    for d in DERIVED:
        if d.name not in kept:
            create_derived(con, d, d.tables[0].name)
    if not kept:
        views(con)


def pick_names(con, src: str = "names", dst: str = "names_one") -> None:
    """Fill dst with one row per key of src, in place of what it held: the least of each text, so an id a
    release lists under two names (Capacious Coffer and Modest Coffer) gets the same one every time."""
    con.command(f"TRUNCATE TABLE {dst}")
    con.command(
        f"INSERT INTO {dst} SELECT release, kind, log_id, id, min(name), min(name_passive), min(log),"
        f" arraySort(groupUniqArray(name)) FROM {src} GROUP BY release, kind, log_id, id"
    )


def views(con) -> None:
    """The views over the derived tables, made again from this code, so a changed definition or table takes
    effect."""
    for view in ("bestiary_list", "bestiary"):
        con.command(f"DROP VIEW IF EXISTS {view} SYNC")
    for statement in VIEWS:
        con.command(statement)


def script(con, name: str) -> None:
    """Run each statement of one of sql/'s files."""
    text = "\n".join(line for line in (SQL / name).read_text().splitlines() if not line.startswith("--"))
    for statement in text.split(";\n"):
        if statement.strip():
            con.command(statement)


def _changed(con, d, name: str) -> bool:
    """Whether the table name exists under another engine than d's, or holds a column d's SQL dropped or
    retyped."""
    sql = "SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = {t:String}"
    engine = one(con, sql, {"t": name})
    if not engine:
        return False
    if engine[0] != d.engine.split("(")[0]:
        return True
    # DESCRIBE spells a named tuple over several lines, system.columns on one: compare without spaces.
    flat = "".join
    want = {c: flat(typ.split()) for c, typ, *_ in rows(con, f"DESCRIBE ({d.sql})", {"capture": ""})}
    held = rows(con, "SELECT name, type FROM system.columns WHERE database = currentDatabase()"
                     " AND table = {t:String}", {"t": name})  # fmt: skip
    return any(want.get(c) != flat(typ.split()) for c, typ in held)


def pending(con) -> list[str]:
    """The derived units whose table must be made again before it takes this code's rows: of another engine,
    or with a column the SQL dropped or retyped, and every unit that reads one, whose SQL may read a column
    the old table lacks. Such a change comes with a new version, which writes every capture's rows again."""
    out: list[str] = []
    for d in DERIVED:  # in order, so a unit's inputs are judged before it
        if d.reads & set(out) or _changed(con, d, d.tables[0].name):
            out.append(d.name)
    return out


def create_derived(con, d, name: str) -> None:
    """A derived unit's table, typed by its SQL. A table pending() would list is made again, empty. A column
    the SQL gained is added, so the next runs can write it. Units go in the order of DERIVED, so one over
    another reads its new columns."""
    if _changed(con, d, name):
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
    for index in d.tables[0].indexes:
        con.command(f"ALTER TABLE {name} ADD INDEX IF NOT EXISTS {index}")


def tables_of(unit: str) -> tuple[str, ...]:
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


def _runs(con, units: dict[str, dict[str, tuple]], decoder: str, state: str, started: int) -> None:
    """One runs row per capture and unit, in one insert: units maps each capture to {unit: (version, rows,
    error)}."""
    finished = int(time.time() * 1000) if state != "attempting" else None
    records = [
        [c, u, v, decoder, state, e, started, finished, n, now()]
        for c, us in units.items()
        for u, (v, n, e) in us.items()
    ]
    if records:
        con.insert("runs", records, column_names=[c.name for c in RUNS.columns])


def _held(con, captures: list[str]) -> dict[tuple[str, str], str]:
    """(capture, unit) -> state of its last run, for each that may have left rows: every run but one that
    recorded writing none."""
    got = rows(con, "SELECT capture_id, unit, state FROM runs FINAL WHERE capture_id IN {c:Array(String)}"
                    " AND coalesce(rows, -1) != 0", {"c": captures})  # fmt: skip
    return {(c, u): s for c, u, s in got}


def delete(con, table: str, captures: list[str]) -> None:
    """Delete these captures' rows from a table, again until none are left. ClickHouse 26.8 can lose one of
    two DELETEs that land on a table at once, when it applies both mutations in one step."""
    sql = f"SELECT count() FROM `{table}` WHERE capture_id IN {{c:Array(String)}}"
    for _ in range(5):
        con.command(
            f"DELETE FROM `{table}` WHERE capture_id IN {{c:Array(String)}}", parameters={"c": captures}
        )
        if not one(con, sql, {"c": captures})[0]:
            return
    raise RuntimeError(f"{table} kept rows of {len(captures)} captures after five deletes")


def delete_all(con, tables: dict[str, list[str]]) -> None:
    """Delete each table's captures' rows, the tables at once: a DELETE waits on its mutation, about 0.3 s,
    so a capture's 65 tables in turn took 11 s of a re-run's capture. One DELETE a table at a time keeps
    clear of 26.8's lost DELETE (delete's)."""
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda t: delete(con, t, tables[t]), tables))


def _clear(con, units: dict[str, list[str]]) -> None:
    """Delete each capture's rows of its units: units maps each capture to them."""
    tables: dict[str, list[str]] = {}
    for c, us in units.items():
        for t in dict.fromkeys(t for u in us for t in tables_of(u)):
            tables.setdefault(t, []).append(c)
    delete_all(con, tables)


def begin(con, capture_id: str, versions: dict[str, str], decoder: str, started: int) -> None:
    """Record an attempt at these units, and clear what an earlier run wrote. A unit whose last run wrote no
    rows has none to clear: about half a capture's tables hold none, and a first ingest sends no DELETE."""
    held = _held(con, [capture_id])
    _runs(
        con, {capture_id: {u: (v, None, None) for u, v in versions.items()}}, decoder, "attempting", started
    )
    _clear(con, {capture_id: [u for u in versions if (capture_id, u) in held]})


def begin_many(con, units: dict[str, dict[str, str]], decoder: str, started: int) -> None:
    """begin for many captures before any of them runs, with one DELETE a table for all: units maps each
    capture to {unit: version}. Only units that may hold rows are touched: their attempts are recorded, their
    rows deleted, and the attempts recorded again as having written none, so the capture's own begin sends
    no DELETE. A DELETE waits about 0.5 s on ClickHouse's mutation scheduling, so a DELETE a table for each
    capture took 44% of a re-index. A run stopped before it is done stays attempting, as with begin."""
    held = _held(con, list(units))
    clear = {c: {u: v for u, v in us.items() if (c, u) in held} for c, us in units.items()}

    def attempts(n):
        return {c: {u: (v, n, None) for u, v in us.items()} for c, us in clear.items()}

    _runs(con, attempts(None), decoder, "attempting", started)
    _clear(con, {c: list(us) for c, us in clear.items()})
    _runs(con, attempts(0), decoder, "attempting", started)


def insert(con, table: str, data: pa.Table) -> None:
    if data.num_rows:
        con.insert_arrow(table, data)


def done(con, capture_id: str, units: dict[str, tuple[str, int]], decoder: str, started: int) -> None:
    """Record these units' runs done: units maps each to (version, rows)."""
    _runs(con, {capture_id: {u: (v, n, None) for u, (v, n) in units.items()}}, decoder, "done", started)


def fail(con, capture_id: str, versions: dict[str, str], decoder: str, error: str, started: int = 0) -> None:
    """Record that these units failed on a capture. A unit that failed partway keeps no rows of it; one that
    failed before writing keeps the rows of its last good run."""
    held = _held(con, [capture_id])
    _clear(con, {capture_id: [u for u in versions if held.get((capture_id, u)) == "attempting"]})
    _runs(
        con,
        {capture_id: {u: (v, None, error[:2000]) for u, v in versions.items()}},
        decoder,
        "failed",
        started,
    )


def drop(con, capture_id: str) -> None:
    """Remove every row of a capture: its runs, trust, and share of the mob pages with it. A fight it
    held a copy of counts in another capture's copy."""
    others = partners(con, [capture_id])
    tables = rows(
        con,
        "SELECT DISTINCT table FROM system.columns c JOIN system.tables t ON t.database = c.database"
        " AND t.name = c.table WHERE c.database = currentDatabase() AND c.name = 'capture_id'"
        " AND t.engine LIKE '%MergeTree' AND NOT startsWith(t.name, '.inner')",
    )
    delete_all(con, {t: [capture_id] for (t,) in tables})
    reroll(con, others)


def trust(con, levels: list[tuple[str, str | None]]) -> None:
    """Mogsafe's trust level for each (capture, level), in one insert: gold, silver, bronze, plain or flagged;
    None forgets it. A mob page leaves out Flagged captures at once. A capture flagged or no longer
    flagged writes again its mob roll-up and its partners', whose copies it stops or starts counting."""
    if levels:
        sql = "SELECT capture_id, trust FROM capture_trust FINAL WHERE capture_id IN {c:Array(String)}"
        before = dict(rows(con, sql, {"c": [c for c, _ in levels]}))
        at = now()
        con.insert(
            "capture_trust", [[c, v, at] for c, v in levels], column_names=["capture_id", "trust", "at"]
        )
        changed = [c for c, v in levels if (before.get(c) == "flagged") != (v == "flagged")]
        reroll(con, changed + partners(con, changed))


def trust_levels(con) -> dict[str, str]:
    return dict(rows(con, "SELECT capture_id, trust FROM capture_trust FINAL WHERE trust IS NOT NULL"))
