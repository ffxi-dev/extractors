import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

KESU = int.from_bytes(b"kesu", "little")  # the despawn animation's name in 0x038
MIN_RESPAWN_MS = 20_000  # spawntrack ignores updates sooner than this after the defeat


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

    def __init__(self):
        self.pos: dict[int, tuple] = {}  # entity id -> last (x, y, z)
        self.defeated: dict[int, int] = {}  # mob id -> its defeat's time, until it is seen alive
        self.despawned: dict[int, int] = {}  # mob id -> its despawn's time, after that defeat

    def packet(self, p, f, world, emit):
        op = p.opcode
        if op == 0x00A:
            self.pos.clear()
            self.defeated.clear()
            self.despawned.clear()
        elif op == 0x00E:
            uid = f("UniqueNo")
            if not f("SendFlg.Position"):
                return
            self.pos[uid] = (f("x"), f("y"), f("z"))
            defeat = self.defeated.get(uid)
            if defeat is not None and f("server_status") == 0 and p.ts_ms >= defeat + MIN_RESPAWN_MS:
                del self.defeated[uid]
                self._row(emit, p, world, "spawned", uid, defeat, self.despawned.pop(uid, None))
        elif op == 0x029:
            uid = f("UniqueNoTar")
            defeat = self.defeated.get(uid)
            # A second defeat message for the same death is skipped; one later means it came back unseen.
            if (
                f("MessageNum") in combat.DEFEAT
                and combat.is_mob(uid)
                and (defeat is None or p.ts_ms >= defeat + MIN_RESPAWN_MS)
            ):
                self.defeated[uid] = p.ts_ms
                self.despawned.pop(uid, None)
                self._row(emit, p, world, "defeated", uid, None, None)
        elif f("ident") == KESU:
            uid = f("UniqueNoTar")
            defeat = self.defeated.get(uid)
            if defeat is not None and uid not in self.despawned:
                self.despawned[uid] = p.ts_ms
                self._row(emit, p, world, "despawned", uid, defeat, None)

    def _row(self, emit, p, world, kind, uid, defeat, despawn):
        x, y, z = self.pos.get(uid, (None, None, None))
        emit("spawns", p, kind=kind, entity_id=uid, x=x, y=y, z=z,
             since_defeat_ms=p.ts_ms - defeat if defeat is not None else None,
             since_despawn_ms=p.ts_ms - despawn if despawn is not None else None,
             zone_id=world.zone)  # fmt: skip
