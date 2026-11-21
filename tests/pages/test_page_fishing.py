"""Fishing: each cast, its minigame, and its outcome; the catalog across captures. Packets are given as
decoded fields, shaped as retail sent them in 7L7PbiQJyutk and i_zaYdBG2fqK."""

from conftest import drive
from fill import ask, put

from ffxi_extractors.extractors.items.fishing import Fishing

ZONE, ROD, BAIT, ICEFISH, GAVIAL = 111, 17386, 17399, 4470, 4477
C2S = 1
GAME = {"stamina": 4462, "arrow_delay": 5, "regen": 128, "move_frequency": 11, "arrow_damage": 820,
        "arrow_regen": 410, "time": 40, "angler_sense": 0, "intuition": 18}  # fmt: skip


def cast():
    return 0x01A, {"ActionID": 14}


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


def catch(capture, idx, item, rod=ROD, stamina=4462, count=1, **more):
    return {"capture_id": capture, "idx": idx, "ts_ms": idx * 1000, "client_version": "v", "zone_id": ZONE,
            "rod_id": rod, "bait_id": BAIT, "weather_id": 12, "vana_hour": 6, "vana_weekday": 2,
            "moon_phase": 47, "hook_ms": idx * 1000, "end_ms": idx * 1000 + 5000, "outcome": "caught",
            "item_id": item, "count": count, **GAME, "stamina": stamina, **more}  # fmt: skip


def test_the_catalog_gives_each_fish_its_minigame_by_rod_and_where_and_when_it_bit(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in ("a", "b", "x")])
    put(con, "capture_trust", [{"capture_id": "x", "trust": "flagged"}])
    name = {"release": "r", "log_id": 0}
    put(con, "names", [{**name, "kind": "item", "id": ICEFISH, "name": "Icefish"},
                       {**name, "kind": "item", "id": ROD, "name": "Lu Shang's Fishing Rod"},
                       {**name, "kind": "zone", "id": ZONE, "name": "Beaucedine Glacier"}])  # fmt: skip
    put(con, "fishing", [
        catch("a", 1, ICEFISH, stamina=4200), catch("b", 2, ICEFISH, stamina=4400),
        catch("b", 3, ICEFISH, stamina=5200, count=3),  # a multiple catch: not in the skill estimate
        catch("x", 4, ICEFISH, stamina=9999),  # flagged
        {**catch("a", 5, None), "outcome": "gave up"},  # no catch: not in the catalog
    ])  # fmt: skip
    (fish,) = ask(con, "fishing_catalog")
    assert (fish["name"], fish["n"], fish["captures"], fish["sense"], fish["skill"]) == (
        "Icefish",
        3,
        2,
        [0],
        50,
    )
    rod, n, avg, s_lo, s_hi, d_lo, d_hi = 0, 2, 3, 4, 5, 6, 7
    single, many = fish["params"]
    assert (single[rod], single[1], single[n], single[avg], single[s_lo], single[s_hi]) == (
        ROD,
        1,
        2,
        4300,
        4200,
        4400,
    )
    assert (many[1], many[n], many[s_lo], single[d_lo], single[d_hi]) == (3, 1, 5200, 5, 5)
    assert fish["zones"] == [{"key": ZONE, "name": "Beaucedine Glacier", "n": 3}]
    assert fish["rods"] == [{"key": ROD, "name": "Lu Shang's Fishing Rod", "n": 3}]
    assert fish["weathers"] == [{"key": 12, "name": "Snow", "n": 3}]
    assert [fish["hours"], fish["moons"]] == [[[6], [3]], [[50], [3]]]
