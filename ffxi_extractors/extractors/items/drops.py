import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Drops(Extractor):
    name = "drops"
    version = 3
    doc = "Each item that entered the treasure pool, and the mob it came from."
    reads = frozenset({(0, 0x0D2), (0, 0x0D3)})
    tables = (
        Table(
            "drops",
            "One row per treasure pool entry (0x0D2). The pool is sent again at each zone-in; an entry seen"
            " before, with the same mob, item, slot, and start time, gives no new row. The lot result (0x0D3)"
            " that settles the slot fills in who won.",
            (
                Column("item_id", pa.int32(), "The item; its name is in item_names."),
                Column("quantity", pa.int32(), "How many."),
                Column("mob_id", pa.int64(), "The mob (or chest) the item came from."),
                Column("mob_index", pa.int32(), "Its index in the zone."),
                Column("slot", pa.int32(), "The pool slot, 0 to 9."),
                Column(
                    "start_time", pa.int64(), "When the item entered the pool, in the server's Unix seconds."
                ),
                Column("gold", pa.int32(), "Gold, as the packet sends it."),
                Column(
                    "outcome",
                    pa.string(),
                    "won, error (the winner could not take it, or nobody lotted), or lost; none if the"
                    " capture never saw the slot settled.",
                ),
                Column("winner_id", pa.int64(), "Who won it, or for an error who could not take it."),
                Column("winner_name", pa.string(), "Their name, as the lot result sends it."),
                Column("winning_lot", pa.int32(), "The winning lot; 0 when nobody lotted."),
                Column("settled_ms", pa.int64(), "When the lot result came, Unix milliseconds UTC."),
                Column("settled_idx", pa.int64(), "The lot result's packet."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
