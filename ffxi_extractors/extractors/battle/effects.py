import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Effects(Extractor):
    """The character's status effects, as the zone lists them in 0x063 type 9 with each one's expiry, and the
    action that applied each. Only the character's own list carries expiries: the party's (0x076) has
    icons only, and nothing lists a mob's, so theirs have no row."""

    name = "effects"
    version = 9  # 2: a mob's move or spell that gives its effect silently, and named; a Cure's HP names no
    # status; 3: a renewal no result names has no source; 4: a silent move waits for a naming result and
    # takes no buff a player gave; 5: a silent move lands and gives no buff; the capture's clock offset;
    # 6: the offset from a zone-in's server time, so a capture whose clock runs ahead keeps its sources;
    # 7: each row by the offset in force at it, for a capture across a clock change; a job ability a player,
    # trust, or pet used on the character comes before a silent move; 8: such an ability gives no ailment,
    # a paralyzed mob gives nothing, and an icon cleared early counts against no clock offset; 9: a silent
    # move gives only an ailment
    doc = (
        "Each status effect applied to the character: how long the zone said it would last, and what gave it."
    )
    reads = frozenset({(0, 0x063), (0, 0x028), (0, 0x00A)})
    tables = (
        Table(
            "effects",
            "One row per status effect applied to the character: an icon added to its status list (0x063"
            " type 9), or one whose expiry moved over 2 s later. idx and ts_ms are that 0x063's.",
            (
                Column(
                    "status_id",
                    pa.int32(),
                    "The icon, which is the status id (status_names); 0 is KO, which has no source.",
                ),
                Column(
                    "expires_ms",
                    pa.int64(),
                    "When 0x063 said it would wear off, Unix ms by the capture's clock; none for an effect"
                    " without an end. The list counts by the server's clock: a capture whose clock ran whole"
                    " hours off it, as a PacketViewer log stamped in local time does, is set back by them.",
                ),
                Column(
                    "duration_ms",
                    pa.int64(),
                    "expires_ms less when it was applied: the action's time when one applied it, else the"
                    " 0x063's. The duration retail gave it, to within the recorder's clock.",
                ),
                Column(
                    "ended_ms",
                    pa.int64(),
                    "When this application ended: its icon left the list, or a later one renewed it. None if"
                    " the capture ended first. A zone-in that lists the same expiry again does not end it.",
                ),
                Column("renewed", pa.bool_(), "Whether the icon was already listed, and this renewed it."),
                Column(
                    "source_idx",
                    pa.int64(),
                    "The action packet (0x028) whose result on the character applied it: one from 3 s before"
                    " the icon to 1 s after that names the status: by a message that lands an effect, or a"
                    " job ability's or item's value. Else, for a new icon, the latest item or job ability a"
                    " player, trust, or pet used on the character, such as a roll, which names its total;"
                    " else a mob's TP move or spell that landed on it under 1.5 s before, unless the status"
                    " is one a player can click off, or a player, trust, or pet gave it that status by name"
                    " in the capture. None when none did, such as"
                    " an effect a 0x029 message gave, a renewal no result named, or an expiry before the"
                    " action.",
                ),
                Column(
                    "named",
                    pa.bool_(),
                    "Whether the source's result names the status. False for an item, and for a mob's move or"
                    " spell whose result gave only damage: it gave the effect silently.",
                ),
                Column("source_ms", pa.int64(), "That action's time."),
                Column("actor_id", pa.int64(), "Who acted: a mob, player, trust, or pet."),
                Column(
                    "actor_name",
                    pa.string(),
                    "A mob or NPC actor's name as the client spells it (0x00E), as the bestiary names mobs.",
                ),
                Column("category", pa.int32(), "The action's category, as in actions."),
                Column("action_id", pa.int64(), "The action's id: spell, ability, item, or mob skill."),
                Column("message", pa.int32(), "The result's message."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
