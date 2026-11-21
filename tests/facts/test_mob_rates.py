"""The mob card's rates on hand-built rows: the Wilson function, the level-correction zones, and the mobs
query's accuracy and TP delay, one test per case in scholar-mob-oax's design."""

import pytest
from conftest import rows
from fill import put, records

ZONE, CORRECTED = 250, 100  # a zone without level correction, and one with it
CAPPED, FLOORED, TP, UNKNOWN, BINNED, KILLED, LV_A, LV_B, LV_C, BOUNCED, ZONED, RESPAWNED = (
    0x01000000 | (ZONE << 12) | i for i in range(1, 13)
)
CHECKED = 0x01000000 | (CORRECTED << 12) | 5
SAM = 0x01000000 | (ZONE << 12) | 13


def rounds(mob, first, passed, missed, zone=ZONE, tp=None, interval=4080):
    """A mob's single-swing rounds at the character: passed swings hit, the rest miss."""
    return [
        {
            "capture_id": "h",
            "idx": first + i,
            "actor_id": mob,
            "actor_is_mob": True,
            "interval_ms": interval,
            "swings": 1,
            "hits": int(i < passed),
            "main_hand": 1,
            "off_hand": 0,
            "kicks": 0,
            "targets": 1,
            "cut_short": False,
            "at_character": True,
            "misses": int(i >= passed),
            "dodged": 0,
            "other": 0,
            "zone_id": zone,
            "tp_gain": tp,
        }
        for i in range(passed + missed)
    ]


def capture(con, cid="h"):
    """The capture the rows are of, which names its entities."""
    put(con, "captures", [{"capture_id": cid, "client_version": "", "retail": True, "packets": 0}])


def test_a_progress_field_past_the_four_logs_names_none(con):
    """An array index past its end reads 0, so field 3 named log 0, San d'Oria's quests."""
    got = rows(
        con,
        "SELECT mission_log('progress', 128, '', 3, 0, 0, 0), mission_log('progress', 128, '', 4, 0, 0, 0)",
    )
    assert got == [(None, 7)]


def test_wilson_known_values(con):
    (got,) = records(
        con,
        "SELECT wilson(0, 10, 1.96) AS a, wilson(10, 10, 1.96) AS b,"
        " wilson(50, 100, 1.96) AS c, wilson(0, 0, 1.96) AS d",
    )
    none, every, half, empty = got.values()
    assert none["lo"] == pytest.approx(0, abs=1e-12) and none["hi"] == pytest.approx(0.27754, abs=1e-5)
    assert every["lo"] == pytest.approx(0.72246, abs=1e-5) and every["hi"] == pytest.approx(1)
    assert half["lo"] == pytest.approx(0.40383, abs=1e-5) and half["hi"] == pytest.approx(0.59617, abs=1e-5)
    assert empty is None


def test_level_corrected_zones_are_lsbs(con):
    zones = {z for (z,) in rows(con, "SELECT zone_id FROM level_corrected_zones")}
    assert len(zones) == 216
    assert {1, 100, 298} <= zones and 256 not in zones  # Phanauet Channel, West Ronfaure; not West Adoulin


def test_tp_shadows(con):
    """tp-move-shadows 1.1: the shadows each use took, by the recorder's Copy Image icon. 110 took 2 of the
    recorder's 3: exact. 120 took the recorder's last one and 3 from B, whose shadows are not known: at
    least 3. 130 landed on the recorder's 2 and the icon left 0.7 s later: wiped. 140 landed on its 3 and
    the icon stayed: left. 150 missed: nothing."""
    from ffxi_extractors.index import run

    mob, me, b = 0x01000000 | (ZONE << 12) | 30, 0x00100001, 0x00100002
    put(con, "captures", [{"capture_id": "h", "client_version": "", "retail": True, "packets": 0,
                           "character_id": me}])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": "h", "entity_id": mob, "idx": 1, "name": "Lamia",
                                 "model_id": 1}])  # fmt: skip
    put(con, "fights", [{"capture_id": "h", "idx": 100, "mob_id": mob, "end_idx": 200, "zone_id": ZONE,
                         "outcome": "defeated", "actions": 5}])  # fmt: skip
    uses = ((110, 500, 11), (120, 500, 12), (130, 600, 20), (140, 700, 31), (150, 700, 40))
    put(con, "actions", [{"capture_id": "h", "idx": i, "ts_ms": t * 1000, "actor_id": mob, "category": 11,
                          "action_id": a, "resend": False, "targets": 1} for i, a, t in uses])  # fmt: skip
    hits = ((110, me, 31, 2, 1), (120, me, 31, 1, 1), (120, b, 31, 3, 1), (130, me, 185, 300, 0),
            (140, me, 185, 300, 0), (150, me, 188, 0, 1))  # fmt: skip
    at, move = {i: t * 1000 for i, _, t in uses}, {i: a for i, a, _ in uses}
    put(con, "action_results", [{"capture_id": "h", "idx": i, "ts_ms": at[i], "category": 11,
                                 "action_id": move[i], "target_id": who,
                                 "message": msg, "value": v, "miss": miss}
                                for i, who, msg, v, miss in hits])  # fmt: skip
    icons = ((445, 10000, 11800), (66, 11800, 12600), (444, 19000, 20700), (445, 30000, 51000))
    put(con, "effects", [{"capture_id": "h", "idx": k, "ts_ms": on, "status_id": s, "ended_ms": off}
                         for k, (s, on, off) in enumerate(icons)])  # fmt: skip
    run(con, None, "h", units={"bestiary"})
    (fight,) = records(con, "SELECT tp FROM bestiary_fights")
    got = [(u["idx"], u["shadows"], u["shadow_exact"], u["through"]) for u in fight["tp"]]
    assert got == [(110, 2, True, None), (120, 3, False, None), (130, None, None, True),
                   (140, None, None, False), (150, None, None, None)]  # fmt: skip


def test_the_bestiary_keeps_no_tp_gain_from_a_sam_recorder(con):
    """The mob pages' TP delay, as the capture view's: a gain from a round while the recorder was SAM, main or
    sub, is left out; one before it stays."""
    from ffxi_extractors.index import run

    mob = 0x01000000 | (ZONE << 12) | 30
    capture(con)
    put(con, "entity_changes", [{"capture_id": "h", "entity_id": mob, "idx": 1, "name": "Sam",
                                 "model_id": 1}])  # fmt: skip
    put(con, "fights", [{"capture_id": "h", "idx": 100, "mob_id": mob, "end_idx": 200, "zone_id": ZONE,
                         "outcome": "defeated", "actions": 3}])  # fmt: skip
    war = {"capture_id": "h", "main_job": "WAR", "main_level": 75}
    put(con, "character", [{**war, "idx": 10, "sub_job": "NIN"}, {**war, "idx": 150, "sub_job": "SAM"}])
    put(con, "attack_rounds", [*rounds(mob, 110, 1, 0, tp=21), *rounds(mob, 160, 1, 0, tp=28)])
    run(con, None, "h", units={"bestiary"})
    (fight,) = records(con, "SELECT tp_gains FROM bestiary_fights")
    assert fight["tp_gains"] == [21]
