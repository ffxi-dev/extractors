import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World
from ffxi_extractors.extractors.world.character import job

# GP_GROUP_ATTR's bits, low first, as 0x0DD, 0x0E2, and each 0x0C8 entry send them.
GATTR = (("PartyNo", 0), ("PartyLeaderFlg", 2), ("AllianceLeaderFlg", 3), ("PartyRFlg", 4),
         ("AllianceRFlg", 5), ("unknown06", 6), ("unknown07", 7))  # fmt: skip


def gattr(f, prefix: str) -> int | None:
    bits = [(f(prefix + name), shift) for name, shift in GATTR]
    if all(v is None for v, _ in bits):
        return None
    return sum((v or 0) << shift for v, shift in bits)


def is_trust(member_id: int | None) -> bool:
    """Any NPC id, 0x01ZZZIII, in the party list: a Trust, whose index the zone hands out (0x700 on), or an
    Adventuring Fellow, which reads as one. A player's id is under 0x1000000."""
    return member_id is not None and member_id >> 24 == 1


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

    def __init__(self):
        self.names: dict[int, str] = {}

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x0C8:
            for i in range(20):
                g = f"GroupTbl[{i}]."
                uid = f(g + "UniqueNo")
                if not uid:
                    continue
                e = world.entities.get(f(g + "ActIndex")) or {}
                name = self.names.get(uid) or (e.get("name") if e.get("id") == uid else None)
                emit("party", p, member_id=uid, name=name, member_number=i, list="alliance",
                     zone_id=f(g + "ZoneNo"), trust=is_trust(uid), flags=gattr(f, g))  # fmt: skip
            return
        uid = f("UniqueNo")
        if name := f("Name"):
            self.names[uid] = name
        emit(
            "party",
            p,
            member_id=uid,
            name=name or None,
            member_number=f("MemberNumber"),
            list="party",
            zone_id=f("ZoneNo"),
            trust=is_trust(uid),
            main_job=job(f("mjob_no")),
            main_level=f("mjob_lv"),
            sub_job=job(f("sjob_no")),
            sub_level=f("sjob_lv"),
            hpp=f("Hpp"),
            mpp=f("Mpp"),
            tp=f("Tp"),
            flags=gattr(f, "GAttr."),
        )
