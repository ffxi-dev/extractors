"""item_sources, the view of every way an item came: each source counted once, whoever recorded it."""

from fill import put, records

ITEM = 4098


def sources(con, kind):
    return [r for r in records(con, f"SELECT * FROM item_sources(item = {ITEM})") if r["kind"] == kind]


def test_a_pool_entry_two_party_members_saw_counts_once(con):
    put(
        con,
        "captures",
        [{"capture_id": c, "client_version": "v", "retail": True, "packets": 1} for c in "ab"],
    )
    entry = {"idx": 5, "item_id": ITEM, "quantity": 1, "mob_id": 0, "slot": 3, "start_time": 1000}
    put(con, "drops", [{**entry, "capture_id": c, "ts_ms": 9000 + i} for i, c in enumerate("ab")])
    put(con, "drops", [{**entry, "capture_id": "a", "idx": 9, "ts_ms": 20000, "slot": None}])  # no slot sent
    (drop,) = sources(con, "drop")
    assert (drop["n"], drop["captures"]) == (2, 2)


def test_only_the_characters_own_synthesis_gives_a_recipe(con):
    """0x070 reports a stranger's synthesis with no recipe: it showed as a recipe [0] of its own."""
    put(con, "synths", [
        {"capture_id": "a", "idx": 1, "ts_ms": 0, "own": True, "item_id": ITEM, "grade": 0,
         "crystal_id": 4096, "ingredients": [640, 641]},
        {"capture_id": "b", "idx": 1, "ts_ms": 0, "own": False, "item_id": ITEM, "grade": 0},
    ])  # fmt: skip
    assert [s["ids"] for s in sources(con, "synth")] == [[4096, 640, 641]]
