"""Hand-built rows into a test's ClickHouse, and query answers as dicts."""

import json

import pyarrow as pa

from ffxi_extractors import store


def put(con, table: str, rows: list[dict]) -> None:
    """Insert rows by column name; a column they leave out takes its default. Names go on to names_one, as
    resources.load sends them."""
    keys = dict.fromkeys(k for r in rows for k in r)
    store.insert(con, table, pa.table({k: [r.get(k) for r in rows] for k in keys}))
    if table == "names":
        store.pick_names(con)


def records(con, sql: str, params: dict | None = None) -> list[dict]:
    """A query's rows in ClickHouse's own JSON, as Scholar's API answers them."""
    with con.raw_stream(sql, parameters=params, fmt="JSONCompact", settings={"wait_end_of_query": 1}) as body:
        got = json.loads(body.read())
    names = [m["name"] for m in got["meta"]]
    return [dict(zip(names, row, strict=True)) for row in got["data"]]


def ask(con, query_name: str, **values) -> list[dict]:
    """A page query's rows, its {blank:Type}s given by values, as a page reads them."""
    return records(con, store.pages()[query_name], values)
