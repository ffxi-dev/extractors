"""The action packet (0x028) as the combat extractors read it: its actor, category, and each target's
results, decoded once per packet however many extractors ask. Also the rules the combat ports share:
which ids are mobs, which messages mean a defeat, and how a resent packet is spotted."""

from __future__ import annotations

from functools import lru_cache

P = "action (decoded bitstream)."
RESULT = ("miss", "kind", "sub_kind", "info", "scale", "value", "message", "bit")
EXTRA = ("kind", "info", "value", "message")
DEFEAT = frozenset({6, 20})  # LSB msg_basic: DefeatsTarget, FallsToGround; captain's addons use both
RESEND_MS = 500  # hptrack: a packet whose payload repeats within this window is a resend


def is_player(entity_id: int | None) -> bool:
    """A player: an id under 0x1000000."""
    return entity_id is not None and entity_id < 0x1000000


def is_dynamic(entity_id: int | None) -> bool:
    """A trust or pet: an NPC id, 0x01ZZZIII, with an index the zone hands out, 0x700 on."""
    return entity_id is not None and entity_id >> 24 == 1 and (entity_id & 0xFFF) >= 0x700


def is_mob(entity_id: int | None) -> bool:
    """A zone's own NPC or mob: id 0x01ZZZIII with index III under 0x400, as actionview's isMob. Trusts,
    pets, and players fall outside it."""
    return entity_id is not None and entity_id >> 24 == 1 and (entity_id & 0xFFF) < 0x400


@lru_cache(maxsize=1)  # the extractors share one packet's getter, so this decodes each packet once
def action(f) -> dict:
    """{"actor_id", "cmd_no", "cmd_arg", "info", "targets": [(target_id, [result, ...]), ...]}. A result is
    a dict of RESULT, plus "proc" and "react": dicts of EXTRA, or None when the result has none."""
    a = {k: f(P + k) for k in ("actor_id", "cmd_no", "cmd_arg", "info")}
    targets = []
    for t in range(f(P + "target_count") or 0):
        tp = f"{P}targets[{t}]"
        results = []
        for i in range(f(tp + ".result_count") or 0):
            rp = f"{tp}[{i}]."
            r = {k: f(rp + k) for k in RESULT}
            for g in ("proc", "react"):
                r[g] = {k: f(f"{rp}{g}.{k}") for k in EXTRA} if f(f"{rp}{g}.message") is not None else None
            results.append(r)
        targets.append((f(tp + ".target_id"), results))
    a["targets"] = targets
    return a


class Resends:
    """Spots a resent packet: the same bytes after the sync counter within RESEND_MS, as hptrack does."""

    def __init__(self):
        self.seen: dict[bytes, int] = {}

    def is_resend(self, p) -> bool:
        key = bytes(p.data[4:])
        at = self.seen.get(key)
        self.seen[key] = p.ts_ms
        if len(self.seen) > 4096:
            self.seen = {k: t for k, t in self.seen.items() if p.ts_ms - t < RESEND_MS}
        return at is not None and p.ts_ms - at < RESEND_MS
