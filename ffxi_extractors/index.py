"""Indexes one capture: read its packets a batch at a time, decode only the opcodes the run needs, walk them
in order with the world and the extractors, and write each unit's rows as they come; then the derived
facts."""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from ffxi_packets import Decoder

from ffxi_extractors import combat, resources, store
from ffxi_extractors.capture import Capture, read
from ffxi_extractors.decode import DECODER_VERSION, CaptureStats, Decoded
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


def walk(cap: Capture, extractors: Iterable[Extractor], write=None) -> tuple[CaptureStats, World, list[Sink]]:
    """One pass over the packets, decoding the world's opcodes and those the extractors read: the decoder's
    facts, the world at the end, and every extractor's sink. With write(table, arrow), sinks write their
    rows as they fill."""
    world = World(cap)
    stats = CaptureStats(cap)
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
            stats.see(p, world.zone)
            if p.channel == 0:
                for x, s in by_key.get(key, ()):
                    x.packet(p, f, world, s.emit)
        if write:
            for _, s in sinks:
                s.flush()
    for x, s in sinks:
        x.finish(world, s.emit)
    combat.action.cache_clear()  # let go of the last batch's columns
    return stats, world, [s for _, s in sinks]


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
    whose nearest the capture keeps as its release. A run that raises leaves its units attempting, with the
    rows they wrote: the caller drops a skipped capture (store.drop), records a failure (store.fail), or
    runs it again, which replaces them."""
    started = int(time.time() * 1000)
    current = versions()
    units = set(current) if units is None else set(units)
    chosen = [x() for x in ALL if x.name in units]
    walked = [u for u in ("decode", *(x.name for x in chosen)) if u in units]
    out: dict[str, int] = {}
    if walked:
        if path is None:
            raise ValueError("indexing extractors or the decoder reads the capture: give its path")
        cap = read(path, capture_id, ((record or {}).get("capture") or {}).get("retail"))
        capture_id = cap.capture_id
        store.begin(con, capture_id, {u: current[u] for u in walked}, DECODER_VERSION, started)
        stats, world, sinks = walk(cap, chosen, lambda t, a: store.insert(con, t, a))
        for x, s in zip(chosen, sinks, strict=True):
            s.flush(everything=True)
            out[x.name] = s.written
        if "decode" in units:
            release = (
                resources.release_for(cap.client_version, cap.start_ms, resources.releases(names))
                if names
                else None
            )
            tables = stats.tables(record, release, cap.character_id or world.character_id)
            for t, data in tables.items():
                store.insert(con, t, data)
            out["decode"] = sum(t.num_rows for t in tables.values())
        store.done(con, capture_id, {u: (current[u], out[u]) for u in walked}, DECODER_VERSION, started)
    elif capture_id is None:
        raise ValueError("a run of derived units alone names its capture: give capture_id")
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
