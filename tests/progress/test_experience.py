"""Point gains and level changes (0x02D), with what changes the points, and exp_kills over them."""

from conftest import MEMBER, MOB, PLAYER, drive
from fill import put, records

from ffxi_extractors.extractors.progress.experience import Experience
from ffxi_extractors.index import run

DEDICATION, SIGNET, WHITE = 249, 253, 2884


def message(msg, data, data2=0, who=PLAYER, target=MOB):
    return 0x02D, {"UniqueNoCas": who, "UniqueNoTar": target, "Data": data, "Data2": data2, "MessageNum": msg}


def statuses(*ids):
    return 0x063, {"type": 9, **{f"data.icon[{i}]": s for i, s in enumerate(ids)}, "data.icon[5]": 255}


def key_items(*ids):  # table 5 holds 2560 to 3071
    words = {}
    for k in ids:
        words[(k - 2560) // 32] = words.get((k - 2560) // 32, 0) | 1 << (k - 2560) % 32
    return 0x055, {"TableIndex": 5, **{f"GetItemFlag[{i}]": w for i, w in words.items()}}


def test_gains_name_their_chain_mob_and_bonuses():
    # drive's party holds a member, so Signet counts.
    steps = (statuses(DEDICATION, SIGNET, 40), key_items(WHITE, 2890), message(8, 493), message(253, 1200, 1),
             message(253, 1250, 2), message(372, 4888, 52), message(8, 300, target=PLAYER))  # fmt: skip
    rows = drive(Experience, *steps)["exp_gains"]
    got = [
        (r["kind"], r["points"], r["chain"], r["mob_id"], r["effects"], r["key_items"], r["party_size"])
        for r in rows
    ]
    bonus = ([DEDICATION, SIGNET], [WHITE], 2)
    assert got == [
        ("exp", 493, 0, MOB, *bonus),
        ("exp", 1200, 1, MOB, *bonus),
        ("exp", 1250, 2, MOB, *bonus),
        ("limit", 4888, 52, MOB, *bonus),
        ("exp", 300, 0, None, *bonus),
    ]


def test_level_ups_and_downs_of_anyone():
    steps = (message(9, 12), message(9, 12, who=MEMBER), message(11, 74, target=PLAYER))
    rows = drive(Experience, *steps)["level_changes"]
    assert [(r["member_id"], r["own"], r["change"], r["level"], r["mob_id"]) for r in rows] == [
        (PLAYER, True, "up", 12, MOB),
        (MEMBER, False, "up", 12, MOB),
        (PLAYER, True, "down", 74, None),
    ]


def test_a_clean_gain_and_a_party_one(con):
    cap = "e1"
    base = {"capture_id": cap, "client_version": "v"}
    put(con, "captures", [{**base, "release": "r", "retail": True, "packets": 0, "start_ms": 0}])
    put(con, "entity_changes", [{**base, "idx": 0, "ts_ms": 0, "entity_id": MOB, "name": "Goblin Thug"}])
    put(con, "character", [{**base, "idx": 1, "ts_ms": 1, "character_id": PLAYER, "main_level": 10}])
    put(con, "levels", [{**base, "idx": 2, "ts_ms": 2, "entity_id": MOB, "level": 12, "source": "check",
                         "zone_id": 100, "end_idx": 10}])  # fmt: skip
    put(con, "kills", [{**base, "idx": 10, "ts_ms": 10_000, "mob_id": MOB, "message": 6, "zone_id": 100}])
    gain = {**base, "recipient_id": PLAYER, "own": True, "kind": "exp", "message": 8, "mob_id": MOB,
            "zone_id": 100, "effects": [], "key_items": []}  # fmt: skip
    put(con, "exp_gains", [
        {**gain, "idx": 11, "ts_ms": 10_000, "points": 240, "chain": 0, "party_size": 1},
        {**gain, "idx": 12, "ts_ms": 10_000, "points": 150, "chain": 0, "party_size": 2},
    ])  # fmt: skip
    run(con, None, cap, units={"exp_kills"})
    rows = records(con, f"SELECT * FROM exp_kills WHERE capture_id = '{cap}' ORDER BY idx")
    assert [(r["mob_name"], r["kill_idx"], r["level_diff"], r["points"], r["clean"]) for r in rows] == [
        ("Goblin Thug", 10, 2, 240, True),
        ("Goblin Thug", 10, 2, 150, False),
    ]
