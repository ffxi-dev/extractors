"""extractors_rs against the Python declarations: each Rust extractor declares what its Python class does,
every Python class has one, and the pinned tags agree."""

import re
import tomllib
from pathlib import Path

import extractors_rs
import pyarrow as pa
import pytest
from conftest import MEMORIA

from ffxi_extractors.decode import PACKETS
from ffxi_extractors.extract import COMMON
from ffxi_extractors.extractors import ALL

ROOT = Path(__file__).parents[1]
PYTHON = {x.name: x for x in ALL}
RUST = extractors_rs.extractors()


@pytest.mark.parametrize("r", RUST, ids=lambda r: r["name"])
def test_it_declares_what_python_does(r):
    x = PYTHON[r["name"]]
    assert r["version"] == x.version
    assert r["sparse"] == x.sparse
    assert set(r["reads"]) == set(x.reads)
    assert r["tables"] == [(t.name, [(c.name, c.type) for c in t.columns]) for t in x.tables]


def test_every_extractor_is_in_rust():
    assert {r["name"] for r in RUST} == set(PYTHON)


def test_its_tables_are_typed_as_declared():
    tables = extractors_rs.run(str(MEMORIA), "m", list(PYTHON))
    for x in ALL:
        for t in x.tables:
            assert tables[t.name].schema == pa.schema([(c.name, c.type) for c in COMMON + t.columns]), t.name


def test_the_pinned_tags_agree():
    """xicap's tag for the Python reader and the Rust one; packets' for decode.PACKETS and xc-decode."""
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    build = (ROOT / "rust" / "xc-core" / "build.rs").read_text()
    assert f'XICAP_TAG: &str = "{sources["xicap"]["tag"]}"' in build
    readme = (ROOT / "rust" / "xc-decode" / "README.md").read_text()
    assert re.search(rf"tag v{re.escape(PACKETS)}\b", readme)


def test_world_alone_writes_nothing():
    assert extractors_rs.run(str(MEMORIA), "m", ["world"]) == {}
