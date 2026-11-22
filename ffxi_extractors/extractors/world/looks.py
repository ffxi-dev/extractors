import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Looks(Extractor):
    """How each entity looks and moves, as its updates (0x00E) say: one row per entity and state in a
    capture, with how many updates came in it. A state is the speeds from the last update with a position,
    the flags and animation from the last general update, and the model or look from the last that sent
    one."""

    name = "looks"
    version = 1
    doc = "Each entity's speeds, model or look, animation, and flags, with how many updates sent each."
    reads = frozenset({(0, 0x00E), (0, 0x00A)})
    sparse = False  # it reads only the world's packets
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
