"""Each extractor's and derived fact's output on the fixtures is pinned to its version: change the output
without bumping the version and this fails, so Scholar never skips a re-run it needed. After a bump, write
the new expected output with BLESS=1 and commit it."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from conftest import CAPTAIN, MEMORIA
from fill import records

from ffxi_extractors.capture import read
from ffxi_extractors.extractors import ALL
from ffxi_extractors.facts import DERIVED
from ffxi_extractors.index import walk

EXPECTED = Path(__file__).parent / "expected"
CAPTURES = ((MEMORIA, "m"), (CAPTAIN, "c"))
# A derived fact's rows, in a fixed order.
ORDER = {
    "bestiary_fights": "idx, mob_id",
    "bestiary_mobs": "zone_id, mob_name, model",
    "melee": "idx, target_id, swing",
    "tp_uses": "idx",
    "steals": "idx",
    "mob_events": "idx",
    "exp_kills": "idx",
    "bestiary_looks": "idx",
    "aggro": "idx",
    "aggro_passes": "idx, mob_id",
    "npc_events": "idx",
    "npc_trades": "idx",
    "npc_shops": "idx, item_id, price",
}
# bestiary_mobs holds aggregate states: compare what they finalise to.
KEY = "zone_id, mob_name, model, capture_id"
FINAL = {"bestiary_mobs": f"{KEY}, * EXCEPT ({KEY}, at) APPLY finalizeAggregation"}


@pytest.fixture(scope="module")
def walked():
    """Each extractor's tables by capture, from one walk of each capture with every extractor."""
    out = {}
    for path, cid in CAPTURES:
        _, _, sinks = walk(read(path, cid), [x() for x in ALL])
        for x, sink in zip(ALL, sinks, strict=True):
            out[cid, x.name] = {name: t.to_pylist() for name, t in sink.arrow().items()}
    return out


def digest(x, con, walked) -> dict:
    out = {}
    for _, cid in CAPTURES:
        if x in DERIVED:
            table = x.tables[0].name
            cols = FINAL.get(table, "*")
            where = f"capture_id = '{cid}' ORDER BY {ORDER[table]}"
            rows = records(con, f"SELECT {cols} FROM {table} WHERE {where}")
            tables = {table: rows}
        else:
            tables = walked[cid, x.name]
        for name, rows in tables.items():
            data = json.dumps(rows, sort_keys=True, default=str).encode()
            out[f"{cid}/{name}"] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
    return out


@pytest.mark.parametrize("x", (*ALL, *DERIVED), ids=lambda x: x.name)
def test_output_matches_its_version(x, both, walked):
    path = EXPECTED / f"{x.name}-v{x.version}.json"
    got = digest(x, both, walked)
    if os.environ.get("BLESS"):
        EXPECTED.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert path.exists(), f"no expected output for {x.name} v{x.version}: run with BLESS=1"
    assert json.loads(path.read_text()) == got, f"{x.name}'s output changed: bump its version"
