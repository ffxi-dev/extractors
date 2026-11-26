import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.extractors.items.gathering import HELD, PLACE

ROD, BAIT = 2, 3  # 0x050's EquipKind: the range and ammo slots
# The zone's fishing messages, from its own offset, as LSB's FISHMESSAGEOFFSET numbers them; retail's agree.
NOTHING, KEEN, ONE, MANY, GAVE_UP = 0x04, 0x35, 0x27, 0x0E, 200


class Fishing(Extractor):
    """The character's fishing: each cast (c2s 0x01A, action 14), the minigame the zone sends for a bite
    (0x115), how the client ended it (c2s 0x110 mode 3), how the zone took it (0x037's animation), and the
    catch it names (0x027), or the monster that claims the character when it reels one in (0x00E). The
    zone's fishing messages (0x036) have ids that differ by zone; they are kept as sent."""

    name = "fishing"
    # 2: the zone's offset is the one that explains the most casts, not a refusal's; 3: an emptied slot holds
    # no rod or bait; 4: a cast keeps only the messages before its animation ends; 5: the monster reeled in
    version = 5
    doc = "Each cast the character made: where, with what rod and bait, what bit, its minigame, its outcome."
    reads = HELD | {(0, 0x00A), (0, 0x00E),
        (1, 0x01A), (1, 0x110), (0, 0x115), (0, 0x027), (0, 0x02A), (0, 0x036), (0, 0x037), (0, 0x050)
    }  # fmt: skip
    tables = (
        Table(
            "fishing",
            "One row per cast (c2s 0x01A, action 14), and per minigame (0x115) the capture holds no cast for."
            " The minigame columns are empty when nothing bit.",
            (
                *PLACE,
                Column("rod_id", pa.int32(), "The item in the range slot (0x050) at the cast."),
                Column("bait_id", pa.int32(), "The item in the ammo slot (0x050) at the cast."),
                Column("hook_ms", pa.int64(), "When the minigame (0x115) came, Unix milliseconds."),
                Column("end_ms", pa.int64(), "When the outcome's animation (0x037) came, Unix milliseconds."),
                Column(
                    "stamina",
                    pa.int32(),
                    "0x115 stamina: the fish's HP. LSB sends rand(95, 105) * ((skill_level + 36) / 2) for one"
                    " fish (CalculateStamina).",
                ),
                Column(
                    "arrow_delay",
                    pa.int32(),
                    "0x115 arrow_delay. LSB: base_delay plus the rod's sm/lg_delay_bonus, at most 15.",
                ),
                Column("regen", pa.int32(), "0x115 regen: from the character's skill against skill_level."),
                Column(
                    "move_frequency",
                    pa.int32(),
                    "0x115 move_frequency. LSB: base_move plus the rod's sm/lg_move_bonus, at most 15.",
                ),
                Column(
                    "arrow_damage",
                    pa.int32(),
                    "0x115 arrow_damage. LSB: difficulty * fish_attack / 100 * 20 (fishing_rod.fish_attack).",
                ),
                Column(
                    "arrow_regen",
                    pa.int32(),
                    "0x115 arrow_regen. LSB: arrow_damage / 20 * fish_recovery / 100, times 10.",
                ),
                Column("time", pa.int32(), "0x115 time, in seconds. LSB: the rod's fish_time, with bonuses."),
                Column(
                    "angler_sense",
                    pa.int32(),
                    "0x115 angler_sense. LSB: 0 a small fish, 1 a large one, 2 and 3 the same with a keen"
                    " angler's sense (fishing_fish.size_type).",
                ),
                Column("intuition", pa.int32(), "0x115 intuition: LSB's lucky timing."),
                Column(
                    "hook",
                    pa.string(),
                    "What bit, from the zone's message: small fish, large fish, item, or monster. Empty when"
                    " the capture's zone has no cast that caught nothing to read the zone's messages by.",
                ),
                Column(
                    "feeling",
                    pa.string(),
                    "The message after the bite: good, bad, terrible, no skill, no skill sure, no skill"
                    " positive, keen, or epic, as LSB's FISHMESSAGEOFFSET names them.",
                ),
                Column(
                    "sensed_id",
                    pa.int32(),
                    "The fish a keen angler's sense named (0x02A), whether or not it was caught.",
                ),
                Column(
                    "reel",
                    pa.int32(),
                    "How the client ended the minigame (c2s 0x110 mode 3, para): 0 reeled in, 200 gave up,"
                    " 300 out of time, else the fish's stamina left.",
                ),
                Column(
                    "outcome",
                    pa.string(),
                    "nothing when nothing bit; else the character's animation (0x037) after the minigame:"
                    " caught, rod break, line break, monster, gave up (reel 200), or lost.",
                ),
                Column("item_id", pa.int32(), "What was caught, as the catch message (0x027) names it."),
                Column(
                    "count", pa.int32(), "How many were caught: more than one only by the zone's own message."
                ),
                Column(
                    "monster_id",
                    pa.int64(),
                    "The monster reeled in (outcome monster): the first mob whose update (0x00E) claims the"
                    " character from the bite to 10 s after the animation, that had not claimed it already."
                    " Retail spawns it beside the character, claimed, just before the animation. A monster"
                    " given up never spawns, so names none.",
                ),
                Column(
                    "messages",
                    pa.list_(pa.int32()),
                    "The zone's fishing messages (0x036) to the character during the cast, as sent.",
                ),
            ),
        ),
    )
