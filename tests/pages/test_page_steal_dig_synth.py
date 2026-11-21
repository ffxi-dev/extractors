"""Steal, Mug, and Despoil; chocobo digs; synthesis results. Packets are given as decoded fields."""

from conftest import PLAYER
from fill import ask, put

from ffxi_extractors.index import run

GREENS, PEBBLE, HINT = 4545, 17296, 3
ZONE = 117
MOB = 0x01000000 | (ZONE << 12) | 0x020


def steal(idx, action, message, value=0, target=MOB, actor=PLAYER, resend=False, ts=None):
    base = {"idx": idx, "ts_ms": ts if ts is not None else idx * 1000, "client_version": "v"}
    action_row = {**base, "actor_id": actor, "category": 3, "action_id": action, "zone_id": ZONE,
                  "resend": resend, "targets": 1}  # fmt: skip
    result = {**base, "actor_id": actor, "category": 3, "action_id": action, "target_id": target,
              "target_index": 0, "result_index": 0, "message": message, "value": value}  # fmt: skip
    return action_row, result


def setup_steals(con, capture, *steals):
    put(con, "captures", [{"capture_id": capture, "client_version": "v", "release": "r", "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": capture, "idx": 0, "ts_ms": 0, "client_version": "v",
                                 "entity_id": MOB, "name": "Goblin Digger"}])  # fmt: skip
    put(con, "actions", [{**a, "capture_id": capture} for a, _ in steals])
    put(con, "action_results", [{**r, "capture_id": capture} for _, r in steals])
    run(con, None, capture, units={"steals"})


def test_the_mob_card_counts_a_steal_two_recorders_saw_once(con):
    setup_steals(con, "a", steal(1, 41, 125, 4569, ts=60_000), steal(2, 41, 153, ts=400_000))
    setup_steals(con, "b", steal(5, 41, 125, 4569, ts=60_300))  # the same steal, from a party member
    put(con, "names", [{"release": "r", "kind": "item", "log_id": 0, "id": 4569, "name": "Quadav Stew"}])
    got = ask(con, "bestiary_steals", zone=ZONE, name="Goblin Digger")
    assert [(r["ability"], r["success"], r["item_name"], r["n"]) for r in got] == [
        ("steal", True, "Quadav Stew", 1),
        ("steal", False, None, 1),
    ]
