"""Hand-built rows into a test's ClickHouse, and query answers as dicts."""

import json

import pyarrow as pa

from ffxi_extractors import store


def put(con, table: str, rows: list[dict]) -> None:
    """Insert rows by column name; a column they leave out takes its default."""
    keys = dict.fromkeys(k for r in rows for k in r)
    store.insert(con, table, pa.table({k: [r.get(k) for r in rows] for k in keys}))


def records(con, sql: str) -> list[dict]:
    """A query's rows in ClickHouse's own JSON, as Scholar's API answers them."""
    with con.raw_stream(sql, fmt="JSONCompact", settings={"wait_end_of_query": 1}) as body:
        got = json.loads(body.read())
    names = [m["name"] for m in got["meta"]]
    return [dict(zip(names, row, strict=True)) for row in got["data"]]
