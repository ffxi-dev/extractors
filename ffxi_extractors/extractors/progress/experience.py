import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

INTS = pa.list_(pa.int32())


class Experience(Extractor):
    """Points the character gained and level changes, from the battle message 0x02D, with what changes the
    points: its status effects (0x063's status list), key items (0x055), and party (the world's)."""

    name = "experience"
    version = 1
    doc = "EXP, limit, capacity, and exemplar point gains with their chain and bonuses; level ups and downs."
    reads = frozenset({(0, 0x02D), (0, 0x063), (0, 0x055)})
    tables = (
        Table(
            "exp_gains",
            "One row per point gain (0x02D 8, 253, 371, 372, 718, 735, 809, 810), resends skipped.",
            (
                Column("recipient_id", pa.int64(), "Who gained (UniqueNoCas)."),
                Column("own", pa.bool_(), "Whether that is the character."),
                Column("kind", pa.string(), "exp, limit, capacity, or exemplar."),
                Column("points", pa.int64(), "The points (Data)."),
                Column("chain", pa.int32(), "The chain number: Data2 on a chain message (253 ...), else 0."),
                Column("message", pa.int32(), "The message."),
                Column(
                    "mob_id",
                    pa.int64(),
                    "The mob the points came from (UniqueNoTar); none when it names no mob, as for a"
                    " Records of Eminence reward.",
                ),
                Column(
                    "party_size",
                    pa.int32(),
                    "The character and every party and alliance member listed (0x0DD, 0x0E2, 0x0C8),"
                    " Trusts included.",
                ),
                Column(
                    "effects",
                    INTS,
                    "The character's status effects that change the points (0x063 type 9): Dedication"
                    " (249), Commitment (579), Corsair's Roll (326), Sanction (256), Ionis (512), Level Sync"
                    " (269), Level Restriction (143), and Signet (253) in a party of 2 to 5.",
                ),
                Column(
                    "key_items",
                    INTS,
                    "Key items held that raise the points (0x055): the Rhapsodies (2884 to 2889),"
                    " Moghancement: Bounty, Moglification: Experience and Capacity Boost, and the Monster"
                    " Rearing cheers that raise EXP.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
        Table(
            "level_changes",
            "One row per level up (0x02D 9) or down (11), the character's or a party member's.",
            (
                Column("member_id", pa.int64(), "Whose level changed (UniqueNoCas)."),
                Column("own", pa.bool_(), "Whether that is the character."),
                Column("change", pa.string(), "up or down."),
                Column("level", pa.int32(), "The new level (Data)."),
                Column("mob_id", pa.int64(), "The mob whose defeat gave it, if the message names one."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
