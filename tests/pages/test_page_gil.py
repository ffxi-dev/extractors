"""The gil a mob gives, by Gilfinder level: the recorder's own kills, no other player sharing it."""

from fill import ask, put

ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x020


def test_a_mobs_gil_by_gilfinder_from_kills_no_one_shared(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in "abc"])
    put(con, "capture_trust", [{"capture_id": "c", "trust": "flagged", "at": 0}])
    fight = {"zone_id": ZONE, "mob_id": MOB, "mob_name": "Yagudo Votary", "players": 0, "gf": 0}
    put(con, "bestiary_fights", [
        {**fight, "capture_id": "a", "idx": 1, "fight_key": 1, "gil": 20},
        {**fight, "capture_id": "a", "idx": 2, "fight_key": 2, "gil": 26},
        {**fight, "capture_id": "a", "idx": 3, "fight_key": 3, "gil": 23},
        {**fight, "capture_id": "b", "idx": 3, "fight_key": 3, "gil": 23},  # a copy of the same kill
        {**fight, "capture_id": "a", "idx": 4, "fight_key": 4, "gil": 36, "gf": 1},
        {**fight, "capture_id": "a", "idx": 5, "fight_key": 5, "gil": 12, "players": 1},  # a party's share
        {**fight, "capture_id": "a", "idx": 6, "fight_key": 6, "gil": 40, "gf": None},
        {**fight, "capture_id": "a", "idx": 7, "fight_key": 7, "gil": None},  # no gil came
        {**fight, "capture_id": "c", "idx": 8, "fight_key": 8, "gil": 999},  # flagged
    ])  # fmt: skip
    rows = ask(con, "bestiary_gil", zone=ZONE, name="Yagudo Votary")
    assert [(r["gf"], r["kills"], r["lo"], r["hi"], r["median"], r["shared"]) for r in rows] == [
        (0, 3, 20, 26, 23, 1), (1, 1, 36, 36, 36, 0), (None, 1, 40, 40, 40, 0)]  # fmt: skip
