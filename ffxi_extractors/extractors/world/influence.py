import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

ARMY_COLUMNS = ("sandoria", "bastok", "windurst", "orcs", "quadav", "yagudo", "kindred")
ARMY_NAMES = ("San d'Oria", "Bastok", "Windurst", "The Orcs", "The Quadav", "The Yagudo", "The Kindred")
OWNER = "1 San d'Oria, 2 Bastok, 3 Windurst, 4 Orcs, 5 Quadav, 6 Yagudo, 7 Kindred"


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
