"""Whether a mob has MP: a player's, trust's, or pet's drain took some from it."""

from fill import ask, put

ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x020
PLAYER, TRUST = 0x0A0001, 0x01000000 | (ZONE << 12) | 0x701
ASPIR, DRAINED = 247, 228  # "<caster> casts <spell>. <amount> MP drained from <target>."


def test_a_mob_has_mp_when_a_drain_took_some(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in "ab"])
    put(con, "capture_trust", [{"capture_id": "b", "trust": "flagged", "at": 0}])
    fight = {"zone_id": ZONE, "mob_id": MOB, "mob_name": "Yagudo Parivir"}
    put(con, "bestiary_fights", [{**fight, "capture_id": c} for c in "ab"])
    hit = {"capture_id": "a", "client_version": "v", "category": 4, "action_id": ASPIR, "target_id": MOB,
           "message": DRAINED, "actor_id": PLAYER}  # fmt: skip
    put(con, "action_results", [
        {**hit, "idx": 1, "ts_ms": 1, "value": 45},
        {**hit, "idx": 2, "ts_ms": 2, "value": 80, "actor_id": TRUST},
        {**hit, "idx": 3, "ts_ms": 3, "value": 0},  # the caster's MP was full: no proof either way
        {**hit, "idx": 4, "ts_ms": 4, "value": 99},  # a resend of a packet already counted
        {**hit, "idx": 5, "ts_ms": 5, "value": 120, "capture_id": "b"},  # flagged
        {**hit, "idx": 6, "ts_ms": 6, "value": 60, "target_id": MOB + 1},  # another mob
    ])  # fmt: skip
    put(con, "actions", [{"capture_id": "a", "idx": i, "ts_ms": i, "client_version": "v", "resend": i == 4}
                         for i in (1, 2, 3, 4)])  # fmt: skip
    (r,) = ask(con, "bestiary_mp", zone=ZONE, name="Yagudo Parivir")
    assert (r["n"], r["most"], r["lens_url"]) == (2, 80, "https://lens.sruon.dev/c/a#packet=2")
    (none,) = ask(con, "bestiary_mp", zone=ZONE, name="Nobody")
    assert none["n"] == 0
