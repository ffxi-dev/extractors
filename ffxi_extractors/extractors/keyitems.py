import pyarrow as pa

from ..extract import Column, Extractor, Table
from .events import KINDS, LINK_MS, Link


class KeyItems(Extractor):
    """Ported from captain's kitrack, with the event each change follows, as log_changes links them."""

    name = "keyitems"
    version = 3
    doc = "Key items the character gained or lost, where, and the event that gave or took each."
    # The character's position comes from its own position packets (0x015) and its zone-ins; the event from
    # the event packets events reads.
    reads = frozenset(KINDS) | {(0, 0x055), (0, 0x00A), (1, 0x015)}
    tables = (
        Table(
            "keyitems",
            "One row per key item gained or lost (0x055). The first list of each table of 512 key items in a"
            " capture is the starting state and gives no rows, as in kitrack, unless it follows an event"
            " whose message (0x02A) named one of its key items, with no zone-in since: it was gained.",
            (
                Column("key_item_id", pa.int32(), "The key item; its name is in keyitem_names."),
                Column("change", pa.string(), "gained or lost."),
                Column("x", pa.float32(), "The character's last position, as XiPackets names it."),
                Column("y", pa.float32(), "Position."),
                Column("z", pa.float32(), "Position."),
                Column("zone_id", pa.int32(), "The zone."),
                Column(
                    "event_idx",
                    pa.int64(),
                    f"The start of the event this change follows, in events: the open one, or one that ended"
                    f" under {LINK_MS // 1000} s before. Its npc_id is the NPC that gave or took it.",
                ),
                Column("event_id", pa.int32(), "That event's id."),
            ),
        ),
    )

    def __init__(self):
        self.held: dict[int, set[int]] = {}  # table index -> key items held
        self.pos: tuple = (None, None, None)
        self.link = Link()
        self.told: dict[int, set[int]] = {}  # event start idx -> its 0x02A messages' first numbers

    def packet(self, p, f, world, emit):
        key = (p.direction, p.opcode)
        if key == (1, 0x015):
            self.pos = (f("x"), f("y"), f("z"))
            return
        if key == (0, 0x00A):
            self.pos = (f("PosHead.x"), f("PosHead.y"), f("PosHead.z"))
            self.link.end()
            self.told = {}
            if f("EventNum"):
                self.link.see(p.ts_ms, {"idx": p.idx, "event_id": f("EventPara")})
            return
        if key in KINDS:
            start = KINDS[key] == "start"
            self.link.see(p.ts_ms, {"idx": p.idx, "event_id": f("EventPara")} if start else None)
            if KINDS[key] == "release":
                self.link.end()
            if key == (0, 0x02A) and (event := self.link.at(p.ts_ms)):
                self.told.setdefault(event["idx"], set()).add(f("num[0]"))
            return
        table = f("TableIndex")
        held = set()
        for i in range(16):
            word = f(f"GetItemFlag[{i}]") or 0
            held.update(table * 512 + i * 32 + b for b in range(32) if word >> b & 1)
        before = self.held.get(table)
        self.held[table] = held
        event = self.link.at(p.ts_ms) or {}
        if before is None:
            # The server sends a lone list when a key item changes, and an event's "Obtained key item" message
            # names it first. ponytail: any message number that is a held key item counts; reading the zone's
            # dialog text would tell an "obtained" message from one that only names a key item.
            changes = (("gained", held & self.told.get(event.get("idx"), set())),)
        else:
            changes = (("gained", held - before), ("lost", before - held))
        x, y, z = self.pos
        for change, ids in changes:
            for ki in sorted(ids):
                emit("keyitems", p, key_item_id=ki, change=change, x=x, y=y, z=z, zone_id=world.zone,
                     event_idx=event.get("idx"), event_id=event.get("event_id"))  # fmt: skip
