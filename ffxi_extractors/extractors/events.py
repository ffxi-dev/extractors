import pyarrow as pa

from ..extract import Column, Extractor, Table

# (direction, opcode) -> kind
KINDS = {
    (0, 0x032): "start",
    (0, 0x033): "start",
    (0, 0x034): "start",
    (0, 0x05C): "update",
    (0, 0x05D): "update",
    (1, 0x05B): "reply",
    (1, 0x05C): "reply",
    (0, 0x052): "release",
    (0, 0x036): "message",
    (0, 0x027): "message",
    (0, 0x02A): "message",
    (0, 0x053): "message",
}
LINK_MS = 30_000  # a log change this soon after an event's last packet follows from it

# Mission and quest log ports (0x056), as missiontrack reads them.
CURRENT = {0x50: "San d'Oria", 0x58: "Bastok", 0x60: "Windurst", 0x68: "Jeuno", 0x70: "Other Areas",
           0x78: "Outlands", 0x80: "Aht Urhgan", 0x88: "Crystal War", 0xE0: "Abyssea", 0xF0: "Adoulin",
           0x100: "Coalition"}  # fmt: skip
DONE = {0x90: "San d'Oria", 0x98: "Bastok", 0xA0: "Windurst", 0xA8: "Jeuno", 0xB0: "Other Areas",
        0xB8: "Outlands", 0xC0: "Aht Urhgan", 0xC8: "Crystal War", 0xE8: "Abyssea", 0xF8: "Adoulin",
        0x108: "Coalition"}  # fmt: skip
MISSIONS = {0x30: "Campaign (1-256)", 0x38: "Campaign (257-512)", 0xD0: "Nations and RotZ",
            0xD8: "ToAU and WotG"}  # fmt: skip
MAIN = ("Nation", "Nation mission", "RotZ", "CoP", "CoP extended", "Addons and tales", "SoA", "RoV")
PROGRESS = {4: "Assault", 5: "ToAU mission", 6: "WotG mission", 7: "Campaign"}  # port 0x80's last four


def log_changes(port: int, old: list[int], new: list[int]):
    """missiontrack's reading of one 0x056 change: (log, area, field, old, new, id, action) per change."""
    for i, (a, b) in enumerate(zip(old, new, strict=True)):
        if a == b:
            continue
        if port == 0xFFFF:
            yield "main", MAIN[i], i, a, b, None, "set"
        elif port == 0x80 and i in PROGRESS:
            yield "progress", PROGRESS[i], i, a, b, None, "set"
        elif port in CURRENT or port in DONE or port in MISSIONS:
            for bit in range(32):
                if (a ^ b) >> bit & 1:
                    now = bool(b >> bit & 1)
                    if port in CURRENT:
                        action = "accepted" if now else "removed"
                        yield "quests_current", CURRENT[port], i, a, b, i * 32 + bit, action
                    elif port == 0xD8:
                        area, n = ("ToAU", i) if i < 2 else ("WotG", i - 2)
                        yield "missions_done", area, i, a, b, n * 32 + bit, "completed" if now else "reset"
                    else:
                        log = "quests_done" if port in DONE else "missions_done"
                        area = DONE.get(port) or MISSIONS[port]
                        yield log, area, i, a, b, i * 32 + bit, "completed" if now else "reset"
        else:
            yield "tvr" if port == 0xFFFE else "unknown", None, i, a, b, None, "set"


class Link:
    """The event a change follows: the one under way, or one whose last packet came at most LINK_MS before.
    log_changes and keyitems link by it alike."""

    def __init__(self):
        self.open: dict | None = None  # the start row of the event under way
        self.last: tuple[dict, int] | None = None  # (start row, ts of its last packet)

    def see(self, ts: int, start: dict | None = None) -> dict | None:
        """An event packet at ts, which begins start if given; returns the event it belongs to."""
        if start is not None:
            self.open = start
        if self.open is not None:
            self.last = (self.open, ts)
        return self.open

    def end(self) -> None:
        """The event under way is over: a release or a zone-in. It still links changes for LINK_MS."""
        self.open = None

    def at(self, ts: int) -> dict | None:
        if self.open is not None:
            return self.open
        if self.last and ts - self.last[1] <= LINK_MS:
            return self.last[0]
        return None


