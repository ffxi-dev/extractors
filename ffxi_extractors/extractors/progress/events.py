import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.link import KINDS, LINK_MS


class Events(Extractor):
    """Ported from captain's eventview and missiontrack."""

    name = "events"
    version = 3  # 2: 0x05D, an update with strings; 3: log_changes' event stops at a zone-in's lists
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
                    f" {LINK_MS // 1000} s before. An event from before a zone-in follows only into the list"
                    " of each port the zone-in sends.",
                ),
                Column("event_id", pa.int32(), "That event's id."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
