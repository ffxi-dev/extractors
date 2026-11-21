import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World
from ffxi_extractors.extractors.items.gathering import PLACE, WINDOW_MS, Held, place


class Digs(Extractor):
    """The character's chocobo digs. The client asks with 0x063 after the dig's animation (0x02F, which the
    zone sends for anyone's dig and which carries no result). The zone answers in its own dialog:
    'Obtained: <item>' is a 0x02A whose first number is the item, among other 0x02A lines (the dig's hints,
    the conquest points a cache gives) whose numbers are not items; 'You dig and you dig, but find nothing'
    is a 0x036. Which message is which differs by zone, so the item found is the one a 0x02A named that also
    entered the inventory."""

    name = "digs"
    version = 1
    doc = "Each chocobo dig the character made: where, in what weather and Vana'diel time, and what it found."
    reads = Held.reads | {(0, 0x00A), (1, 0x063), (0, 0x02A)}
    tables = (
        Table(
            "digs",
            "One row per dig the character asked for (0x063). A dig whose item the inventory could not take"
            " (thrown away) reads as nothing found.",
            (
                *PLACE,
                Column(
                    "item_id",
                    pa.int32(),
                    "What it found: the item an 'Obtained' message (0x02A) named and the inventory gained"
                    " under 3 s after; none when it found nothing. A raised chocobo's second find is left"
                    " out.",
                ),
            ),
        ),
    )

    def __init__(self):
        self.held = Held()
        self.open: dict | None = None  # the last dig: its row, its window's end, items named and gained

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        key = (p.direction, p.opcode)
        if key == (0, 0x00A):
            self.open = None
        elif key == (1, 0x063):
            row = emit("digs", p, **place(p, world), item_id=None)
            self.open = {"row": row, "end": p.ts_ms + WINDOW_MS, "named": [], "gained": set()}
        elif key == (0, 0x02A):
            me = world.character_id
            if (dig := self._live(p)) and (not me or f("UniqueNo") == me):
                dig["named"].append(f("num[0]"))
                _settle(dig)
        elif (item := self.held.gained(p, f)) is not None and (dig := self._live(p)):
            dig["gained"].add(item)
            _settle(dig)

    def _live(self, p) -> dict | None:
        """The last dig, while p falls in its window."""
        return self.open if self.open is not None and p.ts_ms <= self.open["end"] else None


def _settle(dig: dict) -> None:
    """The dig's item: the first one its messages named that the inventory gained."""
    found = [i for i in dig["named"] if i in dig["gained"]]
    if found and dig["row"]["item_id"] is None:
        dig["row"]["item_id"] = found[0]
