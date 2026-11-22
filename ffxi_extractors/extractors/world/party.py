import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Party(Extractor):
    name = "party"
    version = 3  # 3: list
    doc = "Who was with the recording character: each party and alliance member and Trust, as listed."
    reads = frozenset({(0, 0x0DD), (0, 0x0E2), (0, 0x0C8)})
    sparse = False  # it reads only the world's packets
    tables = (
        Table(
            "party",
            "One row per member in a party list: 0x0DD or 0x0E2 (one member each), or the alliance list"
            " 0x0C8 (every member, with no job, HP, or name of its own).",
            (
                Column("member_id", pa.int64(), "The member's id."),
                Column(
                    "name",
                    pa.string(),
                    "The member's name; for 0x0C8, from an earlier 0x0DD or 0x0E2, or its entity.",
                ),
                Column("member_number", pa.int32(), "Its place in the list; for 0x0C8, its slot of 20."),
                Column(
                    "list",
                    pa.string(),
                    "alliance for 0x0C8, which lists every party and alliance member alike to each of them;"
                    " party for 0x0DD and 0x0E2.",
                ),
                Column("zone_id", pa.int32(), "The member's zone, as sent: often 0 in the character's zone."),
                Column("trust", pa.bool_(), "Whether it is a Trust: its id is an NPC id (0x01ZZZIII)."),
                Column("main_job", pa.string(), "Main job."),
                Column("main_level", pa.int32(), "Main job level."),
                Column("sub_job", pa.string(), "Support job."),
                Column("sub_level", pa.int32(), "Support job level."),
                Column("hpp", pa.int32(), "HP percent."),
                Column("mpp", pa.int32(), "MP percent."),
                Column("tp", pa.int32(), "TP."),
                Column("flags", pa.int64(), "GAttr: party number (bits 0-1), then leader and other flags."),
            ),
        ),
    )
