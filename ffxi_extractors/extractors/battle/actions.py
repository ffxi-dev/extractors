import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.extractors.battle import positions


class Actions(Extractor):
    """Ported from captain's actionview: every action packet, by anyone, in every category. actionview
    shows only mobs and some categories, and drops message 84; this keeps all and leaves the choice to
    the query. Ready time is measured from packet times rather than the client's clock. A mob TP move's
    range and spread are measured as actionview does, from the last positions the packets sent rather than
    the client's memory. Who stood near a TP move and whether it hit them follows the method Skold177 set
    out in phoenixffxi/xi-ai#13: each entity's distance and bearing from the mob, and its distance from the
    first target, so a query can bound a move's radius and arc."""

    name = "actions"
    version = 5  # 2: a mob TP move's max_range and max_spread; 3: actor_dir, actor_size, tp_nearby; 4: the
    # party follows 0x0E2 and 0x0C8; 5: ready_ms pairs a finish with its own start only, and an interrupt
    # carries what it stopped
    doc = "Each action (0x028): who acted, what they did, and what it did to each target."
    # The positions and HP%, so a fallen bystander is not taken for one missed.
    reads = frozenset({(0, 0x028)}) | positions.READS
    tables = (
        Table(
            "actions",
            "One row per action packet (0x028), by anyone. A mob TP move (category 11) carries its mob skill"
            " id; retail-resources has no mob skill names yet, so ability_names does not name it.",
            (
                Column("actor_id", pa.int64(), "Who acted: a player, trust, pet, NPC, or mob id."),
                Column(
                    "actor_is_mob", pa.bool_(), "Whether the actor is one of the zone's own NPCs or mobs."
                ),
                Column(
                    "category",
                    pa.int32(),
                    "cmd_no: 1 melee, 2 ranged, 3 weapon skill or damaging ability, 4 spell, 5 item,"
                    " 6 job ability, 7 TP move start, 8 spell start, 9 item start, 11 mob TP move,"
                    " 12 ranged start, 13 pet TP move, 14 dance, 15 rune fencer ability.",
                ),
                Column(
                    "action_id",
                    pa.int64(),
                    "What was used: the spell, ability, item, or mob skill id (cmd_arg). For a start (7, 8,"
                    " 9) the id of what is starting, which the packet carries in its first result; for an"
                    " interrupt (cmd_arg's low half 28787), the id of the start it stopped, else 0.",
                ),
                Column("cmd_arg", pa.int64(), "cmd_arg as sent."),
                Column("targets", pa.int32(), "How many targets the action had."),
                Column("message", pa.int32(), "The first result's message, an LSB msg_basic id."),
                Column("animation", pa.int32(), "The first result's sub_kind, which actionview calls Anim."),
                Column(
                    "ready_ms",
                    pa.int64(),
                    "For a mob TP move, spell, or ranged attack (11, 4, 2): ms since the same actor's start"
                    " of it (7, 8, 12; for 11 and 4 the same id), as actionview's ready time. None when the"
                    " actor's last start was another's, was interrupted, or is over 30 s old. For an"
                    " interrupt: ms since the start it stopped.",
                ),
                Column(
                    "max_range",
                    pa.float32(),
                    "For a mob TP move (11): how far its farthest target stood from the mob, in yalms, from"
                    " the last positions sent. None when a position is unknown. actionview's Range.",
                ),
                Column(
                    "max_spread",
                    pa.float32(),
                    "For a mob TP move with two or more targets: how far apart the two farthest targets"
                    " stood, in yalms. actionview's Spread.",
                ),
                Column(
                    "actor_dir",
                    pa.int32(),
                    "For a mob TP move: the mob's heading, 0 to 255, from its own update at most 2 s before."
                    " None when older. Headings run as LSB's worldAngle: 0 faces +x, 64 faces -y.",
                ),
                Column(
                    "actor_size",
                    pa.float32(),
                    "For a mob TP move: the mob's size in yalms, from its last full update (0x00E Flags2.g,"
                    " in tenths), where LSB sends its modelHitboxSize. None when not sent.",
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
                Column(
                    "resend",
                    pa.bool_(),
                    "Whether the same packet arrived within 500 ms before: a resend, not a second action."
                    " The combat tables skip resends.",
                ),
            ),
            indexes=("action action_id TYPE bloom_filter GRANULARITY 1",),
        ),
        Table(
            "action_results",
            "One row per result of an action on a target. A target can take several results, such as the"
            " hits of a multi-hit round. Join actions on capture_id and idx.",
            (
                Column("actor_id", pa.int64(), "Who acted."),
                Column("category", pa.int32(), "The action's category, as in actions."),
                Column("action_id", pa.int64(), "The action's id, as in actions."),
                Column("target_id", pa.int64(), "The target."),
                Column("target_index", pa.int32(), "The target's place in the packet, from 0."),
                Column("result_index", pa.int32(), "The result's place for that target, from 0."),
                Column("miss", pa.int32(), "miss, as sent."),
                Column("kind", pa.int32(), "kind, as sent."),
                Column(
                    "sub_kind",
                    pa.int32(),
                    "sub_kind: the animation; for melee 0 main hand, 1 off hand, 2 and 3 kicks.",
                ),
                Column(
                    "info", pa.int32(), "info, as sent: 2 marks a critical hit, a TP move's too; 1 a defeat."
                ),
                Column(
                    "scale",
                    pa.int32(),
                    "scale, as sent: LSB packs a hit distortion in its low 2 bits and the knockback, 0 to 7,"
                    " in its high 3 (scale >> 2).",
                ),
                Column(
                    "value", pa.int64(), "The amount: damage, healing, or a status or item id, by message."
                ),
                Column("message", pa.int32(), "The result's message, an LSB msg_basic id."),
                Column("bit", pa.int64(), "bit, as sent; for a resisted spell, 2 marks a trait resist."),
                Column("proc_kind", pa.int32(), "The added effect's kind, when there is one."),
                Column("proc_info", pa.int32(), "The added effect's info."),
                Column("proc_value", pa.int64(), "The added effect's amount, such as skillchain damage."),
                Column(
                    "proc_message",
                    pa.int32(),
                    "The added effect's message: 288 to 302 and 767, 768 skillchains, 229 enspell or rune,"
                    " 163 additional effect damage.",
                ),
                Column("react_kind", pa.int32(), "The reaction's kind, when there is one."),
                Column("react_info", pa.int32(), "The reaction's info."),
                Column("react_value", pa.int64(), "The reaction's amount, such as spikes or counter damage."),
                Column(
                    "react_message",
                    pa.int32(),
                    "The reaction's message: 44 spikes, 132 Dread Spikes, 33 counter, 536 retaliation. Its"
                    " damage lands on the actor.",
                ),
            ),
        ),
        Table(
            "tp_nearby",
            "For each mob TP move (category 11), one row per entity placed near the mob: each target, and"
            " everyone else with a known position within 30 yalms not known to be at 0 HP. Join actions on"
            " capture_id and idx. After Skold177's method in phoenixffxi/xi-ai#13.",
            (
                Column("actor_id", pa.int64(), "The mob."),
                Column("action_id", pa.int64(), "The mob skill."),
                Column("entity_id", pa.int64(), "The entity near it: a player, trust, pet, NPC, or mob."),
                Column("hit", pa.bool_(), "Whether it was a target, a miss or a shadow taken included."),
                Column("party", pa.bool_(), "Whether it is the character or in its party or alliance."),
                Column("distance", pa.float32(), "Yalms from the mob, centre to centre, in 3D."),
                Column(
                    "bearing",
                    pa.float32(),
                    "Degrees off the mob's heading (actor_dir), -180 to 180: 0 ahead, 180 behind; the sign"
                    " gives the side. None when the heading is unknown.",
                ),
                Column(
                    "from_target",
                    pa.float32(),
                    "Yalms from the move's first target, in 3D. None when its position is unknown.",
                ),
                Column("age_ms", pa.int64(), "How old the entity's position was, in ms."),
            ),
        ),
    )
