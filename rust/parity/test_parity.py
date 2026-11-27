"""The harness's own check: `uv run pytest rust/parity`."""

import json

import archive
import parity
import pyarrow as pa
import pytest


def test_a_changed_row_shows_each_way(tmp_path, monkeypatch):
    monkeypatch.setattr(parity, "REF", tmp_path)
    monkeypatch.setattr(
        parity, "python", lambda *_: {"t": pa.table({"a": [2, 1, 3], "b": [0.1, None, 1e-7]})}
    )
    ref = parity.reference(tmp_path / "x.xicap", "c", "zones")
    assert parity.cached("c", "zones") == ref
    tabs, rows = parity.summary({"t": pa.table({"a": [1, 2, 3], "b": [None, 0.1, 1e-7]})})
    assert tabs == ref["tables"]  # the order rows come in does not count
    tabs, rows = parity.summary({"t": pa.table({"a": [1, 2, 4], "b": [None, 0.1, 1e-7]})})
    assert parity.diff("c", "zones", ref, tabs, rows, 5) == [
        "  t: rows python 3, rust 3",
        "    columns: a, b",
        "    - [3, 1e-07]",
        "    + [4, 1e-07]",
    ]
    tabs, rows = parity.summary(
        {"t": pa.table({"a": pa.array([1, 2, 3], pa.int32()), "b": [None, 0.1, 1e-7]})}
    )
    assert parity.diff("c", "zones", ref, tabs, rows, 5) == [
        "  t: rows python 3, rust 3",
        "    schema python: a int64, b double",
        "    schema rust:   a int32, b double",
    ]


def test_the_sample_is_read_at_its_sha256(tmp_path, monkeypatch):
    """A live capture grows a new file in the mirror; the sample reads the one it was pinned at, or stops."""
    monkeypatch.setattr(parity, "MIRROR", tmp_path)
    (i, sha), *_ = parity.sample()
    (tmp_path / f"{i}.{'0' * 64}.xicap").write_bytes(b"newer")
    with pytest.raises(SystemExit, match=sha):
        parity.captures("sample")
    (tmp_path / f"{i}.{sha}.xicap").write_bytes(b"pinned")
    monkeypatch.setattr(parity, "sample", lambda: [(i, sha)])
    assert parity.captures("sample") == [(tmp_path / f"{i}.{sha}.xicap", i)]


def test_archive_hashes_rows_in_any_order_and_compare_names_what_differs(tmp_path, capsys):
    a, b = archive.Sums(), archive.Sums()
    a.add("t", pa.table({"x": [1, 2], "y": ["a", None]}))
    a.add("t", pa.table({"x": [3], "y": ["c"]}))
    a.add("empty", pa.table({"x": pa.array([], pa.int64())}))
    b.add("t", pa.table({"x": [3, 1, 2], "y": ["c", "a", None]}))
    assert a.out() == b.out() and set(a.out()) == {"t"}
    for side, sums in (("py", a), ("rs", b)):
        (tmp_path / side).mkdir()
        (tmp_path / side / "c.json").write_text(json.dumps({"file": "c.x.xicap", "tables": sums.out()}))
    assert archive.compare(tmp_path / "py", tmp_path / "rs") == 0
    b.add("t", pa.table({"x": [4], "y": ["d"]}))
    (tmp_path / "rs" / "c.json").write_text(json.dumps({"file": "c.x.xicap", "tables": b.out()}))
    assert archive.compare(tmp_path / "py", tmp_path / "rs") == 1
    assert "c t: python (3, " in capsys.readouterr().out
