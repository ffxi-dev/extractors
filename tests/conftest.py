import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import xicap

from ffxi_extractors import store
from ffxi_extractors.capture import Capture, Packet
from ffxi_extractors.extract import Sink
from ffxi_extractors.index import run, walk
from ffxi_extractors.world import World

DATA = Path(__file__).parent / "data"
# Public Mogsafe captures as archived: AIxeAsqgUD5p, a Memoria recording (client 30261006_0), and
# QWFQtl0r5ciu, a converted captain log.
MEMORIA = DATA / "memoria.xicap"
CAPTAIN = DATA / "captain.xicap"
# The Memoria recording's packets as stored, in the small frames a recorder writes live. The archived copy
# is one frame; a cut-off copy of this one reads part of it, as Mogsafe serves a recording still uploading.
MEMORIA_LIVE = DATA / "memoria-live.xicap"
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


def walked(extractors, packets, me=0, capture_id="t", client_version=""):
    """Walk Packet objects as one capture's packets: (facts, world, sinks)."""
    c2s = int(xicap.PacketFlag.ClientToServer)
    raw = [
        SimpleNamespace(timestamp=p.ts_ms, channel=p.channel, flags=p.flags | (c2s if p.direction else 0),
                        opcode=p.opcode, data=p.data)
        for p in packets
    ]  # fmt: skip
    return walk(Capture(capture_id, client_version, "Tester", me, 0, 0, reader=raw), extractors)


def rows(con, sql: str, params: dict | None = None) -> list[tuple]:
    return store.rows(con, sql, params)


def value(con, sql: str, params: dict | None = None):
    return store.rows(con, sql, params)[0][0]


# Extractor tests' ids and drivers: packets as decoded fields (drive), or as raw bytes (raw).
PLAYER, MEMBER, STRANGER = 0x0001_0001, 0x0001_0002, 0x0001_0003
MOB = 0x01000000 | (0x0A3 << 12) | 0x010


def drive(x, *steps, capture="c", t0=0, times=None, directions=None, me=PLAYER):
    """steps: (opcode, fields), at t0 + i seconds unless times are given. The extractor's rows by table. me is
    the character's id as the capture names it; a captain log names none (0)."""
    w = World(Capture(capture, "v", "Me", me, 0, 0))
    w.party.add(MEMBER)
    x = x()
    sink = Sink(x, capture, "v")
    for i, (op, d) in enumerate(steps):
        ts = times[i] if times else t0 + i * 1000
        p = Packet(
            i, ts, 0, directions[i] if directions else 0, op, 0, bytes([i]) * 8
        )  # distinct bytes, so none reads as a resend
        w.update(p, d.get)
        if (p.direction, op) in x.reads:  # as index.walk
            x.packet(p, d.get, w, sink.emit)
    x.finish(w, sink.emit)
    return sink.rows


def claim(by):
    return 0x00E, {"UniqueNo": MOB, "ActIndex": 0x010, "SendFlg.ClaimStatus": 1, "BtTargetID": by}


def raw(x, *packets, me=PLAYER):
    """packets: (ts_ms, (opcode, data)). The extractor's rows by table. me is the character's id as the
    capture names it; a captain log names none (0)."""
    _, _, (sink,) = walked(
        [x()], [Packet(i, ts, 0, 0, op, 0, data) for i, (ts, (op, data)) in enumerate(packets)], me
    )
    return sink.rows
