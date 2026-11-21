import pyarrow as pa

from ..extract import Column, Extractor, Table

WINDOW_MS = 3000  # a dig's result: the messages and inventory updates under this long after it
EPOCH_MS = 1009810800000  # LSB's earth_time::vanadiel_epoch: Vana'diel time runs 25 times as fast from here


def vana(ts_ms: int) -> tuple[int, int, int]:
    """The Vana'diel weekday (0 Firesday to 7 Darksday), hour, and moon phase in percent, as LSB's
    vanadiel_time reads an Earth time."""
    v = (ts_ms - EPOCH_MS) * 25
    days = v // 86_400_000
    moon = (days + 886 * 360 + 26) % 84
    phase = 100 * (moon - 42) / 42 if moon >= 42 else 100 * (1 - moon / 42)
    return days % 8, v // 3_600_000 % 24, int(phase + 0.5)


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


class Digs(Extractor):
    """The character's chocobo digs. The client asks with 0x063 after the dig's animation (0x02F, which the
    zone sends for anyone's dig and which carries no result). The zone answers in its own dialog:
    'Obtained: <item>' is a 0x02A whose first number is the item, among other 0x02A lines (the dig's hints,
    the conquest points a cache gives) whose numbers are not items; 'You dig and you dig, but find nothing'
    is a 0x036. Which message is which differs by zone, so the item found is the one a 0x02A named that also
    entered the inventory."""

    name = "digs"
    version = 1
    doc = "Each chocobo dig the character made: where, in what weather and Vana'diel time, and what it found."
    reads = Place.reads | Held.reads | {(1, 0x063), (0, 0x02A)}
    tables = (
        Table(
            "digs",
            "One row per dig the character asked for (0x063). A dig whose item the inventory could not take"
            " (thrown away) reads as nothing found.",
            (
                *PLACE,
                Column(
                    "item_id",
                    pa.int32(),
                    "What it found: the item an 'Obtained' message (0x02A) named and the inventory gained"
                    " under 3 s after; none when it found nothing. A raised chocobo's second find is left"
                    " out.",
                ),
            ),
        ),
    )

    def __init__(self):
        self.place = Place()
        self.held = Held()
        self.open: dict | None = None  # the last dig: its row, its window's end, items named and gained

    def packet(self, p, f, world, emit):
        key = (p.direction, p.opcode)
        if self.place.see(p, f):
            if key == (0, 0x00A):
                self.open = None
        elif key == (1, 0x063):
            row = emit("digs", p, **self.place.row(p, world), item_id=None)
            self.open = {"row": row, "end": p.ts_ms + WINDOW_MS, "named": [], "gained": set()}
        elif key == (0, 0x02A):
            me = world.character_id
            if self._on(p) and (not me or f("UniqueNo") == me):
                self.open["named"].append(f("num[0]"))
                self._settle()
        elif (item := self.held.gained(p, f)) is not None and self._on(p):
            self.open["gained"].add(item)
            self._settle()

    def _on(self, p) -> bool:
        return self.open is not None and p.ts_ms <= self.open["end"]

    def _settle(self):
        found = [i for i in self.open["named"] if i in self.open["gained"]]
        if found and self.open["row"]["item_id"] is None:
            self.open["row"]["item_id"] = found[0]
