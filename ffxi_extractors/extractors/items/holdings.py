import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Holdings(Extractor):
    """What the character holds, a row each time one of its bag slots changes. Every zone-in lists each bag
    again; a slot listed as it was gives no row."""

    name = "holdings"
    version = 1
    doc = "Each change to what the recording character holds, by bag and slot."
    reads = frozenset({(0, 0x01E), (0, 0x01F), (0, 0x020)})
    sparse = False  # it reads only the world's packets
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
