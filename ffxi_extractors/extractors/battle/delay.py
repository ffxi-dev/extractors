import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Delay(Extractor):
    """Ported from captain's attackdelay: the time between an actor's auto-attack rounds, what each
    round's swings did, and the recorder's TP gain from a mob's hit. attackdelay's own warning stands:
    none of this is to be trusted on its own. Network latency, server ticks, Store TP, Subtle Blow, and
    hand-to-hand mobs all move it. attackdelay pins a TP gain on the client's current target; the action
    packet names the mob that hit, so this ties the gain to its round instead."""

    name = "delay"
    version = 5  # 4: a defeat or despawn ends the actor's interval, so a respawn's first round has none;
    # 5: a zone-in's character id comes from the decoder
    doc = "Each auto-attack round (0x028 category 1), with the time since the actor's last round."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x0DF), (0, 0x00A), (0, 0x00E)})
    tables = (
        Table(
            "attack_rounds",
            "One row per auto-attack round. Delay in FFXI units is interval_ms * 60 / 1000. attackdelay's"
            " warning: not to be trusted on its own; latency, server ticks, Store TP, Subtle Blow, and"
            " hand-to-hand mobs move it. Use the median over many rounds. Swing counts are of results on"
            " the first target. Each swing counts under one outcome column, or none for a plain hit, so"
            " plain hits are swings minus the outcome columns.",
            (
                Column("actor_id", pa.int64(), "Who attacked: the character, a party member, or a mob."),
                Column("actor_is_mob", pa.bool_(), "Whether the attacker is one of the zone's own mobs."),
                Column("target_id", pa.int64(), "Who the round was aimed at: the action's first target."),
                Column(
                    "interval_ms",
                    pa.int64(),
                    "ms since the actor's last round. None for its first round, the first after it cast a"
                    " spell or used a TP move (those rounds include the casting time), the first after a"
                    " zone change or its defeat, as attackdelay, and the first after it left view: a mob"
                    " that respawns keeps its id.",
                ),
                Column("swings", pa.int32(), "Results in the round on the first target: its swings."),
                Column(
                    "hits",
                    pa.int32(),
                    "Swings with message 1 or 67, as attackdelay counts connects. Overlaps crits, blocked,"
                    " guarded, and countered.",
                ),
                Column("main_hand", pa.int32(), "Swings from the main hand (sub_kind 0)."),
                Column("off_hand", pa.int32(), "Swings from the off hand (sub_kind 1)."),
                Column("kicks", pa.int32(), "Kicks (sub_kind 2 and 3): the attacker fights hand to hand."),
                Column("targets", pa.int32(), "Targets in the round; swing counts are of the first only."),
                Column(
                    "cut_short",
                    pa.bool_(),
                    "Whether its target was defeated (0x029 6, 20, or 97) within a second after it: the"
                    " round may have stopped before all its swings.",
                ),
                Column("at_character", pa.bool_(), "Whether the first target is the recording character."),
                Column("crits", pa.int32(), "Critical hits (message 67), not blocked or guarded."),
                Column("misses", pa.int32(), "Misses (message 15): failed the accuracy check."),
                Column("parried", pa.int32(), "Parried (message 70)."),
                Column("absorbed", pa.int32(), "Absorbed by a shadow (message 31)."),
                Column("anticipated", pa.int32(), "Anticipated (message 30)."),
                Column(
                    "countered",
                    pa.int32(),
                    "Countered: the reaction is 33, or 14 (a counter a shadow absorbed). attackdelay counts"
                    " 14 as an evasion; in LSB's msg_basic it is a counter.",
                ),
                Column("dodged", pa.int32(), "Dodged by Perfect Dodge (message 32)."),
                Column("blocked", pa.int32(), "Hits a shield blocked (miss field 4)."),
                Column("guarded", pa.int32(), "Hits the target guarded (miss field 2)."),
                Column("other", pa.int32(), "Swings with any other message."),
                Column(
                    "tp_gain",
                    pa.int32(),
                    "For a mob's round whose only swing at the character hit: the character's TP rise in"
                    " its next 0x0DF, if no other action by or on the character came first. Delay is about"
                    " tp_gain / 21 * 240; Subtle Blow on the mob lowers the gain, Store TP on the character"
                    " raises it.",
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
