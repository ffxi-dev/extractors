"""A xicap capture's header, and which captures are read: extractors_rs reads the packets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import xicap


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


def read(path: str | Path, capture_id: str | None = None, marked: bool | None = None) -> Capture:
    """The capture's header, once check_retail lets it in. Raises Skipped past MAX_PACKETS by the trailer's
    count; extractors_rs.run raises it for a capture with no trailer once it reads past them."""
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
    )
