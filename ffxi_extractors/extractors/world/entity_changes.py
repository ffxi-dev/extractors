import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World


class EntityChanges(Extractor):
    """After captain's npclogger, but only what changes: each entity's first update in a capture, then each
    update that changes its name, model, or monster flag. XiPackets' x, y, z are kept as they are; npclogger
    swaps y and z for its old files."""

    name = "entity_changes"
    version = 1
    doc = "Each NPC, mob, and player's first sighting in a capture, and each change of name, model, or flag."
    reads = frozenset({(0, 0x00E), (0, 0x00D)})
    tables = (
        Table(
            "entity_changes",
            "One row per entity's first update (0x00E, or 0x00D for a player) and per update that changes"
            " its name, model, or monster flag. Each row holds what the entity is known to be from then on.",
            (
                Column(
                    "entity_id", pa.int64(), "The entity's id; an NPC's or mob's zone is in bits 12 to 23."
                ),
                Column("act_index", pa.int32(), "The entity's index in the zone."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
                Column(
                    "name",
                    pa.string(),
                    "The entity's name as the packets last gave it, cut to 15 characters without spaces. The"
                    " capture_entities view spells it as the client does.",
                ),
                Column("monster", pa.bool_(), "Whether the updates mark the entity as a monster."),
                Column("model_id", pa.int32(), "A monster's or NPC's model; none for a humanoid look."),
                Column("x", pa.float32(), "Position, as XiPackets names it, when the update sends it."),
                Column("y", pa.float32(), "Position, when sent."),
                Column("z", pa.float32(), "Height, when sent."),
            ),
        ),
    )

    def __init__(self):
        self.known: dict[int, tuple] = {}  # entity id -> (name, monster, model)

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        uid = f("UniqueNo")
        if uid is None:
            return
        if p.opcode == 0x00D:
            name, monster, model = f("name") or None, None, None
        else:
            name = f("Data.name") or (world.entities.get(f("ActIndex")) or {}).get("name")
            monster = bool(f("Flags1.MonsterFlag")) if f("SendFlg.General") else None
            model = f("Data.model_id") if f("SubKind") == 0 else None  # SendFlg.Model: a humanoid look
        last = self.known.get(uid)
        now = (
            (name, monster, model)
            if last is None
            else tuple(
                new if new is not None else old for new, old in zip((name, monster, model), last, strict=True)
            )
        )
        if now == last:
            return
        self.known[uid] = now
        placed = f("SendFlg.Position")
        emit(
            "entity_changes",
            p,
            entity_id=uid,
            act_index=f("ActIndex"),
            zone_id=world.zone,
            name=now[0],
            monster=now[1],
            model_id=now[2],
            x=f("x") if placed else None,
            y=f("y") if placed else None,
            z=f("z") if placed else None,
        )
