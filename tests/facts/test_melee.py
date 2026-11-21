"""melee: each swing, and at the recorder the recorder's stats from its last status update before it."""

from conftest import CAPTAIN
from fill import put, records

from ffxi_extractors.index import run

ME, OTHER = 0x0001_0001, 0x0001_0002
MOB = 0x01000000 | (0x0A3 << 12) | 0x010

# The lake plan's worked example: a mob's top non-crit hit against each defence bounds its attack.
ATTACK = """
SELECT attacker_name, zone_id, attacker_level, target_defense, target_level, count() AS hits,
  min(damage) AS lo, median(damage) AS mid, max(damage) AS hi
FROM melee
WHERE attacker_is_mob AND target_is_recorder AND outcome = 1 AND NOT crit AND target_defense IS NOT NULL
GROUP BY ALL HAVING count() >= 30
ORDER BY attacker_name, attacker_level, target_defense
"""


def test_each_swing_carries_the_stats_in_force_at_its_packet(con):
    put(
        con,
        "captures",
        [{"capture_id": "h", "client_version": "", "retail": True, "packets": 0, "character_id": ME}],
    )
    put(con, "entity_changes", [{"capture_id": "h", "idx": 0, "entity_id": MOB, "name": "Goblin"}])
    put(con, "levels", [{"capture_id": "h", "idx": 1, "entity_id": MOB, "level": 30}])
    put(
        con,
        "character",
        [
            {
                "capture_id": "h",
                "idx": 10,
                "main_job": "WAR",
                "main_level": 75,
                "defense": 300,
                "vit": 50,
                "vit_bonus": 5,
            },
            {
                "capture_id": "h",
                "idx": 20,
                "main_job": "WAR",
                "main_level": 76,
                "defense": 320,
                "vit": 50,
                "vit_bonus": 10,
            },
        ],
    )
    swings = [(5, ME), (15, ME), (15, OTHER), (25, ME)]
    put(
        con,
        "actions",
        [
            {
                "capture_id": "h",
                "idx": i,
                "actor_id": MOB,
                "actor_is_mob": True,
                "category": 1,
                "resend": False,
                "zone_id": 0x0A3,
            }
            for i in (5, 15, 25)
        ],
    )
    put(
        con,
        "action_results",
        [
            {
                "capture_id": "h",
                "idx": i,
                "actor_id": MOB,
                "category": 1,
                "target_id": t,
                "result_index": 0,
                "sub_kind": 0,
                "message": 1,
                "value": 40,
            }
            for i, t in swings
        ],
    )
    assert run(con, None, "h", units={"melee"}) == {"melee": 4}
    got = records(
        con,
        "SELECT idx, target_is_recorder, target_defense, target_vit, target_level, target_job,"
        " attacker_name, attacker_level FROM melee ORDER BY idx, target_id",
    )
    assert [tuple(r.values()) for r in got] == [
        (5, True, None, None, None, None, "Goblin", 30),  # before any status update
        (15, True, 300, 55, 75, "WAR", "Goblin", 30),
        (15, False, None, None, None, None, "Goblin", 30),  # at someone else
        (25, True, 320, 60, 76, "WAR", "Goblin", 30),
    ]


def test_the_attack_query_answers_on_the_captain_fixture(con):
    run(con, CAPTAIN, "c")
    # Every swing at the recorder comes after its first status update.
    swings = records(
        con, "SELECT countIf(target_is_recorder) AS n, countIf(target_defense IS NOT NULL) AS d FROM melee"
    )
    assert swings == [{"n": 289, "d": 289}]
    # Aspidochelone, level 85, at defence 1112 (the recorder at 99): 31 plain hits, 15 to 70, middle 40.
    assert [tuple(r.values()) for r in records(con, ATTACK)] == [
        ("Aspidochelone", 128, 85, 1112, 99, 31, 15, 40, 70)
    ]
