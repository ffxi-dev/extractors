import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

INTS = pa.list_(pa.int32())
# 0x02D messages that give points (LSB msg_basic): (kind, whether Data2 holds the chain number).
GAINS = {8: ("exp", False), 253: ("exp", True), 371: ("limit", False), 372: ("limit", True),
         718: ("capacity", False), 735: ("capacity", True), 809: ("exemplar", False),
         810: ("exemplar", True)}  # fmt: skip
LEVEL = {9: "up", 11: "down"}  # LSB msg_basic LevelUp, LevelDown
STATUS_ICONS = 9  # 0x063's type for the character's status list
# Status effects that change the points a kill gives. LSB scripts/globals/experience_points.lua applies
# Dedication, Sanction, Signet (a party's share), and Corsair's Roll (by EXP_BONUS); bg-wiki "Experience
# Points" (flagged for verification, no JP entry) adds Commitment for capacity points and Ionis. Level Sync
# and Level Restriction change the level the points are graded on.
EFFECTS = {249: "Dedication", 579: "Commitment", 326: "Corsair's Roll", 256: "Sanction", 512: "Ionis",
           269: "Level Sync", 143: "Level Restriction"}  # fmt: skip
SIGNET = 253  # bg-wiki: a bonus in a party of 2 to 5 only; LSB's share table is 1.0 alone with it or not
# Key items that raise the points. The Rhapsodies: LSB experienceBonusKeyItems, +30% each. bg-wiki
# "Experience Points": Moghancement: Bounty, Moglification: Experience Boost, Capacity Boost, and the Monster
# Rearing cheers with an EXP bonus.
KEY_ITEMS = frozenset({2884, 2885, 2886, 2887, 2888, 2889, 542, 562, 563,
                       2716, 2745, 2746, 2754, 2762, 2765, 2771, 2775, 2787, 2788})  # fmt: skip


class Experience(Extractor):
    """Points the character gained and level changes, from the battle message 0x02D, with what changes the
    points: its status effects (0x063's status list), key items (0x055), and party (the world's)."""

    name = "experience"
    version = 1
    doc = "EXP, limit, capacity, and exemplar point gains with their chain and bonuses; level ups and downs."
    reads = frozenset({(0, 0x02D), (0, 0x063), (0, 0x055)})
    tables = (
        Table(
            "exp_gains",
            "One row per point gain (0x02D 8, 253, 371, 372, 718, 735, 809, 810), resends skipped.",
            (
                Column("recipient_id", pa.int64(), "Who gained (UniqueNoCas)."),
                Column("own", pa.bool_(), "Whether that is the character."),
                Column("kind", pa.string(), "exp, limit, capacity, or exemplar."),
                Column("points", pa.int64(), "The points (Data)."),
                Column("chain", pa.int32(), "The chain number: Data2 on a chain message (253 ...), else 0."),
                Column("message", pa.int32(), "The message."),
                Column(
                    "mob_id",
                    pa.int64(),
                    "The mob the points came from (UniqueNoTar); none when it names no mob, as for a"
                    " Records of Eminence reward.",
                ),
                Column(
                    "party_size",
                    pa.int32(),
                    "The character and every party and alliance member listed (0x0DD, 0x0E2, 0x0C8),"
                    " Trusts included.",
                ),
                Column(
                    "effects",
                    INTS,
                    "The character's status effects that change the points (0x063 type 9): Dedication"
                    " (249), Commitment (579), Corsair's Roll (326), Sanction (256), Ionis (512), Level Sync"
                    " (269), Level Restriction (143), and Signet (253) in a party of 2 to 5.",
                ),
                Column(
                    "key_items",
                    INTS,
                    "Key items held that raise the points (0x055): the Rhapsodies (2884 to 2889),"
                    " Moghancement: Bounty, Moglification: Experience and Capacity Boost, and the Monster"
                    " Rearing cheers that raise EXP.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
        Table(
            "level_changes",
            "One row per level up (0x02D 9) or down (11), the character's or a party member's.",
            (
                Column("member_id", pa.int64(), "Whose level changed (UniqueNoCas)."),
                Column("own", pa.bool_(), "Whether that is the character."),
                Column("change", pa.string(), "up or down."),
                Column("level", pa.int32(), "The new level (Data)."),
                Column("mob_id", pa.int64(), "The mob whose defeat gave it, if the message names one."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.statuses: set[int] = set()
        self.held: dict[int, set[int]] = {}  # key item table -> bonus key items held
        self.resends = combat.Resends()

    def packet(self, p, f, world, emit):
        if p.opcode == 0x063:
            if f("type") == STATUS_ICONS:
                self.statuses = {s for i in range(32) if (s := f(f"data.icon[{i}]")) not in (None, 0, 255)}
            return
        if p.opcode == 0x055:
            table = f("TableIndex") or 0
            held = set()
            for i in range(16):
                word = f(f"GetItemFlag[{i}]") or 0
                held.update(table * 512 + i * 32 + b for b in range(32) if word >> b & 1)
            self.held[table] = held & KEY_ITEMS
            return
        msg = f("MessageNum")
        if (msg not in GAINS and msg not in LEVEL) or self.resends.is_resend(p):
            return
        who, target = f("UniqueNoCas"), f("UniqueNoTar")
        mob = target if combat.is_mob(target) else None
        own = who == world.character_id
        if msg in LEVEL:
            emit("level_changes", p, member_id=who, own=own, change=LEVEL[msg], level=f("Data"), mob_id=mob,
                 zone_id=world.zone)  # fmt: skip
            return
        kind, chained = GAINS[msg]
        size = len(world.party - {world.character_id}) + 1
        effects = sorted(self.statuses & (EFFECTS.keys() | ({SIGNET} if 2 <= size <= 5 else set())))
        held = sorted(set().union(*self.held.values())) if own else []
        emit("exp_gains", p, recipient_id=who, own=own, kind=kind, points=f("Data"),
             chain=(f("Data2") or 0) if chained else 0, message=msg, mob_id=mob, party_size=size,
             effects=effects if own else [], key_items=held, zone_id=world.zone)  # fmt: skip
