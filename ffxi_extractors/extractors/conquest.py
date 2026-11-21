import pyarrow as pa

from ..extract import Column, Extractor, Table

STRONGHOLDS = ("Mamook", "Halvung", "Arrapago")  # LSB's besieged_stronghold: 1, 2, 3
CANDESCENCE = ("Al Zahbi", *STRONGHOLDS)  # who holds it, by AstralCandescence
NATIONS = ("Sandoria", "Bastok", "Windurst")
OWNER = "0 none, 1 San d'Oria, 2 Bastok, 3 Windurst, 4 beastmen"
ORDERS = "0 train, 1 advance, 2 attack, 3 retreat, 4 defend, 5 prepare"


class Conquest(Extractor):
    """Ported from captain's conquesttrack and besiegedtrack, which log the two halves of one packet (0x05E),
    and so what regiontrack's polls bring. The server sends it at each zone-in and when the map opens. The
    character's own conquest points and imperial standing stay in s2c_0x05e."""

    name = "conquest"
    version = 2  # 2: an AstralCandescence past the strongholds is unknown, not a failed capture
    doc = "The conquest and Besieged map (0x05E): who holds each region, and the beastmen armies of Besieged."
    reads = frozenset({(0, 0x05E)})
    tables = (
        Table(
            "conquest",
            "One row per conquest map (0x05E): the nations' standing, and the influence in the character's"
            " region. Each region's owner is in conquest_regions.",
            (
                Column("zone_id", pa.int32(), "The zone the character was in."),
                *(
                    Column(
                        f"{n.lower()}_rank",
                        pa.int32(),
                        f"{n}'s place by regions held, 1 to 3 (Balance, 2 bits per nation).",
                    )
                    for n in NATIONS
                ),
                Column(
                    "alliance",
                    pa.int32(),
                    "Alliance as sent: a bit per allied nation, San d'Oria 1, Bastok 2, Windurst 4; 0 none.",
                ),
                Column("next_tally", pa.int32(), "Vana'diel days to the weekly tally."),
                *(
                    Column(
                        n.lower(),
                        pa.int32(),
                        f"{n}'s share of influence in the character's region, beastmen counted, in percent;"
                        " 0 outside a conquest region.",
                    )
                    for n in NATIONS
                ),
                Column("beastmen", pa.int32(), "The beastmen's share, in percent."),
                *(
                    Column(
                        f"{n.lower()}_no_beastmen", pa.int32(), f"{n}'s share among the nations, in percent."
                    )
                    for n in NATIONS
                ),
            ),
        ),
        Table(
            "conquest_regions",
            "One row per region per conquest map (0x05E), regions the packet leaves blank left out. Names are"
            " in conquest_region_names.",
            (
                Column(
                    "region_id",
                    pa.int32(),
                    "The region, as LSB numbers it: 0 Ronfaure to 18 Tavnazian Archipelago.",
                ),
                Column("owner", pa.int32(), f"Who holds it: {OWNER}."),
                Column(
                    "ranking",
                    pa.int32(),
                    "The nations' order by influence, beastmen counted, packed as LSB's GetInfluenceRanking.",
                ),
                Column("ranking_no_beastmen", pa.int32(), "The same without the beastmen."),
                Column(
                    "graphics", pa.int32(), "InfluenceGraphics as sent: how the map draws the influence bar."
                ),
            ),
        ),
        Table(
            "besieged",
            "One row per beastman stronghold per conquest map (0x05E), with who holds the Astral Candescence."
            " An army whose orders are advance or attack is marching on Al Zahbi: Besieged.",
            (
                Column(
                    "stronghold", pa.string(), "Mamook (Mamool Ja), Halvung (Trolls), or Arrapago (Undead)."
                ),
                Column("orders", pa.int32(), f"The army's orders: {ORDERS}."),
                Column("forces", pa.int32(), "Its forces, as the map counts them."),
                Column("level", pa.int32(), "Its level, 0 to 15."),
                Column("mirrors", pa.int32(), "Its archaic mirrors."),
                Column("prisoners", pa.int32(), "The prisoners it holds."),
                Column(
                    "flag", pa.int32(), "The stronghold's Unknown bit, as sent; captain prints it as Flag."
                ),
                Column(
                    "map_orders", pa.int32(), "The orders the map's overview shows for it, which can differ."
                ),
                Column("map_level", pa.int32(), "The level the overview shows."),
                Column(
                    "candescence",
                    pa.string(),
                    "Who holds the Astral Candescence: Al Zahbi, or a stronghold that took it.",
                ),
                Column(
                    "al_zahbi_orders",
                    pa.int32(),
                    "Al Zahbi's orders: 0 defend (under attack), 1 intercept (an army advances), 2 infiltrate"
                    " (no siege), 3 recover (a stronghold holds the Astral Candescence).",
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )

    def packet(self, p, f, world, emit):
        balance = f("Conquest.Balance")
        if balance is None:  # an older layout, or a stubbed packet
            return
        emit(
            "conquest",
            p,
            zone_id=world.zone,
            **{f"{n.lower()}_rank": (balance >> (2 * i)) & 3 for i, n in enumerate(NATIONS)},
            alliance=f("Conquest.Alliance"),
            next_tally=f("Conquest.NextTally"),
            **{n.lower(): f(f"Conquest.CurrentRegion{n}") for n in NATIONS},
            beastmen=f("Conquest.CurrentRegionBeastmen"),
            **{f"{n.lower()}_no_beastmen": f(f"Conquest.CurrentRegion{n}Pct") for n in NATIONS},
        )
        for i in range(27):
            r = f"Conquest.Regions[{i}]."
            row = {
                "owner": f(r + "Owner"),
                "ranking": f(r + "InfluenceRankingWithBeastmen"),
                "ranking_no_beastmen": f(r + "InfluenceRankingNoBeastmen"),
                "graphics": f(r + "InfluenceGraphics"),
            }
            if any(row.values()):
                emit("conquest_regions", p, region_id=i, **row)
        held = f("Besieged.Overview.AstralCandescence")
        for name in STRONGHOLDS:
            s = f"Besieged.{name}Stronghold."
            emit(
                "besieged",
                p,
                stronghold=name,
                orders=f(s + "Orders"),
                forces=f(s + "Forces"),
                level=f(s + "Level"),
                mirrors=f(s + "Mirrors"),
                prisoners=f(s + "Prisoners"),
                flag=f(s + "Unknown"),
                map_orders=f(f"Besieged.Overview.{name}Orders"),
                map_level=f(f"Besieged.Overview.{name}Level"),
                candescence=CANDESCENCE[held] if held is not None and held < len(CANDESCENCE) else None,
                al_zahbi_orders=f("Besieged.Overview.AlZahbiOrders"),
                zone_id=world.zone,
            )
