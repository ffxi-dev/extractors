"""Indexes one capture: read its packets a batch at a time, decode only the opcodes the run needs, walk them
in order with the world and the extractors, and write each unit's rows as they come; then the derived
facts."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
from ffxi_packets import Decoder

from ffxi_extractors import resources, store
from ffxi_extractors.capture import Capture, Packet, read
from ffxi_extractors.decode import DECODER_VERSION, Decoded
from ffxi_extractors.extract import Extractor, Sink
from ffxi_extractors.extractors import ALL
from ffxi_extractors.facts import DERIVED
from ffxi_extractors.facts.bestiary_mobs import partners, reroll
from ffxi_extractors.world import WORLD, World


def versions(extractors=ALL, derived=DERIVED) -> dict[str, str]:
    """The version each unit has in this code: the decoder's is the packets release and the world's; a
    derived unit's joins its own with its inputs'."""
    out = {"decode": DECODER_VERSION, **{x.name: str(x.version) for x in extractors}}
    for d in derived:
        out[d.name] = d.full_version(out)
    return out


class Facts:
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


def walk(cap: Capture, extractors: Iterable[Extractor], write=None) -> tuple[Facts, World, list[Sink]]:
    """One pass over the packets, decoding the world's opcodes and those the extractors read: the decoder's
    facts, the world at the end, and every extractor's sink. With write(table, arrow), sinks write their
    rows as they fill."""
    world = World(cap)
    facts = Facts(cap)
    sinks = [(x, Sink(x, cap.capture_id, cap.client_version, write)) for x in extractors]
    by_key: dict[tuple[int, int], list[tuple[Extractor, Sink]]] = {}
    for x, s in sinks:
        for key in x.reads:
            by_key.setdefault(key, []).append((x, s))
    keys = WORLD | set(by_key)
    decoder = Decoder()
    for batch in cap.batches():
        decoded = Decoded(decoder, cap.client_version, batch, keys)
        for i, p in enumerate(batch):
            key = (p.direction, p.opcode)
            f = decoded.fields(i, p)
            if key in WORLD:
                world.update(p, f)
            facts.see(p, world.zone)
            if p.channel == 0:
                for x, s in by_key.get(key, ()):
                    x.packet(p, f, world, s.emit)
        if write:
            for _, s in sinks:
                s.flush()
    for x, s in sinks:
        x.finish(world, s.emit)
    return facts, world, [s for _, s in sinks]


def run(
    con,
    path: str | Path | None,
    capture_id: str | None = None,
    units: set[str] | None = None,
    record: dict | None = None,
    names: str | Path | None = None,
) -> dict[str, int]:
    """Index a capture's units (all when None) into ClickHouse, each an idempotent replace (store.py): the
    decoder and the extractors in one pass over the packets, then the derived units. A run of derived units
    alone reads no file. Units this code does not know are left to the caller. Returns rows by unit. Raises
    Skipped for a capture not from retail or too large. names is the folder of retail-resources' releases,
    whose nearest the capture keeps as its release."""
    started = int(time.time() * 1000)
    current = versions()
    units = set(current) if units is None else set(units)
    chosen = [x() for x in ALL if x.name in units]
    walked = [u for u in ("decode", *(x.name for x in chosen)) if u in units]
    out: dict[str, int] = {}
    if walked:
        cap = read(path, capture_id, ((record or {}).get("capture") or {}).get("retail"))
        capture_id = cap.capture_id
        store.begin(con, capture_id, {u: current[u] for u in walked}, DECODER_VERSION, started)
        facts, world, sinks = walk(cap, chosen, lambda t, a: store.insert(con, t, a))
        for x, s in zip(chosen, sinks, strict=True):
            s.flush(everything=True)
            out[x.name] = s.written
        if "decode" in units:
            release = (
                resources.release_for(cap.client_version, cap.start_ms, resources.releases(names))
                if names
                else None
            )
            tables = facts.tables(record, release, cap.character_id or world.character_id)
            for t, data in tables.items():
                store.insert(con, t, data)
            out["decode"] = sum(t.num_rows for t in tables.values())
        store.done(con, capture_id, {u: (current[u], out[u]) for u in walked}, DECODER_VERSION, started)
    # The captures sharing a fight with this one before its fights are written again: a fight it no longer
    # holds counts in theirs, so their mob rows are written again with those it shares after.
    before = partners(con, [capture_id]) if "bestiary_mobs" in units else []
    for d in DERIVED:
        if d.name in units:
            store.begin(con, capture_id, {d.name: current[d.name]}, DECODER_VERSION, started)
            written = con.command(
                f"INSERT INTO {d.tables[0].name} {d.sql}", parameters={"capture": capture_id}
            )
            out[d.name] = written.written_rows
            if d.name == "bestiary_mobs":
                reroll(con, sorted(set(before) | set(partners(con, [capture_id]))))
            store.done(con, capture_id, {d.name: (current[d.name], out[d.name])}, DECODER_VERSION, started)
    return out
