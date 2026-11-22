import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

INTS = pa.list_(pa.int32())


class Synths(Extractor):
    """Each synthesis result the zone sent: the character's own (0x06F), which names the crystal and
    ingredients beside the result, and those of others nearby (0x070), which name the result only."""

    name = "synths"
    version = 2  # 2: only results retail's captures explain are named; lost follows grade -1
    doc = (
        "Each synthesis result: the character's with its recipe, lost items, and skill-ups; others' results."
    )
    reads = frozenset({(0, 0x06F), (0, 0x070)})
    tables = (
        Table(
            "synths",
            "One row per synthesis result: 0x06F for the character's own, 0x070 for someone else's nearby."
            " Recipe columns are the character's own only.",
            (
                Column("own", pa.bool_(), "Whether it is the character's own synthesis (0x06F)."),
                Column("crafter", pa.string(), "Who synthesized: the character, or the name 0x070 sends."),
                Column(
                    "result",
                    pa.int32(),
                    "Result as sent: 0 success, 1 failed, 12 desynthesis. Retail also sends 2, 3, 4, 6, 9,"
                    " 10, 11, 13 and 14, often with an item made, whose meaning is unknown; LSB's names for"
                    " them do not fit.",
                ),
                Column(
                    "outcome",
                    pa.string(),
                    "failed when grade is -1, whatever the result; success for result 0, desynth for 12;"
                    " none for the rest.",
                ),
                Column(
                    "grade", pa.int32(), "Grade as sent: 0 normal quality, 1 to 3 the HQ tier, -1 on failure."
                ),
                Column(
                    "item_id", pa.int32(), "The item made; on failure, what the client shows in its place."
                ),
                Column("count", pa.int32(), "How many were made."),
                Column("crystal_id", pa.int32(), "The crystal (0x06F CrystalNo). Own only."),
                Column(
                    "ingredients",
                    INTS,
                    "The ingredients' item ids in the order put in (MaterialNo). Own only.",
                ),
                Column(
                    "lost",
                    INTS,
                    "The ingredients lost (BreakNo) on a failure (grade -1); for the character's own,"
                    " only those among its ingredients. Retail leaves BreakNo as an earlier synthesis set it"
                    " on other results, so a success has none here.",
                ),
                Column(
                    "skill_kinds",
                    INTS,
                    "UpKind as sent: in captures, the craft skill that rose (49 woodworking to 57 cooking),"
                    " with skill_levels at the same place. Own only.",
                ),
                Column(
                    "skill_levels",
                    INTS,
                    "UpLevel as sent: in captures, the rise in tenths, as the skill-up message (0x029, 38)"
                    " gave it. Own only.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
