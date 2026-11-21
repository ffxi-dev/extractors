"""Where each entity is, as the packets last placed it, and which way it faces."""

import math


class Places:
    """The last position, heading, size, and HP% the packets sent of each entity, and the character's own
    position: NPCs, mobs, and trusts (0x00E), other players (0x00D), the character (0x015, zone-in), HP% from
    those and the party's (0x0DD, 0x0DF)."""

    reads = frozenset({(0, 0x00A), (0, 0x00E), (0, 0x00D), (0, 0x0DD), (0, 0x0DF), (1, 0x015)})

    def __init__(self):
        self.pos: dict[int, tuple[float, float, float]] = {}  # entity id -> last x, y, z
        self.at: dict[int, int] = {}  # entity id -> when its position came
        self.dir: dict[int, tuple[int, int]] = {}  # entity id -> (heading, when)
        self.size: dict[int, float] = {}  # entity id -> yalms
        self.hpp: dict[int, int] = {}  # entity id -> last HP%
        self.me: tuple | None = None  # the character's last position
        self.me_at = 0

    def update(self, p, f) -> bool:
        """Keep what p says; True when p is one of reads."""
        key = (p.direction, p.opcode)
        if key == (0, 0x00A):
            for d in (self.pos, self.at, self.dir, self.size, self.hpp):
                d.clear()
            self.me, self.me_at = (f("PosHead.x"), f("PosHead.y"), f("PosHead.z")), p.ts_ms
        elif key == (1, 0x015):
            self.me, self.me_at = (f("x"), f("y"), f("z")), p.ts_ms
        elif key in ((0, 0x0DD), (0, 0x0DF)):
            if f("UniqueNo") is not None and f("Hpp") is not None:
                self.hpp[f("UniqueNo")] = f("Hpp")
        elif key in ((0, 0x00D), (0, 0x00E)):
            uid = f("UniqueNo")
            if f("SendFlg.Despawn"):
                self.pos.pop(uid, None)
                return True
            if f("SendFlg.Position"):
                x, y, z = f("x"), f("y"), f("z")
                if uid is not None and None not in (x, y, z):
                    self.pos[uid], self.at[uid] = (x, y, z), p.ts_ms
                if p.opcode == 0x00E and f("dir") is not None:
                    self.dir[uid] = (f("dir"), p.ts_ms)
            if f("SendFlg.General"):
                if f("Hpp") is not None:
                    self.hpp[uid] = f("Hpp")
                if p.opcode == 0x00E and f("Flags2.g"):
                    self.size[uid] = f("Flags2.g") / 10
        else:
            return False
        return True


def bearing(here, there, heading: int | None) -> float | None:
    """Degrees from the heading to there, -180 to 180. A heading counts 256ths of a turn as LSB's worldAngle
    does: -atan2(dy, dx) on the ground plane, which XiPackets names x and y."""
    dx, dy = there[0] - here[0], there[1] - here[1]
    if heading is None or math.hypot(dx, dy) < 0.1:
        return None
    return (-math.degrees(math.atan2(dy, dx)) - heading * 360 / 256 + 180) % 360 - 180
