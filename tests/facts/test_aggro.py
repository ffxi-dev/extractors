"""Mob aggro: engages and passes from the packets, sorted by what started them, and the mob card's figures.
Packets are given as decoded fields."""

import pytest
from conftest import MEMBER, PLAYER, STRANGER, drive
from fill import put, records

from ffxi_extractors.combat import P
from ffxi_extractors.extractors.battle.engages import Engages
from ffxi_extractors.index import run

ZONE = 104  # Jugner Forest: outdoors
MOB, OTHER, THIRD, CRAB = (0x01000000 | (ZONE << 12) | i for i in (0x020, 0x021, 0x022, 0x023))
C2S = 1


def mob(uid=MOB, status=0, x=0.0, y=0.0, d=0, speed=40, claim=0, **more):
    """A full update: idle or engaged, placed, facing d (0 faces +x), with its claim."""
    return 0x00E, {
        "UniqueNo": uid,
        "ActIndex": uid & 0xFFF,
        "SendFlg.General": 1,
        "server_status": status,
        "Flags1.MonsterFlag": 1,
        "SendFlg.Position": 1,
        "x": x,
        "y": y,
        "z": 0.0,
        "dir": d,
        "Speed": speed,
        "SendFlg.ClaimStatus": 1,
        "BtTargetID": claim,
        **more,
    }


def me(x, y=0.0, z=1.0):
    return 0x015, {"x": x, "y": y, "z": z}


def hits(actor, target):
    return 0x028, {
        P + "actor_id": actor,
        P + "cmd_no": 1,
        P + "target_count": 1,
        P + "targets[0].target_id": target,
        P + "targets[0].result_count": 1,
        P + "targets[0][0].message": 1,
    }


def walk(*steps, gap=1000):
    times = [i * gap for i in range(len(steps))]
    zone_in = (
        0x00A,
        {"ZoneNo": ZONE, "WeatherNumber": 6, "PosHead.x": 50.0, "PosHead.y": 0.0, "PosHead.z": 1.0},
    )
    status = (0x037, {"BufStatus[0]": 71, "BufStatus[1]": 255, "server_status": 0, "Flags0.hpp": 90})
    steps = (zone_in, status, *steps)
    times = [0, 0, *(t + 1 for t in times)]
    directions = [C2S if op in (0x015, 0x01A) else 0 for op, _ in steps]
    return drive(Engages, *steps, times=times, directions=directions)


def test_a_mob_that_turns_on_the_character_unprovoked():
    # Idle and unclaimed, facing +x; the character 8 yalms ahead; it engages, turning to it, then hits it.
    got = walk(
        mob(),
        me(30.0),
        me(8.0),
        mob(status=1, d=0, speed=100),
        hits(MOB, PLAYER),
        mob(status=1, claim=PLAYER),
    )
    (e,) = got["mob_engages"]
    assert e["distance"] == pytest.approx(8.0625, abs=1e-3)  # 8 across, 1 up
    assert (round(e["facing"]), e["dz"], e["mob_speed"], e["flip_speed"]) == (0, 1.0, 40, 100)
    assert (e["sneak"], e["invisible"], e["hpp"], e["weather_id"], e["zone_id"]) == (True, False, 90, 6, ZONE)
    assert (e["first_ms"], e["first_target_recorder"], e["claim_ms"], e["claimer_id"]) == (
        1000,
        True,
        2000,
        PLAYER,
    )
    assert e["me_action_id"] is None and e["party_ms"] is None
    assert got["mob_passes"] == []  # it engaged: the approach is no pass


def test_a_pull_is_the_characters_action_before_the_engage():
    (e,) = walk(mob(), me(20.0), (0x01A, {"UniqueNo": MOB, "ActionID": 2}), mob(status=1))["mob_engages"]
    assert (e["me_action_id"], e["me_action_ms"]) == (2, 1000)


def test_a_strangers_fight_close_by_is_one_a_mob_may_have_linked_to():
    # OTHER, 5 yalms off, engages a stranger and is claimed; MOB engages 1 s later.
    got = walk(
        mob(OTHER, x=5.0),
        mob(),
        me(30.0),
        mob(OTHER, status=1, x=5.0, claim=STRANGER),
        mob(status=1),
    )
    _, e = got["mob_engages"]
    assert (e["link_mob_id"], e["link_distance"], e["link_ms"]) == (OTHER, 5.0, 1000)


def test_a_pass_by_a_mob_that_does_not_engage_is_one_row_at_the_closest():
    # Behind it (it faces -x), from 30 yalms to 10 and back past 17, then near again.
    got = walk(mob(d=128), me(30.0), me(16.0), me(10.0), me(16.5), me(20.0), me(12.0))
    first, second = got["mob_passes"]
    assert (first["distance"], abs(round(first["facing"])), first["duration_ms"]) == (
        pytest.approx(10.05, abs=0.01),
        180,
        1000,
    )
    assert (first["sneak"], second["distance"]) == (True, pytest.approx(12.04, abs=0.01))


