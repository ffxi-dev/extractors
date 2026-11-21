from types import SimpleNamespace

import pytest

from ffxi_extractors import capture


def reader(monkeypatch, packets, count=0):
    """xicap's Reader over these packets: no trailer, so no end time, and the trailer's count."""
    character = SimpleNamespace(name="", character_id=0)

    class Reader(list):
        metadata = SimpleNamespace(
            client_version="", character=character, server_kind=1, start_timestamp=1000
        )
        end_timestamp, packet_count = 0, count

    monkeypatch.setattr(capture.xicap, "Reader", lambda path: Reader(packets))


def packet(ts):
    return SimpleNamespace(timestamp=ts, channel=0, opcode=0x00D, flags=0, data=b"")


def test_a_cut_off_capture_ends_at_its_last_packet(monkeypatch):
    reader(monkeypatch, [packet(1000), packet(2500)])
    cap = capture.read("cut.xicap")
    assert sum(len(b) for b in cap.batches()) == 2 and cap.end_ms == 2500


@pytest.mark.parametrize(
    ("count", "packets", "skipped"), [(3, 2, True), (0, 3, True), (0, 2, False), (2, 2, False)]
)
def test_a_capture_past_max_packets_is_skipped(monkeypatch, count, packets, skipped):
    """Over MAX_PACKETS by its trailer's count, or, cut off with no count, by the packets read."""
    monkeypatch.setattr(capture, "MAX_PACKETS", 2)
    reader(monkeypatch, [packet(1000) for _ in range(packets)], count)
    if skipped:
        with pytest.raises(capture.Skipped, match="Not analysed: over 60,000,000 packets"):
            for _ in capture.read("big.xicap").batches():
                pass
    else:
        cap = capture.read("big.xicap")
        assert sum(len(b) for b in cap.batches()) == packets == cap.packets
