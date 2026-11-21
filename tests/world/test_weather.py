"""weathertrack's port on decoded fields, the weather names, and each zone's timeline."""

from conftest import drive, rows

from ffxi_extractors.extractors.world.weather import Weather


def zone_in(zone, weather, start, before):
    return 0x00A, {"ZoneNo": zone, "WeatherNumber": weather, "WeatherTime": start,
                   "WeatherOffsetTime": 1310744, "WeatherNumber2": before}  # fmt: skip


def change(weather, start, offset=11):
    return 0x057, {"WeatherNumber": weather, "StartTime": start, "WeatherOffsetTime": offset}


def test_weather_at_zone_in_and_changes():
    weather = drive(Weather, change(1, 100), zone_in(126, 14, 300, 1), change(3, 426))["weather"]
    got = [(r["zone_id"], r["weather_id"], r["previous_id"], r["start_time"], r["zone_in"]) for r in weather]
    # The capture starts in a zone: the first change has no weather before it.
    assert got == [(None, 1, None, 100, False), (126, 14, 1, 300, True), (126, 3, 14, 426, False)]


def test_weather_names_are_lsbs(con):
    names = dict(rows(con, "SELECT id, name FROM weather_names"))
    assert len(names) == 20 and (names[0], names[4], names[19]) == ("None", "Hot spell", "Darkness")


EPOCH, CYCLE = 1009810800000, 2160 * 1440  # LSB's vanadiel_epoch; the weather cycle in Vana'diel minutes


def test_the_weather_before_a_zone_in_or_a_change_ran_until_it():
    rows = drive(Weather, (0x00A, {"ZoneNo": 106, "WeatherNumber": 0, "WeatherTime": 258127,
                                   "WeatherNumber2": 3, "WeatherTime2": 257938}),
                 change(1, 258856))["weather"]  # fmt: skip
    assert [(r["previous_id"], r["previous_start"]) for r in rows] == [(3, 257938), (0, 258127)]
