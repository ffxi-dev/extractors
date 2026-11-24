import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Immunity(Extractor):
    """Ported from captain's immunitytrack: each spell cast on a mob and how it fared. immunitytrack counts
    655 as immune, 85 with bit 2 as a trait resist, and other 85s as resists; this also counts 284 (the
    target resists the effects) as a resist and 75 as no effect, which immunitytrack counts as landed, and
    each area form: 656 immune, 283 no effect, 653 and 654 (Immunobreak!) a resist. Every cast is kept,
    landed or not, so a resist rate is resists over rows."""

    name = "immunity"
    version = 2  # 2: 656 immune, 283 no effect, 653 and 654 a resist with immunobreak
    doc = "Each spell (0x028 category 4) on a mob, and whether it landed, was resisted, or did nothing."
    reads = frozenset({(0, 0x028)})
    tables = (
        Table(
            "spell_results",
            "One row per spell result on one of the zone's own mobs, landed or not, so a resist rate is a"
            " count. Resends are skipped. Partial resists of damage spells count as landed.",
            (
                Column("caster_id", pa.int64(), "Who cast it."),
                Column("target_id", pa.int64(), "The mob."),
                Column("spell_id", pa.int64(), "The spell, as retail-resources' spells table numbers it."),
                Column("message", pa.int32(), "The result's message, an LSB msg_basic id."),
                Column(
                    "outcome",
                    pa.string(),
                    "immune (655, 656), trait_resist (85 with bit 2), resist (85, 284, 653, 654),"
                    " no_effect (75, 283), or landed (anything else, damage included).",
                ),
                Column(
                    "immunobreak",
                    pa.bool_(),
                    "Whether the resist lowered the mob's resistance (653, 654: Immunobreak!), which an"
                    " immune mob never allows.",
                ),
                Column("value", pa.int64(), "The result's amount: damage, or the status the spell gave."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
