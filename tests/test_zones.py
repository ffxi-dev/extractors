import struct

from conftest import walked

from ffxi_extractors.capture import Packet
from ffxi_extractors.extractors import Zones


def logout(state, server=b""):
    """A 0x00B: the logout state and as much of the zone server as given."""
    if state is None:
        return 0x00B, struct.pack("<HH", 0x0B, 0)
    return 0x00B, struct.pack("<HHI", 0x0B, 0, state) + server


def zone_in():
    data = bytearray(16)
    data[0] = 0x0A
    struct.pack_into("<I", data, 4, 230)
    return 0x00A, bytes(data)


def servers(*packets):
    _, _, (sink,) = walked([Zones()], [Packet(i, i, 0, 0, op, 0, d) for i, (op, d) in enumerate(packets)])
    return [r["server"] for r in sink.rows["zones"]]


def test_a_zone_change_names_its_server_and_a_short_one_none():
    """Codex's review, 13: a 4-byte 0x00B raised IndexError, and one cut short gave half an address."""
    full = bytes([10, 20, 30, 40]) + struct.pack("<H", 54230) + bytes(14)
    assert servers(logout(2, full), zone_in()) == ["10.20.30.40:54230"]
    assert servers(logout(None), zone_in()) == [None]
    assert servers(logout(2, full[:5]), zone_in()) == [None]
    assert servers(logout(1, full), zone_in()) == [None]
