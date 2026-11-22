import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Fights(Extractor):
    """One row per mob life the capture saw fight: from the first action between it and a player, Trust,
    or pet to its defeat, its despawn, a zone change, three minutes with no such action, or the capture's
    end. A mob's casts on itself or another mob do not count. No captain addon records this; it is the
    unit fight analyses count. A defeat with no action seen before it, such as a party member's kill
    out of range, still makes a fight, with no actions."""

    name = "fights"
    version = 3  # 3: a resent defeat is not a second fight
    doc = "Each mob's fight with a player, Trust, or pet, from its first action to its end (0x028, 0x029)."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x00E), (0, 0x00A)})
    tables = (
        Table(
            "fights",
            "One row per mob life seen in combat. idx and ts_ms are the fight's first packet.",
            (
                Column(
                    "mob_id", pa.int64(), "The mob: one of the zone's own, id 0x01ZZZIII, III under 0x400."
                ),
                Column("end_idx", pa.int64(), "The packet that ended it: the defeat, or the last action."),
                Column("end_ms", pa.int64(), "That packet's time."),
                Column(
                    "outcome",
                    pa.string(),
                    "defeated (0x029 6 or 20), despawned (it left without a defeat seen), zoned (the"
                    " character left the zone), disengaged (three minutes with no action), or open (the"
                    " capture ended first).",
                ),
                Column(
                    "actions",
                    pa.int32(),
                    "Action packets it gave or took, resends skipped: with a player, Trust, or pet, or on"
                    " itself or a fellow mob while the fight was on.",
                ),
                Column("actions_by", pa.int32(), "Of those, the ones it gave."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
