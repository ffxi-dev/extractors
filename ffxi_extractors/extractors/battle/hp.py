import math

import pyarrow as pa

from ffxi_extractors import combat
from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World

# hptrackv2's MSG_TYPES: [category][message] -> 1 damage, -1 healing, 0 neither. Anything else is skipped.
_D, _H, _N = 1, -1, 0
MSG_TYPES = {
    1: {1: _D, 67: _D, 15: _N, 30: _N, 31: _N, 32: _N, 33: _N, 70: _N},
    2: {157: _D, 352: _D, 353: _D, 576: _D, 577: _D, 382: _H, 31: _N, 354: _N},
    3: {135: _D, 185: _D, 187: _D, 197: _D, 264: _D, 317: _D, 379: _D, 102: _H, 103: _H, 238: _H, 263: _H,
        318: _H, 539: _H, 158: _N, 186: _N, 188: _N, 189: _N, 194: _N, 224: _N, 225: _N, 226: _N, 323: _N,
        324: _N},
    4: {2: _D, 227: _D, 252: _D, 262: _D, 264: _D, 274: _D, 648: _D, 650: _D, 7: _H, 263: _H, 651: _H},
    7: {43: _N},
    6: {110: _D, 264: _D, 317: _D, 263: _H, 318: _H, 158: _N, 323: _N, 324: _N},
    11: {185: _D, 187: _D, 197: _D, 264: _D, 238: _H, 263: _H, 43: _N, 186: _N, 188: _N, 189: _N, 194: _N},
    13: {110: _D, 185: _D, 264: _D, 317: _D, 238: _H, 263: _H, 188: _N, 189: _N, 323: _N, 324: _N},
    14: {110: _D, 264: _D, 102: _H, 103: _H, 263: _H, 158: _N, 319: _N, 323: _N},
    15: {2: _D, 110: _D, 252: _D, 264: _D, 323: _N},
}  # fmt: skip
PROCS = frozenset({*range(288, 303), 767, 768, 229, 163})  # skillchains, enspells and runes, added damage
REACTS = frozenset({44, 132, 33, 536})  # spikes, Dread Spikes, counter, retaliation
# An HP% fall with no damage seen since the last update, and none in this long after it (the action can
# follow its HP%): damage no packet names, a damage-over-time tick (Helix, Bio, Dia, poison). The kill's
# damage then falls short of its HP, so it gives no HP.
SILENT_MS = 1500


