"""Steal, Mug, and Despoil; chocobo digs; synthesis results. Packets are given as decoded fields."""

from conftest import PLAYER, drive

from ffxi_extractors.extractors.items.digs import Digs
from ffxi_extractors.extractors.items.synths import Synths

GREENS, PEBBLE, HINT = 4545, 17296, 3
ZONE = 117
C2S = 1


def slot(op, index, item, count):
    return op, {"Category": 0, "ItemIndex": index, "ItemNo": item, "ItemNum": count}


def told(number, message=40109):
    return 0x02A, {"UniqueNo": PLAYER, "MesNum": message, "num[0]": number}


def dig(*after):
    """A zone-in in sunshine, greens and a pebble held, a position, then a dig and what follows it."""
    steps = [
        (0x00A, {"ZoneNo": ZONE, "WeatherNumber": 1, "PosHead.x": 1.0, "PosHead.y": 2.0, "PosHead.z": 3.0}),
        slot(0x020, 5, GREENS, 12),
        slot(0x020, 9, PEBBLE, 1),
        (0x015, {"x": 10.0, "y": 20.0, "z": 30.0}),
        (0x063, {}),
        *after,
    ]
    directions = [C2S if op in (0x015, 0x063) else 0 for op, _ in steps]
    times = [i * 1000 for i in range(5)] + [4000 + 200 * (k + 1) for k in range(len(after))]  # inside 3 s
    return drive(Digs, *steps, times=times, directions=directions)["digs"]


def test_a_dig_finds_the_item_a_message_named_that_the_inventory_gained():
    # A hint whose number is no item, the greens eaten, 'Obtained: Pebble', and the pebble's count rising.
    (row,) = dig(
        told(HINT, 40109),
        (0x01E, {"Category": 0, "ItemIndex": 5, "ItemNum": 11}),
        told(PEBBLE, 39344),
        (0x01E, {"Category": 0, "ItemIndex": 9, "ItemNum": 2}),
    )
    assert (row["item_id"], row["zone_id"], row["weather_id"]) == (PEBBLE, ZONE, 1)
    assert (row["x"], row["y"], row["z"]) == (10.0, 20.0, 30.0)


def test_a_dig_that_finds_nothing():
    # The greens go, a hint names a number, and an item the dig did not name enters the inventory.
    (row,) = dig((0x01E, {"Category": 0, "ItemIndex": 5, "ItemNum": 11}), told(HINT), slot(0x020, 12, 515, 1))
    assert row["item_id"] is None


def test_the_characters_synthesis_and_someone_elses():
    # Retail leaves BreakNo as an earlier synthesis set it: a success still names what that one lost, and a
    # failure may name an item that is no ingredient of this one.
    own = {"Result": 0, "Grade": 1, "Count": 1, "ItemNo": 16465, "UpKind[0]": 50, "UpLevel[0]": 2,
           "CrystalNo": 4096, "MaterialNo[0]": 8819, "BreakNo[0]": 1218}  # fmt: skip
    failed = {"Result": 1, "Grade": -1, "ItemNo": 29695, "BreakNo[0]": 8819, "BreakNo[1]": 1223,
              "CrystalNo": 4096, "MaterialNo[0]": 8819}  # fmt: skip
    other = {"Result": 0, "Count": 1, "ItemNo": 16465, "name": "Nours", "BreakNo[0]": 645}
    # Retail's 14 (LSB's critical interruption) made an HQ2; its 10 failed.
    lost = {"Result": 10, "Grade": -1, "ItemNo": 29695, "name": "Nours", "BreakNo[0]": 645}
    made = {"Result": 14, "Grade": 2, "Count": 1, "ItemNo": 745, "name": "Nours", "BreakNo[0]": 645}
    # Smithing 12, its rank 1, at its rank's cap (bit 15); goldsmithing, which this one does not train, 30.
    skills = {"skill_base[50]": 0x8000 | (12 << 5) | 1, "skill_base[51]": 30 << 5}
    # Retail tells of a skill-up that reaches a level, and sends the 0x062 that shows it, before the result:
    # the skill before it is one under. The next synthesis starts at the new level.
    reached = {"MessageNum": 53, "Data": 50, "Data2": 13}
    again = {"Result": 0, "Grade": 0, "Count": 1, "ItemNo": 16465, "UpKind[0]": 50}
    raised = {"skill_base[50]": 13 << 5}
    steps = ((0x062, skills), (0x029, reached), (0x062, raised), (0x06F, own), (0x06F, again),
             (0x06F, failed), (0x070, other), (0x070, lost), (0x070, made))  # fmt: skip
    got = drive(Synths, *steps)["synths"]
    keys = (
        "own",
        "crafter",
        "outcome",
        "grade",
        "item_id",
        "crystal_id",
        "ingredients",
        "lost",
        "skill_kinds",
        "skill_levels",
        "skills",
    )
    assert [tuple(r[k] for k in keys) for r in got] == [
        (True, "Me", "success", 1, 16465, 4096, [8819], [], [50], [2], [12]),
        (True, "Me", "success", 0, 16465, None, [], [], [50], [0], [13]),
        (True, "Me", "failed", -1, 29695, 4096, [8819], [8819], [], [], []),
        (False, "Nours", "success", None, 16465, None, None, [], None, None, None),
        (False, "Nours", "failed", -1, 29695, None, None, [645], None, None, None),
        (False, "Nours", None, 2, 745, None, None, [], None, None, None),
    ]
