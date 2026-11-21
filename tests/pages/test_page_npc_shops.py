"""NPC and guild shops: the extractor on decoded fields, the timeline's marks, and the catalog."""

from fill import ask, put, records

from ffxi_extractors import store
from ffxi_extractors.index import run

ZONE = 235  # Bastok Markets
NPC = 0x0100_0000 | (ZONE << 12) | 0x10C
GUILD = NPC + 1
STEW, ORE, INGOT = 4569, 644, 790


def setup(con, cid, items, actions=(), release="r"):
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "release": release, "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    seen = {"capture_id": cid, "idx": 0, "ts_ms": 0, "client_version": "v"}
    put(
        con,
        "entity_changes",
        [{**seen, "entity_id": e, "name": n} for e, n in ((NPC, "Hortense"), (GUILD, "Smith"))],
    )
    names = (STEW, "Quadav Stew"), (ORE, "Iron Ore"), (INGOT, "Steel Ingot")
    named = [{"release": release, "kind": "item", "log_id": 0, "id": i, "name": n} for i, n in names]
    zone = {"release": release, "kind": "zone", "log_id": 0, "id": ZONE, "name": "Bastok Markets"}
    put(con, "names", [*named, zone])
    base = {"capture_id": cid, "client_version": "v", "zone_id": ZONE}
    if items:
        put(con, "shop_items", [{**base, **r} for r in items])
    if actions:
        put(con, "shop_actions", [{**base, **r} for r in actions])
    run(con, None, cid, units={"npc_shops"})


def listed(idx, ts, kind, npc, item, price, rank, stock=None, conquest=2):
    row = {"idx": idx, "ts_ms": ts, "list_idx": idx, "kind": kind, "npc_id": npc, "item_id": item}
    row |= {"price": price, "stock": stock, "max": 80 if stock is not None else None, "nation": "Bastok"}
    return row | {"nation_rank": rank, "conquest_rank": conquest}


def test_the_catalog_gives_prices_by_standing_and_a_guilds_latest_stock(con):
    setup(con, "a", [listed(1, 1000, "shop", NPC, STEW, 60, 8), listed(9, 9000, "shop", NPC, STEW, 60, 8),
                     listed(2, 2000, "guild_sells", GUILD, INGOT, 8000, 8, stock=30)])  # fmt: skip
    setup(con, "b", [listed(1, 5000, "shop", NPC, STEW, 54, 10, conquest=1),
                     listed(2, 7000, "guild_sells", GUILD, INGOT, 7900, 10, stock=45)])  # fmt: skip
    setup(con, "e", [listed(1, 1000, "shop", NPC, STEW, 1, 8)])
    store.trust(con, [("e", "flagged")])
    folded = records(
        con, "SELECT capture_id, item_id, price, n FROM npc_shops ORDER BY capture_id, item_id, price"
    )
    assert [tuple(r.values()) for r in folded] == [
        ("a", INGOT, 8000, 1), ("a", STEW, 60, 2), ("b", INGOT, 7900, 1), ("b", STEW, 54, 1),
        ("e", STEW, 1, 1),
    ]  # fmt: skip
    got = {(r["npc_name"], r["item_name"]): r for r in ask(con, "npc_zone_shops", zone=ZONE)}
    assert list(got) == [("Hortense", "Quadav Stew"), ("Smith", "Steel Ingot")]
    stew = got["Hortense", "Quadav Stew"]
    assert (stew["kind"], stew["n"], stew["captures"], stew["stock"]) == ("shop", 3, 2, [])
    standing = {"nation": "Bastok", "nation_rank": 8, "conquest_rank": 2}
    assert [(x["v"], x["k"]) for x in stew["prices"]] == [
        ({"price": 60, **standing}, 2),
        ({"price": 54, "nation": "Bastok", "nation_rank": 10, "conquest_rank": 1}, 1),
    ]
    ingot = got["Smith", "Steel Ingot"]
    assert [s[:3] for s in ingot["stock"]] == [[7000, 45, 80], [2000, 30, 80]], "the latest first"


def test_the_shops_page_lists_every_item_by_zone_npc_and_list_with_its_prices(con):
    setup(con, "a", [listed(1, 1000, "shop", NPC, STEW, 60, 8),
                     listed(2, 2000, "guild_sells", GUILD, INGOT, 8000, 8, stock=30)])  # fmt: skip
    setup(con, "b", [listed(1, 5000, "shop", NPC, STEW, 54, 10, conquest=1)])
    setup(con, "e", [listed(1, 1000, "shop", NPC, STEW, 1, 8)])
    store.trust(con, [("e", "flagged")])
    keys = "item_name", "zone_name", "npc_name", "kind", "price_lo", "price_hi", "n", "captures"
    got = [tuple(r[k] for k in keys) for r in ask(con, "shops")]
    assert got == [
        ("Quadav Stew", "Bastok Markets", "Hortense", "shop", 54, 60, 2, 2),
        ("Steel Ingot", "Bastok Markets", "Smith", "guild_sells", 8000, 8000, 1, 1),
    ]  # fmt: skip