class Events(Extractor):
    """Ported from captain's eventview and missiontrack."""

    name = "events"
    version = 2  # 2: 0x05D, an update with strings
    doc = "NPC events with their parameters and the replies, NPC messages, and mission and quest log changes."
    reads = frozenset(KINDS) | {(0, 0x00A), (0, 0x056)}
    tables = (
        Table(
            "events",
            "One row per event packet, in order: starts (0x032, 0x033, 0x034, and a zone-in that plays one),"
            " updates (0x05C, and 0x05D with strings), the client's replies (0x05B, 0x05C), releases (0x052),"
            " and NPC and system messages (0x036, 0x027, 0x02A, 0x053). eventview's music and animation"
            " packets are left out.",
            (
                Column("kind", pa.string(), "start, update, reply, release, or message."),
                Column("opcode", pa.int32(), "The packet."),
                Column(
                    "event_idx",
                    pa.int64(),
                    "The packet position of the start of the event under way, if any.",
                ),
                Column("npc_id", pa.int64(), "UniqueNo: the NPC, or the character for a message it gets."),
                Column("npc_index", pa.int32(), "ActIndex, the NPC's index in the zone."),
                Column("event_id", pa.int32(), "EventPara, the event (cutscene) id, as eventview labels it."),
                Column("event_num", pa.int32(), "EventNum."),
                Column("mode", pa.int32(), "Mode; in a reply, 0 ends the event and 1 asks for an update."),
                Column("event_id2", pa.int32(), "EventPara2, for a start."),
                Column("event_num2", pa.int32(), "EventNum2, for a start."),
                Column(
                    "params",
                    pa.list_(pa.int64()),
                    "A start's or update's parameters, or a message's numbers.",
                ),
                Column(
                    "strings",
                    pa.list_(pa.string()),
                    "A string start's, a 0x05D update's, or a message's strings.",
                ),
                Column("option", pa.int64(), "EndPara: the option a reply sends."),
                Column("message", pa.int32(), "The message number, top bit cleared, as eventview shows it."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
        Table(
            "log_changes",
            "One row per mission or quest log change (0x056), or per changed bit of a log kept as bits. The"
            " first list of each log in a capture is the starting state and gives no rows.",
            (
                Column("port", pa.int32(), "The log's port, as the packet sends it."),
                Column(
                    "log",
                    pa.string(),
                    "main (current missions), progress (Aht Urhgan's assault and mission progress),"
                    " quests_current, quests_done, missions_done, tvr, or unknown.",
                ),
                Column("area", pa.string(), "The nation, region, or mission line, as missiontrack names it."),
                Column("field", pa.int32(), "Which of the packet's eight values changed, from 0."),
                Column("old", pa.int64(), "The value before."),
                Column("new", pa.int64(), "The value now."),
                Column("id", pa.int32(), "For a log of bits: the quest or mission id the bit stands for."),
                Column("action", pa.string(), "set, accepted, removed, completed, or reset."),
                Column(
                    "event_idx",
                    pa.int64(),
                    f"The start of the event this change follows: the open one, or one that ended under"
                    f" {LINK_MS // 1000} s before.",
                ),
                Column("event_id", pa.int32(), "That event's id."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.link = Link()
        self.ports: dict[int, list[int]] = {}

    def packet(self, p, f, world, emit):
        key = (p.direction, p.opcode)
        if key == (0, 0x00A):
            self.link.end()
            if f("EventNum"):
                row = {"npc_id": None, "npc_index": None, "event_id": f("EventPara"),
                       "event_num": f("EventNum"), "mode": f("EventMode")}  # fmt: skip
                self._emit(emit, p, world, "start", row)
            return
        if key == (0, 0x056):
            self._log(p, f, world, emit)
            return
        kind = KINDS[key]
        npc = {"npc_id": f("UniqueNo"), "npc_index": f("ActIndex")}
        if kind == "start":
            row = {**npc, "event_id": f("EventPara"), "event_num": f("EventNum"), "mode": f("Mode")}
            if p.opcode == 0x033:
                row.update(strings=[f(f"String{i}") for i in range(1, 5)], params=nums(f, "Data", 8))
            else:
                row.update(event_id2=f("EventPara2"), event_num2=f("EventNum2"))
                if p.opcode == 0x034:
                    row["params"] = nums(f, "num", 8)
        elif p.opcode == 0x05D:
            row = {"params": nums(f, "num", 9), "strings": [f(f"string{i}") for i in range(1, 5)]}
        elif kind == "update":
            row = {"params": nums(f, "num", 8)}
        elif kind == "reply":
            row = {**npc, "event_id": f("EventPara"), "event_num": f("EventNum"), "mode": f("Mode"),
                   "option": f("EndPara")}  # fmt: skip
        elif kind == "release":
            row = {"mode": f("Mode")}
        elif p.opcode == 0x053:
            row = {"message": f("Number"), "params": [f("para"), f("para2")]}
        else:
            row = {**npc, "message": (f("MesNum") or 0) & 0x7FFF}
            if p.opcode == 0x02A:
                row.update(params=nums(f, "num", 4), strings=[f("String")])
            elif p.opcode == 0x027:
                row.update(
                    params=nums(f, "Num1", 4) + nums(f, "Num2", 8), strings=[f("String1"), f("String2")]
                )
        self._emit(emit, p, world, kind, row)
        if kind == "release":
            self.link.end()

    def _emit(self, emit, p, world, kind, row):
        out = emit("events", p, kind=kind, opcode=p.opcode, zone_id=world.zone, **row)
        start = self.link.see(p.ts_ms, out if kind == "start" else None)
        out["event_idx"] = start["idx"] if start else None

    def _log(self, p, f, world, emit):
        port = f("Port")
        new = nums(f, "data", 8)
        old = self.ports.get(port)
        self.ports[port] = new
        if old is None:
            return
        start = self.link.at(p.ts_ms)
        for log, area, field, a, b, id_, action in log_changes(port, old, new):
            emit("log_changes", p, port=port, log=log, area=area, field=field, old=a, new=b, id=id_,
                 action=action, event_idx=start["idx"] if start else None,
                 event_id=start["event_id"] if start else None, zone_id=world.zone)  # fmt: skip


def nums(f, name, n):
    return [v or 0 for v in (f(f"{name}[{i}]") for i in range(n))]
