"""The archive-wide record of the Rust switch (rust-extractors 1.4): every unit's rows on every capture, by
v1.14.4's Python and by v2.0.0's Rust, as a row count and a hash per (table, capture). README.md says how it
ran. In an image of either tag, with this file mounted:

    archive.py list <mirror> > captures.txt          # <id> <file>, the newest file of each id, largest first
    archive.py python|rust <out> < captures.txt      # <out>/<id>.json for each capture not yet there
    archive.py compare <python out> <rust out>       # what differs; exit 1 if anything does

python is v1.14.4's walk with every extractor and the decoder's tables in one pass, as its index.run wrote
Scholar's rows; rust is extractors_rs.run with the same units. A row is parity.py's canonical line, a JSON
list of its values in column order. A table's hash is the sum, mod 2**128, of its rows' md5s, so the order
rows come in does not count and no row is kept. Tables with no rows are left out."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


class Sums:
    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}

    def add(self, name: str, table) -> None:
        if not table.num_rows:
            return
        e = self.tables.setdefault(
            name, {"rows": 0, "sum": 0, "schema": [f"{f.name} {f.type}" for f in table.schema]}
        )
        if [f"{f.name} {f.type}" for f in table.schema] != e["schema"]:
            e["mixed"] = True
        for b in table.to_batches(max_chunksize=65536):
            for r in zip(*(c.to_pylist() for c in b.columns), strict=True):
                e["sum"] += int.from_bytes(
                    hashlib.md5(json.dumps(r, ensure_ascii=False, default=str).encode()).digest()
                )
            e["rows"] += b.num_rows

    def out(self) -> dict:
        return {
            n: {
                "rows": e["rows"],
                "hash": f"{e['sum'] % 2**128:032x}",
                "schema": e["schema"],
                **({"mixed": True} if e.get("mixed") else {}),
            }
            for n, e in sorted(self.tables.items())
        }


def python(path: str, cid: str) -> dict:
    from ffxi_extractors.capture import read
    from ffxi_extractors.extractors import ALL
    from ffxi_extractors.index import walk  # type: ignore[attr-defined]

    s = Sums()
    cap = read(path, cid, True)
    stats, world, sinks = walk(cap, [x() for x in ALL], s.add, True)
    for sink in sinks:
        sink.flush(everything=True)
    for name, t in stats.tables(None, None, cap.character_id or world.character_id).items():
        s.add(name, t)
    return s.out()


def rust(path: str, cid: str) -> dict:
    import extractors_rs  # type: ignore[import-not-found]

    from ffxi_extractors.capture import read
    from ffxi_extractors.extractors import ALL

    read(path, cid, True)  # raises Skipped as Python's walk does
    s = Sums()
    for name, t in extractors_rs.run(path, cid, ["decode", *(x.name for x in ALL)]).items():
        s.add(name, t)
    return s.out()


def run(side: str, out: Path) -> int:
    from ffxi_extractors.capture import Skipped

    f = {"python": python, "rust": rust}[side]
    out.mkdir(parents=True, exist_ok=True)
    for ln in sys.stdin:
        cid, path = ln.split()
        dest = out / f"{cid}.json"
        if dest.exists():
            continue
        try:
            got = {"file": Path(path).name, "tables": f(path, cid)}
        except Skipped as e:
            got = {"file": Path(path).name, "skipped": str(e)}
        except Exception as e:  # noqa: BLE001 - one capture's failure is a result, not the end of the run
            got = {"file": Path(path).name, "error": f"{type(e).__name__}: {e}"}
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}")
        tmp.write_text(json.dumps(got))
        tmp.replace(dest)
        print(cid, flush=True)
    return 0


def listing(mirror: Path) -> int:
    files: dict[str, Path] = {}
    for f in sorted(mirror.glob("*.xicap"), key=lambda f: f.stat().st_mtime):
        files[f.name.split(".")[0]] = f
    for cid, f in sorted(files.items(), key=lambda kv: -kv[1].stat().st_size):
        print(cid, f)
    return 0


def compare(py: Path, rs: Path) -> int:
    """Each capture either side lacks, each skipped by one side only, and each table whose rows, hash, or
    schema differ. Then the totals."""
    ids = sorted({p.stem for p in py.glob("*.json")} | {p.stem for p in rs.glob("*.json")})
    bad, pairs, rows, skipped = [], 0, 0, 0
    for cid in ids:
        a, b = (
            json.loads(p.read_text()) if p.exists() else None
            for p in (py / f"{cid}.json", rs / f"{cid}.json")
        )
        if a is None or b is None:
            bad.append(f"{cid}: no {'python' if a is None else 'rust'} result")
            continue
        if a["file"] != b["file"]:
            bad.append(f"{cid}: python read {a['file']}, rust {b['file']}")
            continue
        if "error" in a or "error" in b:
            bad.append(f"{cid}: python {a.get('error', 'ran')}, rust {b.get('error', 'ran')}")
            continue
        if "skipped" in a or "skipped" in b:
            if ("skipped" in a) != ("skipped" in b):
                bad.append(f"{cid}: skipped by {'python' if 'skipped' in a else 'rust'} only")
            skipped += 1
            continue
        ta, tb = a["tables"], b["tables"]
        for t in sorted(set(ta) | set(tb)):
            x, y = ta.get(t), tb.get(t)
            if x != y:
                bad.append(
                    f"{cid} {t}: python {x and (x['rows'], x['hash'])}, rust {y and (y['rows'], y['hash'])}"
                    + (" (schema differs)" if x and y and x["schema"] != y["schema"] else "")
                )
            elif x:
                pairs += 1
                rows += x["rows"]
    print("\n".join(bad))
    print(
        f"{len(ids)} captures ({skipped} skipped by both): {pairs:,} (table, capture) pairs,"
        f" {rows:,} rows the same; {len(bad)} differ"
    )
    return 1 if bad else 0


def main() -> int:
    cmd, *args = sys.argv[1:]
    if cmd == "list":
        return listing(Path(args[0]))
    if cmd == "compare":
        return compare(Path(args[0]), Path(args[1]))
    return run(cmd, Path(args[0]))


if __name__ == "__main__":
    sys.exit(main())
