"""extractors_rs against the Python declarations: each Rust extractor declares what its Python class does,
every Python class has one, and the pinned tags agree."""

import tomllib
from importlib.metadata import version
from pathlib import Path

import extractors_rs
import ffxi_packets
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
    """xicap's tag for Python's reader and Rust's; packets' for decode.PACKETS and the one installed."""
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    build = (ROOT / "rust" / "xc-core" / "build.rs").read_text()
    assert f'XICAP_TAG: &str = "{sources["xicap"]["tag"]}"' in build
    assert sources["ffxi-packets"]["tag"] == f"v{PACKETS}"
    assert version("ffxi-packets") == PACKETS


def test_xc_decode_holds_the_packets_release():
    """rust/xc-decode/packets holds the pinned packets release's schemas byte for byte, not a hand edit.
    Line endings aside: a Windows checkout writes CRLF."""
    release = Path(ffxi_packets.__file__).parent / "schemas"
    copy = ROOT / "rust" / "xc-decode" / "packets"
    assert sorted(f.name for f in copy.glob("*.json")) == sorted(f.name for f in release.glob("*.json"))

    def read(f: Path) -> bytes:
        return f.read_bytes().replace(b"\r\n", b"\n")

    for f in copy.glob("*.json"):
        assert read(f) == read(release / f.name), f"{f.name} is not packets v{PACKETS}'s"


def test_world_alone_writes_nothing():
    assert extractors_rs.run(str(MEMORIA), "m", ["world"]) == {}
