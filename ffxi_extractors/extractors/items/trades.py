import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

ANSWER_MS = 5000  # the NPC's event or message this soon after a trade answers it


class Trades(Extractor):
    """The character's trades to NPCs. The client sends 0x036 with up to ten inventory slots and a count for
    each; it names no item, so the item is the one the world's inventory holds in that slot. LSB's onTrade
    answers with an event or a message, which the NPC sends under ANSWER_MS after."""

    name = "trades"
    version = 1
    doc = "Each trade the character made to an NPC: the items and gil handed over, and how the NPC answered."
    reads = frozenset({(1, 0x036), (0, 0x032), (0, 0x033), (0, 0x034), (0, 0x036), (0, 0x02A)})
    tables = (
        Table(
            "trades",
            "One row per trade to an NPC (c2s 0x036), with the event or message the NPC answered with.",
            (
                Column("npc_id", pa.int64(), "UniqueNo: the NPC traded to."),
                Column("npc_index", pa.int32(), "ActIndex."),
                Column(
                    "item_ids",
                    pa.list_(pa.int32()),
                    "Each item handed over, in the trade window's order: the one the main inventory held in"
                    " its slot (0x01F, 0x020), or none where the capture never said. Gil is apart.",
                ),
                Column("quantities", pa.list_(pa.int64()), "How many of each."),
                Column("slots", pa.list_(pa.int32()), "Each item's main inventory slot."),
                Column("gil", pa.int64(), "The gil handed over (slot 0), if any."),
                Column(
                    "event_id",
                    pa.int32(),
                    f"The event the NPC started under {ANSWER_MS // 1000} s after: onTrade's startEvent.",
                ),
                Column("event_idx", pa.int64(), "That event's start, in events."),
                Column(
                    "message",
                    pa.int32(),
                    f"The first message the NPC sent under {ANSWER_MS // 1000} s after (0x036, 0x02A), top"
                    " bit cleared, as events keeps it.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
