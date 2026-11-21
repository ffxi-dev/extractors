import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World

OUTCOME = {1: "won", 2: "error", 3: "lost"}  # 0x0D3 JudgeFlg; 0 is a lot or pass with the slot still open


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

    def __init__(self):
        self.seen: dict[tuple, dict] = {}  # entry -> its row
        self.open: dict[int, dict] = {}  # pool slot -> the row its lot result fills in

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x0D3:
            outcome = OUTCOME.get(f("JudgeFlg"))
            row = self.open.pop(f("TrophyItemIndex"), None) if outcome else None
            if row:
                row.update(outcome=outcome, winner_id=f("LootUniqueNo") or None,
                           winner_name=f("sLootName"), winning_lot=f("LootPoint"), settled_ms=p.ts_ms,
                           settled_idx=p.idx)  # fmt: skip
            return
        item = f("TrophyItemNo")
        if not item:
            return
        key = (f("TargetUniqueNo"), item, f("TrophyItemIndex"), f("StartTime"))
        if key in self.seen:
            if self.seen[key]["outcome"] is None:
                self.open[key[2]] = self.seen[key]
            return
        row = emit("drops", p, item_id=item, quantity=f("TrophyItemNum"), mob_id=key[0],
                   mob_index=f("TargetActIndex"), slot=key[2], start_time=key[3], gold=f("Gold"),
                   outcome=None, zone_id=world.zone)  # fmt: skip
        self.seen[key] = self.open[key[2]] = row
