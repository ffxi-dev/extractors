"""The header checks a run makes before reading packets. Past MAX_PACKETS with no count, and a cut-off
capture's end time, are extractors_rs's (rust/xc-core's run.rs and stats.rs)."""

from types import SimpleNamespace

import pytest

from ffxi_extractors import capture


def reader(monkeypatch, count, server_kind=1):
    """xicap's Reader with this trailer count."""
    character = SimpleNamespace(name="", character_id=0)
    meta = SimpleNamespace(
        client_version="", character=character, server_kind=server_kind, start_timestamp=1000
    )
    r = SimpleNamespace(metadata=meta, end_timestamp=0, packet_count=count)
    monkeypatch.setattr(capture.xicap, "Reader", lambda path: r)


@pytest.mark.parametrize(("count", "skipped"), [(3, True), (2, False), (0, False)])
def test_a_capture_past_max_packets_by_its_count_is_skipped(monkeypatch, count, skipped):
    monkeypatch.setattr(capture, "MAX_PACKETS", 2)
    reader(monkeypatch, count)
    if skipped:
        with pytest.raises(capture.Skipped, match="Not analysed: over 60,000,000 packets"):
            capture.read("big.xicap")
    else:
        assert capture.read("big.xicap").start_ms == 1000


def test_a_private_server_capture_is_not_read(monkeypatch):
    reader(monkeypatch, 0, server_kind=2)
    with pytest.raises(capture.NotRetail):
        capture.read("lsb.xicap")
