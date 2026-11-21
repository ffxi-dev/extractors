"""The decode unit: decodes a batch of a capture's game packets a whole opcode at a time with packets'
decoder, only the opcodes asked for, and gives each packet's fields by path to the world and the extractors;
CaptureStats keeps the unit's own tables, what it counts of every packet."""

from __future__ import annotations

from collections import Counter, defaultdict
from importlib.metadata import version

import numpy as np
import pyarrow as pa
from ffxi_packets import Decoder

from ffxi_extractors.capture import Capture, Fields, Packet
from ffxi_extractors.extract import Column, Table, arrow
from ffxi_extractors.world import WORLD_VERSION

# Every unit's rows depend on the decoder and on what the world keeps: a change to either re-runs them all.
DECODER_VERSION = f"{version('ffxi-packets')}+world{WORLD_VERSION}"


def _none(path: str):
    return None


class Decoded:
    """A batch of packets, with the fields of those whose (direction, opcode) is in keys."""

    def __init__(self, decoder: Decoder, client_version: str, packets: list[Packet], keys):
        groups: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, p in enumerate(packets):
            if p.channel == 0 and (p.direction, p.opcode) in keys:
                groups[(p.direction, p.opcode)].append(i)
        self.cols: dict[tuple[int, int], dict] = {}
        self._lists: dict[tuple[int, int], dict[str, list]] = {}  # the columns read so far, as lists
        self._row = np.full(len(packets), -1, dtype=np.int64)
        for key, at in groups.items():
            self.cols[key] = decoder.decode(client_version, *key, [packets[i].data for i in at])
            self._row[at] = np.arange(len(at))

    def fields(self, i: int, p: Packet) -> Fields:
        """A getter for the batch's packet i by path: f("UniqueNo"), f("SendFlg.Position"). A field the
        packet does not hold, or that has no value, is None."""
        key = (p.direction, p.opcode)
        cols = self.cols.get(key) if p.channel == 0 else None
        if not cols:
            return _none
        row, lists = int(self._row[i]), self._lists.setdefault(key, {})

        def f(path: str):
            got = lists.get(path)
            if got is None:
                col = cols.get(path)
                if col is None:
                    return None
                got = lists[path] = _plain(col)
            return got[row]

        return f


def _plain(col) -> list:
    """A decoded column as a list of Python values, None where masked: a field read is then a list index, not
    a numpy element read. Reading every field of every packet that way took half of a capture's time."""
    out = col.tolist()  # a masked array's tolist gives None where masked
    if col.dtype == object:
        out = [v.item() if isinstance(v, np.generic) else v for v in out]
    return out


# The decode unit's tables, which CaptureStats fills.
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


class CaptureStats:
    """What the decoder keeps of every packet: sizes by opcode, packets per second, and zone visits."""

    def __init__(self, cap: Capture):
        self.cap = cap
        self.sizes: Counter = Counter()
        self.seconds: Counter = Counter()
        self.visits: list[list] = []  # one list per visit, as VISIT names its values
        self.zone: int | None = None

    def see(self, p: Packet, zone: int | None) -> None:
        """Count a packet; zone is the one the character is in once the world has read it."""
        zoned_in = p.channel == 0 and p.direction == 0 and p.opcode == 0x00A
        if p.channel == 0:
            self.sizes[("s2c" if p.direction == 0 else "c2s", p.opcode, len(p.data))] += 1
        self.seconds[p.ts_ms // 1000] += 1
        if zone is not None and (zone != self.zone or zoned_in):
            self.visits.append([p.idx, p.ts_ms, p.idx, p.ts_ms, zone, zoned_in])
        elif zone is not None:
            self.visits[-1][2:4] = p.idx, p.ts_ms
        self.zone = zone

    def tables(self, record: dict | None, release: str | None, character_id: int) -> dict[str, pa.Table]:
        """The decoder's tables. record is Mogsafe's {"capture", "sessions"} for the capture, when known."""
        cap, cid = self.cap, self.cap.capture_id
        c = (record or {}).get("capture") or {}
        sessions = (record or {}).get("sessions") or []
        # An activity graph's buckets: about 400 over the capture, a second or more each.
        bucket = max(1000, (cap.end_ms - cap.start_ms) // 400 // 1000 * 1000)
        activity: Counter[int] = Counter()
        for second, n in self.seconds.items():
            activity[second * 1000 // bucket * bucket] += n
        v = self.visits
        days = sorted(activity)
        return {
            t.name: arrow(t, cols)
            for t, cols in (
                (CAPTURES, {
                    "capture_id": [cid], "client_version": [cap.client_version], "release": [release],
                    "character": [cap.character], "character_id": [character_id], "retail": [True],
                    "start_ms": [cap.start_ms], "end_ms": [cap.end_ms], "packets": [cap.packets],
                    **{k: [c.get(k)] for k in ("world", "uploader", "format", "source")},
                }),
                (SESSIONS, {
                    "capture_id": [cid] * len(sessions), "name": [s["name"] for s in sessions],
                    "start_idx": [s["start_packet"] for s in sessions],
                    "end_idx": [s["end_packet"] for s in sessions],
                    "start_ms": [s["start_ms"] for s in sessions], "end_ms": [s["end_ms"] for s in sessions],
                    "cut_short": [bool(s.get("cut_short")) for s in sessions],
                }),
                (SIZES, {
                    "capture_id": [cid] * len(self.sizes),
                    "client_version": [cap.client_version] * len(self.sizes),
                    "direction": [k[0] for k in self.sizes], "opcode": [k[1] for k in self.sizes],
                    "size": [k[2] for k in self.sizes], "packets": list(self.sizes.values()),
                }),
                (ZONE_VISITS, {
                    "capture_id": [cid] * len(v),
                    **{k: [x[i] for x in v] for i, k in enumerate(VISIT)},
                }),
                (ACTIVITY, {"capture_id": [cid] * len(days), "t": days, "n": [activity[t] for t in days]}),
            )
        }  # fmt: skip
