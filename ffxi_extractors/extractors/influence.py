import pyarrow as pa

from ..extract import Column, Extractor, Table

# Campaign areas in packet order, as zone ids: LSB's sql/campaign_map.sql (LandSandBoat/server commit
# 2baf9d4a24). The first packet of a pair carries areas 0 to 12, the second 13 to 25.
CAMPAIGN_ZONES = (80, 81, 82, 83, 84, 85, 175, 87, 88, 89, 90, 91, 92, 171, 94, 95, 96, 97, 98, 99, 164, 136,
                  137, 138, 155, 156)  # fmt: skip
# The packet's army order; ControlledAreas counts the four beastman armies as one.
ARMIES = (
    "Sandoria",
    "Bastok",
    "Windurst",
    "BeastmanOrc",
    "BeastmanQuadav",
    "BeastmanYagudo",
    "BeastmanDarkKindred",
)
ARMY_COLUMNS = ("sandoria", "bastok", "windurst", "orcs", "quadav", "yagudo", "kindred")
ARMY_NAMES = ("San d'Oria", "Bastok", "Windurst", "The Orcs", "The Quadav", "The Yagudo", "The Kindred")
OWNER = "1 San d'Oria, 2 Bastok, 3 Windurst, 4 Orcs, 5 Quadav, 6 Yagudo, 7 Kindred"
# Colonization areas in packet order (its first slot is unused), with their zone ids from LSB's zone enum.
COLONIES = (
    ("YahseHuntingGrounds", 260), ("CeizakBattlegrounds", 261), ("ForetDeHennetiel", 262),
    ("YorciaWeald", 263), ("MorimarBasaltFields", 265), ("MarjamiRavine", 266), ("KamihrDrifts", 267),
    ("RaKaznar", 274),
)  # fmt: skip


class Influence(Extractor):
    """Ported from captain's campaigntrack and colonizationtrack, which log the two modes of one packet
    (0x071): the Campaign map of the Crystal War (mode 2, two packets of 13 areas) and Adoulin's
    colonization map (mode 3). The server sends both at each zone-in and when the map opens, after the
    conquest map. The character's own allied notes, bayld, and coalition ranks are not kept here."""

    name = "influence"
    version = 1
    doc = "The Campaign and colonization maps (0x071): who holds each Campaign area, and each colony's rate."
    reads = frozenset({(0, 0x071)})
    tables = (
        Table(
            "campaign",
            "One row per Campaign map (0x071 mode 2): areas held and each army's standing. The server sends"
            " the map in two packets with the same totals; the first gives the row.",
            (
                *(
                    Column(f"{n}_areas", pa.int32(), f"Areas {label} holds.")
                    for n, label in (
                        ("sandoria", "San d'Oria"),
                        ("bastok", "Bastok"),
                        ("windurst", "Windurst"),
                        ("beastmen", "the beastmen, all four armies,"),
                    )
                ),
                *(
                    Column(
                        f"{a}_{k}", pa.int32(), f"{name}' {k}." if name.endswith("s") else f"{name}'s {k}."
                    )
                    for a, name in zip(ARMY_COLUMNS, ARMY_NAMES, strict=True)
                    for k in ("morale", "prosperity", "reconnaissance")
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
        Table(
            "campaign_areas",
            "One row per Campaign area per Campaign map packet (0x071 mode 2), 26 areas over two packets.",
            (
                Column(
                    "area", pa.int32(), "The area, 0 to 25, in the packet's order (LSB's campaign_map id)."
                ),
                Column("area_zone_id", pa.int32(), "The area's zone, as LSB's campaign_map maps it."),
                Column("owner", pa.int32(), f"The army that holds it: {OWNER}."),
                Column("fortifications", pa.int32(), "Its fortifications now."),
                Column("max_fortifications", pa.int32(), "Their most."),
                Column("resources", pa.int32(), "Its resources now."),
                Column("max_resources", pa.int32(), "Their most."),
                Column("heroism", pa.int32(), "Its heroism, 0 to 200."),
                *(
                    Column(f"influence_{n}", pa.int32(), f"{label}'s influence in it.")
                    for n, label in (
                        ("sandoria", "San d'Oria"),
                        ("bastok", "Bastok"),
                        ("windurst", "Windurst"),
                        ("beastmen", "The beastmen"),
                    )
                ),
                Column(
                    "flag",
                    pa.int32(),
                    "The bit before Owner, which XiPackets and LSB call unused; it changes between areas and"
                    " captures. Its meaning is unknown.",
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
        Table(
            "colonization",
            "One row per colonization area per colonization map (0x071 mode 3), in Adoulin's eight frontier"
            " areas.",
            (
                Column("area_zone_id", pa.int32(), "The area's zone."),
                Column("rate", pa.int32(), "Its colonization rate, in percent."),
                Column("bivouacs", pa.int32(), "Bivouacs set up."),
                Column("max_bivouacs", pa.int32(), "Bivouacs it can have."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )

    def packet(self, p, f, world, emit):
        mode = f("Mode")
        if mode == 2:
            offset = f("data.ZoneOffset")
            if offset is None:
                return
            if offset == 0:
                n = "data.Nations."
                emit(
                    "campaign",
                    p,
                    **{f"{k}_areas": f(f"data.ControlledAreas.{v}")
                       for k, v in (("sandoria", "Sandoria"), ("bastok", "Bastok"), ("windurst", "Windurst"),
                                    ("beastmen", "Beastman"))},
                    **{f"{c}_{k}": f(f"{n}{a}.{k.title()}")
                       for a, c in zip(ARMIES, ARMY_COLUMNS, strict=True)
                       for k in ("morale", "prosperity", "reconnaissance")},
                    zone_id=world.zone,
                )  # fmt: skip
            for i in range(13):
                z = f"data.Zones[{i}]."
                area = offset + i
                if area >= len(CAMPAIGN_ZONES):
                    break
                emit(
                    "campaign_areas",
                    p,
                    area=area,
                    area_zone_id=CAMPAIGN_ZONES[area],
                    owner=f(z + "Owner"),
                    fortifications=f(z + "CurrentFortifications"),
                    max_fortifications=f(z + "MaxFortifications"),
                    resources=f(z + "CurrentResources"),
                    max_resources=f(z + "MaxResources"),
                    heroism=f(z + "Heroism"),
                    **{f"influence_{c}": f(z + f"Influence{n}")
                       for c, n in (("sandoria", "Sandoria"), ("bastok", "Bastok"), ("windurst", "Windurst"),
                                    ("beastmen", "Beastman"))},
                    flag=f(z + "unused00"),
                    zone_id=world.zone,
                )  # fmt: skip
        elif mode == 3:
            for name, zone in COLONIES:
                z = f"data.Zones.{name}."
                rate = f(z + "ColonizationRate")
                if rate is None:
                    return
                emit(
                    "colonization",
                    p,
                    area_zone_id=zone,
                    rate=rate,
                    bivouacs=f(z + "CurrentBivouacs"),
                    max_bivouacs=f(z + "MaxBivouacs"),
                    zone_id=world.zone,
                )
