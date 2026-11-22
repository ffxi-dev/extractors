import os
import uuid
from pathlib import Path

import extractors_rs
import pytest
import xicap

from ffxi_extractors import store
from ffxi_extractors.index import run

DATA = Path(__file__).parent / "data"
# Public Mogsafe captures as archived: AIxeAsqgUD5p, a Memoria recording (client 30261006_0), and
# QWFQtl0r5ciu, a converted captain log.
MEMORIA = DATA / "memoria.xicap"
CAPTAIN = DATA / "captain.xicap"
# A ClickHouse server, as compose.yaml starts it. Setup takes seconds, so a session sets up each database once
# and empties it for each test.
SERVER = os.environ.get("FFXI_TEST_CLICKHOUSE", "http://ffxi:ffxi@127.0.0.1:8123")
SESSION = "t_" + uuid.uuid4().hex[:12]


def database(name: str):
    c = store.connect(f"{SERVER}/{name}", create=True)
    store.setup(c)
    return c


def drop(name: str) -> None:
    c = store.connect(f"{SERVER}/default")
    c.command(f"DROP DATABASE IF EXISTS {name} SYNC")
    c.close()


def schema(c) -> list[tuple]:
    return store.rows(c, "SELECT name, create_table_query FROM system.tables"
                         " WHERE database = currentDatabase() ORDER BY name")  # fmt: skip


@pytest.fixture(scope="session")
def made():
    """The databases this session set up, with the schema setup left; dropped at the end."""
    made = {}
    yield made
    for name in made:
        drop(name)


def empty(made: dict, name: str):
    """The database name, set up and empty. Its tables are emptied, or, if a test changed its schema, it is
    made again."""
    c = store.connect(f"{SERVER}/{name}", create=True)
    if made.get(name) == schema(c):
        # One table at a time: on 26.8 a mutation hangs on a table TRUNCATE ALL TABLES emptied.
        sql = "SELECT name FROM system.tables WHERE database = currentDatabase() AND total_rows > 0"
        for (table,) in store.rows(c, sql):
            c.command(f"TRUNCATE TABLE {table}")
        return c
    c.close()
    drop(name)
    c = database(name)
    made[name] = schema(c)
    return c


@pytest.fixture(scope="session")
def both():
    """Both fixture captures indexed, as m and c, once a session. Read only: a test that writes uses con."""
    name = SESSION + "_both"
    c = database(name)
    run(c, MEMORIA, "m")
    run(c, CAPTAIN, "c")
    yield c
    c.close()
    drop(name)


@pytest.fixture
def con(made):
    c = empty(made, SESSION)
    yield c
    c.close()


def lists(tables) -> dict[str, list[dict]]:
    return {name: t.to_pylist() for name, t in tables.items()}


def walked(x, packets, me=0, capture_id="t", client_version=""):
    """packets: (ts_ms, direction, opcode, data), walked in Rust as one capture's with one extractor. Its
    rows by table."""
    return lists(extractors_rs.raw(x.name, list(packets), me, capture_id, client_version))


def packets(path):
    """A capture's game packets as walked takes them."""
    c2s = int(xicap.PacketFlag.ClientToServer)
    return [
        (p.timestamp, int(bool(p.flags & c2s)), p.opcode, p.data)
        for p in xicap.Reader(str(path))
        if not p.channel
    ]


def rows(con, sql: str, params: dict | None = None) -> list[tuple]:
    return store.rows(con, sql, params)


def value(con, sql: str, params: dict | None = None):
    return store.rows(con, sql, params)[0][0]


# Extractor tests' ids and drivers: packets as decoded fields (drive), or as raw bytes (raw).
PLAYER, MEMBER, STRANGER = 0x0001_0001, 0x0001_0002, 0x0001_0003
MOB = 0x01000000 | (0x0A3 << 12) | 0x010
P = "action (decoded bitstream)."  # the action packet's fields' prefix, as packets names them


def drive(x, *steps, capture="c", t0=0, times=None, directions=None, me=PLAYER):
    """steps: (opcode, fields), at t0 + i seconds unless times are given, through the world and the extractor
    in Rust (xc_core::testing::drive): its rows by table, every column. me is the character's id as the
    capture names it; a captain log names none (0). The world starts with MEMBER in the party."""
    return lists(extractors_rs.drive(x.name, list(steps), capture, t0, times, directions, me))


def claim(by):
    return 0x00E, {"UniqueNo": MOB, "ActIndex": 0x010, "SendFlg.ClaimStatus": 1, "BtTargetID": by}


def raw(x, *packets, me=PLAYER):
    """packets: (ts_ms, (opcode, data)), s2c. The extractor's rows by table. me is the character's id as the
    capture names it; a captain log names none (0)."""
    return walked(x, [(ts, 0, op, data) for ts, (op, data) in packets], me)
