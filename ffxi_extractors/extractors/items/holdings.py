import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World


class Holdings(Extractor):
    """What the character holds, a row each time one of its bag slots changes. Every zone-in lists each bag
    again; a slot listed as it was gives no row."""

    name = "holdings"
    version = 1
    doc = "Each change to what the recording character holds, by bag and slot."
    reads = frozenset({(0, 0x01E), (0, 0x01F), (0, 0x020)})
    tables = (
        Table(
            "holdings",
            "One row per change to a slot of the character's bags (0x01E, 0x01F, 0x020): the item now in it,"
            " or none once it empties. A zone-in lists every bag the character can reach, so after the"
            " capture's first zone-in a slot with no row is empty.",
            (
                Column(
                    "container", pa.int32(), "The bag: 0 inventory, 1 Mog Safe, 2 Storage, 17 Recycle Bin."
                ),
                Column("item_index", pa.int32(), "The slot in it."),
                Column("item_id", pa.int32(), "The item now in the slot; None once it empties."),
            ),
        ),
    )

    def __init__(self):
        self.slots: dict[tuple, int | None] = {}  # (bag, slot) -> the item last written

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        key = (f("Category"), f("ItemIndex"))
        if None in key:
            return
        if not f("ItemNum"):
            item = None
        elif p.opcode == 0x01E:  # a quantity alone: the slot keeps its item
            return
        else:
            item = f("ItemNo")
        if key in self.slots and self.slots[key] == item:
            return
        self.slots[key] = item
        emit("holdings", p, container=key[0], item_index=key[1], item_id=item)
