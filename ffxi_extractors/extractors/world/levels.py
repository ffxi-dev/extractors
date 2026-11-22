import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Levels(Extractor):
    """Ported from captain's levelrangetrack, plus /check replies. levelrangetrack keeps a range per mob;
    this keeps each new report in a mob's life, so a kill can take the level its own life had."""

    name = "levels"
    version = 2  # 2: a row per change of level in a mob's life, which ends at its defeat, despawn, or a zone
    doc = "Mob levels, as widescan lists and /check replies report them."
    reads = frozenset({(0, 0x0F4), (0, 0x029), (0, 0x00E), (0, 0x00A)})
    tables = (
        Table(
            "levels",
            "One row each time a source reports a mob at a level other than its last report in the mob's"
            " life: widescan entries (0x0F4) of enemies, as levelrangetrack keeps them, and /check replies"
            " (0x029 170 to 178). A mob keeps its id when it respawns, so a life, as the capture sees it,"
            " ends at the mob's defeat, its despawn (it may die and respawn out of view), or a zone change."
            " A kill takes the latest row at or before it whose end_idx is at or after it; with none, its"
            " level is unknown. A level range is the minimum and maximum over rows.",
            (
                Column("entity_id", pa.int64(), "The mob; for widescan, worked out from the zone and index."),
                Column("level", pa.int32(), "The level reported."),
                Column("source", pa.string(), "widescan or check."),
                Column("name", pa.string(), "The name widescan gives; none for a check."),
                Column("zone_id", pa.int32(), "The zone."),
                Column(
                    "end_idx",
                    pa.int64(),
                    "The packet that ended the mob's life: its defeat (0x029 6 or 20), its despawn (0x00E),"
                    " or a zone change (0x00A). None when the capture ended first.",
                ),
            ),
        ),
    )
