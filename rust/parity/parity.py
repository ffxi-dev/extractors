"""Parity and timing of the Rust extractors against the Python ones, a capture at a time. README.md says how
to run it; this runs inside its image on lsb.

    parity.py check <unit>... [--captures sample|all|<id>,<id>] [-j N] [--rows N]
    parity.py ref [<unit>...] [--captures ...] [-j N]      Python's rows and times, cached in --ref
    parity.py baseline [--captures ...]                   Python's time per unit, from the cache

A unit is an extractor, "decode" (the decoder's tables), or "world" (the walk alone, no rows). A unit's
rows are canonical: each row a JSON list of its values in column order, the rows sorted, a table's md5 over
them. Python's rows and time are cached per capture and unit, and made again when the unit's version or the
decoder's changes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pyarrow as pa
import xicap

from ffxi_extractors.capture import Skipped, read
from ffxi_extractors.decode import DECODER_VERSION
from ffxi_extractors.extractors import ALL

HERE = Path(__file__).parent
MIRROR = Path(os.environ.get("PARITY_MIRROR", "/mirror"))
REF = Path(os.environ.get("PARITY_REF", "/ref"))
EXTRACTORS = {x.name: x for x in ALL}
UNITS = ("world", "decode", *EXTRACTORS)


def version(unit: str) -> str:
    x = EXTRACTORS.get(unit)
    return f"{x.version if x else 0}/{DECODER_VERSION}"


def lines(t: pa.Table) -> list[str]:
    cols = [t.column(c).to_pylist() for c in t.column_names]
    return sorted(json.dumps(r, ensure_ascii=False, default=str) for r in zip(*cols, strict=True))


def python(path: Path, cid: str, unit: str) -> dict[str, pa.Table]:
    """Python's tables for one unit, from a walk with that unit alone. Only a checkout from before the Rust
    switch (v1.14.4 and older) has the Python walk; after it, the cache in REF is the reference."""
    try:
        from ffxi_extractors.index import walk  # type: ignore[attr-defined]
    except ImportError:
        sys.exit(f"no Python reference for {unit} at {version(unit)} on {cid}: parity ref, from v1.14.4")
    cap = read(path, cid, True)
    if unit == "decode":
        stats, world, _ = walk(cap, [], count=True)
        return stats.tables(None, None, cap.character_id or world.character_id)
    if unit == "world":
        walk(cap, [], count=False)
        return {}
    _, _, sinks = walk(cap, [EXTRACTORS[unit]()], count=False)
    return sinks[0].arrow()


def rust(path: Path, cid: str, unit: str) -> dict[str, pa.Table]:
    """Rust's tables for one unit, from a pass with that unit alone. PARITY_RUST=python runs Python instead,
    to check the harness."""
    if os.environ.get("PARITY_RUST") == "python":
        return python(path, cid, unit)
    import extractors_rs  # type: ignore[import-not-found]

    return extractors_rs.run(str(path), cid, [unit])


def timed(f, path: Path, cid: str, unit: str) -> tuple[float, dict[str, pa.Table]]:
    t0 = time.perf_counter()
    tables = f(path, cid, unit)
    return time.perf_counter() - t0, tables


def summary(tables: dict[str, pa.Table]) -> tuple[dict, dict[str, list[str]]]:
    rows = {name: lines(t) for name, t in tables.items()}
    return {
        name: {
            "rows": len(rows[name]),
            "md5": hashlib.md5("\n".join(rows[name]).encode()).hexdigest(),
            "schema": [f"{f.name} {f.type}" for f in t.schema],
        }
        for name, t in tables.items()
    }, rows


def write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}")
    tmp.write_bytes(data)
    tmp.replace(path)


def cached(cid: str, unit: str) -> dict | None:
    f = REF / cid / f"{unit}.json"
    got = json.loads(f.read_text()) if f.exists() else None
    return got if got and got["version"] == version(unit) else None


def reference(path: Path, cid: str, unit: str) -> dict:
    """Python's summary of a unit on a capture, from the cache or made and cached."""
    if got := cached(cid, unit):
        return got
    seconds, tables = timed(python, path, cid, unit)
    tabs, rows = summary(tables)
    out = REF / cid
    out.mkdir(parents=True, exist_ok=True)
    for name, ls in rows.items():
        write(out / f"{unit}.{name}.jsonl.gz", gzip.compress("\n".join(ls).encode(), 1))
    got = {"version": version(unit), "seconds": seconds, "tables": tabs}
    write(out / f"{unit}.json", json.dumps(got, indent=1).encode())
    return got


def ref_lines(cid: str, unit: str, table: str) -> list[str]:
    f = REF / cid / f"{unit}.{table}.jsonl.gz"
    text = gzip.decompress(f.read_bytes()).decode() if f.exists() else ""
    return text.split("\n") if text else []


