"""extractors_rs against the Python extractors: each Rust extractor declares what its Python class does, and
its rows on the fixtures hash to the Python pins in tests/expected."""

import hashlib
import json
from pathlib import Path

import extractors_rs
import pyarrow as pa
import pytest

from ffxi_extractors.extract import COMMON
from ffxi_extractors.extractors import ALL

TESTS = Path(__file__).parents[3] / "tests"
CAPTURES = ((TESTS / "data" / "memoria.xicap", "m"), (TESTS / "data" / "captain.xicap", "c"))
PYTHON = {x.name: x for x in ALL}
RUST = extractors_rs.extractors()


@pytest.mark.parametrize("r", RUST, ids=lambda r: r["name"])
def test_it_declares_what_python_does(r):
    x = PYTHON[r["name"]]
    assert r["version"] == x.version
    assert r["sparse"] == x.sparse
    assert set(r["reads"]) == set(x.reads)
    assert r["tables"] == [(t.name, [(c.name, c.type) for c in t.columns]) for t in x.tables]


@pytest.mark.parametrize("r", RUST, ids=lambda r: r["name"])
def test_its_rows_match_the_pins(r):
    x = PYTHON[r["name"]]
    got = {}
    for path, cid in CAPTURES:
        tables = extractors_rs.run(str(path), cid, [x.name])
        for t in x.tables:
            table = tables[t.name]
            assert table.schema == pa.schema([(c.name, c.type) for c in COMMON + t.columns])
            rows = json.dumps(table.to_pylist(), sort_keys=True, default=str).encode()
            got[f"{cid}/{t.name}"] = {"rows": table.num_rows, "sha256": hashlib.sha256(rows).hexdigest()}
    pin = TESTS / "expected" / f"{x.name}-v{x.version}.json"
    assert json.loads(pin.read_text()) == got


def test_world_alone_writes_nothing():
    assert extractors_rs.run(str(CAPTURES[0][0]), "m", ["world"]) == {}
