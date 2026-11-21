import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World
from ffxi_extractors.vana import EPOCH_S

COUNTDOWN = 1  # 0x075 Flags bit 0: the packet holds a countdown (LSB OBJECTIVEUTILITY_COUNTDOWN)
# 0x075's Timestamp counts Earth seconds from the Vana'diel epoch.
SAME_END_S = 5  # a countdown ending within this of the open one's end is that timer sent again
# LSB's battlefield events (scripts/globals/battlefield.lua): 32001 starts on a win, 32002 on a loss.
OUTCOME = {32001: "won", 32002: "lost"}
LATE_MS = 10_000  # a result event this soon after the timer cleared is still its result
# 0x0BF Result, as LSB's instance entry sends it (scripts/globals/instance.lua and zone NPCs): 1 refused,
# 3 reservation failed, 4 entering. 0 and 2 are unnamed.
REGISTRATION = {1: "refused", 3: "reservation failed", 4: "entering"}


class Battlefields(Extractor):
    """Battlefield timers (0x075) with the win or loss event that ended them, and the answers of registration
    NPCs (0x0BF)."""

    name = "battlefields"
    version = 1
    doc = "Battlefield countdowns with their time limit and result, and registration answers."
    reads = frozenset({(0, 0x075), (0, 0x0BF), (0, 0x032), (0, 0x034), (0, 0x00A)})
    tables = (
        Table(
            "battlefields",
            "One row per countdown the zone started (0x075 with Flags bit 0): a battlefield's time limit,"
            " Dynamis's, a Walk of Echoes wave's. The same countdown sent again, ending within"
            f" {SAME_END_S} s of the open one, adds no row.",
            (
                Column(
                    "mode", pa.int64(), "Mode as sent: 1 for a battlefield, other values in other content."
                ),
                Column(
                    "start_ms",
                    pa.int64(),
                    "When the countdown started (Timestamp, Earth seconds from LSB's Vana'diel epoch).",
                ),
                Column("time_limit_s", pa.int32(), "Duration: seconds left at start_ms."),
                Column("warning_s", pa.int32(), "DurationWarn: when the client warns, as sent."),
                Column(
                    "end_idx",
                    pa.int64(),
                    "The packet that ended it: the next 0x075 without a countdown (the clear), a zone-in to"
                    " another zone, or another countdown. None if the capture ended first.",
                ),
                Column("end_ms", pa.int64(), "That packet's time."),
                Column("ended_by", pa.string(), "cleared, zoned, replaced, or none."),
                Column(
                    "outcome",
                    pa.string(),
                    f"won or lost: the result event (32001 or 32002) the zone started while the timer ran or"
                    f" under {LATE_MS // 1000} s after it cleared; none without one.",
                ),
                Column("result_idx", pa.int64(), "That event's packet."),
                Column(
                    "battlefield_index",
                    pa.int32(),
                    "On a win, the battlefield's index in its zone (32001's sixth number), as LSB's"
                    " battlefield scripts number them.",
                ),
                Column("time_inside_s", pa.int32(), "On a win, the seconds spent inside (32001's fourth)."),
                Column("record_s", pa.int32(), "On a win, the record clear time (32001's second)."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
        Table(
            "registrations",
            "One row per registration NPC's answer (0x0BF), as for Dynamis, Salvage, or Assault.",
            (
                Column("result", pa.int32(), "Result as sent: 1 refused, 3 reservation failed, 4 entering."),
                Column("outcome", pa.string(), "Result's name as LSB uses it; none for 0 and 2."),
                Column("npc_index", pa.int32(), "ActIndex: the NPC answering."),
                Column("npc_id", pa.int64(), "Its id, from the NPC updates; none if never seen."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.open: dict | None = None
        self.open_end = 0  # when the open countdown runs out, server seconds
        self.last: dict | None = None  # the timer that cleared most recently, for a late result event

    def _end(self, p, why):
        if self.open:
            self.open.update(end_idx=p.idx, end_ms=p.ts_ms, ended_by=why)
            self.last = self.open
        self.open = None

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        op = p.opcode
        if op == 0x075:
            if not (f("Flags") or 0) & COUNTDOWN:
                self._end(p, "cleared")
                return
            start, limit = f("Timestamp"), f("Duration")
            end = start + limit
            if self.open and abs(self.open_end - end) <= SAME_END_S:
                return
            self._end(p, "replaced")
            self.open = emit("battlefields", p, mode=f("Mode"), start_ms=(start + EPOCH_S) * 1000,
                             time_limit_s=limit, warning_s=f("DurationWarn"), zone_id=world.zone)  # fmt: skip
            self.open_end = end
        elif op == 0x00A:
            if self.open and f("ZoneNo") != self.open["zone_id"]:
                self._end(p, "zoned")
        elif op == 0x0BF:
            index = f("ActIndex")
            e = world.entities.get(index) or {}
            result = f("Result")
            emit("registrations", p, result=result, outcome=REGISTRATION.get(result), npc_index=index,
                 npc_id=e.get("id"), zone_id=world.zone)  # fmt: skip
        elif (outcome := OUTCOME.get(f("EventPara"))) is not None:
            t = self.open or (self.last if self.last and p.ts_ms - self.last["end_ms"] <= LATE_MS else None)
            if t is None or t.get("outcome") is not None:
                return
            t.update(outcome=outcome, result_idx=p.idx)
            if outcome == "won" and op == 0x034:
                t.update(record_s=f("num[1]"), time_inside_s=f("num[3]"), battlefield_index=f("num[5]"))
