"""Decodes a batch of a capture's game packets a whole opcode at a time with packets' decoder, only the
opcodes asked for, and gives each packet's fields by path to the world and the extractors."""

from __future__ import annotations

from collections import defaultdict
from importlib.metadata import version

import numpy as np
from ffxi_packets import Decoder

from ffxi_extractors.capture import Fields, Packet
from ffxi_extractors.world import WORLD_VERSION

# Every unit's rows depend on the decoder and on what the world keeps: a change to either re-runs them all.
DECODER_VERSION = f"{version('ffxi-packets')}+world{WORLD_VERSION}"


def _none(path: str):
    return None


class Decoded:
    """A batch of packets, with the fields of those whose (direction, opcode) is in keys."""

    def __init__(self, decoder: Decoder, client_version: str, packets: list[Packet], keys):
        groups: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, p in enumerate(packets):
            if p.channel == 0 and (p.direction, p.opcode) in keys:
                groups[(p.direction, p.opcode)].append(i)
        self.cols: dict[tuple[int, int], dict] = {}
        self._lists: dict[tuple[int, int], dict[str, list]] = {}  # the columns read so far, as lists
        self._row = np.full(len(packets), -1, dtype=np.int64)
        for key, at in groups.items():
            self.cols[key] = decoder.decode(client_version, *key, [packets[i].data for i in at])
            self._row[at] = np.arange(len(at))

    def fields(self, i: int, p: Packet) -> Fields:
        """A getter for the batch's packet i by path: f("UniqueNo"), f("SendFlg.Position"). A field the
        packet does not hold, or that has no value, is None."""
        key = (p.direction, p.opcode)
        cols = self.cols.get(key) if p.channel == 0 else None
        if not cols:
            return _none
        row, lists = int(self._row[i]), self._lists.setdefault(key, {})

        def f(path: str):
            got = lists.get(path)
            if got is None:
                col = cols.get(path)
                if col is None:
                    return None
                got = lists[path] = _plain(col)
            return got[row]

        return f


def _plain(col) -> list:
    """A decoded column as a list of Python values, None where masked: a field read is then a list index, not
    a numpy element read. Reading every field of every packet that way took half of a capture's time."""
    out = col.tolist()  # a masked array's tolist gives None where masked
    if col.dtype == object:
        out = [v.item() if isinstance(v, np.generic) else v for v in out]
    return out
