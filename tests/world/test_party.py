"""The party extractor on hand-built packets: every list that names members, and Trusts."""

import struct

from conftest import PLAYER, raw

from ffxi_extractors.extractors.world.party import Party

TRUST = 0x01000000 | (0x026 << 12) | 0x63C  # Curilla in Apollyon, as retail sent her


def member(op, uid, index, name, number, gattr=0, zone=0, job=0, level=0):
    """A 0x0DD or 0x0E2 party member (one layout)."""
    data = bytearray(56)
    data[0], data[1] = op, (56 // 4) << 1
    struct.pack_into("<IIIIIHB", data, 4, uid, 1000, 100, 0, gattr, index, number)
    struct.pack_into("<HBB", data, 32, zone, job, level)
    data[40 : 40 + len(name)] = name.encode()
    return op, bytes(data)


def alliance(*entries):
    """A 0x0C8 alliance list: (id, index, flags, zone) per slot."""
    data = bytearray(8 + 20 * 12)
    data[0], data[1] = 0xC8, (len(data) // 4) << 1
    for i, (uid, index, flags, zone) in enumerate(entries):
        struct.pack_into("<IHBxH", data, 8 + 12 * i, uid, index, flags, zone)
    return 0x0C8, bytes(data)


def test_members_and_trusts_from_every_list():
    rows = raw(
        Party,
        (0, member(0xDD, PLAYER, 0x464, "Friend", 1, gattr=4, job=1, level=75)),
        (1000, member(0xE2, TRUST, 0x73C, "Curilla", 2, zone=0x026)),
        (2000, alliance((PLAYER, 0x464, 4, 0x026), (TRUST, 0x73C, 0, 0x026), (0x0001_0003, 0x465, 0, 0x026))),
    )["party"]
    assert [(x["member_id"], x["name"], x["member_number"], x["trust"], x["flags"]) for x in rows] == [
        (PLAYER, "Friend", 1, False, 4),
        (TRUST, "Curilla", 2, True, 0),
        (PLAYER, "Friend", 0, False, 4),
        (TRUST, "Curilla", 1, True, 0),
        (0x0001_0003, None, 2, False, 0),
    ]
    assert (rows[0]["main_job"], rows[0]["main_level"], rows[2]["zone_id"]) == ("WAR", 75, 0x026)