class _Mob:
    def __init__(self, start_hpp: int, hpp: int):
        self.damage = self.hits = self.healing = 0
        self.last = self.extra = 0  # the last ordinary hit, and the proc and reaction damage since it
        self.start_hpp, self.hpp = start_hpp, hpp
        self.hp_min, self.hp_max = 1, None
        self.contradictions = 0
        self.base = 0  # net damage when the HP% window last restarted, after a rise no heal explains
        self.healed = False  # a heal seen since the last HP% update
        self.regen = 0  # HP% points regained with no heal seen
        self.run_pts = self.run_ms = 0  # of those, the ones in back-to-back rises, and the time they took
        self.last_rise: tuple[int, int, int] | None = None  # (when, hits then, healing then)
        self.windows: list[tuple[int, int]] = []  # max HP bounds, one per HP% update, for range() under regen
        self.lag = 0  # the latest action's damage, which the next HP% update may not show yet
        self.hits_at = 0  # hits when the HP% last changed
        self.falling: int | None = None  # when an HP% fall with no damage seen came, until damage explains it
        self.silent = False  # an HP% fall nothing explained: damage no packet named

    def hit(self, damage: int, side: bool, ts_ms: int | None = None) -> None:
        """Damage taken; side: from a proc or reaction. It explains an HP% fall just before it."""
        if self.falling is not None and ts_ms is not None and ts_ms - self.falling <= SILENT_MS:
            self.falling = None
        self.damage += damage
        self.hits += 1
        if side:
            self.extra += damage
        else:
            self.last, self.extra = damage, 0

    def net(self) -> int:
        return self.damage - self.healing

    def update(self, hpp: int, ts_ms: int) -> None:
        """A new HP%. A rise with no heal seen is regen: the HP% window restarts there, since the damage
        before it no longer explains the bar. Back-to-back rises, with no hit or heal between them however
        far apart, give regen's rate: a big mob's bar can take 90 s to move a point. Any other update
        bounds max HP from the window so far, for range() to vote on. A fall with no damage seen since the
        last, and none soon after, is silent."""
        self.settle(ts_ms)
        if hpp < self.hpp and self.hits == self.hits_at and self.falling is None:
            self.falling = ts_ms
        if hpp != self.hpp:
            self.hits_at = self.hits
        if hpp > self.hpp > 0 and not self.healed:
            self.regen += hpp - self.hpp
            if self.last_rise is not None and self.last_rise[1:] == (self.hits, self.healing):
                self.run_pts += hpp - self.hpp
                self.run_ms += ts_ms - self.last_rise[0]
            self.last_rise = (ts_ms, self.hits, self.healing)
            self.start_hpp, self.base = hpp, self.net()
        else:
            if hpp != self.hpp:
                self.last_rise = None
            d_hpp, net = self.start_hpp - hpp, self.net() - self.base
            if d_hpp > 0 and hpp > 1:
                self.windows.append((math.ceil((net - self.lag) * 100 / (d_hpp + 1)),
                                     math.floor(net * 100 / (d_hpp - 0.99999))))  # fmt: skip
        self.hpp, self.healed, self.lag = hpp, False, 0

    def settle(self, ts_ms: int) -> None:
        """A fall no damage came to explain in time is silent."""
        if self.falling is not None and ts_ms - self.falling > SILENT_MS:
            self.silent, self.falling = True, None

    def regen_rate(self) -> float | None:
        """HP% regained per 3 s tick, from back-to-back rises."""
        return round(self.run_pts * 3000 / self.run_ms, 4) if self.run_ms else None

    def refine(self, round_damage: int) -> None:
        """hptrackv2's refineHpRange: with hpp = floor(100 * hp / max), the HP% drop bounds max HP."""
        self.lag = round_damage
        d_hpp = self.start_hpp - self.hpp
        if d_hpp <= 0 or self.hpp <= 1:
            return
        net = self.net() - self.base
        lo = math.ceil((net - round_damage) * 100 / d_hpp)
        hi = math.floor(net * 100 / (d_hpp - 0.99999))
        if hi < self.hp_min or (self.hp_max is not None and lo > self.hp_max):
            self.contradictions += 1
            return
        self.hp_min = max(self.hp_min, lo)
        self.hp_max = hi if self.hp_max is None else min(self.hp_max, hi)

    def range(self) -> tuple[int, int]:
        """hptrackv2's calculateHpRange: the killing blow overkills, so death bounds HP between everything
        but the last hit (and the procs and reactions after it) and everything. With regen the damage
        overstates HP, so only the HP% windows bound it, by vote: the HP the most windows allow. Regen
        the bar doesn't show yet throws a window off, and taking the first window that narrows the range
        let one bad window rule out every later one. With no window left standing, the damage bounds it."""
        if self.regen and self.windows:
            edges = sorted([(lo, 1) for lo, _ in self.windows] + [(hi + 1, -1) for _, hi in self.windows])
            best = cur = 0
            for _, e in edges:
                cur += e
                best = max(best, cur)
            spans, cur, at = [], 0, None
            for x, e in edges:
                cur += e
                if cur == best and at is None:
                    at = x
                elif cur < best and at is not None:
                    spans.append((at, x - 1))
                    at = None
            if spans:
                return spans[0][0], spans[-1][1]
        total = self.net()
        if self.hits == 1:
            return max(1, self.hp_min), min(total, self.hp_max if self.hp_max is not None else total)
        lo, hi = total - (self.last + self.extra) + 1, total
        nlo = max(lo, self.hp_min)
        nhi = min(hi, self.hp_max) if self.hp_max is not None else hi
        return (lo, hi) if nlo > nhi else (nlo, nhi)


