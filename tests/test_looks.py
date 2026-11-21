"""How a mob looks and moves: each entity's states from its updates, and a mob page's sums of them."""

from conftest import drive
from fill import put

from ffxi_extractors.extractors import Looks
from ffxi_extractors.index import run

ZONE = 0x0A3
MOB = 0x01000000 | (ZONE << 12) | 0x010
PAL = MOB + 1


def update(uid, **fields):
    return 0x00E, {"UniqueNo": uid, **fields}


def test_a_state_holds_the_speeds_flags_and_model_last_sent_and_counts_its_updates():
    walk = {"SendFlg.Position": 1, "Speed": 40, "SpeedBase": 40}
    general = {"SendFlg.General": 1, "server_status": 0, "Flags1.MonsterFlag": 1, "Flags2.g": 12}
    steps = [
        (0x00A, {"ZoneNo": ZONE}),
        update(
            MOB, **walk, **general, **{"SendFlg.Name": 1, "SubKind": 0, "Status": 0, "Data.model_id": 291}
        ),
        update(MOB, **walk),  # the same state: no flags sent, the last kept
        update(MOB, **{**walk, "Speed": 100}, **{**general, "server_status": 1}),  # it runs at a target
        update(MOB, **{"SendFlg.Despawn": 1}),  # a despawn sends no state
        update(
            PAL,
            **{"SendFlg.Model": 1, "SubKind": 1, "Status": 0},
            **{f"Data.GrapIDTbl[{i}]": i for i in range(9)},
        ),
    ]
    rows = drive(Looks, *steps)["entity_looks"]
    got = [(r["entity_id"], r["speed"], r["speed_base"], r["animation"], r["flags"], r["model_id"], r["look"],
            r["updates"]) for r in rows]  # fmt: skip
    assert got == [
        (MOB, 40, 40, 0, ["Flags1.MonsterFlag=1", "Flags2.g=12"], 291, None, 2),
        (MOB, 100, 40, 1, ["Flags1.MonsterFlag=1", "Flags2.g=12"], 291, None, 1),
        (PAL, None, None, None, [], None, list(range(9)), 1),
    ]


def looks(con, capture, *, listed):
    base = {"capture_id": capture, "client_version": "v", "zone_id": ZONE}
    put(con, "captures", [{"capture_id": capture, "client_version": "v", "release": "r", "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    put(con, "entity_changes", [{**base, "idx": 0, "ts_ms": 0, "entity_id": e, "name": "Goblin Thug"}
                                for e in (MOB, PAL)])  # fmt: skip
    mon = ["Flags1.MonsterFlag=1", "Flags2.NamedFlag=1", "Flags2.g=12"]  # sorted, as the extractor keeps them
    put(con, "entity_looks", [
        {**base, "idx": 1, "ts_ms": 1, "entity_id": MOB, "speed": 40, "speed_base": 40, "animation": 0,
         "flags": mon, "model_id": 291, "updates": 90},
        {**base, "idx": 2, "ts_ms": 2, "entity_id": MOB, "speed": 100, "speed_base": 40, "animation": 1,
         "flags": mon, "model_id": 291, "updates": 10},
        {**base, "idx": 3, "ts_ms": 3, "entity_id": PAL, "speed": 40, "speed_base": 40, "animation": 0,
         "flags": [], "model_id": 291, "updates": 50},  # no monster flag: not the mob's
    ])  # fmt: skip
    if listed is not None:
        put(con, "levels", [{**base, "idx": 4, "ts_ms": 4, "entity_id": MOB if listed else PAL,
                             "level": 10, "source": "widescan"}])  # fmt: skip
    run(con, None, capture, units={"bestiary_looks"})
