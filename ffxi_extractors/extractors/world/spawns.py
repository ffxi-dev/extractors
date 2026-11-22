import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Spawns(Extractor):
    """Ported from captain's spawntrack, light mode: no packets sent, so only what comes into view."""

    name = "spawns"
    version = 1
    doc = "Mob defeats, despawns, and respawns in view, with times and positions."
    reads = frozenset({(0, 0x00E), (0, 0x029), (0, 0x038), (0, 0x00A)})
    tables = (
        Table(
            "spawns",
            "One row per mob defeat (0x029 6 or 20), its despawn (0x038 'kesu'), and its next appearance"
            " alive (0x00E with a position and status 0, at least 20 s after the defeat), as spawntrack's"
            " light mode sees them. A mob that comes back out of view, or after the character zones, has no"
            " respawn row.",
            (
                Column("kind", pa.string(), "defeated, despawned, or spawned."),
                Column("entity_id", pa.int64(), "The mob."),
                Column(
                    "x",
                    pa.float32(),
                    "Its last position for a defeat or despawn; where it appeared for a spawn.",
                ),
                Column("y", pa.float32(), "Position."),
                Column("z", pa.float32(), "Position."),
                Column("since_defeat_ms", pa.int64(), "For a despawn or spawn: time since the defeat."),
                Column(
                    "since_despawn_ms", pa.int64(), "For a spawn: time since the despawn, if one was seen."
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
