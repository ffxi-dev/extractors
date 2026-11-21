"""Draw-ins and blue magic learned: their mob, the move a spell ties to, the marks and the mob card."""

from conftest import PLAYER
from fill import ask, put

from ffxi_extractors.index import run

ZONE = 0x0A3
MOB = 0x01000000 | (ZONE << 12) | 0x010
SHEEP_SONG, SHEEP_SKILL, RAGE = 584, 264, 261


def mob(uid, x, monster=1):
    flags = {"SendFlg.General": 1, "SendFlg.Position": 1, "Flags1.MonsterFlag": monster}
    return 0x00E, {"UniqueNo": uid, **flags, "x": x, "y": 0.0, "z": 0.0}


def message(number, who=PLAYER, data=0):
    return 0x029, {"UniqueNoCas": who, "UniqueNoTar": who, "MessageNum": number, "Data": data}


def setup(con, capture, *, learned=True, ts=10_000):
    base = {"capture_id": capture, "client_version": "v"}
    put(con, "captures", [{**base, "release": "r", "retail": True, "packets": 0, "start_ms": 0}])
    put(con, "entity_changes", [{**base, "idx": 0, "ts_ms": 0, "entity_id": MOB, "name": "Fluffy Sheep"}])
    put(con, "fights", [{**base, "idx": 1, "ts_ms": 1000, "mob_id": MOB, "end_idx": 5, "end_ms": ts,
                         "outcome": "defeated", "zone_id": ZONE}])  # fmt: skip
    move = {**base, "actor_id": MOB, "category": 11, "resend": False}
    put(con, "actions", [{**move, "idx": 2, "ts_ms": 2000, "action_id": RAGE},
                         {**move, "idx": 3, "ts_ms": 3000, "action_id": SHEEP_SKILL}])  # fmt: skip
    put(con, "kills", [{**base, "idx": 5, "ts_ms": ts, "mob_id": MOB, "message": 6, "zone_id": ZONE}])
    rows = [{**base, "idx": 4, "ts_ms": 4000, "kind": "drawn_in", "player_id": PLAYER, "mob_id": MOB,
             "distance": 1.5, "zone_id": ZONE}]  # fmt: skip
    if learned:
        rows.append({**base, "idx": 6, "ts_ms": ts + 2, "kind": "learned", "player_id": PLAYER,
                     "spell_id": SHEEP_SONG, "zone_id": ZONE})  # fmt: skip
    put(con, "mob_messages", rows)
    run(con, None, capture, units={"mob_events"})


NAMES = [
    {"release": "r", "kind": "spell", "log_id": 0, "id": SHEEP_SONG, "name": "Sheep Song"},
    {"release": "r", "kind": "mob_skill", "log_id": 0, "id": SHEEP_SKILL, "name": "Sheep Song"},
    {"release": "r", "kind": "mob_skill", "log_id": 0, "id": RAGE, "name": "Rage"},
]


def test_the_mob_card_counts_a_draw_in_two_recorders_saw_once(con):
    put(con, "names", NAMES)
    setup(con, "a")
    setup(con, "b", learned=False)  # a party member's copy of the same draw-in
    got = ask(con, "bestiary_events", zone=ZONE, name="Fluffy Sheep")
    assert [(r["kind"], r["skill"], r["spell_name"], r["n"]) for r in got] == [
        ("drawn_in", None, None, 1),
        ("learned", SHEEP_SKILL, "Sheep Song", 1),
    ]
