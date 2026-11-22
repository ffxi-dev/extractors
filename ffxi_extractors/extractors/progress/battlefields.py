import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

# 0x075's Timestamp counts Earth seconds from the Vana'diel epoch.
SAME_END_S = 5  # a countdown ending within this of the open one's end is that timer sent again
LATE_MS = 10_000  # a result event this soon after the timer cleared is still its result


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
