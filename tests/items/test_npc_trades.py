"""Trades to NPCs: the extractor on decoded fields, the timeline's marks, and the catalog."""

from conftest import drive

from ffxi_extractors.extractors.items.trades import Trades

ZONE = 245
NPC = 0x0100_0000 | (ZONE << 12) | 100
OTHER = NPC + 1
STEW, ORE = 4569, 643
C2S = 1


def held(index, item, count):
    return 0x020, {"Category": 0, "ItemIndex": index, "ItemNo": item, "ItemNum": count}


def trade(npc, *slots):
    """slots: (inventory slot, count); slot 0 is gil."""
    fields = {"UniqueNo": npc, "ActIndex": npc & 0xFFF, "ItemNum": len(slots)}
    for i, (slot, n) in enumerate(slots):
        fields |= {f"PropertyItemIndexTbl[{i}]": slot, f"ItemNumTbl[{i}]": n}
    return 0x036, fields


def trades(*after, times):
    steps = [(0x00A, {"ZoneNo": ZONE}), held(5, STEW, 12), held(9, ORE, 3), *after]
    directions = [C2S if op == 0x036 and "ItemNum" in d else 0 for op, d in steps]
    return drive(Trades, *steps, times=[0, 0, 0, *times], directions=directions)["trades"]


def test_a_trade_names_its_items_from_the_inventory_and_takes_the_npcs_answer():
    rows = trades(
        trade(NPC, (5, 3), (0, 1000)),
        (0x034, {"UniqueNo": NPC, "EventPara": 10}),  # onTrade's startEvent
        trade(NPC, (9, 1), (7, 2)),  # slot 7 the capture never named
        (0x036, {"UniqueNo": OTHER, "MesNum": 0x8000 | 6000}),  # another NPC: no answer
        (0x036, {"UniqueNo": NPC, "MesNum": 0x8000 | 7000}),
        trade(NPC, (5, 1)),
        (0x034, {"UniqueNo": NPC, "EventPara": 11}),  # too late: 6 s after
        times=[1000, 2000, 10_000, 10_500, 11_000, 20_000, 26_000],
    )
    got = [(r["item_ids"], r["quantities"], r["slots"], r["gil"], r["event_id"], r["message"]) for r in rows]
    assert got == [
        ([STEW], [3], [5], 1000, 10, None),
        ([ORE, None], [1, 2], [9, 7], None, None, 7000),
        ([STEW], [1], [5], None, None, None),
    ]
    assert (rows[0]["npc_id"], rows[0]["zone_id"], rows[0]["event_idx"]) == (NPC, ZONE, 4)
