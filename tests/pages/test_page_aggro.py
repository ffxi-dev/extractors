"""Mob aggro: engages and passes from the packets, sorted by what started them, and the mob card's figures.
Packets are given as decoded fields."""

from fill import ask, put

from ffxi_extractors.index import run

ZONE = 104  # Jugner Forest: outdoors
MOB, OTHER, THIRD, CRAB = (0x01000000 | (ZONE << 12) | i for i in (0x020, 0x021, 0x022, 0x023))


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


def test_the_mob_card_counts_an_aggro_two_recorders_saw_once(con):
    one = {"idx": 1, "ts_ms": 61_000, "first_ms": 3000, "first_target_party": True}
    setup_engages(con, {**one, "first_target_recorder": True, "facing": 10.0}, capture="a")
    setup_engages(con, {**one, "ts_ms": 61_300, "first_target_recorder": False}, capture="b")
    put(
        con,
        "mob_passes",
        [
            {
                "capture_id": "b",
                "idx": 9,
                "ts_ms": 90_000,
                "client_version": "v",
                "zone_id": ZONE,
                "mob_id": MOB,
                "distance": 11.0,
                "sneak": True,
            }
        ],
    )
    run(con, None, "b", units={"aggro_passes"})
    got = ask(con, "bestiary_aggro", zone=ZONE, name="Forest Hare")
    assert sorted((r["kind"], r["distance"], r["gap"]) for r in got) == [
        ("aggro_recorder", 8.0, -8),
        ("pass", 11.0, -8),
    ]
