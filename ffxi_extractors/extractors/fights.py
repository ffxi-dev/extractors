import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

# A fight with no action between its mob and a player, Trust, or pet for this long is over. Inside fights
# 99.9% of gaps are under 18 s; the 30 to 180 s ones are fights partly out of range (scholar-combat design).
IDLE_MS = 180_000


class Fights(Extractor):
    """One row per mob life the capture saw fight: from the first action between it and a player, Trust,
    or pet to its defeat, its despawn, a zone change, three minutes with no such action, or the capture's
    end. A mob's casts on itself or another mob do not count. No captain addon records this; it is the
    unit the capture page shows. A defeat with no action seen before it, such as a party member's kill
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

    def __init__(self):
        self.open: dict[int, dict] = {}  # mob id -> its open fight's row
        self.resends = combat.Resends()
        self.last = None  # the last packet read, to tell at the capture's end which fights went idle

    def _close(self, mob_id, outcome, p, end=False):
        """Close a fight at p; it ends at p only when end is set, else at its last action. A fight already
        idle for IDLE_MS was disengaged, whatever closes it now."""
        row = self.open.pop(mob_id)
        if p.ts_ms - row["end_ms"] > IDLE_MS:
            outcome, end = "disengaged", False
        if end:
            row.update(end_idx=p.idx, end_ms=p.ts_ms)
        row["outcome"] = outcome

    def _expire(self, mob_id, p):
        fight = self.open.get(mob_id)
        if fight and p.ts_ms - fight["end_ms"] > IDLE_MS:
            self._close(mob_id, "disengaged", p)

    def _start(self, mob_id, p, world, emit):
        row = emit("fights", p, mob_id=mob_id, end_idx=p.idx, end_ms=p.ts_ms, outcome="open", actions=0,
                   actions_by=0, zone_id=world.zone)  # fmt: skip
        self.open[mob_id] = row
        return row

    def packet(self, p, f, world, emit):
        self.last = p
        op = p.opcode
        if op == 0x00A:
            for mob_id in list(self.open):
                self._close(mob_id, "zoned", p)
        elif op == 0x00E:
            uid = f("UniqueNo")
            if f("SendFlg.Despawn") and uid in self.open:
                self._close(uid, "despawned", p)
        elif op == 0x029:
            mob_id = f("UniqueNoTar")
            if f("MessageNum") in combat.DEFEAT and combat.is_mob(mob_id) and not self.resends.is_resend(p):
                self._expire(mob_id, p)
                if mob_id not in self.open:
                    self._start(mob_id, p, world, emit)
                self._close(mob_id, "defeated", p, end=True)
        elif op == 0x028:
            if self.resends.is_resend(p):
                return
            a = combat.read(f)
            actor = a["actor_id"]
            targets = {t for t, _ in a["targets"] if t is not None}
            # Only actions between a mob and someone else open or extend a fight: a mob buffing itself or a
            # fellow mob is not fighting, and kept fights open for hours. Mid-fight, such a buff still counts.
            if combat.is_mob(actor):
                if all(combat.is_mob(t) for t in targets):
                    fight = self.open.get(actor)
                    if fight and p.ts_ms - fight["end_ms"] <= IDLE_MS:
                        fight["actions"] += 1
                        fight["actions_by"] += 1
                    return
                mobs = {actor}
            else:
                mobs = {t for t in targets if combat.is_mob(t)}
            for mob_id in mobs:
                self._expire(mob_id, p)
                fight = self.open.get(mob_id)
                row = fight or self._start(mob_id, p, world, emit)
                row.update(end_idx=p.idx, end_ms=p.ts_ms, actions=row["actions"] + 1,
                           actions_by=row["actions_by"] + (mob_id == actor))  # fmt: skip

    def finish(self, world, emit):
        for mob_id in list(self.open):
            self._expire(mob_id, self.last)
