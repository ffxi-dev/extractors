"""Point gains and level changes (0x02D), with what changes the points, and exp_kills over them."""

from fill import ask, put

DEDICATION, SIGNET, WHITE = 249, 253, 2884


def test_the_mob_card_counts_clean_gains_and_says_how_many_it_left_out(con):
    base = {"client_version": "v", "kind": "exp", "zone_id": 100, "mob_name": "Goblin Thug", "chain": 0,
            "kill_idx": 1}  # fmt: skip
    put(con, "exp_kills", [
        {**base, "capture_id": "e3", "idx": 1, "ts_ms": 1, "level_diff": 2, "char_level": 11, "points": 200,
         "clean": True},
        {**base, "capture_id": "e4", "idx": 1, "ts_ms": 1, "level_diff": 2, "char_level": 11, "points": 300,
         "clean": False, "effects": [249]},
        {**base, "capture_id": "e4", "idx": 2, "ts_ms": 2, "level_diff": 2, "char_level": 11, "points": 500,
         "clean": True, "kind": "capacity"},
    ])  # fmt: skip
    rows = ask(con, "bestiary_exp", zone=100, name="Goblin Thug")
    assert [(r["diff"], r["bracket"], r["n"], r["lo"], r["mid"], r["left_out"]) for r in rows] == [
        (2, 11, 1, 200, 200, 1)
    ]
