"""What digs and fishing share: where the character was, and what it held."""

import pyarrow as pa

from ffxi_extractors.extract import Column
from ffxi_extractors.vana import vana

WINDOW_MS = 3000  # a dig's result: the messages and inventory updates under this long after it


class Place:
    """Where the character stands and the zone's weather, from the packets that say: c2s 0x015, the zone-in
    (0x00A), and weather changes (0x057)."""

    reads = frozenset({(1, 0x015), (0, 0x00A), (0, 0x057)})

    def __init__(self):
        self.pos: tuple = (None, None, None)
        self.weather: int | None = None

    def see(self, p, f) -> bool:
        """Read p if it is one of these; whether it was."""
        key = (p.direction, p.opcode)
        if key == (1, 0x015):
            self.pos = (f("x"), f("y"), f("z"))
        elif key == (0, 0x00A):
            self.pos = (f("PosHead.x"), f("PosHead.y"), f("PosHead.z"))
            self.weather = f("WeatherNumber")
        elif key == (0, 0x057):
            self.weather = f("WeatherNumber")
        else:
            return False
        return True

    def row(self, p, world) -> dict:
        """The columns digs and fishing share: zone, position, weather, Vana'diel time."""
        day, hour, moon = vana(p.ts_ms)
        x, y, z = self.pos
        return {"zone_id": world.zone, "x": x, "y": y, "z": z, "weather_id": self.weather,
                "vana_weekday": day, "vana_hour": hour, "moon_phase": moon}  # fmt: skip


class Held:
    """Each inventory slot's item and count, from 0x01E (a count without its item), 0x01F and 0x020."""

    reads = frozenset({(0, 0x01E), (0, 0x01F), (0, 0x020)})

    def __init__(self):
        self.slots: dict[tuple[int, int], tuple[int, int]] = {}  # (container, slot) -> (item, count)

    def gained(self, p, f) -> int | None:
        """Read p; the item whose count it raised in the main inventory, if any. Slot 0 is gil."""
        slot = (f("Category") or 0, f("ItemIndex") or 0)
        count = f("ItemNum") or 0
        was_item, was = self.slots.get(slot, (None, 0))
        item = was_item if p.opcode == 0x01E else f("ItemNo")
        if not count or item is None:
            self.slots.pop(slot, None)
            return None
        self.slots[slot] = (item, count)
        return item if slot[0] == 0 and slot[1] and (item != was_item or count > was) else None


PLACE = (
    Column("zone_id", pa.int32(), "The zone."),
    Column("x", pa.float32(), "The character's last position, as XiPackets names it."),
    Column("y", pa.float32(), "Position."),
    Column("z", pa.float32(), "Position."),
    Column(
        "weather_id",
        pa.int32(),
        "The weather the last zone-in or weather packet named; none before the first. Names"
        " are in weather_names.",
    ),
    Column("vana_weekday", pa.int32(), "The Vana'diel day: 0 Firesday to 7 Darksday."),
    Column("vana_hour", pa.int32(), "The Vana'diel hour, 0 to 23."),
    Column("moon_phase", pa.int32(), "The moon, 0 (new) to 100 (full) percent, as LSB computes it."),
)
