"""Trades to NPCs: the extractor on decoded fields, the timeline's marks, and the catalog."""

from conftest import drive
from fill import ask, put, records

from ffxi_extractors import store
from ffxi_extractors.extractors.items.trades import Trades
from ffxi_extractors.index import run

ZONE = 245
NPC = 0x0100_0000 | (ZONE << 12) | 100
STEW, ORE = 4569, 643
C2S = 1


def held(index, item, count):
    return 0x020, {"Category": 0, "ItemIndex": index, "ItemNo": item, "ItemNum": count}


def trades(*after, times):
    steps = [(0x00A, {"ZoneNo": ZONE}), held(5, STEW, 12), held(9, ORE, 3), *after]
    directions = [C2S if op == 0x036 and "ItemNum" in d else 0 for op, d in steps]
    return drive(Trades, *steps, times=[0, 0, 0, *times], directions=directions)["trades"]


def setup(con, cid, rows, release="r", name="Moogle"):
    """rows: (idx, ts, npc, items, quantities, gil, event)."""
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "release": release, "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": cid, "idx": 0, "ts_ms": 0, "client_version": "v",
                                 "entity_id": NPC, "name": name}])  # fmt: skip
    put(con, "names", [{"release": release, "kind": "item", "log_id": 0, "id": STEW, "name": "Quadav Stew"}])
    keys = ("idx", "ts_ms", "npc_id", "item_ids", "quantities", "gil", "event_id")
    base = {"capture_id": cid, "client_version": "v", "zone_id": ZONE}
    put(con, "trades", [{**base, **dict(zip(keys, r, strict=True))} for r in rows])
    run(con, None, cid, units={"npc_trades"})


def test_the_catalog_gives_each_npcs_trades_and_answers(con):
    setup(con, "a", [(1, 1000, NPC, [STEW], [3], None, 10), (2, 2000, NPC, [STEW], [3], None, 10)])
    setup(con, "b", [(1, 5000, NPC, [STEW], [3], None, None)], release="r2")
    setup(con, "e", [(1, 1000, NPC, [STEW], [3], None, 10)])
    store.trust(con, [("e", "flagged")])
    folded = records(con, "SELECT capture_id, item_ids, event_id, n FROM npc_trades ORDER BY capture_id")
    assert [tuple(r.values()) for r in folded] == [
        ("a", [STEW], 10, 2),
        ("b", [STEW], None, 1),
        ("e", [STEW], 10, 1),
    ]
    (row,) = ask(con, "npc_zone_trades", zone=ZONE)
    assert (row["npc_name"], row["item_names"], row["quantities"], row["n"], row["captures"]) == (
        "Moogle", ["Quadav Stew"], [3], 3, 2,
    )  # fmt: skip
    assert [(a["v"], a["k"]) for a in row["answers"]] == [("event 10", 2), ("nothing", 1)]
    assert row["answers"][1]["seen"] == {"capture_id": "b", "ts_ms": 5000}
