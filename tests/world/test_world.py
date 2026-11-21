from conftest import MOB, PLAYER, claim, drive

from ffxi_extractors.capture import Capture, Packet
from ffxi_extractors.extract import Sink
from ffxi_extractors.extractors.battle.kills import Kills
from ffxi_extractors.extractors.world.character import Character
from ffxi_extractors.extractors.world.entity_changes import EntityChanges
from ffxi_extractors.world import World, zone_of


def packet(op, idx=0, direction=0, data=b"\0" * 4):
    return Packet(idx, 1000 + idx, 0, direction, op, 0, data)


def fields(d):
    return d.get


def test_zone_from_entity_ids_before_the_first_zone_in():
    w = World(Capture("c", "30261006_0", "", 0, 0, 0))
    assert w.zone is None
    w.update(packet(0x00E), fields({"UniqueNo": 0x1000000 | (178 << 12) | 5, "ActIndex": 5}))
    assert w.zone == 178
    w.update(packet(0x00A, 1), fields({"ZoneNo": 230}))
    assert w.zone == 230
    w.update(packet(0x00E, 2), fields({"UniqueNo": 0x1000000 | (178 << 12) | 5, "ActIndex": 5}))
    assert w.zone == 230, "a zone-in wins over entity ids"


def test_player_ids_say_no_zone():
    assert zone_of(0x0004_0BB8) is None
    assert zone_of(0x0101_2005) == 0x012


def test_gear_names_its_item_from_the_inventory():
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    w.update(packet(0x020), fields({"ItemNum": 1, "ItemNo": 12345, "Category": 0, "ItemIndex": 7}))
    sink = Sink(Character(), "c", "v")
    p = packet(0x050, 1)
    f = fields({"EquipKind": 4, "Category": 0, "PropertyItemIndex": 7})
    w.update(p, f)
    Character().packet(p, f, w, sink.emit)
    row = sink.arrow()["character_gear"].to_pylist()[0]
    assert (row["slot"], row["item_id"], row["character_id"]) == ("head", 12345, 77)


def test_an_update_without_a_slot_has_no_slot():
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    sink = Sink(Character(), "c", "v")
    p, f = packet(0x050), fields({"Category": 0, "PropertyItemIndex": 0})
    Character().packet(p, f, w, sink.emit)
    assert sink.arrow()["character_gear"].to_pylist()[0]["slot"] is None


def test_a_resent_checkparam_gives_one_row():
    w = World(Capture("c", "v", "Me", PLAYER, 0, 0))
    x, sink = Character(), Sink(Character(), "c", "v")
    f = fields({"MessageNum": 712, "UniqueNoTar": PLAYER, "Data": 300, "Data2": 280})
    for i, ts in enumerate((1000, 1100)):
        x.packet(Packet(i, ts, 0, 0, 0x029, 0, b"the same packet"), f, w, sink.emit)
    assert len(sink.rows["character_params"]) == 1


def test_gear_sent_before_the_inventory_gets_its_item_later():
    """At login the gear (0x050) comes before the inventory lists (0x020)."""
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    x, sink = Character(), Sink(Character(), "c", "v")
    for p, d in (
        (packet(0x050, 1), {"EquipKind": 0, "Category": 8, "PropertyItemIndex": 3}),
        (packet(0x020, 2), {"ItemNum": 1, "ItemNo": 20515, "Category": 8, "ItemIndex": 3}),
    ):
        w.update(p, fields(d))
        x.packet(p, fields(d), w, sink.emit)
    assert sink.arrow()["character_gear"].to_pylist()[0]["item_id"] == 20515


