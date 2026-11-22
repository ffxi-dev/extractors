"""What digs and fishing share: the place they happened, and what the character held."""

import pyarrow as pa

from ffxi_extractors.extract import Column

# Each inventory slot's item and count: 0x01E (a count without its item), 0x01F and 0x020.
HELD = frozenset({(0, 0x01E), (0, 0x01F), (0, 0x020)})


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
