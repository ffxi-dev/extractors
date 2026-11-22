import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.extractors.battle import positions

INVISIBLE, DEODORIZE, SNEAK = 69, 70, 71


# The character's state and the world's at a moment: both tables carry it.
STATE = (
    Column("zone_id", pa.int32(), "The zone."),
    Column("mob_id", pa.int64(), "The mob."),
    Column(
        "distance",
        pa.float32(),
        "Yalms from the mob to the character, centre to centre, in 3D, from the last positions sent. None"
        " when one is unknown.",
    ),
    Column("dz", pa.float32(), "The character's height above the mob, in yalms."),
    Column(
        "facing",
        pa.float32(),
        "Degrees from the mob's heading to the character, -180 to 180: 0 ahead, 180 behind. None when the"
        " heading is unknown.",
    ),
    Column("mob_x", pa.float32(), "The mob's last position, as XiPackets names it."),
    Column("mob_y", pa.float32(), "Position."),
    Column("mob_z", pa.float32(), "Height."),
    Column("mob_dir", pa.int32(), "The mob's last heading, 0 to 255, as actions.actor_dir."),
    Column(
        "mob_age_ms", pa.int64(), "How old the mob's position was. An idle mob sends one only when it moves."
    ),
    Column("me_age_ms", pa.int64(), "How old the character's position was (c2s 0x015)."),
    Column("since_seen_ms", pa.int64(), "Since the mob was first seen alive in this life."),
    Column(
        "invisible",
        pa.bool_(),
        "Whether the character had Invisible (status 69), from its last 0x037; None before one.",
    ),
    Column("sneak", pa.bool_(), "Whether it had Sneak (71)."),
    Column("deodorize", pa.bool_(), "Whether it had Deodorize (70)."),
    Column("hpp", pa.int32(), "The character's HP%, from its last 0x037, 0x0DD or 0x0DF."),
    Column("resting", pa.bool_(), "Whether it was resting (0x037 status 33)."),
    Column(
        "recorder_status", pa.int32(), "The character's 0x037 server_status: 0 idle, 1 engaged, 33 resting."
    ),
    Column("vana_hour", pa.int32(), "The Vana'diel hour, 0 to 23, as LSB counts it."),
    Column(
        "weather_id",
        pa.int32(),
        "The weather the last zone-in or 0x057 named; none before the first. From 4 on, ids pair by"
        " element, the odd one double. Names are in weather_names.",
    ),
)


class Engages(Extractor):
    """Mobs that start a fight, and mobs the character walks past. A mob's claim (0x00E BtTargetID) stays 0
    when it aggroes and is set only once the party acts, so the start is its status going from idle to
    engaged (server_status 0 to 1) while unclaimed: in that update its speed jumps and its heading turns to
    its target. What the party did before, and whom the mob acts on first, tell an aggro from a pull: the
    derived aggro fact sorts them."""

    name = "engages"
    version = 2  # 2: a stranger's claimed mob can be the one it linked to
    doc = "Each idle, unclaimed mob that engaged, and each pass the character made by one that did not."
    reads = positions.READS | frozenset({(0, 0x028), (0, 0x037), (1, 0x01A)})
    sparse = False  # a pass needs only the world's sightings
    tables = (
        Table(
            "mob_engages",
            "One row per idle, unclaimed mob whose status went to engaged (0x00E server_status 0 to 1), or"
            " that a claim reached first. idx is that update. Position columns are from before it; flip_*"
            " are what it sent.",
            (
                *STATE,
                Column("status_before", pa.int32(), "The mob's server_status before: 0 idle."),
                Column("status", pa.int32(), "Its status in the update: 1 engaged."),
                Column("mob_speed", pa.int32(), "The mob's Speed before the update."),
                Column("flip_dir", pa.int32(), "The heading the update sent, if it sent a position."),
                Column("flip_speed", pa.int32(), "The Speed it sent."),
                Column(
                    "flip_facing",
                    pa.float32(),
                    "Degrees from the heading sent to the character, as facing: near 0 when the mob turned"
                    " to it.",
                ),
                Column(
                    "me_action_id",
                    pa.int32(),
                    "The character's last c2s 0x01A on the mob in the 30 s before: its ActionID.",
                ),
                Column("me_action_ms", pa.int64(), "How long before the engage it was."),
                Column(
                    "party_actor_id",
                    pa.int64(),
                    "The last of the party (trusts and pets too) to act on the mob in the 30 s before.",
                ),
                Column("party_category", pa.int32(), "That action's category."),
                Column("party_ms", pa.int64(), "How long before the engage it was."),
                Column(
                    "other_ms",
                    pa.int64(),
                    "How long before the engage another player last acted on the mob, within 30 s.",
                ),
                Column(
                    "mob_acted_ms",
                    pa.int64(),
                    "How long before the engage the mob last acted on a player, within 30 s.",
                ),
                Column(
                    "first_ms",
                    pa.int64(),
                    "The mob's first action on a player after the engage, within 60 s: ms after.",
                ),
                Column("first_category", pa.int32(), "Its category."),
                Column("first_target_id", pa.int64(), "Its first target."),
                Column("first_target_recorder", pa.bool_(), "Whether that is the character."),
                Column(
                    "first_target_party",
                    pa.bool_(),
                    "Whether that is the character, its party, a trust, or a pet.",
                ),
                Column(
                    "answered_ms",
                    pa.int64(),
                    "The first c2s 0x01A on the mob, or party action on it, after the engage: ms after.",
                ),
                Column(
                    "claim_ms",
                    pa.int64(),
                    "When a claim first reached it after, within 60 s: ms after; 0 in the update itself.",
                ),
                Column("claimer_id", pa.int64(), "Who claimed it."),
                Column(
                    "claimer_party",
                    pa.bool_(),
                    "Whether the claimer is the character, its party, a trust, or a pet.",
                ),
                Column(
                    "link_mob_id",
                    pa.int64(),
                    "The nearest other mob engaged at the time: claimed by the party, by a stranger within 15"
                    " yalms, or itself engaged in the 30 s before unclaimed.",
                ),
                Column("link_distance", pa.float32(), "Yalms between the two mobs."),
                Column(
                    "link_ms",
                    pa.int64(),
                    "How long before the other mob's own engage was; None when not seen.",
                ),
            ),
        ),
        Table(
            "mob_passes",
            "One row per time the character came within 15 yalms of an idle, unclaimed monster that did not"
            " engage, until it was 17 yalms off, the mob changed, or the zone did. idx is the closest moment,"
            " and the columns are as they were then.",
            (*STATE, Column("duration_ms", pa.int64(), "How long the character stayed in range.")),
        ),
    )
