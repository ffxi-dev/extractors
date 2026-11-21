"""How a mob looks and moves: each entity's states from its updates, and a mob page's sums of them."""

from fill import ask, put

from ffxi_extractors.index import run

ZONE = 0x0A3
MOB = 0x01000000 | (ZONE << 12) | 0x010
PAL = MOB + 1


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


def test_a_mob_page_sums_its_looks_over_every_capture(con):
    looks(con, "a", listed=True)
    looks(con, "b", listed=False)  # widescanned, but the mob was not listed
    looks(con, "c", listed=None)  # never widescanned
    got = {(r["kind"], tuple(r["key"])): (r["updates"], r["mobs"], r["captures"])
           for r in ask(con, "bestiary_looks", zone=ZONE, name="Goblin Thug")}  # fmt: skip
    assert got == {
        ("speed", ("40", "40", "0")): (270, 1, 3),
        ("speed", ("100", "40", "1")): (30, 1, 3),
        ("model", ("291", "")): (300, 1, 3),
        ("animation", ("0",)): (270, 1, 3),
        ("animation", ("1",)): (30, 1, 3),
        ("flag", ("Flags1.MonsterFlag=1",)): (300, 1, 3),
        ("flag", ("Flags2.NamedFlag=1",)): (300, 1, 3),
        ("flag", ("Flags2.g=12",)): (300, 1, 3),
        ("flags", ("Flags1.MonsterFlag=1", "Flags2.NamedFlag=1", "Flags2.g=12")): (300, 1, 3),
        ("widescan", ("1",)): (0, 0, 1),
        ("widescan", ("0",)): (0, 0, 1),
    }
