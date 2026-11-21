"""The character's status effects (0x063 type 9 beside 0x028), its defeats, and the items it and its party
used. Packets are given as decoded fields."""

from conftest import MEMBER, PLAYER, drive
from fill import ask, put

from ffxi_extractors.extractors.battle.effects import Effects

ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x020
POISON, FOOD, PROTECT = 3, 251, 40


def effects(*steps, times):
    return drive(Effects, *steps, times=times)["effects"]


def capture(con, cid="e"):
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "release": "r", "retail": True,
                           "packets": 0, "character_id": PLAYER, "character": "Me"}])  # fmt: skip
    put(con, "party", [{"capture_id": cid, "idx": 0, "ts_ms": 0, "client_version": "v", "member_id": MEMBER,
                        "name": "Nours"}])  # fmt: skip
    name = {"release": "r", "log_id": 0}
    put(con, "names", [
        {**name, "kind": "status", "id": POISON, "name": "Poison"},
        {**name, "kind": "status", "id": FOOD, "name": "Food"},
        {**name, "kind": "mob_skill", "id": 392, "name": "Jet Stream"},
        {**name, "kind": "item", "id": 4422, "name": "Orange Juice"},
        {**name, "kind": "item", "id": 4112, "name": "Potion"},
    ])  # fmt: skip


def test_the_mob_card_gives_each_moves_effect_and_its_usual_duration(con):
    capture(con, "a")
    capture(con, "b")
    put(con, "capture_trust", [{"capture_id": "b", "trust": "flagged", "at": 0}])
    # The card asks by the mob's name as its fights have it; the packet squashes it (Codex's review, 12).
    fight = {"zone_id": ZONE, "mob_id": MOB, "mob_name": "Locus Dire Bat"}
    put(con, "bestiary_fights", [{**fight, "capture_id": c} for c in "ab"])
    row = {"client_version": "v", "zone_id": ZONE, "actor_id": MOB, "actor_name": "LocusDireBat",
           "category": 11, "action_id": 392, "status_id": POISON}  # fmt: skip
    durations = [("a", 180_100), ("a", 179_900), ("a", 90_000), ("b", 30_000)]
    put(con, "effects", [{**row, "capture_id": c, "idx": i, "ts_ms": i, "duration_ms": d}
                         for i, (c, d) in enumerate(durations)])  # fmt: skip
    other = {**row, "actor_id": MOB + 1, "capture_id": "a", "idx": 9, "ts_ms": 9, "duration_ms": 5}
    put(con, "effects", [other])  # another mob of the same packet name
    (r,) = ask(con, "bestiary_effects", zone=ZONE, name="Locus Dire Bat")
    assert (r["source_name"], r["status_name"], r["n"], r["usual_s"], r["lo"], r["hi"]) == (
        "Jet Stream", "Poison", 3, 180, 90_000, 180_100,
    )  # fmt: skip
