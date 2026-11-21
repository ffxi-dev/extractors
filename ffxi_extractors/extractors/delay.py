import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

HIT = frozenset({1, 67})  # AttackHits, AttackCrit
COUNTER = frozenset({33, 14})  # reactions: a counter, and a counter a shadow absorbed
DEFEATED = combat.DEFEAT | {97}  # 97: a player was defeated
CUT_SHORT_MS = 1000
OUTCOMES = ("crits", "misses", "parried", "absorbed", "anticipated", "countered", "dodged", "blocked",
            "guarded", "other")  # fmt: skip


def outcome(r: dict) -> str | None:
    """A swing's outcome, in the order LSB resolves a swing; None for a plain hit."""
    msg, react = r["message"], (r["react"] or {}).get("message")
    if msg == 32:
        return "dodged"
    if msg == 70:
        return "parried"
    if msg == 31:
        return "absorbed"
    if msg == 30:
        return "anticipated"
    if react in COUNTER:
        return "countered"
    if msg in HIT:
        return {4: "blocked", 2: "guarded"}.get(r["miss"], "crits" if msg == 67 else None)
    return "misses" if msg == 15 else "other"


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

    def __init__(self):
        self.last: dict[int, int | None] = {}  # actor -> time of its last round, None while paused
        self.recent: dict[int, dict] = {}  # target -> its last round
        self.tp: int | None = None  # the character's TP in its last 0x0DF
        self.waiting: dict | None = None  # a round whose TP gain the next 0x0DF gives
        self.spoiled = False  # something else touched the character since its last 0x0DF
        self.resends = combat.Resends()

    def packet(self, p, f, world, emit):
        me = world.character_id
        if p.opcode == 0x00A:
            self.last.clear()
            self.recent.clear()
            self.tp, self.waiting, self.spoiled = None, None, False
            return
        if p.opcode == 0x0DF:
            if f("UniqueNo") != me or (tp := f("Tp")) is None:
                return
            if self.waiting is not None and not self.spoiled and self.tp is not None:
                self.waiting["tp_gain"] = tp - self.tp
            self.tp, self.waiting, self.spoiled = tp, None, False
            return
        if p.opcode == 0x00E:
            if f("SendFlg.Despawn"):
                self.last.pop(f("UniqueNo"), None)
            return
        if p.opcode == 0x029:
            if f("MessageNum") in DEFEATED:
                self.last.pop(f("UniqueNoTar"), None)  # as attackdelay forgets a defeated mob
                if row := self.recent.pop(f("UniqueNoTar"), None):
                    row["cut_short"] = p.ts_ms - row["ts_ms"] <= CUT_SHORT_MS
            return
        if self.resends.is_resend(p):
            return
        a = combat.read(f)
        actor, cat = a["actor_id"], a["cmd_no"]
        on_me = [rs for t, rs in a["targets"] if me and t == me]
        # A TP gain counts only when one mob swing that hit is all that touched the character since its
        # last 0x0DF: anything else (its own actions, other hits, spells on it) moves its TP too.
        wait = False
        if on_me or (me and actor == me):
            one_hit = len(on_me) == 1 and len(on_me[0]) == 1 and outcome(on_me[0][0]) in (None, "crits")
            if cat == 1 and combat.is_mob(actor) and one_hit and self.waiting is None and not self.spoiled:
                wait = True
            else:
                self.spoiled = True
        if cat in (4, 8, 11):  # a spell or TP move: the next round's interval includes it
            if actor in self.last:
                self.last[actor] = None
            return
        if cat != 1 or not a["targets"]:
            return
        target_id, results = a["targets"][0]
        before = self.last.get(actor)
        self.last[actor] = p.ts_ms
        outcomes = [outcome(r) for r in results]
        row = emit(
            "attack_rounds",
            p,
            actor_id=actor,
            actor_is_mob=combat.is_mob(actor),
            target_id=target_id,
            interval_ms=p.ts_ms - before if before is not None else None,
            swings=len(results),
            hits=sum(r["message"] in HIT for r in results),
            main_hand=sum(r["sub_kind"] == 0 for r in results),
            off_hand=sum(r["sub_kind"] == 1 for r in results),
            kicks=sum(r["sub_kind"] in (2, 3) for r in results),
            targets=len(a["targets"]),
            cut_short=False,
            at_character=bool(me) and target_id == me,
            **{k: outcomes.count(k) for k in OUTCOMES},
            zone_id=world.zone,
        )
        self.recent[target_id] = row
        if wait:
            self.waiting = row
