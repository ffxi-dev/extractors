import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.link import KINDS, LINK_MS


class KeyItems(Extractor):
    """Ported from captain's kitrack, with the event each change follows, as log_changes links them."""

    name = "keyitems"
    version = 4
    doc = "Key items the character gained or lost, where, and the event that gave or took each."
    # The character's position is the world's; the event comes from the event packets events reads.
    reads = frozenset(KINDS) | {(0, 0x055), (0, 0x00A)}
    tables = (
        Table(
            "keyitems",
            "One row per key item gained or lost (0x055). The first list of each table of 512 key items in a"
            " capture is the starting state and gives no rows, as in kitrack, unless it follows an event"
            " whose message (0x02A) named one of its key items, with no zone-in since: it was gained.",
            (
                Column("key_item_id", pa.int32(), "The key item; its name is in keyitem_names."),
                Column("change", pa.string(), "gained or lost."),
                Column("x", pa.float32(), "The character's last position, as XiPackets names it."),
                Column("y", pa.float32(), "Position."),
                Column("z", pa.float32(), "Position."),
                Column("zone_id", pa.int32(), "The zone."),
                Column(
                    "event_idx",
                    pa.int64(),
                    f"The start of the event this change follows, in events: the open one, or one that ended"
                    f" under {LINK_MS // 1000} s before. An event from before a zone-in follows only into the"
                    " list of each table the zone-in sends. Its npc_id is the NPC that gave or took it.",
                ),
                Column("event_id", pa.int32(), "That event's id."),
            ),
        ),
    )
