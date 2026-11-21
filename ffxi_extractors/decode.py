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


class CaptureStats:
    """What the decoder keeps of every packet: sizes by opcode, packets per second, and zone visits."""

    def __init__(self, cap: Capture):
        self.cap = cap
        self.sizes: Counter = Counter()
        self.seconds: Counter = Counter()
        self.visits: list[list] = []  # [idx, start_ms, end_idx, end_ms, zone_id, zoned_in]
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
        activity = Counter()
        for second, n in self.seconds.items():
            activity[second * 1000 // bucket * bucket] += n
        v = self.visits
        return {
            "captures": pa.table({
                "capture_id": [cid], "client_version": [cap.client_version],
                "release": pa.array([release], pa.string()),
                "character": [cap.character], "character_id": pa.array([character_id], pa.int64()),
                "retail": [True], "start_ms": pa.array([cap.start_ms], pa.int64()),
                "end_ms": pa.array([cap.end_ms], pa.int64()), "packets": pa.array([cap.packets], pa.int64()),
                **{k: pa.array([c.get(k)], pa.string()) for k in ("world", "uploader", "format", "source")},
            }),
            "sessions": pa.table({
                "capture_id": pa.array([cid] * len(sessions), pa.string()),
                "name": pa.array([s["name"] for s in sessions], pa.string()),
                "start_idx": pa.array([s["start_packet"] for s in sessions], pa.int64()),
                "end_idx": pa.array([s["end_packet"] for s in sessions], pa.int64()),
                "start_ms": pa.array([s["start_ms"] for s in sessions], pa.int64()),
                "end_ms": pa.array([s["end_ms"] for s in sessions], pa.int64()),
                "cut_short": pa.array([bool(s.get("cut_short")) for s in sessions], pa.bool_()),
            }),
            "sizes": pa.table({
                "capture_id": pa.array([cid] * len(self.sizes), pa.string()),
                "client_version": pa.array([cap.client_version] * len(self.sizes), pa.string()),
                "direction": pa.array([k[0] for k in self.sizes], pa.string()),
                "opcode": pa.array([k[1] for k in self.sizes], pa.int32()),
                "size": pa.array([k[2] for k in self.sizes], pa.int32()),
                "packets": pa.array(list(self.sizes.values()), pa.int64()),
            }),
            "zone_visits": pa.table({
                "capture_id": pa.array([cid] * len(v), pa.string()),
                **{k: pa.array([x[i] for x in v], pa.int64())
                   for i, k in enumerate(("idx", "start_ms", "end_idx", "end_ms"))},
                "zone_id": pa.array([x[4] for x in v], pa.int32()),
                "zoned_in": pa.array([x[5] for x in v], pa.bool_()),
            }),
            "activity": pa.table({
                "capture_id": pa.array([cid] * len(activity), pa.string()),
                "t": pa.array(sorted(activity), pa.int64()),
                "n": pa.array([activity[t] for t in sorted(activity)], pa.int64()),
            }),
        }  # fmt: skip
