"""Reads a xicap capture: its header, then its packets in order, a batch at a time."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import xicap

Fields = Callable[[str], Any]  # f(path) -> a field of the current packet, or None
BATCH = 50_000  # packets read and decoded at once: well under 1 GB of memory


@dataclass(slots=True)
class Packet:
    idx: int  # position in the capture, counting from 0 across every channel, as Lens's #packet= links do
    ts_ms: int
    channel: int  # 0 game, 1 search
    direction: int  # 0 to the client (s2c), 1 from the client (c2s)
    opcode: int
    flags: int  # xicap's packet flags: injected, excluded (stubbed), redacted, ...
    data: bytes


class Skipped(Exception):
    """A capture this does not read; the message says why."""


class NotRetail(Skipped):
    """Only retail captures are read."""


# The largest capture read, as Mogsafe limits a capture.
MAX_PACKETS = 60_000_000
TOO_LARGE = f"Not analysed: over {MAX_PACKETS:,} packets"


def check_retail(server_kind: int, marked: bool | None) -> None:
    """Raise NotRetail unless the header says retail or, saying nothing, Mogsafe's record marks it retail."""
    if server_kind == xicap.ServerKind.Private:
        raise NotRetail("Not analysed: private server")
    if server_kind != xicap.ServerKind.Retail and marked is not True:
        raise NotRetail("Not analysed: not marked retail")


@dataclass
class Capture:
    capture_id: str
    client_version: str
    character: str
    character_id: int
    start_ms: int
    end_ms: int
    reader: Any = None
    packets: int = 0  # read so far

    def batches(self, size: int = BATCH) -> Iterator[list[Packet]]:
        """The packets in order, size at a time. Raises Skipped once a capture with no count passes
        MAX_PACKETS. A cut-off capture has no trailer, so no end time: its last packet's time stands in."""
        c2s = int(xicap.PacketFlag.ClientToServer)  # an int: an enum's & runs Python code per packet
        batch: list[Packet] = []
        for i, p in enumerate(self.reader):
            if i >= MAX_PACKETS:
                raise Skipped(TOO_LARGE)
            batch.append(Packet(i, p.timestamp, p.channel, p.flags & c2s, p.opcode, p.flags, p.data))
            if len(batch) == size:
                yield from self._seen(batch)
                batch = []
        if batch:
            yield from self._seen(batch)

    def _seen(self, batch: list[Packet]) -> Iterator[list[Packet]]:
        self.packets += len(batch)
        self.end_ms = max(self.end_ms, batch[-1].ts_ms)
        yield batch


def read(path: str | Path, capture_id: str | None = None, marked: bool | None = None) -> Capture:
    """The capture's header, once check_retail lets it in; its packets come from batches(). Raises Skipped
    past MAX_PACKETS by the trailer's count."""
    r = xicap.Reader(str(path))
    m = r.metadata
    check_retail(m.server_kind, marked)
    if r.packet_count > MAX_PACKETS:
        raise Skipped(TOO_LARGE)
    return Capture(
        capture_id=capture_id or Path(path).stem,
        client_version=m.client_version,
        character=m.character.name,
        character_id=m.character.character_id,
        start_ms=m.start_timestamp,
        end_ms=r.end_timestamp,
        reader=r,
    )
