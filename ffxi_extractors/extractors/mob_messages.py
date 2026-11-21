import math

import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

DRAWN_IN = 232  # "<target> is drawn in!": actor and target are both the player drawn in
LEARNED = 419  # "<target> learns <spell>!": blue magic, sent to the learner once a mob it saw is defeated
NEAR = 10  # yalms: a draw-in leaves the player beside its mob
WAIT_MS = 3000  # a drawn player's next position comes within this


class MobMessages(Extractor):
    """Draw-ins and blue magic learned, from 0x029. A draw-in's message names only the player drawn in: retail
    moves the player beside the mob first (0x05B), so the mob is the one nearest the player's next position,
    the character's own (c2s 0x015), another player's (0x00D), or a trust's (0x00E). Trusts and pets are no
    candidates: only a zone's own monsters draw in."""

    name = "mob_messages"
    version = 2  # 2: a trust drawn in lands by its 0x00E; trusts and pets draw no one in
    doc = "Each draw-in, with the mob nearest where the player landed, and each blue magic spell learned."
    reads = frozenset({(0, 0x029), (0, 0x00E), (0, 0x00D), (1, 0x015), (0, 0x00A)})
    tables = (
        Table(
            "mob_messages",
            f"One row per draw-in (0x029 {DRAWN_IN}) and per blue magic spell learned (0x029 {LEARNED}),"
            " resends skipped.",
            (
                Column("kind", pa.string(), "drawn_in or learned."),
                Column("player_id", pa.int64(), "The player drawn in, or who learned the spell."),
                Column(
                    "mob_id",
                    pa.int64(),
                    f"For a draw-in: the monster nearest the player's next position, within {NEAR} yalms and"
                    f" {WAIT_MS // 1000} s; none when no position came or no monster was near.",
                ),
                Column("distance", pa.float32(), "Yalms from that monster's last position, in 3D."),
                Column("spell_id", pa.int32(), "For a spell learned: the spell."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )

    def __init__(self):
        self.resends = combat.Resends()
        self.monsters: set[int] = set()
        self.pos: dict[int, tuple[float, float, float]] = {}  # monster id -> its last position
        self.drawn: dict[int, dict] = {}  # player id -> its draw-in's row, until the player's next position

    def _landed(self, uid, at, p):
        row = self.drawn.pop(uid, None)
        if row is None or p.ts_ms - row["ts_ms"] > WAIT_MS or None in at:
            return
        near = min(((math.dist(at, xyz), m) for m, xyz in self.pos.items()), default=None)
        if near and near[0] <= NEAR:
            row["distance"], row["mob_id"] = near

    def packet(self, p, f, world, emit):
        op = p.opcode
        if op == 0x00A:
            self.monsters.clear()
            self.pos.clear()
            self.drawn.clear()
        elif p.direction == 1:
            self._landed(world.character_id, (f("x"), f("y"), f("z")), p)
        elif op == 0x00D:
            if f("SendFlg.Position"):
                self._landed(f("UniqueNo"), (f("x"), f("y"), f("z")), p)
        elif op == 0x00E:
            uid = f("UniqueNo")
            if f("SendFlg.Despawn"):
                self.pos.pop(uid, None)
                return
            if f("SendFlg.General"):
                (self.monsters.add if f("Flags1.MonsterFlag") else self.monsters.discard)(uid)
            xyz = (f("x"), f("y"), f("z"))
            if f("SendFlg.Position") and None not in xyz:
                if uid in self.monsters and combat.is_mob(uid):
                    self.pos[uid] = xyz
                self._landed(uid, xyz, p)
        elif f("MessageNum") in (DRAWN_IN, LEARNED) and not self.resends.is_resend(p):
            who = f("UniqueNoTar")
            if f("MessageNum") == LEARNED:
                emit("mob_messages", p, kind="learned", player_id=who, spell_id=f("Data"), zone_id=world.zone)
            else:
                self.drawn[who] = emit("mob_messages", p, kind="drawn_in", player_id=who, zone_id=world.zone)
