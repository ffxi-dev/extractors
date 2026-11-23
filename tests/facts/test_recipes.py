"""recipes: the character's syntheses folded by crystal and ingredients, with each grade's result and the
bounds the skill-ups put on the recipe's level."""

from conftest import rows
from fill import put

from ffxi_extractors.index import run

FIRE, COPPER, TIN, BRONZE, BROKEN = 4096, 640, 641, 649, 29695
SMITHING = 50


def synth(idx, ingredients, grade, item, count, up, skill, **kw):
    return {"capture_id": "a", "idx": idx, "ts_ms": idx * 1000, "client_version": "v", "own": True,
            "result": 1 if grade == -1 else 0, "grade": grade, "item_id": item, "count": count,
            "crystal_id": FIRE, "ingredients": ingredients, "skill_kinds": [SMITHING], "skill_levels": [up],
            "skills": [skill], **kw}  # fmt: skip


def test_a_recipe_folds_whatever_order_its_ingredients_went_in(con):
    put(con, "captures", [{"capture_id": c, "client_version": "v", "release": "r", "retail": True,
                           "packets": 1} for c in "ab"])  # fmt: skip
    put(con, "synths", [
        synth(1, [COPPER, COPPER, COPPER, TIN], 0, BRONZE, 1, 1, 20),  # a skill-up at 20 on a success: >= 10
        synth(2, [TIN, COPPER, COPPER, COPPER], 1, BRONZE, 2, 0, 21),  # none: bounds nothing but <= 21 + 27
        synth(3, [COPPER, TIN, COPPER, COPPER], -1, BROKEN, 1, 2, 12),  # one at 12 on a break: 13 to 17
        synth(4, [COPPER, TIN], 0, 650, 1, 0, None),  # another recipe, no skill known
        synth(5, [], 0, None, 0, 0, 30, crystal_id=None, result=3),  # nothing synthesized
        {**synth(6, [], 0, BRONZE, 1, 0, None), "own": False, "crystal_id": None},  # someone else's
        {**synth(7, [COPPER, COPPER, COPPER, TIN], 0, BRONZE, 1, 1, 50), "capture_id": "b"},
    ])  # fmt: skip
    run(con, None, "a", units={"recipes"})
    got = rows(con, "SELECT capture_id, idx, release, crystal_id, ingredients, attempts, nq, hq1, hq2, hq3,"
                    " breaks, nq_item_id, nq_count, hq1_item_id, hq1_count, hq2_item_id, levels FROM recipes"
                    " ORDER BY idx")  # fmt: skip
    level = ("craft", "attempts", "skill_ups", "level_min", "min_n", "level_max", "max_n")
    flat = [(*r[:4], [(i["item_id"], i["quantity"]) for i in r[4]], *r[5:-1],
             [tuple(x[k] for k in level) for x in r[-1]]) for r in got]  # fmt: skip
    assert flat == [
        ("a", 1, "r", FIRE, [(COPPER, 3), (TIN, 1)], 3, 1, 1, 0, 0, 1, BRONZE, 1, BRONZE, 2, None,
         [(SMITHING, 3, 2, 13, 2, 17, 3)]),
        ("a", 4, "r", FIRE, [(COPPER, 1), (TIN, 1)], 1, 1, 0, 0, 0, 0, 650, 1, None, None, None,
         [(SMITHING, 1, 0, None, 0, None, 0)]),
    ]  # fmt: skip
