"""ffxi-extractors: index captures into ClickHouse, with retail-resources' names."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import resources, store
from .capture import Skipped
from .index import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ffxi-extractors")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("index", help="index captures into FFXI_CLICKHOUSE, else compose.yaml's ClickHouse")
    i.add_argument("captures", nargs="+", type=Path, help=".xicap files")
    i.add_argument(
        "--names",
        type=Path,
        default=Path("var/names"),
        help="where retail-resources is mirrored; delete it to fetch newer releases",
    )
    i.add_argument("--no-names", action="store_true", help="leave names out: no download")
    a = p.parse_args(argv)
    con = store.connect(create=True)
    store.setup(con)
    names = None if a.no_names else a.names
    if names:
        if not resources.releases(names):
            resources.sync(names)
        if resources.lacking(con, names):
            resources.load(con, names)
    for f in a.captures:
        try:
            rows = run(con, f, names=names)
        except Skipped as e:
            print(f"{f}: {e}", file=sys.stderr)
            continue
        print(f"{f.stem}: {sum(rows.values()):,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
