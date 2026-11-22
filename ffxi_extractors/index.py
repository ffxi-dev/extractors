"""Indexes one capture: one pass over its packets in Rust (extractors_rs) with the world, the decoder, and the
extractors the run needs; then each unit's rows into ClickHouse, then the derived facts."""

from __future__ import annotations

import time
from pathlib import Path

import extractors_rs

from ffxi_extractors import decode, resources, store
from ffxi_extractors.capture import read
from ffxi_extractors.decode import DECODER_VERSION
from ffxi_extractors.extractors import ALL
from ffxi_extractors.facts import DERIVED
from ffxi_extractors.facts.bestiary_mobs import partners, reroll


def versions(extractors=ALL, derived=DERIVED) -> dict[str, str]:
    """The version each unit has in this code: the decoder's is the packets release and the world's; a
    derived unit's joins its own with its inputs'."""
    out = {"decode": DECODER_VERSION, **{x.name: str(x.version) for x in extractors}}
    for d in derived:
        out[d.name] = d.full_version(out)
    return out


def run(
    con,
    path: str | Path | None,
    capture_id: str | None = None,
    units: set[str] | None = None,
    record: dict | None = None,
    names: str | Path | None = None,
) -> dict[str, int]:
    """Index a capture's units (all when None) into ClickHouse, each an idempotent replace (store.py): the
    decoder and the extractors in one pass over the packets (extractors_rs.run), then the derived units. A
    run of derived units alone reads no file. Units this code does not know are left to the caller. Returns
    rows by unit. Raises Skipped for a capture not from retail or too large. names is the folder of
    retail-resources' releases, whose nearest the capture keeps as its release. A run that raises leaves its
    units attempting, with the rows they wrote: the caller drops a skipped capture (store.drop), records a
    failure (store.fail), or runs it again, which replaces them."""
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
        tables = extractors_rs.run(str(path), capture_id, walked)
        for x in chosen:
            for t in x.tables:
                store.insert(con, t.name, tables[t.name])
            out[x.name] = sum(tables[t.name].num_rows for t in x.tables)
        if "decode" in units:
            release = (
                resources.release_for(cap.client_version, cap.start_ms, resources.releases(names))
                if names
                else None
            )
            mine = decode.tables(tables, record, release)
            for name, data in mine.items():
                store.insert(con, name, data)
            out["decode"] = sum(t.num_rows for t in mine.values())
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
