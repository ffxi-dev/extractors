"""The recipe catalog: each recipe's recipes rows summed across captures, Flagged ones left out."""

from fill import ask, put

FIRE, CHIP, WATER, BEESWAX, ALCHEMY = 4096, 912, 4509, 913, 55
LIGHTNING, RING, INGOT = 4100, 14630, 747
BEESWAX_RECIPE = [(CHIP, 3), (WATER, 1)]
LEVEL = ("craft", "attempts", "skill_ups", "level_min", "min_n", "level_max", "max_n")


def recipe(capture, idx, crystal=FIRE, ingredients=BEESWAX_RECIPE, levels=(), **counts):
    return {"capture_id": capture, "idx": idx, "ts_ms": idx * 1000, "client_version": "v",
            "release": "r", "crystal_id": crystal,
            "ingredients": [{"item_id": i, "quantity": q} for i, q in ingredients],
            "levels": [dict(zip(LEVEL, x, strict=True)) for x in levels], **counts}  # fmt: skip


def test_the_catalog_sums_each_recipe_across_captures_and_narrows_its_level_bounds(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in ("a", "b", "x")])
    put(con, "capture_trust", [{"capture_id": "x", "trust": "flagged"}])
    name = {"release": "r", "log_id": 0, "kind": "item"}
    items = ((FIRE, "Fire Crystal"), (CHIP, "Beehive Chip"), (WATER, "Distilled Water"), (BEESWAX, "Beeswax"),
             (RING, "Flame Ring"), (INGOT, "Ocl. Ingot"))  # fmt: skip
    put(con, "names", [{**name, "id": i, "name": n} for i, n in items])
    wax = {"nq_item_id": BEESWAX, "nq_count": 1}
    put(con, "recipes", [
        recipe("a", 10, attempts=100, nq=80, hq1=10, breaks=10, **wax, hq1_item_id=BEESWAX, hq1_count=2,
               levels=[(ALCHEMY, 100, 50, 3, 50, 9, 100)]),
        recipe("b", 20, attempts=69, nq=45, hq2=3, hq3=2, breaks=7, **wax, hq2_item_id=BEESWAX, hq2_count=3,
               hq3_item_id=BEESWAX, hq3_count=4, levels=[(ALCHEMY, 69, 33, 4, 33, 5, 69)]),
        recipe("x", 30, attempts=999, nq=999, **wax),  # flagged
        recipe("a", 40, crystal=LIGHTNING, ingredients=[(RING, 1)], desynth=True, attempts=3, nq=1, breaks=2,
               nq_item_id=INGOT, nq_count=1),
    ])  # fmt: skip
    wax_row, ring = ask(con, "recipe_catalog")
    assert (wax_row["crystal_name"], wax_row["ingredients"], wax_row["desynth"]) == (
        "Fire Crystal",
        [
            {"item": CHIP, "quantity": 3, "name": "Beehive Chip"},
            {"item": WATER, "quantity": 1, "name": "Distilled Water"},
        ],
        0,
    )
    counts = [wax_row[k] for k in ("attempts", "nq", "hq1", "hq2", "hq3", "breaks", "captures")]
    assert counts == [169, 125, 10, 3, 2, 17, 2]
    tiers = [(wax_row[t + "_name"], wax_row[t + "_count"]) for t in ("nq", "hq1", "hq2", "hq3")]
    assert tiers == [("Beeswax", 1), ("Beeswax", 2), ("Beeswax", 3), ("Beeswax", 4)]
    # The highest lower bound, the lowest upper bound, each with every observation behind it.
    assert wax_row["levels"] == [
        {
            "craft": ALCHEMY,
            "attempts": 169,
            "skill_ups": 83,
            "level_min": 4,
            "min_n": 83,
            "level_max": 5,
            "max_n": 169,
        }
    ]
    assert (wax_row["last_capture"], wax_row["last_idx"], wax_row["release"]) == ("b", 20, "r")
    assert (ring["desynth"], ring["nq_name"], ring["hq1_name"], ring["levels"]) == (1, "Ocl. Ingot", None, [])
