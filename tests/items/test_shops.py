"""NPC and guild shops: the extractor on decoded fields, the timeline's marks, and the catalog."""

from conftest import drive

from ffxi_extractors.extractors.items.shops import Shops, hours

ZONE = 235  # Bastok Markets
NPC = 0x0100_0000 | (ZONE << 12) | 0x10C
GUILD = NPC + 1
STEW, ORE, INGOT = 4569, 644, 790
C2S = 1


def talk(npc):
    return 0x01A, {"UniqueNo": npc, "ActIndex": npc & 0xFFF, "ActionID": 0}


def shop_list(*items, offset=0):
    fields = {"ShopItemOffsetIndex": offset}
    for i, (index, item, price) in enumerate(items):
        t = f"ShopItemTbl[{i}]."
        fields |= {t + "ItemNo": item, t + "ItemPrice": price, t + "ShopIndex": index, t + "Skill": 0}
    return 0x03C, fields


def guild_list(stat, *items):
    fields = {"Stat": stat, "Count": len(items)}
    for i, (item, count, most, price) in enumerate(items):
        fields |= {f"List[{i}].ItemNo": item, f"List[{i}].Count": count, f"List[{i}].Max": most,
                   f"List[{i}].Price": price}  # fmt: skip
    return 0x083, fields


def test_guild_hours_come_only_with_a_closed_guild():
    assert hours(1, 0x807FFF00) == (8, 23)  # Bastok's smiths: 8:00 to 23:00, the client not told
    assert hours(1, 0x000FFFE0) == (5, 20)
    assert hours(0, 261379) == (None, None)  # open: Time is whatever the buffer held
    assert hours(1, 0b1011 << 8) == (None, None)  # no run of hours


def test_a_shop_and_a_guild_with_the_characters_standing_and_purchases():
    steps = [
        (0x00A, {"ZoneNo": ZONE}),
        (0x061, {"statusdata.nation": 1, "statusdata.rank": 8}),  # Bastok, rank 8
        (0x05E, {"Conquest.Balance": 0b11_10_01}),  # San d'Oria 1st, Bastok 2nd, Windurst 3rd
        talk(NPC),
        (0x03E, {"ShopListNum": 2}),
        shop_list((0, STEW, 60), (1, ORE, 200)),
        (0x083, {"ShopItemIndex": 1, "ItemNum": 12}),  # the character buys 12 ore
        (0x03F, {"ShopItemIndex": 1, "BuyState": 1, "Count": 12}),
        talk(GUILD),
        (0x086, {"Stat": 1, "Time": 0x007FFF00}),
        guild_list(0x40, (INGOT, 30, 80, 8000)),  # a list in two packets
        guild_list(0x81, (ORE, 5, 40, 210)),
        (0x0AA, {"ItemNo": INGOT, "ItemNum": 10}),
        (0x082, {"ItemNo": INGOT, "Count": 20, "Trade": 10}),
    ]
    c2s = {(0x01A, "ActionID"), (0x083, "ShopItemIndex"), (0x0AA, "ItemNum")}
    directions = [C2S if any(op == o and k in d for o, k in c2s) and op != 0x03F else 0 for op, d in steps]
    got = drive(Shops, *steps, directions=directions)
    keys = ["kind", "npc_id", "list_idx", "item_id", "price", "stock", "max", "nation", "nation_rank"]
    keys += ["conquest_rank"]
    assert [tuple(r.get(k) for k in keys) for r in got["shop_items"]] == [
        ("shop", NPC, 4, STEW, 60, None, None, "Bastok", 8, 2),
        ("shop", NPC, 4, ORE, 200, None, None, "Bastok", 8, 2),
        ("guild_sells", GUILD, 10, INGOT, 8000, 30, 80, "Bastok", 8, 2),
        ("guild_sells", GUILD, 10, ORE, 210, 5, 40, "Bastok", 8, 2),
    ]
    keys = ["action", "npc_id", "items", "item_id", "quantity", "price", "bought", "stock", "open_hour"]
    keys += ["close_hour"]
    assert [tuple(r.get(k) for k in keys) for r in got["shop_actions"]] == [
        ("open", NPC, 2, None, None, None, None, None, None, None),
        ("buy", NPC, None, ORE, 12, 200, 12, None, None, None),
        ("guild", GUILD, None, None, None, None, None, None, 8, 23),
        ("guild_buy", GUILD, None, INGOT, 10, 8000, 10, 20, None, None),
    ]
