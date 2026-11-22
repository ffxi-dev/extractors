import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.link import KINDS, LINK_MS


class Obtained(Extractor):
    name = "obtained"
    # 2: a zone-in that plays a cutscene starts the event its reward follows; 3: taking an item back out of
    # the recycle bin is no gain
    version = 3
    doc = "Items the character received, whatever gave them: a quest, a trade, a shop, a synthesis, the pool."
    reads = frozenset(KINDS) | {(0, op) for op in (0x00A, 0x01D, 0x01E, 0x01F, 0x020, 0x0D2, 0x0D3)}
    tables = (
        Table(
            "obtained",
            "One row per item the character's containers gained (0x01E, 0x01F, 0x020): its count across"
            " every container went up over a run of changes, each under 1 s after the last, so a move between"
            " slots or containers nets out. After a zone-in the server sends each container whole, and"
            " 0x01D's Flags marks it done; a slot first seen before then is what the character held and gives"
            " no row, so a capture's rows start at its first zone-in. Gil is left out. The recycle bin counts"
            " as a container, so a drop into it and a take back out of it each net out.",
            (
                Column("item_id", pa.int32(), "The item; its name is in item_names."),
                Column("quantity", pa.int32(), "How many more."),
                Column("container", pa.int32(), "Where the first of them landed: 0 is the inventory."),
                Column(
                    "source",
                    pa.string(),
                    "pool when the character had just won it from the treasure pool (0x0D3), and drops has"
                    " its row; null otherwise.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
                Column(
                    "event_idx",
                    pa.int64(),
                    f"The start of the event it follows, in events: the open one, or one that ended under"
                    f" {LINK_MS // 1000} s before. Its npc_id is the NPC that gave it.",
                ),
            ),
        ),
    )
