"""A sparse extractor writes rows only from its reads outside the world's: Scholar passes by a capture that
holds none of them on a re-run, so one that wrote rows without them would lose those rows."""

import pytest
from conftest import CAPTAIN, MEMORIA

from ffxi_extractors.capture import read
from ffxi_extractors.extractors import ALL
from ffxi_extractors.index import walk
from ffxi_extractors.world import WORLD


def without(path, ops):
    """The capture with every game packet of ops left out."""
    cap = read(path)
    batches = cap.batches
    keep = lambda p: p.channel or (p.direction, p.opcode) not in ops  # noqa: E731
    cap.batches = lambda *a: ([p for p in b if keep(p)] for b in batches(*a))
    return cap


@pytest.mark.parametrize("x", [x for x in ALL if x.sparse], ids=lambda x: x.name)
def test_a_sparse_extractor_writes_nothing_from_a_capture_without_its_own_packets(x):
    ops = x.reads - WORLD
    assert ops, f"{x.name} reads only the world's packets: it is not sparse"
    for path in (MEMORIA, CAPTAIN):
        _, _, (sink,) = walk(without(path, ops), [x()])
        assert {t: a.num_rows for t, a in sink.arrow().items() if a.num_rows} == {}, path
