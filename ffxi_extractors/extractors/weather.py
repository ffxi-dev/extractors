import pyarrow as pa

from ..extract import Column, Extractor, Table


class Weather(Extractor):
    """Ported from captain's weathertrack (after cocosolos' WeatherWatch): the weather each zone-in names,
    and each change while in the zone. The day of the week it read from the client is left out: no packet
    carries it."""

    name = "weather"
    version = 2  # 2: previous_start, when the weather before began
    doc = "The zone's weather at each zone-in and each change after it."
    reads = frozenset({(0, 0x00A), (0, 0x057)})
    tables = (
        Table(
            "weather",
            "One row per zone-in (0x00A) and per weather packet (0x057). A capture that starts in a zone has"
            " no weather until the first change. Names are in weather_names.",
            (
                Column("zone_id", pa.int32(), "The zone."),
                Column("weather_id", pa.int32(), "The weather now: 0 none, 1 sunshine, 2 clouds, and so on."),
                Column(
                    "start_time",
                    pa.int64(),
                    "When it began, in Vana'diel minutes into the zone's 2160-day weather cycle, as sent"
                    " (WeatherTime or StartTime).",
                ),
                Column("offset_time", pa.int32(), "WeatherOffsetTime, as sent."),
                Column(
                    "previous_id",
                    pa.int32(),
                    "The weather before it: at a zone-in, WeatherNumber2; at a change, the weather the last"
                    " row named, if any.",
                ),
                Column(
                    "previous_start",
                    pa.int64(),
                    "When the weather before it began, as start_time counts: at a zone-in, WeatherTime2; at a"
                    " change, the last row's start_time, if any. That weather ran until this one began.",
                ),
                Column("zone_in", pa.bool_(), "Whether the row is a zone-in rather than a change."),
            ),
        ),
    )

    def __init__(self):
        self.now: int | None = None
        self.start: int | None = None

    def packet(self, p, f, world, emit):
        zone_in = p.opcode == 0x00A
        weather = f("WeatherNumber")
        if weather is None:
            return
        start = f("WeatherTime") if zone_in else f("StartTime")
        emit(
            "weather",
            p,
            zone_id=world.zone,
            weather_id=weather,
            start_time=start,
            offset_time=f("WeatherOffsetTime"),
            previous_id=f("WeatherNumber2") if zone_in else self.now,
            previous_start=f("WeatherTime2") if zone_in else self.start,
            zone_in=zone_in,
        )
        self.now, self.start = weather, start
