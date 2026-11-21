"""conquesttrack, besiegedtrack, campaigntrack, and colonizationtrack's ports on decoded fields, one test per
spec scenario in scholar-ports-3."""

from conftest import drive, rows

from ffxi_extractors.extractors.world.conquest import Conquest
from ffxi_extractors.extractors.world.influence import Influence


def conquest_map(owners, balance=26, candescence=0, al_zahbi=2, mamook=(5, 145, 4)):
    """A 0x05E: region owners by index, the nations' Balance, and Mamook's orders, forces, and level."""
    d = {"Conquest.Balance": balance, "Conquest.Alliance": 0, "Conquest.NextTally": 33,
         "Conquest.CurrentRegionSandoria": 16, "Conquest.CurrentRegionBeastmen": 38,
         "Besieged.Overview.AstralCandescence": candescence,
         "Besieged.Overview.AlZahbiOrders": al_zahbi}  # fmt: skip
    for i in range(27):
        d[f"Conquest.Regions[{i}].Owner"] = owners[i] if i < len(owners) else 0
        d[f"Conquest.Regions[{i}].InfluenceRankingWithBeastmen"] = 45 if i < len(owners) else 0
    for name in ("Mamook", "Halvung", "Arrapago"):
        orders, forces, level = mamook if name == "Mamook" else (0, 97, 0)
        s = f"Besieged.{name}Stronghold."
        d.update({s + "Orders": orders, s + "Forces": forces, s + "Level": level, s + "Mirrors": 8,
                  s + "Prisoners": 0, s + "Unknown": 0})  # fmt: skip
    return 0x05E, d


def test_a_conquest_map():
    rows = drive(Conquest, conquest_map([1, 3, 4]))
    (c,) = rows["conquest"]
    # Balance 26 is 0b01_10_10: Windurst first, San d'Oria and Bastok second.
    assert (c["sandoria_rank"], c["bastok_rank"], c["windurst_rank"], c["next_tally"]) == (2, 2, 1, 33)
    assert [(r["region_id"], r["owner"]) for r in rows["conquest_regions"]] == [(0, 1), (1, 3), (2, 4)]
    assert [(b["stronghold"], b["orders"], b["level"], b["candescence"]) for b in rows["besieged"]] == [
        ("Mamook", 5, 4, "Al Zahbi"), ("Halvung", 0, 0, "Al Zahbi"), ("Arrapago", 0, 0, "Al Zahbi")
    ]  # fmt: skip


def test_the_astral_candescence_taken_then_recovered():
    taken = conquest_map([1], candescence=1, al_zahbi=3, mamook=(0, 0, 0))
    rows = drive(Conquest, taken, conquest_map([1]))["besieged"]
    assert [(b["candescence"], b["al_zahbi_orders"]) for b in rows if b["stronghold"] == "Mamook"] == [
        ("Mamook", 3), ("Al Zahbi", 2)
    ]  # fmt: skip


def test_an_unknown_holder_of_the_astral_candescence_is_none():
    rows = drive(Conquest, conquest_map([1], candescence=7))["besieged"]
    assert {b["candescence"] for b in rows} == {None}


def campaign_map(offset, owner):
    d = {"Mode": 2, "data.ZoneOffset": offset, "data.ControlledAreas.Sandoria": 9,
         "data.ControlledAreas.Beastman": 5,
         "data.Nations.BeastmanQuadav.Morale": 95}  # fmt: skip
    for i in range(13):
        d[f"data.Zones[{i}].Owner"] = owner
        d[f"data.Zones[{i}].Heroism"] = 200
    return 0x071, d


def test_a_campaign_map_in_two_packets():
    rows = drive(Influence, campaign_map(0, 1), campaign_map(13, 7))
    (c,) = rows["campaign"]
    assert (c["sandoria_areas"], c["beastmen_areas"], c["quadav_morale"]) == (9, 5, 95)
    areas = rows["campaign_areas"]
    assert len(areas) == 26
    assert (areas[0]["area_zone_id"], areas[0]["owner"]) == (80, 1)  # Southern San d'Oria [S]
    assert (areas[25]["area"], areas[25]["area_zone_id"], areas[25]["owner"]) == (
        25,
        156,
        7,
    )  # Throne Room [S]


def test_a_colonization_map():
    d = {"Mode": 3}
    for name in ("YahseHuntingGrounds", "CeizakBattlegrounds", "ForetDeHennetiel", "YorciaWeald",
                 "MorimarBasaltFields", "MarjamiRavine", "KamihrDrifts", "RaKaznar"):  # fmt: skip
        d.update({f"data.Zones.{name}.ColonizationRate": 80, f"data.Zones.{name}.CurrentBivouacs": 3,
                  f"data.Zones.{name}.MaxBivouacs": 3})  # fmt: skip
    rows = drive(Influence, (0x071, d))["colonization"]
    assert [r["area_zone_id"] for r in rows] == [260, 261, 262, 263, 265, 266, 267, 274]
    assert {(r["rate"], r["bivouacs"], r["max_bivouacs"]) for r in rows} == {(80, 3, 3)}


def test_conquest_region_names_are_lsbs(con):
    names = dict(rows(con, "SELECT id, name FROM conquest_region_names"))
    assert len(names) == 19 and (names[0], names[11], names[18]) == (
        "Ronfaure",
        "Li'Telor",
        "Tavnazian Archipelago",
    )
