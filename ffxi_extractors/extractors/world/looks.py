import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World

# Each flag 0x00E carries, by atom0s's names in XiPackets (as ffxi_packets keeps them; unknown_* are his
# too), but Flags0's MovTime and facetarget, which change with every step. Flags0 comes with a position,
# Flags1 to 3 with SendFlg.General.
MOVING = tuple("Flags0." + k for k in ("RunMode", "unknown_1_6", "GroundFlag", "KingFlag"))
GENERAL = tuple(
    f"Flags{n}.{k}"
    for n, names in (
        (1, "MonsterFlag HideFlag SleepFlag unknown_0_3 unknown_0_4 ChocoboIndex CliPosInitFlag GraphSize"
            " LfgFlag AnonymousFlag YellFlag AwayFlag Gender PlayOnelineFlag LinkShellFlag LinkDeadFlag"
            " TargetOffFlag TalkUcoffFlag unknown_2_5 unknown_2_6 unknown_2_7 GmLevel HackMove unknown_3_4"
            " InvisFlag TurnFlag BazaarFlag"),
        (2, "r g b PvPFlag ShadowFlag ShipStartMode CharmFlag GmIconFlag NamedFlag SingleFlag AutoPartyFlag"),
        (3, "TrustFlag LfgMasterFlag PetNewFlag unknown_0_3 MotStopFlag CliPriorityFlag PetFlag"
            " OcclusionoffFlag BallistaTeam MonStat unknown_2_3 unknown_2_4 SilenceFlag unknown_2_6"
            " NewCharacterFlag MentorFlag unknown_3_1 unknown_3_2 unknown_3_3 unknown_3_4 unknown_3_5"
            " unknown_3_6 unknown_3_7"),
    )
    for k in names.split()
)  # fmt: skip
HUMANOID = (1, 7)  # SubKinds whose Data is a look (GrapIDTbl) rather than a model
STATE = ("speed", "speed_base", "animation", "flags0", "flags", "sub_kind", "status", "model_id", "look")


class Looks(Extractor):
    """How each entity looks and moves, as its updates (0x00E) say: one row per entity and state in a
    capture, with how many updates came in it. A state is the speeds from the last update with a position,
    the flags and animation from the last general update, and the model or look from the last that sent
    one."""

    name = "looks"
    version = 1
    doc = "Each entity's speeds, model or look, animation, and flags, with how many updates sent each."
    reads = frozenset({(0, 0x00E), (0, 0x00A)})
    tables = (
        Table(
            "entity_looks",
            "One row per entity and state its updates (0x00E) put it in within a zone visit: the speeds,"
            " animation, flags, and model or look as last sent. idx is the update that first put it there.",
            (
                Column("entity_id", pa.int64(), "The entity; an NPC's or mob's id holds its zone."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
                Column("speed", pa.int32(), "Speed, from the last update with a position: LSB's speed."),
                Column("speed_base", pa.int32(), "SpeedBase, from that update: LSB's animationSpeed."),
                Column(
                    "animation",
                    pa.int32(),
                    "server_status, from the last general update: LSB's render.animation (0 none, 1 attack).",
                ),
                Column(
                    "flags",
                    pa.list_(pa.string()),
                    "Each flag set, as name=value by atom0s's names: Flags0 from the last update with a"
                    " position, Flags1 to 3 from the last general update; MovTime and facetarget left out.",
                ),
                Column("sub_kind", pa.int32(), "SubKind: 0 a model, 1 or 7 a humanoid look, 2 to 4 a door."),
                Column("status", pa.int32(), "Status, the 13 bits beside SubKind, raw."),
                Column("model_id", pa.int32(), "The model, for a SubKind other than 1 or 7."),
                Column("look", pa.list_(pa.int32()), "GrapIDTbl, for SubKind 1 or 7: race, face, then gear."),
                Column("updates", pa.int64(), "Updates (0x00E) that came while it was in this state."),
            ),
        ),
    )

    def __init__(self):
        self.state: dict[int, dict] = {}  # entity id -> what its updates last said
        self.rows: dict[tuple, dict] = {}  # (entity id, state) -> its row

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x00A:
            self.state.clear()
            self.rows.clear()
            return
        uid = f("UniqueNo")
        if uid is None or f("SendFlg.Despawn"):
            return
        s = self.state.setdefault(uid, {"flags0": (), "flags": ()})
        if f("SendFlg.Position"):
            s["speed"], s["speed_base"] = f("Speed"), f("SpeedBase")
            s["flags0"] = tuple(f"{k}={v}" for k in MOVING if (v := f(k)))
        if f("SendFlg.General"):
            s["animation"] = f("server_status")
            s["flags"] = tuple(f"{k}={v}" for k in GENERAL if (v := f(k)))
        if (f("SendFlg.Model") or f("SendFlg.Name")) and (kind := f("SubKind")) is not None:
            s["sub_kind"], s["status"] = kind, f("Status")
            if kind in HUMANOID:
                if f("SendFlg.Model"):
                    s["look"], s["model_id"] = tuple(f(f"Data.GrapIDTbl[{i}]") for i in range(9)), None
            elif f("Data.model_id") is not None:
                s["model_id"], s["look"] = f("Data.model_id"), None
        key = (uid, *(s.get(k) for k in STATE))
        row = self.rows.get(key)
        if row is None:
            values = {k: s.get(k) for k in STATE if k not in ("flags0", "flags", "look")}
            look = list(s["look"]) if s.get("look") else None
            flags = sorted(s["flags0"] + s["flags"])
            values |= {"entity_id": uid, "zone_id": world.zone, "flags": flags, "look": look, "updates": 0}
            row = self.rows[key] = emit("entity_looks", p, **values)
        row["updates"] += 1
