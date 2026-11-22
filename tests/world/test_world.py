"""The extractors that read the world's packets as the world keeps them; the world's own tests are
rust/xc-core's world.rs."""

from conftest import MOB, PLAYER, claim, drive

from ffxi_extractors.extractors.battle.kills import Kills
from ffxi_extractors.extractors.world.character import Character
from ffxi_extractors.extractors.world.entity_changes import EntityChanges


def test_gear_names_its_item_from_the_inventory():
    inventory = (0x020, {"ItemNum": 1, "ItemNo": 12345, "Category": 0, "ItemIndex": 7})
    gear = (0x050, {"EquipKind": 4, "Category": 0, "PropertyItemIndex": 7})
    (row,) = drive(Character, inventory, gear, me=77)["character_gear"]
    assert (row["slot"], row["item_id"], row["character_id"]) == ("head", 12345, 77)


def test_an_update_without_a_slot_has_no_slot():
    (row,) = drive(Character, (0x050, {"Category": 0, "PropertyItemIndex": 0}), me=77)["character_gear"]
    assert row["slot"] is None


def test_gear_sent_before_the_inventory_gets_its_item_later():
    """At login the gear (0x050) comes before the inventory lists (0x020)."""
    rows = drive(
        Character,
        (0x050, {"EquipKind": 0, "Category": 8, "PropertyItemIndex": 3}),
        (0x020, {"ItemNum": 1, "ItemNo": 20515, "Category": 8, "ItemIndex": 3}),
        me=77,
    )["character_gear"]
    assert rows[0]["item_id"] == 20515


def test_an_entity_keeps_its_first_update_and_each_change():
    """A row for the first update, then only for a new name, model, or monster flag; a part an update does
    not send keeps what an earlier one gave."""
    uid = 0x0100_0000 | (0x0A3 << 12) | 1
    updates = (
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
    rows = drive(EntityChanges, *((0x00E, {"UniqueNo": uid, "ActIndex": 1} | d) for d in updates), me=77)
    got = [(r["entity_id"], r["idx"], r["name"], r["model_id"], r["monster"]) for r in rows["entity_changes"]]
    assert got == [(uid, 0, "Goblin", 7, True), (uid, 2, "Goblin", 8, True), (99, 4, "Bee", None, None),
                   (uid, 5, "GoblinThug", 8, True)]  # fmt: skip


def test_a_player_is_an_entity_by_its_own_update():
    kupipi = (0x00D, {"UniqueNo": PLAYER, "name": "Kupipi"})
    rows = drive(EntityChanges, kupipi, kupipi, me=77)["entity_changes"]
    assert [(r["entity_id"], r["name"]) for r in rows] == [(PLAYER, "Kupipi")]


# A captain log has no zone-in, so the capture names no character (0): its status, 0x037, does.
STATUS = (0x037, {"UniqueNo": PLAYER})


def test_a_captain_log_counts_the_characters_claims_and_checkparam():
    defeat = (0x029, {"UniqueNoCas": PLAYER, "UniqueNoTar": MOB, "MessageNum": 6})
    rows = drive(Kills, STATUS, claim(PLAYER), defeat, me=0)["kills"]
    assert [r["claimed_by_party"] for r in rows] == [True]
    check = (0x029, {"MessageNum": 712, "UniqueNoTar": PLAYER, "Data": 300, "Data2": 280})
    (p,) = drive(Character, STATUS, check, me=0)["character_params"]
    assert (p["character_id"], p["kind"], p["accuracy"]) == (PLAYER, "main", 300)


def test_an_emptied_slot_waits_for_its_next_item():
    """0x01E sends a slot's quantity; at zero the slot's old item is gone."""
    rows = drive(
        Character,
        (0x020, {"ItemNum": 1, "ItemNo": 111, "Category": 8, "ItemIndex": 3}),
        (0x01E, {"ItemNum": 0, "Category": 8, "ItemIndex": 3}),
        (0x050, {"EquipKind": 0, "Category": 8, "PropertyItemIndex": 3}),
        (0x020, {"ItemNum": 1, "ItemNo": 222, "Category": 8, "ItemIndex": 3}),
        me=77,
    )["character_gear"]
    assert rows[0]["item_id"] == 222
