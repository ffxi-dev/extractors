"""The gil a mob gives, by Gilfinder level: what its claimed kills' pools found, whole."""

from fill import ask, put

ZONE = 0x0A7
MOB = 0x01000000 | (ZONE << 12) | 0x0E6


def test_a_mobs_gil_by_gilfinder_over_its_claimed_kills(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in "abc"])
    put(con, "capture_trust", [{"capture_id": "c", "trust": "flagged", "at": 0}])
    fight = {"zone_id": ZONE, "mob_id": MOB, "mob_name": "Bloodsucker", "claimed": True,
             "outcome": "defeated", "gf": 0}  # fmt: skip
    put(con, "bestiary_fights", [
        {**fight, "capture_id": "a", "idx": 1, "fight_key": 1, "gil": 6000},
        {**fight, "capture_id": "a", "idx": 2, "fight_key": 2, "gil": 6000},
        {**fight, "capture_id": "b", "idx": 2, "fight_key": 2, "gil": 6000},  # another recorder's copy
        {**fight, "capture_id": "a", "idx": 3, "fight_key": 3, "gil": None},  # its pool found no gil
        {**fight, "capture_id": "a", "idx": 4, "fight_key": 4, "gil": 9000, "gf": 1},
        {**fight, "capture_id": "a", "idx": 5, "fight_key": 5, "gil": 7, "claimed": False},  # not our kill
        {**fight, "capture_id": "c", "idx": 6, "fight_key": 6, "gil": 1},  # flagged
        {**fight, "capture_id": "a", "idx": 7, "fight_key": 7, "gil": None, "gf": None},  # no gil, unknown GF
    ])  # fmt: skip
    rows = ask(con, "bestiary_gil", zone=ZONE, name="Bloodsucker")
    assert [(r["gf"], r["kills"], r["claimed"], r["lo"], r["hi"], r["median"]) for r in rows] == [
        (0, 2, 3, 6000, 6000, 6000), (1, 1, 1, 9000, 9000, 9000)]  # fmt: skip
    assert ask(con, "bestiary_gil", zone=ZONE, name="Nobody") == []
