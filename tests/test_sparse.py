"""A sparse extractor writes rows only from its reads outside the world's: Scholar passes by a capture that
holds none of them on a re-run, so one that wrote rows without them would lose those rows."""

import pytest
from conftest import CAPTAIN, MEMORIA, packets, walked

from ffxi_extractors.extractors import ALL
from ffxi_extractors.world import WORLD


@pytest.mark.parametrize("x", [x for x in ALL if x.sparse], ids=lambda x: x.name)
def test_a_sparse_extractor_writes_nothing_from_a_capture_without_its_own_packets(x):
    ops = x.reads - WORLD
    assert ops, f"{x.name} reads only the world's packets: it is not sparse"
    for path in (MEMORIA, CAPTAIN):
        kept = [p for p in packets(path) if (p[1], p[2]) not in ops]
        assert {t: len(r) for t, r in walked(x, kept).items() if r} == {}, path
