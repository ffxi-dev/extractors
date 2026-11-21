"""Draw-ins and blue magic learned: their mob, the move a spell ties to, the marks and the mob card."""

from conftest import MEMBER, PLAYER, drive

from ffxi_extractors.extractors.battle.mob_messages import MobMessages

ZONE = 0x0A3
MOB = 0x01000000 | (ZONE << 12) | 0x010
OTHER = MOB + 1
SHEEP_SONG, SHEEP_SKILL, RAGE = 584, 264, 261


def mob(uid, x, monster=1):
    flags = {"SendFlg.General": 1, "SendFlg.Position": 1, "Flags1.MonsterFlag": monster}
    return 0x00E, {"UniqueNo": uid, **flags, "x": x, "y": 0.0, "z": 0.0}


def message(number, who=PLAYER, data=0):
    return 0x029, {"UniqueNoCas": who, "UniqueNoTar": who, "MessageNum": number, "Data": data}


def test_a_draw_in_names_the_monster_nearest_where_the_player_landed():
    steps = [
        (0x00A, {"ZoneNo": ZONE}),
        mob(MOB, 0.0),
        mob(OTHER, 20.0),
        mob(OTHER + 1, 1.0, monster=0),  # an NPC beside the player is no monster
        message(232),
        (0x015, {"x": 19.0, "y": 1.0, "z": 0.0}),  # the character lands beside OTHER
        message(232, MEMBER),
        (0x00D, {"UniqueNo": MEMBER, "SendFlg.Position": 1, "x": 0.5, "y": 0.0, "z": 0.0}),
        message(232, MEMBER),  # drawn in again, but its next position comes too late
        (0x00D, {"UniqueNo": MEMBER, "SendFlg.Position": 1, "x": 0.5, "y": 0.0, "z": 0.0}),
        message(419, data=SHEEP_SONG),
    ]
    times = [0, 0, 0, 0, 1000, 1100, 2000, 2200, 3000, 7000, 8000]
    directions = [1 if op == 0x015 else 0 for op, _ in steps]
    rows = drive(MobMessages, *steps, times=times, directions=directions)["mob_messages"]
    got = [(r["kind"], r["player_id"], r.get("mob_id"), r.get("distance"), r.get("spell_id")) for r in rows]
    assert got == [
        ("drawn_in", PLAYER, OTHER, 2**0.5, None),
        ("drawn_in", MEMBER, MOB, 0.5, None),
        ("drawn_in", MEMBER, None, None, None),
        ("learned", PLAYER, None, None, SHEEP_SONG),
    ]


def test_a_trust_drawn_in_lands_by_its_own_update_and_no_trust_draws_in():
    trust, other = 0x01000000 | (ZONE << 12) | 0x700, 0x01000000 | (ZONE << 12) | 0x701
    steps = [
        (0x00A, {"ZoneNo": ZONE}),
        mob(MOB, 0.0),
        mob(other, 9.0),  # another trust, flagged a monster, beside where the trust lands
        message(232, trust),
        mob(trust, 9.5),
    ]
    (row,) = drive(MobMessages, *steps)["mob_messages"]
    assert (row["player_id"], row.get("mob_id"), row.get("distance")) == (trust, MOB, 9.5)