def test_an_entity_keeps_its_first_update_and_each_change():
    """A row for the first update, then only for a new name, model, or monster flag; a part an update does
    not send keeps what an earlier one gave."""
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    x, sink = EntityChanges(), Sink(EntityChanges(), "c", "v")
    uid = 0x0100_0000 | (0x0A3 << 12) | 1
    for i, d in enumerate(
        (
            {
                "Data.name": "Goblin",
                "SubKind": 0,
                "Data.model_id": 7,
                "SendFlg.General": 1,
                "Flags1.MonsterFlag": 1,
            },
            {"SendFlg.Position": 1, "x": 1.5, "y": 2.0, "z": 0.0},  # moves: no row
            {"Data.name": "Goblin", "SubKind": 0, "Data.model_id": 8},  # a new model
            {"SubKind": 1},  # a humanoid look sends no model: no row
            {"UniqueNo": 99, "Data.name": "Bee"},  # another entity
            {"Data.name": "GoblinThug"},  # a new name
        )
    ):
        x.packet(packet(0x00E, i), fields({"UniqueNo": uid, "ActIndex": 1} | d), w, sink.emit)
    got = [
        (r["entity_id"], r["idx"], r["name"], r["model_id"], r["monster"])
        for r in sink.rows["entity_changes"]
    ]
    assert got == [(uid, 0, "Goblin", 7, True), (uid, 2, "Goblin", 8, True), (99, 4, "Bee", None, None),
                   (uid, 5, "GoblinThug", 8, True)]  # fmt: skip


def test_a_player_is_an_entity_by_its_own_update():
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    x, sink = EntityChanges(), Sink(EntityChanges(), "c", "v")
    x.packet(packet(0x00D), fields({"UniqueNo": PLAYER, "name": "Kupipi"}), w, sink.emit)
    x.packet(packet(0x00D, 1), fields({"UniqueNo": PLAYER, "name": "Kupipi"}), w, sink.emit)
    assert [(r["entity_id"], r["name"]) for r in sink.rows["entity_changes"]] == [(PLAYER, "Kupipi")]


# A captain log has no zone-in, so the capture names no character (0): its status, 0x037, does.
STATUS = (0x037, {"UniqueNo": PLAYER})


def test_a_captain_log_names_the_character_by_its_status():
    w = World(Capture("c", "Version 16:42:16 Apr  1 2026", "", 0, 0, 0))
    w.update(packet(0x037), fields({"UniqueNo": PLAYER}))
    assert w.character_id == PLAYER
    w.update(packet(0x037, 1), fields({}))
    assert w.character_id == PLAYER, "a status without an id keeps the one known"


def test_a_captain_log_counts_the_characters_claims_and_checkparam():
    defeat = (0x029, {"UniqueNoCas": PLAYER, "UniqueNoTar": MOB, "MessageNum": 6})
    rows = drive(Kills, STATUS, claim(PLAYER), defeat, me=0)["kills"]
    assert [r["claimed_by_party"] for r in rows] == [True]
    check = (0x029, {"MessageNum": 712, "UniqueNoTar": PLAYER, "Data": 300, "Data2": 280})
    (p,) = drive(Character, STATUS, check, me=0)["character_params"]
    assert (p["character_id"], p["kind"], p["accuracy"]) == (PLAYER, "main", 300)


def test_the_party_follows_its_lists_and_roster():
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    w.update(packet(0x0E2), fields({"UniqueNo": 99}))
    assert w.claimed_by_party(99), "0x0E2 lists a member as 0x0DD does"
    w.update(packet(0x0C8, 1), fields({"GroupTbl[0].UniqueNo": 77, "GroupTbl[1].UniqueNo": 0}))
    assert not w.claimed_by_party(99), "the roster no longer lists it"


def test_an_emptied_slot_waits_for_its_next_item():
    """0x01E sends a slot's quantity; at zero the slot's old item is gone."""
    w = World(Capture("c", "v", "Me", 77, 0, 0))
    x, sink = Character(), Sink(Character(), "c", "v")
    for p, d in (
        (packet(0x020), {"ItemNum": 1, "ItemNo": 111, "Category": 8, "ItemIndex": 3}),
        (packet(0x01E, 1), {"ItemNum": 0, "Category": 8, "ItemIndex": 3}),
        (packet(0x050, 2), {"EquipKind": 0, "Category": 8, "PropertyItemIndex": 3}),
        (packet(0x020, 3), {"ItemNum": 1, "ItemNo": 222, "Category": 8, "ItemIndex": 3}),
    ):
        w.update(p, fields(d))
        if (p.direction, p.opcode) in x.reads:
            x.packet(p, fields(d), w, sink.emit)
    assert sink.arrow()["character_gear"].to_pylist()[0]["item_id"] == 222
