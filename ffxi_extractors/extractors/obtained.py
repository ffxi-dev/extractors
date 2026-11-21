import pyarrow as pa

from ..extract import Column, Extractor, Table
from .events import KINDS, LINK_MS, Link

GIL = 0xFFFF
RECYCLE = 17  # what the character drops waits here a while: neither a gain nor a loss
SETTLE_MS = 1000  # a change this soon after the last is part of the same move, trade or synthesis
POOL_MS = 10_000  # an item the character won from the pool lands this soon after


class Obtained(Extractor):
    name = "obtained"
    version = 1
    doc = "Items the character received, whatever gave them: a quest, a trade, a shop, a synthesis, the pool."
    reads = frozenset(KINDS) | {(0, op) for op in (0x00A, 0x01D, 0x01E, 0x01F, 0x020, 0x0D2, 0x0D3)}
    tables = (
        Table(
            "obtained",
            "One row per item the character's containers gained (0x01E, 0x01F, 0x020): its count across"
            " every container went up over a run of changes, each under 1 s after the last, so a move between"
            " slots or containers nets out. After a zone-in the server sends each container whole, and"
            " 0x01D's Flags marks it done; a slot first seen before then is what the character held and gives"
            " no row, so a capture's rows start at its first zone-in. Gil and the recycle bin are left out.",
            (
                Column("item_id", pa.int32(), "The item; its name is in item_names."),
                Column("quantity", pa.int32(), "How many more."),
                Column("container", pa.int32(), "Where the first of them landed: 0 is the inventory."),
                Column(
                    "source",
                    pa.string(),
                    "pool when the character had just won it from the treasure pool (0x0D3), and drops has"
                    " its row; null otherwise.",
                ),
                Column("zone_id", pa.int32(), "The zone."),
                Column(
                    "event_idx",
                    pa.int64(),
                    f"The start of the event it follows, in events: the open one, or one that ended under"
                    f" {LINK_MS // 1000} s before. Its npc_id is the NPC that gave it.",
                ),
            ),
        ),
    )

    def __init__(self):
        self.slots: dict[tuple[int, int], tuple[int, int]] = {}  # (container, index) -> (item, quantity)
        self.synced: int | None = None  # containers sent whole since the last zone-in, a bit each
        self.net: dict[int, list] = {}  # item -> [count, first rise's packet, container, event, zone]
        self.last = 0  # the last change's time
        self.pool: dict[int, int] = {}  # pool slot -> item
        self.won: dict[int, int] = {}  # item -> when the character won it
        self.link = Link()

    def packet(self, p, f, world, emit):
        if self.net and p.ts_ms - self.last > SETTLE_MS:
            self.settle(emit)
        key = (p.direction, p.opcode)
        if key in KINDS:
            self.link.see(p.ts_ms, {"idx": p.idx} if KINDS[key] == "start" else None)
            if KINDS[key] == "release":
                self.link.end()
            return
        op = p.opcode
        if op == 0x00A:  # the server sends every container again, one by one
            self.synced = 0
            self.link.end()
        elif op == 0x01D:
            if self.synced is not None:
                self.synced |= f("Flags") or 0
        elif op == 0x0D2:
            self.pool[f("TrophyItemIndex")] = f("TrophyItemNo")
        elif op == 0x0D3:
            mine = f("JudgeFlg") == 1 and f("LootUniqueNo") == world.character_id
            if mine and (item := self.pool.get(f("TrophyItemIndex"))):
                self.won[item] = p.ts_ms
        else:
            slot = (f("Category"), f("ItemIndex"))
            if slot[0] == RECYCLE:
                return
            old = self.slots.get(slot)
            if op == 0x01E:  # the quantity alone
                if old is None:
                    return
                new = (old[0], f("ItemNum") or 0)
            else:
                new = (f("ItemNo") or 0, f("ItemNum") or 0)
            if new == old:
                return
            if new[0] and new[1]:
                self.slots[slot] = new
            else:
                self.slots.pop(slot, None)
            # A slot first seen before its container was sent whole is what the character held.
            if old is None and not (self.synced or 0) >> slot[0] & 1:
                return
            if old:
                self.add(old[0], -old[1], p, slot[0], world.zone)
            if new[0] and new[1]:
                self.add(new[0], new[1], p, slot[0], world.zone)

    def add(self, item, n, p, container, zone):
        if item == GIL or not n:
            return
        self.last = p.ts_ms
        e = self.net.setdefault(item, [0, None, None, None, None])
        e[0] += n
        if n > 0 and e[1] is None:
            e[1:] = [p, container, (self.link.at(p.ts_ms) or {}).get("idx"), zone]

    def settle(self, emit):
        for item, (n, p, container, event, zone) in self.net.items():
            if n <= 0:
                continue
            won = self.won.pop(item, None)
            pool = won is not None and won >= p.ts_ms - POOL_MS
            emit("obtained", p, item_id=item, quantity=n, container=container,
                 source="pool" if pool else None, zone_id=zone, event_idx=event)  # fmt: skip
        self.net = {}

    def finish(self, world, emit):
        self.settle(emit)
