"""The event extractors on hand-built packets, one per spec scenario in scholar-events."""

import struct

from conftest import walked

from ffxi_extractors.capture import Packet
from ffxi_extractors.extractors import Events, KeyItems

PLAYER = 0x0001_0001
NPC = 0x0100_0000 | (0x0F5 << 12) | 0x064  # an NPC of Lower Jeuno, index 100


def pkt(op, size, fmt, offset, *values):
    data = bytearray(size)
    data[0], data[1] = op & 0xFF, (op >> 8) | (size // 4) << 1
    struct.pack_into(fmt, data, offset, *values)
    return op, bytes(data)


def event_num(event, params):  # s2c 0x034
    return 0, pkt(0x034, 52, "<I8IHHHHHH", 4, NPC, *params, 100, 0, event, 8, 0, 0)


def update(params):  # s2c 0x05C
    return 0, pkt(0x05C, 36, "<8I", 4, *params)


def reply(event, option, mode):  # c2s 0x05B
    return 1, pkt(0x05B, 20, "<IIHHHH", 4, NPC, option, 100, mode, 0, event)


def update_strings(params, strings):  # s2c 0x05D
    return 0, pkt(0x05D, 104, "<9i16s16s16s16s", 4, *params, *(x.encode() for x in strings))


def release():  # s2c 0x052
    return 0, pkt(0x052, 8, "<B", 4, 1)


def log(port, words):  # s2c 0x056
    return 0, pkt(0x056, 40, "<8IH", 4, *words, port)


def keyitems(table, words):  # s2c 0x055
    return 0, pkt(0x055, 136, "<16I16IB", 4, *words, *[0] * 16, table)


def message(num):  # s2c 0x02A, as an NPC's "Obtained key item" sends it
    return 0, pkt(0x02A, 32, "<I4IHH", 4, NPC, num, 0, 0, 0, 100, 6396)


def zone_in():  # s2c 0x00A that plays no event
    return 0, pkt(0x00A, 260, "<I", 4, PLAYER)


def position(x, y, z):  # c2s 0x015, XiPackets' order x, z, y
    return 1, pkt(0x015, 32, "<fff", 4, x, z, y)


def run(x, *packets):
    """packets: (ts_ms, (direction, (opcode, data))). The extractor's rows by table."""
    _, _, (sink,) = walked(
        [x()], [Packet(i, ts, 0, d, op, 0, data) for i, (ts, (d, (op, data))) in enumerate(packets)], PLAYER
    )
    return sink.rows


def test_a_home_point():
    rows = run(
        Events,
        (1000, event_num(8700, [1, 2, 3, 4, 5, 6, 7, 8])),
        (2000, reply(8700, 2, 1)),
        (2100, update([9, 0, 0, 0, 0, 0, 0, 0])),
        (3000, reply(8700, 0x10002, 0)),
        (3100, release()),
    )["events"]
    assert [r["kind"] for r in rows] == ["start", "reply", "update", "reply", "release"]
    assert {r["event_idx"] for r in rows} == {0}
    start = rows[0]
    assert (start["npc_id"], start["npc_index"], start["event_id"], start["mode"]) == (NPC, 100, 8700, 8)
    assert start["params"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert rows[2]["params"][0] == 9
    assert [(r["mode"], r["option"]) for r in rows if r["kind"] == "reply"] == [(1, 2), (0, 0x10002)]


def test_a_quest_completed():
    rows = run(
        Events,
        (0, log(0x98, [0] * 8)),
        (1000, event_num(10, [0] * 8)),
        (2000, reply(10, 0, 0)),
        (2100, release()),
        (2200, log(0x98, [0, 1 << 5, 0, 0, 0, 0, 0, 0])),
        (90_000, log(0x98, [0, 1 << 5 | 1, 0, 0, 0, 0, 0, 0])),
    )["log_changes"]
    first, second = rows
    assert (first["log"], first["area"], first["id"]) == ("quests_done", "Bastok", 37)
    assert first["action"] == "completed"
    assert (first["event_idx"], first["event_id"]) == (1, 10)
    assert (second["id"], second["event_idx"]) == (32, None)  # long after the event


def test_main_mission_progress():
    rows = run(Events, (0, log(0xFFFF, [1, 5] + [0] * 6)), (1, log(0xFFFF, [1, 6] + [0] * 6)))
    (row,) = rows["log_changes"]
    assert (row["log"], row["area"], row["old"], row["new"], row["id"]) == (
        "main",
        "Nation mission",
        5,
        6,
        None,
    )


def test_a_key_item_gained():
    rows = run(
        KeyItems,
        (0, keyitems(0, [0b1] + [0] * 15)),
        (1000, position(1.5, -20.0, 0.25)),
        (2000, keyitems(0, [0b100] + [0] * 15)),
        (3000, keyitems(1, [0] * 16)),
        (4000, keyitems(1, [0, 1] + [0] * 14)),
    )["keyitems"]
    assert [(r["key_item_id"], r["change"]) for r in rows] == [(2, "gained"), (0, "lost"), (544, "gained")]
    assert (rows[0]["x"], rows[0]["y"], rows[0]["z"]) == (1.5, -20.0, 0.25)


def test_a_key_item_from_an_npc():
    """scholar-progress: a key item follows the event under way, or one that ended under 30 s before."""
    rows = run(
        KeyItems,
        (0, keyitems(0, [0] * 16)),
        (1000, event_num(8700, [0] * 8)),
        (2000, keyitems(0, [0b1] + [0] * 15)),
        (3000, release()),
        (20_000, keyitems(0, [0b11] + [0] * 15)),
        (60_000, keyitems(0, [0b111] + [0] * 15)),
    )["keyitems"]
    got = [(r["key_item_id"], r["event_idx"], r["event_id"]) for r in rows]
    assert got == [(0, 1, 8700), (1, 1, 8700), (2, None, None)]


def test_a_key_item_in_the_first_list():
    """A capture that starts mid-zone gets its first list of a table when an event gives a key item."""
    rows = run(
        KeyItems,
        (1000, event_num(18, [0] * 8)),
        (2000, message(544)),
        (3000, release()),
        (3100, keyitems(1, [1, 1] + [0] * 14)),
        (4000, zone_in()),
        (5000, keyitems(1, [1, 1] + [0] * 14)),
        (6000, event_num(19, [0] * 8)),
        (7000, message(0)),
        (8000, zone_in()),
        (9000, keyitems(0, [1] + [0] * 15)),
    )["keyitems"]
    assert [(r["key_item_id"], r["change"], r["event_id"]) for r in rows] == [(544, "gained", 18)]


def test_a_reward_after_a_warp_follows_its_event():
    """A cutscene often ends in a warp, and its key item or log change comes after the zone-in; a new event
    takes over."""
    for x, table, before, after in (
        (KeyItems, "keyitems", keyitems(0, [0] * 16), lambda n: keyitems(0, [(1 << n) - 1] + [0] * 15)),
        (Events, "log_changes", log(0x98, [0] * 8), lambda n: log(0x98, [(1 << n) - 1] + [0] * 7)),
    ):
        rows = run(
            x,
            (0, before),
            (1000, event_num(8700, [0] * 8)),
            (2000, release()),
            (3000, zone_in()),
            (5000, after(1)),
            (6000, event_num(8800, [0] * 8)),
            (7000, after(2)),
        )[table]
        assert [r["event_id"] for r in rows] == [8700, 8800], x.name


def test_an_update_with_strings():
    """0x05D updates an event with nine numbers and four strings, as LSB's updateEventString sends them."""
    rows = run(
        Events,
        (1000, event_num(8700, [0] * 8)),
        (2000, reply(8700, 3, 1)),
        (2100, update_strings([5, 0, 0, 0, 0, 0, 0, 0, 9], ["Nours", "", "Sword", ""])),
    )["events"]
    update = rows[2]
    assert (update["kind"], update["opcode"], update["event_idx"]) == ("update", 0x05D, 0)
    assert update["params"] == [5, 0, 0, 0, 0, 0, 0, 0, 9]
    assert update["strings"] == ["Nours", None, "Sword", None]
