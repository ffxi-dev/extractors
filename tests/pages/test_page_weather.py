"""weathertrack's port on decoded fields, the weather names, and each zone's timeline."""

import time

from fill import ask, put

EPOCH, CYCLE = 1009810800000, 2160 * 1440  # LSB's vanadiel_epoch; the weather cycle in Vana'diel minutes
T = 1769566979975  # KtMlLljD1vMv's 0x057 in North Gustaberg: StartTime 2414663
S = 2414663


def seen(capture, idx, ts, weather, start, previous=None, previous_start=None, zone=106):
    return {"capture_id": capture, "idx": idx, "ts_ms": ts, "client_version": "v", "zone_id": zone,
            "weather_id": weather, "start_time": start, "previous_id": previous,
            "previous_start": previous_start}  # fmt: skip


def setup(con, *rows, captures=("a", "b", "x")):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in captures])
    put(con, "names", [{"release": "r", "log_id": 0, "kind": "zone", "id": 106, "name": "North Gustaberg"}])
    put(con, "weather", list(rows))


def test_a_period_runs_from_its_tick_to_the_next_and_two_recorders_count_once(con):
    setup(
        con,
        seen("a", 1, T, 1, S, 0, S - 100),  # Sunshine began at S; None ran from S - 100 until then
        seen("b", 7, T + 40_000, 1, S, 0, S - 100),  # the same, from a party member
        seen("a", 2, T + 150_000, 3, S + 60, 1, S),  # Fog: Sunshine ran 60 minutes
        seen("x", 1, T, 6, S),  # flagged
    )
    put(con, "capture_trust", [{"capture_id": "x", "trust": "flagged"}])
    got = ask(con, "weather_zone", zone=106)
    assert [(r["tick"], r["weather"], r["minutes"], r["seen"]) for r in got] == [
        (S - 100, 0, 100, 2), (S, 1, 60, 3), (S + 60, 3, None, 1),
    ]  # fmt: skip
    assert got[0]["zone_name"] == "North Gustaberg" and got[1]["capture_id"] == "a"
    (zone,) = ask(con, "weather_zones")
    assert (zone["zone_name"], zone["periods"], zone["disagree"]) == ("North Gustaberg", 2, 0)
    assert abs(zone["coverage"] - 160 / CYCLE) < 1e-12
    assert zone["mix"] == [[0, 100], [1, 60]] and zone["cells"] == [[S // 8640, 0]]


def test_a_tick_two_cycles_saw_differently_is_flagged(con):
    later = T + CYCLE * 2400  # the same tick, one cycle on
    setup(con, seen("a", 1, T, 1, S, 0, S - 100), seen("b", 1, later, 3, S, 0, S - 90))
    got = {r["tick"]: r for r in ask(con, "weather_zone", zone=106)}
    assert got[S]["weathers"] == [1, 3] and got[S]["cycles"] == 2
    assert got[S - 100]["lengths"] == [100] and got[S - 90]["lengths"] == [90]
    (zone,) = ask(con, "weather_zones")
    assert zone["disagree"] == 1


def test_a_weather_that_began_before_the_cycle_turned_keeps_its_tick(con):
    turn = EPOCH + 102 * CYCLE * 2400  # the 103rd cycle's first minute, on Earth
    # 5 minutes in: Clouds began 10 before the turn, after Sunshine from 30 before.
    setup(con, seen("a", 1, turn + 12_000, 2, CYCLE - 10, 1, CYCLE - 30), captures=("a",))
    got = ask(con, "weather_zone", zone=106)
    assert [(r["tick"], r["weather"], r["minutes"]) for r in got] == [
        (CYCLE - 30, 1, 20),
        (CYCLE - 10, 2, None),
    ]
    put(con, "weather", [seen("a", 2, turn + 60_000, 3, 15, 2, CYCLE - 10)])  # Fog, 15 minutes into the cycle
    (zone,) = ask(con, "weather_zones")
    assert abs(zone["coverage"] - 45 / CYCLE) < 1e-12, "the period across the turn counts on both sides"


def test_upcoming_weather_is_the_next_known_tick_after_now(con):
    now = (int(time.time() * 1000) - EPOCH) * 25 // 60000 % CYCLE
    soon, later = (now + 600) % CYCLE, (now + 900) % CYCLE
    setup(con, seen("a", 1, T, 3, soon, 1, (soon - 50) % CYCLE), seen("a", 2, T, 3, later), captures=("a",))
    got = [(r["weather"], r["zone_name"], r["ahead"]) for r in ask(con, "weather_next")]
    assert [(w, z) for w, z, _ in got] == [
        (1, "North Gustaberg"),
        (3, "North Gustaberg"),
        (3, "North Gustaberg"),
    ]
    assert [abs(m - want) <= 1 for (_, _, m), want in zip(got, (550, 600, 900), strict=True)] == [True] * 3
