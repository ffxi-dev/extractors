//! vana.py: Vana'diel time, which runs 25 times as fast as Earth's from LSB's vanadiel_epoch.

/// LSB's earth_time::vanadiel_epoch, Unix seconds.
pub const EPOCH_S: i64 = 1009810800;
pub const EPOCH_MS: i64 = EPOCH_S * 1000;

/// The Vana'diel weekday (0 Firesday to 7 Darksday), hour, and moon phase in percent, as LSB's vanadiel_time
/// reads an Earth time.
pub fn vana(ts_ms: i64) -> (i64, i64, i64) {
    let v = (ts_ms - EPOCH_MS) * 25;
    let days = v.div_euclid(86_400_000);
    let moon = (days + 886 * 360 + 26).rem_euclid(84);
    let phase = if moon >= 42 { 100.0 * (moon - 42) as f64 / 42.0 } else { 100.0 * (1.0 - moon as f64 / 42.0) };
    (days.rem_euclid(8), v.div_euclid(3_600_000).rem_euclid(24), (phase + 0.5) as i64)
}

#[cfg(test)]
mod tests {
    #[test]
    fn as_python() {
        // vana.vana(1_700_000_000_000) and vana.vana(0) in Python.
        assert_eq!(super::vana(1_700_000_000_000), (3, 12, 83));
        assert_eq!(super::vana(super::EPOCH_MS), (0, 0, 10));
    }
}
