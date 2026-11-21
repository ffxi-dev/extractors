"""Fishing: each cast, its minigame, and its outcome; the catalog across captures. Packets are given as
decoded fields, shaped as retail sent them in 7L7PbiQJyutk and i_zaYdBG2fqK."""

from conftest import PLAYER, drive

from ffxi_extractors.extractors.items.fishing import Fishing

ZONE, ROD, BAIT, ICEFISH, GAVIAL = 111, 17386, 17399, 4470, 4477
BASE = 40018  # the zone's fishing messages start here: 'You didn't catch anything.' is BASE + 4
C2S = 1
GAME = {"stamina": 4462, "arrow_delay": 5, "regen": 128, "move_frequency": 11, "arrow_damage": 820,
        "arrow_regen": 410, "time": 40, "angler_sense": 0, "intuition": 18}  # fmt: skip


def said(n):
    return 0x036, {"UniqueNo": PLAYER, "MesNum": BASE + n}


def status(s):
    return 0x037, {"UniqueNo": PLAYER, "server_status": s}


def cast():
    return 0x01A, {"ActionID": 14}


def reel(para, para2=0):
    return 0x110, {"mode": 3, "para": para, "para2": para2}


def fish(*after):
    """A zone-in, the rod and bait equipped, then what follows."""
    steps = [
        (0x00A, {"ZoneNo": ZONE, "WeatherNumber": 12, "PosHead.x": 1.0, "PosHead.y": 2.0, "PosHead.z": 3.0}),
        (0x020, {"Category": 0, "ItemIndex": 26, "ItemNo": ROD, "ItemNum": 1}),
        (0x020, {"Category": 0, "ItemIndex": 57, "ItemNo": BAIT, "ItemNum": 12}),
        (0x050, {"EquipKind": 2, "Category": 0, "PropertyItemIndex": 26}),
        (0x050, {"EquipKind": 3, "Category": 0, "PropertyItemIndex": 57}),
        *after,
    ]
    directions = [C2S if op in (0x01A, 0x110) else 0 for op, _ in steps]
    return drive(Fishing, *steps, directions=directions)["fishing"]


def test_a_cast_with_the_bait_taken_off_has_no_bait():
    """Index 0 empties the slot, and inventory slot 0 holds the gil: the bait read as gil (65535)."""
    (row,) = fish(
        (0x020, {"Category": 0, "ItemIndex": 0, "ItemNo": 65535, "ItemNum": 1000}),
        (0x050, {"EquipKind": 3, "Category": 0, "PropertyItemIndex": 0}),
        cast(), said(4), status(62),
    )  # fmt: skip
    assert (row["rod_id"], row["bait_id"]) == (ROD, None)


def test_a_message_after_the_cast_ended_is_not_its_own():
    """A cast kept every 0x036 until the next one: a later line left a cast that caught nothing with two
    messages, which no longer read as the zone's 'nothing'."""
    first, later = fish(cast(), said(4), status(62), said(0x2C), cast(), said(8), (0x115, GAME), said(0x29))
    assert first["messages"] == [BASE + 4]
    assert (later["hook"], later["feeling"]) == ("small fish", "good")


def test_a_cast_its_minigame_and_its_catch():
    rows = fish(
        cast(), said(4), status(62),  # nothing bit: the zone's offset
        cast(), said(8), (0x115, GAME), said(0x2C), reel(0, 18), status(58),
        (0x027, {"UniqueNo": PLAYER, "MesNum": BASE + 0x0E, "Num1[0]": ICEFISH, "Num1[1]": 3}),
    )  # fmt: skip
    nothing, caught = rows
    assert (nothing["outcome"], nothing["hook_ms"], nothing["stamina"]) == ("nothing", None, None)
    assert (caught["zone_id"], caught["rod_id"], caught["bait_id"], caught["weather_id"]) == (
        ZONE,
        ROD,
        BAIT,
        12,
    )
    assert {k: caught[k] for k in GAME} == GAME
    got = ("hook", "feeling", "reel", "outcome", "item_id", "count")
    assert tuple(caught[k] for k in got) == ("small fish", "no skill", 0, "caught", ICEFISH, 3)
    assert caught["end_ms"] == caught["hook_ms"] + 3000


def test_an_item_given_up_a_line_break_and_a_keen_sense():
    rows = fish(
        cast(), said(4), status(62),
        cast(), said(0x33), (0x115, GAME), said(0x29), reel(200), said(0x24), status(62),
        cast(), said(0x32), (0x115, {**GAME, "angler_sense": 3}),
        (0x02A, {"UniqueNo": PLAYER, "MesNum": BASE + 0x35, "num[0]": GAVIAL}), reel(0), said(6), status(60),
    )  # fmt: skip
    got = [(r["hook"], r["feeling"], r["sensed_id"], r["outcome"], r["item_id"]) for r in rows[1:]]
    assert got == [
        ("item", "good", None, "gave up", None),
        ("large fish", "keen", GAVIAL, "line break", None),
    ]


def test_a_cast_refused_for_want_of_bait_gives_no_offset():
    # BL2awP8BSNmR: the zone's one cast with no bite was refused, no bait on (offset + 2); its bites, what
    # bit then a feeling, give the offset.
    bite = (cast(), said(8), (0x115, GAME), said(0x29), reel(0), status(58))
    caught = (0x027, {"UniqueNo": PLAYER, "MesNum": BASE + 0x27, "Num1[0]": ICEFISH, "Num1[1]": 6})
    rows = fish(cast(), said(2), *bite, caught, *bite, caught)
    assert [(r["outcome"], r["hook"], r["feeling"], r["item_id"]) for r in rows] == [
        ("nothing", None, None, None),
        ("caught", "small fish", "good", ICEFISH),
        ("caught", "small fish", "good", ICEFISH),
    ]


def test_with_no_offset_a_catch_is_an_item_the_inventory_gained():
    # With no cast that caught nothing and one message a bite, the zone's offset is unknown: the catch is what
    # 0x027 named only if the inventory gained it.
    bite = (cast(), said(8), (0x115, GAME), reel(0), status(58))
    named = (0x027, {"UniqueNo": PLAYER, "MesNum": BASE + 0x27, "Num1[0]": ICEFISH, "Num1[1]": 6})
    got = (0x020, {"Category": 0, "ItemIndex": 40, "ItemNo": ICEFISH, "ItemNum": 1})
    caught, other = fish(*bite, named, got, *bite, named)
    assert (caught["hook"], caught["outcome"], caught["item_id"], caught["count"]) == (
        None,
        "caught",
        ICEFISH,
        1,
    )
    assert (other["outcome"], other["item_id"]) == ("caught", None)


def test_a_quest_line_after_a_bite_is_no_catch():
    # FhjghXg75qEJ and BL2awP8BSNmR: a bite in zone 136 ends in a 0x027 at offset + 0x59 naming 1182,
    # which the inventory never gains: no fish was caught.
    bite = (cast(), said(8), (0x115, GAME), said(0x29), reel(0), status(58))
    quest = (0x027, {"UniqueNo": PLAYER, "MesNum": BASE + 0x59, "Num1[0]": 1182, "Num1[1]": 2})
    rows = fish(*bite, quest, *bite, quest)
    assert [(r["hook"], r["outcome"], r["item_id"]) for r in rows] == [("small fish", "caught", None)] * 2
