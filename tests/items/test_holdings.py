"""What the character holds: a row per bag slot that changes, none for a zone-in's list of the same."""

from conftest import drive

from ffxi_extractors.extractors.items.holdings import Holdings


def item(op, bag, slot, item_id, count):
    return op, {"Category": bag, "ItemIndex": slot, "ItemNo": item_id, "ItemNum": count}


def test_a_slot_gives_a_row_when_it_changes_and_none_when_listed_again():
    got = drive(
        Holdings,
        item(0x020, 0, 1, 21173, 1),  # a zone-in's list: Malignance Pole in the inventory
        item(0x020, 1, 4, 4096, 12),  # and Fire Crystals in the Mog Safe
        item(0x020, 0, 1, 21173, 1),  # the next zone-in lists it again
        item(0x01E, 1, 4, 0, 11),  # a crystal used: a quantity alone
        item(0x01F, 0, 1, 0, 0),  # the pole leaves the slot
        item(0x020, 0, 1, 21173, 1),  # and comes back
    )["holdings"]
    assert [(r["container"], r["item_index"], r["item_id"]) for r in got] == [
        (0, 1, 21173),
        (1, 4, 4096),
        (0, 1, None),
        (0, 1, 21173),
    ]
