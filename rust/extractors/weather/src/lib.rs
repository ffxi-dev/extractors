//! world/weather.py: the weather each zone-in (0x00A) names, and each change (0x057) after it. Its Python
//! twin keeps the docs.

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

pub static META: Meta = Meta {
    name: "weather",
    version: 2,
    reads: &[(S2C, 0x00A), (S2C, 0x057)],
    sparse: false,
    tables: &[Table {
        name: "weather",
        columns: &[
            ("zone_id", I32),
            ("weather_id", I32),
            ("start_time", I64),
            ("offset_time", I32),
            ("previous_id", I32),
            ("previous_start", I64),
            ("zone_in", Bool),
        ],
    }],
};

static ZONE_IN: [Field; 5] = [
    Field::new(S2C, 0x00A, "WeatherNumber"),
    Field::new(S2C, 0x00A, "WeatherTime"),
    Field::new(S2C, 0x00A, "WeatherOffsetTime"),
    Field::new(S2C, 0x00A, "WeatherNumber2"),
    Field::new(S2C, 0x00A, "WeatherTime2"),
];
static CHANGE: [Field; 3] = [
    Field::new(S2C, 0x057, "WeatherNumber"),
    Field::new(S2C, 0x057, "StartTime"),
    Field::new(S2C, 0x057, "WeatherOffsetTime"),
];

#[derive(Default)]
pub struct Weather {
    now: Option<i64>,
    start: Option<i64>,
}

impl Extractor for Weather {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let zone_in = p.opcode == 0x00A;
        let x: &[Field] = if zone_in { &ZONE_IN } else { &CHANGE };
        let Some(weather) = x[0].int(f) else { return };
        let (start, offset) = (x[1].int(f), x[2].int(f));
        let (previous_id, previous_start) =
            if zone_in { (ZONE_IN[3].int(f), ZONE_IN[4].int(f)) } else { (self.now, self.start) };
        out.emit(
            "weather",
            Some(p),
            row! {
                zone_id: world.zone,
                weather_id: weather,
                start_time: start,
                offset_time: offset,
                previous_id: previous_id,
                previous_start: previous_start,
                zone_in: zone_in,
            },
        );
        (self.now, self.start) = (Some(weather), start);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    fn zone_in(zone: i64, weather: i64, start: i64, before: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("ZoneNo", zone).int("WeatherNumber", weather).int("WeatherTime", start);
        (0x00A, f.int("WeatherOffsetTime", 1310744).int("WeatherNumber2", before))
    }

    fn change(weather: i64, start: i64) -> (u16, MapFields) {
        (0x057, MapFields::new().int("WeatherNumber", weather).int("StartTime", start).int("WeatherOffsetTime", 11))
    }

    fn rows<const N: usize>(steps: Vec<(u16, MapFields)>, cols: [&str; N]) -> Vec<[V; N]> {
        let out = drive(&mut Weather::default(), steps, Drive::default());
        let r = out.rows("weather");
        (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect()
    }

    #[test]
    fn weather_at_zone_in_and_changes() {
        let got = rows(
            vec![change(1, 100), zone_in(126, 14, 300, 1), change(3, 426)],
            ["zone_id", "weather_id", "previous_id", "start_time", "zone_in"],
        );
        let (n, b) = (V::Int, V::Bool);
        // The capture starts in a zone: the first change has no weather before it.
        assert_eq!(
            got,
            [
                [V::Null, n(1), V::Null, n(100), b(false)],
                [n(126), n(14), n(1), n(300), b(true)],
                [n(126), n(3), n(14), n(426), b(false)],
            ]
        );
    }

    #[test]
    fn the_weather_before_a_zone_in_or_a_change_ran_until_it() {
        let f = MapFields::new().int("ZoneNo", 106).int("WeatherNumber", 0).int("WeatherTime", 258127);
        let got = rows(
            vec![(0x00A, f.int("WeatherNumber2", 3).int("WeatherTime2", 257938)), change(1, 258856)],
            ["previous_id", "previous_start"],
        );
        assert_eq!(got, [[V::Int(3), V::Int(257938)], [V::Int(0), V::Int(258127)]]);
    }
}
