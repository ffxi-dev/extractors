"""Battlefield timers (0x075) and registration answers (0x0BF). Packets are given as decoded fields."""

from conftest import PLAYER, drive

from ffxi_extractors.extractors.progress.battlefields import Battlefields
from ffxi_extractors.vana import EPOCH_S

ZONE = 168
START = 783520182  # AOIRM1YTB1Wq's countdown Timestamp: the moment it was sent


def countdown(limit=1800, start=START, mode=1):
    return 0x075, {"Mode": mode, "Timestamp": start, "Duration": limit, "DurationWarn": 0, "Flags": 1}


def clear():  # retail clears with Flags 0 and leaves the rest as it was: garbage
    return 0x075, {"Mode": 1, "Timestamp": 3087468518, "Duration": 3286727262, "Flags": 0}


def event(para, *nums):
    return 0x034, {"UniqueNo": PLAYER, "EventPara": para, **{f"num[{i}]": n for i, n in enumerate(nums)}}


def zone_in(zone=ZONE):
    return 0x00A, {"ZoneNo": zone}


def test_a_battlefield_won_its_time_limit_and_index():
    rows = drive(Battlefields, zone_in(), countdown(), countdown(1799, START + 1),
                 event(32001, 0, 28, 0, 442, ZONE, 2, 0, 0), clear(), clear())["battlefields"]  # fmt: skip
    (b,) = rows
    assert (b["start_ms"], b["time_limit_s"], b["mode"], b["zone_id"]) == (
        (START + EPOCH_S) * 1000,
        1800,
        1,
        ZONE,
    )
    assert (b["outcome"], b["result_idx"], b["battlefield_index"], b["time_inside_s"], b["record_s"]) == (
        "won",
        3,
        2,
        442,
        28,
    )
    assert (b["end_idx"], b["ended_by"]) == (4, "cleared")


def test_a_loss_after_the_clear_and_a_timer_that_never_cleared():
    loss = (0x032, {"EventPara": 32002})
    steps = (zone_in(), countdown(), clear(), loss, countdown(900, START + 5000), zone_in(ZONE + 1))
    rows = drive(Battlefields, *steps)["battlefields"]
    assert [(r["time_limit_s"], r.get("outcome"), r["ended_by"]) for r in rows] == [
        (1800, "lost", "cleared"),
        (900, None, "zoned"),
    ]


def test_a_new_countdown_replaces_the_open_one():
    rows = drive(Battlefields, zone_in(), countdown(360), countdown(360, START + 400))["battlefields"]
    assert [(r["time_limit_s"], r.get("ended_by")) for r in rows] == [(360, "replaced"), (360, None)]


def test_a_registration_answer_names_its_npc():
    npc = 0x01000000 | (137 << 12) | 0x297
    seen = (0x00E, {"UniqueNo": npc, "ActIndex": 0x297})
    steps = (seen, (0x0BF, {"Result": 4, "ActIndex": 0x297}), (0x0BF, {"Result": 2, "ActIndex": 0x300}))
    rows = drive(Battlefields, *steps)["registrations"]
    assert [(r["result"], r["outcome"], r["npc_id"]) for r in rows] == [(4, "entering", npc), (2, None, None)]
