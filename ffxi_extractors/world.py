"""The packets the world reads: what a capture's packets say so far of the zone and its weather, the recording
character and where it stands, its party, its inventory, and the entities around it, as rust/xc-core's
world.rs keeps it."""

S2C, C2S = 0, 1
# Every run decodes them, beside its extractors' own; WORLD_VERSION changes whenever what the world keeps
# does, and re-runs every unit.
WORLD = frozenset(
    {
        *((S2C, op) for op in (0x00A, 0x00E, 0x037, 0x0DD, 0x0E2, 0x0C8, 0x01E, 0x01F, 0x020, 0x057)),
        (C2S, 0x015),
    }
)
WORLD_VERSION = 2  # 2: the character's position and the zone's weather
