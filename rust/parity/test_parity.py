"""The harness's own check: `uv run pytest rust/parity`."""

import parity
import pyarrow as pa


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
