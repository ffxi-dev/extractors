"""capture_finds: what a capture showed, for the capture points. A mob counts only when the capture fought,
checked, or widescanned it; a sample keeps its fight, so a party's copies count once."""

from conftest import rows
from fill import put

from ffxi_extractors.index import run

ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x030
NPC = 0x01000000 | (ZONE << 12) | 0x500
TRUST = 0x01000000 | (ZONE << 12) | 0x710
FIRE, BLIZZARD, CYCLONE = 144, 149, 386


def use(idx, skill, ready):
    return {"idx": idx, "id": skill, "targets": 1, "reach": None, "spread": None, "size": None, "hit": None,
            "crit": None, "kb": 0, "ready": ready, "near": [], "rules_out": [0, 0, 0, 0], "shadows": None,
            "shadow_exact": None, "through": None}  # fmt: skip


def test_a_capture_counts_what_it_fought_checked_and_saw(con):
    capture = {"capture_id": "a", "client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [capture])
    put(con, "zones", [{"capture_id": "a", "idx": 1, "ts_ms": 100, "client_version": "v", "zone_id": ZONE}])
    seen = {"capture_id": "a", "client_version": "v", "monster": True}
    put(con, "named_entities", [
        {**seen, "idx": 2, "ts_ms": 200, "entity_id": MOB, "entity_name": "Goblin Thug"},  # fought
        {**seen, "idx": 3, "ts_ms": 300, "entity_id": MOB + 1, "entity_name": "Bat"},  # checked
        {**seen, "idx": 4, "ts_ms": 400, "entity_id": MOB + 2, "entity_name": "Crab"},  # walked past
        {**seen, "idx": 5, "ts_ms": 500, "entity_id": NPC, "entity_name": "Moogle", "monster": False},
        {**seen, "idx": 6, "ts_ms": 600, "entity_id": TRUST, "entity_name": "Shantotto", "monster": False},
    ])  # fmt: skip
    put(con, "levels", [{"capture_id": "a", "idx": 7, "ts_ms": 700, "client_version": "v",
                         "entity_id": MOB + 1, "level": 10, "source": "check", "zone_id": ZONE}])  # fmt: skip
    fight = {"capture_id": "a", "client_version": "v", "zone_id": ZONE, "mob_id": MOB,
             "mob_name": "Goblin Thug", "end_idx": 100, "outcome": "defeated", "claimed": True,
             "coarse": False}  # fmt: skip
    put(con, "bestiary_fights", [
        {**fight, "idx": 10, "ts_ms": 1000, "fight_key": 7, "spells": [FIRE], "idle_spells": [BLIZZARD],
         "rounds": [{"swings": 1, "main_hand": 1, "off_hand": 0, "kicks": 0}] * 3,
         "tp": [use(11, CYCLONE, 1500), use(12, CYCLONE, None)],
         "drops": [{"item": 4096, "slot": 0, "start_time": 0, "idx": 13}]},
        {**fight, "idx": 20, "ts_ms": 2000, "fight_key": None, "claimed": False,
         "tp": [use(21, CYCLONE, 900)]},
    ])  # fmt: skip
    run(con, None, "a", units={"capture_finds"})
    got = rows(con, "SELECT kind, zone_id, subject, thing, fight_key, idx, n FROM capture_finds"
                    " ORDER BY kind, idx, thing")  # fmt: skip
    own = rows(con, "SELECT cityHash64('a', toInt64(20))")[0][0]
    assert got == [
        ("drop", ZONE, "Goblin Thug", 4096, 0, 10, 1),
        ("kill", ZONE, "Goblin Thug", 0, 7, 10, 1),  # the second fight's mob was not claimed
        ("mob", ZONE, "Goblin Thug", 0, 0, 2, 1),
        ("mob", ZONE, "Bat", 0, 0, 3, 1),  # the crab, only seen, is not here
        ("npc", ZONE, "Moogle", 0, 0, 5, 1),  # a trust, past 0x700, is not
        ("rounds", ZONE, "Goblin Thug", 0, 7, 10, 3),
        ("spell", ZONE, "Goblin Thug", FIRE, 0, 10, 1),
        ("spell", ZONE, "Goblin Thug", BLIZZARD, 0, 10, 1),
        ("tp", ZONE, "Goblin Thug", CYCLONE, 0, 10, 3),
        ("tp_ready", ZONE, "Goblin Thug", CYCLONE, 7, 10, 1),  # the use with no ready time is no sample
        ("tp_ready", ZONE, "Goblin Thug", CYCLONE, own, 20, 1),  # a fight with no key keys itself
        ("zone", ZONE, "", 0, 0, 1, 1),
    ]