def diff(cid: str, unit: str, ref: dict, tabs: dict, rows: dict[str, list[str]], n: int) -> list[str]:
    """What differs between Python's tables and Rust's, the first n rows each way per table."""
    out = []
    for name in sorted(set(ref["tables"]) | set(tabs)):
        py, rs = ref["tables"].get(name), tabs.get(name)
        if py is None or rs is None:
            out.append(f"  {name}: only in {'rust' if py is None else 'python'}")
            continue
        if py["md5"] == rs["md5"] and py["schema"] == rs["schema"]:
            continue
        out.append(f"  {name}: rows python {py['rows']}, rust {rs['rows']}")
        if py["schema"] != rs["schema"]:
            out.append(f"    schema python: {', '.join(py['schema'])}")
            out.append(f"    schema rust:   {', '.join(rs['schema'])}")
        if py["md5"] == rs["md5"]:
            continue
        out.append(f"    columns: {', '.join(s.split(' ')[0] for s in rs['schema'])}")
        a, b = Counter(ref_lines(cid, unit, name)), Counter(rows[name])
        out += [f"    - {r}" for r in sorted((a - b).elements())[:n]]
        out += [f"    + {r}" for r in sorted((b - a).elements())[:n]]
    return out


def check(path: Path, cid: str, unit: str, n: int) -> dict:
    try:
        ref = reference(path, cid, unit)
    except Skipped as e:
        return {"cid": cid, "skipped": str(e)}
    seconds, tables = timed(rust, path, cid, unit)
    tabs, rows = summary(tables)
    return {"cid": cid, "py": ref["seconds"], "rs": seconds, "diff": diff(cid, unit, ref, tabs, rows, n)}


def ref_one(path: Path, cid: str, unit: str) -> dict:
    try:
        return {"cid": cid, "unit": unit, "py": reference(path, cid, unit)["seconds"]}
    except Skipped as e:
        return {"cid": cid, "unit": unit, "skipped": str(e)}


def captures(which: str) -> list[tuple[Path, str]]:
    """The captures' files in the mirror, named <id>.<sha256>.xicap: the newest for an id."""
    files: dict[str, Path] = {}
    for f in sorted(MIRROR.glob("*.xicap"), key=lambda f: f.stat().st_mtime):
        files[f.name.split(".")[0]] = f
    if which == "all":
        ids = sorted(files)
    elif which == "sample":
        ids = [s.split()[0] for s in (HERE / "sample.txt").read_text().splitlines() if s and s[0] != "#"]
    else:
        ids = which.split(",")
    if missing := [i for i in ids if i not in files]:
        sys.exit(f"not in {MIRROR}: {', '.join(missing)}")
    return [(files[i], i) for i in ids]


def units(names: list[str]) -> list[str]:
    if bad := [u for u in names if u not in UNITS and u != "all"]:
        sys.exit(f"no unit {', '.join(bad)}; units: {', '.join(UNITS)}")
    return list(UNITS) if "all" in names or not names else names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check", "ref", "baseline"))
    ap.add_argument("units", nargs="*")
    ap.add_argument("--captures", default="sample")
    ap.add_argument("-j", type=int, default=max(1, (os.cpu_count() or 2) // 4))
    ap.add_argument("--rows", type=int, default=5, help="differing rows shown each way per table")
    a = ap.parse_args()
    caps, us = captures(a.captures), units(a.units)
    packets = {cid: xicap.Reader(str(path)).packet_count for path, cid in caps}
    if a.command == "baseline":
        return baseline(caps, us, packets)
    with ProcessPoolExecutor(a.j) as pool:
        if a.command == "ref":
            # The largest first, so the pool ends together.
            jobs = sorted(((p, c, u) for p, c in caps for u in us), key=lambda j: -packets[j[1]])
            for r in pool.map(ref_one, *zip(*jobs, strict=True)):
                print(f"{r['cid']} {r['unit']}: {r.get('skipped') or f'{r["py"]:.2f} s'}", flush=True)
            return 0
        bad = 0
        for unit in us:
            results = list(
                pool.map(check, *zip(*caps, strict=True), [unit] * len(caps), [a.rows] * len(caps))
            )
            done = [r for r in results if "skipped" not in r]
            wrong = [r for r in done if r["diff"]]
            bad += len(wrong)
            for r in wrong:
                print(f"{unit} {r['cid']}: mismatch\n" + "\n".join(r["diff"]))
            py, rs = sum(r["py"] for r in done), sum(r["rs"] for r in done)
            n = sum(packets[r["cid"]] for r in done)
            verdict = "mismatch on" if wrong else "identical on"
            print(
                f"{unit}: {verdict} {len(wrong) or len(done)}/{len(done)} captures ({len(caps) - len(done)}"
                f" skipped), {n:,} packets; python {py:.2f} s, rust {rs:.2f} s, {py / max(rs, 1e-9):.1f}x",
                flush=True,
            )
        return 1 if bad else 0


def baseline(caps: list[tuple[Path, str]], us: list[str], packets: dict[str, int]) -> int:
    """Python's seconds per unit over the captures, alone and over the world-only walk, from the cache."""
    got = {(cid, u): cached(cid, u) or {} for _, cid in caps for u in {*us, "world"}}
    if missing := sorted({u for (_, u), s in got.items() if not s}):
        sys.exit(f"no cached reference for {', '.join(missing)} on some captures: run ref first")
    n = sum(packets[c] for _, c in caps)
    world = sum(got[cid, "world"]["seconds"] for _, cid in caps)
    print(
        f"{len(caps)} captures, {n:,} packets; world-only walk {world:.1f} s, {world / n * 1e6:.2f} us/packet"
    )
    print("| unit | seconds | over the world-only walk | us/packet |\n|---|---|---|---|")
    rows = sorted(((sum(got[cid, u]["seconds"] for _, cid in caps), u) for u in us), reverse=True)
    for s, u in rows:
        print(f"| {u} | {s:.1f} | {s - world:+.1f} | {s / n * 1e6:.2f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
