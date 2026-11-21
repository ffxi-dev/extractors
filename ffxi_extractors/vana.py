"""Vana'diel time: it runs 25 times as fast as Earth's from LSB's vanadiel_epoch."""

EPOCH_S = 1009810800  # LSB's earth_time::vanadiel_epoch, Unix seconds
EPOCH_MS = EPOCH_S * 1000


def vana(ts_ms: int) -> tuple[int, int, int]:
    """The Vana'diel weekday (0 Firesday to 7 Darksday), hour, and moon phase in percent, as LSB's
    vanadiel_time reads an Earth time."""
    v = (ts_ms - EPOCH_MS) * 25
    days = v // 86_400_000
    moon = (days + 886 * 360 + 26) % 84
    phase = 100 * (moon - 42) / 42 if moon >= 42 else 100 * (1 - moon / 42)
    return days % 8, v // 3_600_000 % 24, int(phase + 0.5)
