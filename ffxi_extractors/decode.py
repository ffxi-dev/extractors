"""The decode unit: its tables, what extractors_rs counts of every packet as it decodes a capture (sizes by
opcode, packets per second, zone visits), with the capture's header and Mogsafe's record."""

from __future__ import annotations

import pyarrow as pa

from ffxi_extractors.extract import Column, Table, arrow
from ffxi_extractors.world import WORLD_VERSION

# The packets release whose layouts rust/xc-decode/packets holds.
PACKETS = "2.2.0"
# Every unit's rows depend on the decoder and on what the world keeps: a change to either re-runs them all.
DECODER_VERSION = f"{PACKETS}+world{WORLD_VERSION}"

# The decode unit's tables.
CAPTURES = Table(
    "captures",
    "One row per capture: its header and Mogsafe's record. Join names on release.",
    (
        Column("capture_id", pa.string(), "The Mogsafe capture.", null=False),
        Column(
            "client_version",
            pa.string(),
            "The client build that recorded it, as its header says.",
            null=False,
        ),
        Column(
            "release",
            pa.string(),
            "The retail-resources release whose names fit it: its own, or the nearest before it.",
        ),
        Column("character", pa.string(), "The recording character."),
        Column("character_id", pa.int64(), "Its id, from the header or its status (0x037)."),
        Column(
            "retail",
            pa.bool_(),
            "Recorded on retail: always true, as only retail captures are read.",
            null=False,
        ),
        Column("start_ms", pa.int64(), "First packet, Unix ms UTC."),
        Column("end_ms", pa.int64(), "Last packet."),
        Column("packets", pa.int64(), "Packets in the capture.", null=False),
        Column("world", pa.string(), "The world, from Mogsafe."),
        Column("uploader", pa.string(), "Who uploaded it."),
        Column("format", pa.string(), "xicap, captain, or packetviewer: what Mogsafe received."),
        Column("source", pa.string(), "How Mogsafe converted it, for an import."),
    ),
    order="capture_id",
)
SESSIONS = Table(
    "sessions",
    "Captain /cap sessions: named ranges of a capture's packets, from Mogsafe.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column("name", pa.string(), "The session's name."),
        Column("start_idx", pa.int64(), "Its first packet."),
        Column("end_idx", pa.int64(), "Its last packet."),
        Column("start_ms", pa.int64(), "Start, Unix ms UTC."),
        Column("end_ms", pa.int64(), "End."),
        Column("cut_short", pa.bool_(), "The capture ended before the session.", null=False),
    ),
    order="capture_id",
)
SIZES = Table(
    "sizes",
    "Packets by client version, direction, opcode, and size: a size seen only in older client versions shows"
    " a layout that changed.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column("client_version", pa.string(), "Its client build.", null=False),
        Column("direction", pa.string(), "s2c or c2s.", null=False, low=True),
        Column("opcode", pa.int32(), "The packet's id.", null=False),
        Column("size", pa.int32(), "Bytes.", null=False),
        Column("packets", pa.int64(), "How many.", null=False),
    ),
    order="direction, opcode, capture_id",
)
ZONE_VISITS = Table(
    "zone_visits",
    "Each stretch of a capture spent in one zone.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column("idx", pa.int64(), "The packet that put the character there.", null=False),
        Column("start_ms", pa.int64(), "Its time.", null=False),
        Column("end_idx", pa.int64(), "The visit's last packet.", null=False),
        Column("end_ms", pa.int64(), "Its time.", null=False),
        Column("zone_id", pa.int32(), "The zone.", null=False),
        Column(
            "zoned_in", pa.bool_(), "Whether a zone-in began it, rather than the capture's start.", null=False
        ),
    ),
    order="zone_id, capture_id, start_ms",
)
ACTIVITY = Table(
    "activity",
    "Packets per stretch of a capture: about 400 stretches of a second or more.",
    (
        Column("capture_id", pa.string(), "The capture.", null=False),
        Column("t", pa.int64(), "The stretch's start, Unix ms UTC.", null=False),
        Column("n", pa.int64(), "Packets in it.", null=False),
    ),
    order="capture_id, t",
)
TABLES = (CAPTURES, SESSIONS, SIZES, ZONE_VISITS, ACTIVITY)
VISIT = ("idx", "start_ms", "end_idx", "end_ms", "zone_id", "zoned_in")  # a zone visit's values, in order


def tables(got: dict[str, pa.Table], record: dict | None, release: str | None) -> dict[str, pa.Table]:
    """The decode unit's tables from extractors_rs.run's, with the release and Mogsafe's record filled in:
    record is its {"capture", "sessions"} for the capture, when known."""
    c = (record or {}).get("capture") or {}
    sessions = (record or {}).get("sessions") or []
    captures = got["captures"].to_pylist()[0] | {"release": release}
    captures |= {k: c.get(k) for k in ("world", "uploader", "format", "source")}
    cid = captures["capture_id"]
    out = {t.name: got[t.name] for t in TABLES}
    out["captures"] = arrow(CAPTURES, {k: [v] for k, v in captures.items()})
    out["sessions"] = arrow(SESSIONS, {
        "capture_id": [cid] * len(sessions), "name": [s["name"] for s in sessions],
        "start_idx": [s["start_packet"] for s in sessions], "end_idx": [s["end_packet"] for s in sessions],
        "start_ms": [s["start_ms"] for s in sessions], "end_ms": [s["end_ms"] for s in sessions],
        "cut_short": [bool(s.get("cut_short")) for s in sessions],
    })  # fmt: skip
    return out