def setup_engages(con, *rows, capture="a", fmt="xicap", action_ms=None):
    """mob_engages rows and what aggro joins them to; action_ms, when given, times one action packet."""
    put(
        con,
        "captures",
        [
            {
                "capture_id": capture,
                "client_version": "v",
                "release": "r",
                "retail": True,
                "packets": 0,
                "start_ms": 0,
                "format": fmt,
            }
        ],
    )
    put(
        con,
        "entity_changes",
        [
            {"capture_id": capture, "idx": 0, "ts_ms": 0, "client_version": "v", "entity_id": m, "name": n}
            for m, n in (
                (MOB, "Forest Hare"),
                (OTHER, "Forest Hare"),
                (THIRD, "Forest Hare"),
                (CRAB, "Robber Crab"),
            )
        ],
    )
    put(
        con,
        "levels",
        [
            {
                "capture_id": capture,
                "idx": 0,
                "ts_ms": 0,
                "client_version": "v",
                "entity_id": MOB,
                "level": 12,
                "source": "widescan",
                "zone_id": ZONE,
            }
        ],
    )
    put(
        con,
        "character",
        [{"capture_id": capture, "idx": 0, "ts_ms": 0, "client_version": "v", "main_level": 20}],
    )
    base = {
        "capture_id": capture,
        "client_version": "v",
        "zone_id": ZONE,
        "mob_id": MOB,
        "since_seen_ms": 9000,
        "me_age_ms": 200,
        "distance": 8.0,
        "status_before": 0,
        "status": 1,
    }
    put(con, "mob_engages", [{**base, **r} for r in rows])
    if action_ms is not None:
        put(con, "actions", [{"capture_id": capture, "idx": 0, "ts_ms": action_ms, "client_version": "v",
                              "actor_id": MOB, "category": 1, "resend": False}])  # fmt: skip
    run(con, None, capture, units={"aggro", "aggro_passes"})


def test_each_engage_is_sorted_by_what_started_it(con):
    aggro = {"first_ms": 3000, "first_target_recorder": True, "first_target_party": True}
    stranger = {"first_ms": 1000, "first_target_id": STRANGER, "first_target_recorder": False,
                "first_target_party": False, "claimer_id": STRANGER, "claimer_party": False}  # fmt: skip
    setup_engages(
        con,
        {"idx": 1, "ts_ms": 1000, **aggro, "answered_ms": 5000},
        {
            "idx": 2,
            "ts_ms": 2000,
            "first_ms": 3000,
            "first_target_party": True,
            "first_target_recorder": False,
        },
        {"idx": 3, "ts_ms": 3000, "me_action_id": 2, "me_action_ms": 1000, **aggro},
        {"idx": 4, "ts_ms": 4000, "party_ms": 500, "party_actor_id": MEMBER, **aggro},
        {"idx": 5, "ts_ms": 5000, "other_ms": 500, **aggro},
        # Answered before it acted: no telling whom it went for.
        {"idx": 6, "ts_ms": 6000, **aggro, "answered_ms": 1000},
        # OTHER, pulled by the party; MOB engages 4 s later 6 yalms off and goes for the party.
        {
            "idx": 7,
            "ts_ms": 100_000,
            "mob_id": OTHER,
            "party_ms": 900,
            "claimer_party": True,
            "claimer_id": MEMBER,
        },
        {"idx": 8, "ts_ms": 104_000, **aggro, "link_mob_id": OTHER, "link_distance": 6.0, "link_ms": 4000},
        # THIRD joins MOB, which linked and was never claimed; the crab beside it is of another kind.
        {
            "idx": 9,
            "ts_ms": 105_000,
            "mob_id": THIRD,
            **aggro,
            "link_mob_id": MOB,
            "link_distance": 2.0,
            "link_ms": 1000,
        },
        {
            "idx": 10,
            "ts_ms": 105_500,
            "mob_id": CRAB,
            **aggro,
            "link_mob_id": MOB,
            "link_distance": 3.0,
            "link_ms": 1500,
        },
        # Unprovoked, it goes for a stranger, who claims it.
        {"idx": 11, "ts_ms": 200_000, **stranger},
        # Two hares side by side aggro the character half a second apart: each an aggro, not a link.
        {"idx": 12, "ts_ms": 300_000, "mob_id": OTHER, **aggro},
        {"idx": 13, "ts_ms": 300_500, **aggro, "link_mob_id": OTHER, "link_distance": 4.0, "link_ms": 500},
        # A stranger pulls OTHER; MOB joins it 2 s later and goes for the stranger.
        {"idx": 14, "ts_ms": 400_000, "mob_id": OTHER, "other_ms": 500, **stranger},
        {
            "idx": 15,
            "ts_ms": 402_000,
            **stranger,
            "link_mob_id": OTHER,
            "link_distance": 5.0,
            "link_ms": 2000,
        },
    )
    got = records(
        con,
        "SELECT idx, kind, mob_name, mob_level, level_source, recorder_level, zone_type, clean"
        " FROM aggro ORDER BY idx",
    )
    assert [r["kind"] for r in got] == [
        "aggro_recorder",
        "aggro_party",
        "pull_recorder",
        "pull_party",
        "other",
        "other",
        "pull_party",
        "link",
        "link",
        "aggro_recorder",
        "aggro_other",
        "aggro_recorder",
        "aggro_recorder",
        "other",
        "link",
    ]
    assert tuple(got[0].values())[2:] == ("Forest Hare", 12, "widescan", 20, "outdoors", True)
    # The crab's fight was not the only one on; the first of the side by side hares is clean.
    assert [r["idx"] for r in got if r["clean"]] == [1, 12]


@pytest.mark.parametrize("action_ms, clean", [(2000, False), (2345, True)])
def test_a_whole_second_captures_aggro_counts_but_not_its_range(con, action_ms, clean):
    """A capture whose action packets all came on whole seconds is coarse; a captain log from 1.7 on carries
    milliseconds and counts."""
    engage = {"idx": 1, "ts_ms": 1000, "first_ms": 3000, "first_target_recorder": True}
    setup_engages(con, engage, fmt="captain", action_ms=action_ms)
    assert [(r["kind"], r["clean"]) for r in records(con, "SELECT kind, clean FROM aggro")] == [
        ("aggro_recorder", clean)
    ]
