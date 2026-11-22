import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

# hptrackv2's MSG_TYPES: [category][message] -> 1 damage, -1 healing, 0 neither. Anything else is skipped.
_D, _H, _N = 1, -1, 0


class Hp(Extractor):
    """Ported from captain's hptrackv2: the damage each mob took from everything the capture shows, melee,
    weapon skills, spells, skillchains, added effects, spikes, and counters, narrowed by its HP% updates,
    and its HP range when it dies. hptrackv2's warning stands: more accurate than the original but not
    perfect; regen, damage over time, and effects the capture missed throw it off. Damage the character
    could not see, such as a party member's out of range, is missing, so the range is low then."""

    name = "hp"
    # 2: a despawn ends the mob's life; 3: regen; 4: slow regen's rate; 5: HP by vote under regen; 7: a
    # counter is no hit on the mob, trusts and pets are not mobs
    version = 7
    doc = "Each defeated mob's damage taken and HP range (0x028, 0x029, 0x00E)."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x00E), (0, 0x00A)})
    tables = (
        Table(
            "mob_hp",
            "One row per defeated mob that the capture saw take damage, at its defeat (0x029 6 or 20), but"
            " one whose HP% fell with no damage seen (a damage-over-time tick): its damage falls short of"
            " its HP."
            " hptrackv2's warning: close but not perfect; regen, damage over time, and missed effects throw"
            " it off. Damage the character could not see, such as a party member's out of range, is missing.",
            (
                Column("mob_id", pa.int64(), "The mob."),
                Column("damage", pa.int64(), "Damage it took, procs and reactions included."),
                Column("healing", pa.int64(), "HP it recovered from actions the capture saw."),
                Column("hits", pa.int32(), "Damage entries counted, procs and reactions included."),
                Column("hp_min", pa.int64(), "Least max HP the damage and HP% updates allow."),
                Column("hp_max", pa.int64(), "Most max HP they allow."),
                Column("start_hpp", pa.int32(), "Its HP% when the capture first saw it take damage."),
                Column(
                    "contradictions",
                    pa.int32(),
                    "HP% windows that disagreed with the damage seen: regen, damage over time, or a missed"
                    " effect. Above 0, trust hp_min and hp_max less.",
                ),
                Column(
                    "regen",
                    pa.int32(),
                    "HP% points it regained with no heal seen: regen, or a heal out of view. Its HP then"
                    " comes from the HP% windows alone.",
                ),
                Column("regen_rate", pa.float64(), "HP% regained per 3 s, from back-to-back rises."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