class Hp(Extractor):
    """Ported from captain's hptrackv2: the damage each mob took from everything the capture shows, melee,
    weapon skills, spells, skillchains, added effects, spikes, and counters, narrowed by its HP% updates,
    and its HP range when it dies. hptrackv2's warning stands: more accurate than the original but not
    perfect; regen, damage over time, and effects the capture missed throw it off. Damage the character
    could not see, such as a party member's out of range, is missing, so the range is low then."""

    name = "hp"
    # 2: a despawn ends the mob's life; 3: regen; 4: slow regen's rate; 5: HP by vote under regen; 7: a
    # counter is no hit on the mob, trusts and pets are not mobs
    version = 7
    doc = "Each defeated mob's damage taken and HP range (0x028, 0x029, 0x00E)."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x00E), (0, 0x00A)})
    tables = (
        Table(
            "mob_hp",
            "One row per defeated mob that the capture saw take damage, at its defeat (0x029 6 or 20), but"
            " one whose HP% fell with no damage seen (a damage-over-time tick): its damage falls short of"
            " its HP."
            " hptrackv2's warning: close but not perfect; regen, damage over time, and missed effects throw"
            " it off. Damage the character could not see, such as a party member's out of range, is missing.",
            (
                Column("mob_id", pa.int64(), "The mob."),
                Column("damage", pa.int64(), "Damage it took, procs and reactions included."),
                Column("healing", pa.int64(), "HP it recovered from actions the capture saw."),
                Column("hits", pa.int32(), "Damage entries counted, procs and reactions included."),
                Column("hp_min", pa.int64(), "Least max HP the damage and HP% updates allow."),
                Column("hp_max", pa.int64(), "Most max HP they allow."),
                Column("start_hpp", pa.int32(), "Its HP% when the capture first saw it take damage."),
                Column(
                    "contradictions",
                    pa.int32(),
                    "HP% windows that disagreed with the damage seen: regen, damage over time, or a missed"
                    " effect. Above 0, trust hp_min and hp_max less.",
                ),
                Column(
                    "regen",
                    pa.int32(),
                    "HP% points it regained with no heal seen: regen, or a heal out of view. Its HP then"
                    " comes from the HP% windows alone.",
                ),
                Column("regen_rate", pa.float64(), "HP% regained per 3 s, from back-to-back rises."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )

    def __init__(self):
        self.mobs: dict[int, _Mob] = {}
        self.hpp: dict[int, int] = {}
        self.prev_hpp: dict[int, int] = {}
        self.resends = combat.Resends()

    def _mob(self, mob_id: int) -> _Mob:
        m = self.mobs.get(mob_id)
        if m is None:
            hpp = self.hpp.get(mob_id, 100)
            # The current HP% may already count damage from an action not yet seen: take the higher.
            m = self.mobs[mob_id] = _Mob(max(hpp, self.prev_hpp.get(mob_id, 0)), hpp)
        return m

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        op = p.opcode
        if op == 0x00A:
            self.mobs.clear()
            self.hpp.clear()
            self.prev_hpp.clear()
        elif op == 0x00E:
            uid, hpp = f("UniqueNo"), f("Hpp")
            if f("SendFlg.Despawn"):  # it may die and respawn out of view: its next damage is a new life's
                for d in (self.mobs, self.hpp, self.prev_hpp):
                    d.pop(uid, None)
            elif f("SendFlg.General") and uid is not None and hpp is not None:
                if self.hpp.get(uid) != hpp:
                    if uid in self.hpp:
                        self.prev_hpp[uid] = self.hpp[uid]
                    self.hpp[uid] = hpp
                if uid in self.mobs:
                    self.mobs[uid].update(hpp, p.ts_ms)
        elif op == 0x029:
            mob_id = f("UniqueNoTar")
            if f("MessageNum") in combat.DEFEAT and mob_id in self.mobs:
                m = self.mobs.pop(mob_id)
                m.settle(p.ts_ms)
                if not m.hits or m.silent:
                    return
                lo, hi = m.range()
                emit("mob_hp", p, mob_id=mob_id, damage=m.damage, healing=m.healing, hits=m.hits, hp_min=lo,
                     hp_max=hi, start_hpp=m.start_hpp, contradictions=m.contradictions, regen=m.regen,
                     regen_rate=m.regen_rate(), zone_id=world.zone)  # fmt: skip
        elif op == 0x028 and not self.resends.is_resend(p):
            self._action(combat.read(f), p.ts_ms)

    def _action(self, a, ts_ms: int) -> None:
        """An action's damage, healing, procs, and reactions on each mob it touched."""
        cat, actor = a["cmd_no"], a["actor_id"]
        signs = MSG_TYPES.get(cat, {})
        dealt: dict[int, int] = {}
        for target_id, results in a["targets"]:
            mob = combat.is_mob(target_id)  # a player's, trust's, or pet's damage and healing are not tracked
            for r in results:
                sign = signs.get(r["message"])
                react = r["react"] if r["react"] and r["react"]["message"] in REACTS else None
                if sign == _H and r["value"]:
                    if mob:
                        m = self._mob(target_id)
                        m.healing += r["value"]
                        m.healed = True
                        dealt[target_id] = dealt.get(target_id, 0) - r["value"]
                elif (sign == _D and r["value"]) or react:
                    damage = r["value"] if sign == _D else 0
                    proc = r["proc"]
                    if mob and damage:  # a countered swing does no damage: it is no hit
                        self._mob(target_id).hit(damage, False, ts_ms)
                        dealt[target_id] = dealt.get(target_id, 0) + damage
                        if proc and proc["message"] in PROCS and proc["value"]:
                            self._mob(target_id).hit(proc["value"], True, ts_ms)
                            dealt[target_id] += proc["value"]
                    if react and react["value"] and combat.is_mob(actor):
                        self._mob(actor).hit(react["value"], True, ts_ms)
                        dealt[actor] = dealt.get(actor, 0) + react["value"]
        for mob_id, d in dealt.items():
            if mob_id in self.mobs:
                self.mobs[mob_id].refine(max(d, 0))
