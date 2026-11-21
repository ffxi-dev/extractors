"""The mob extractors, one test per spec scenario in scholar-mobs. Packets are given as decoded fields."""

from conftest import MOB, drive

from ffxi_extractors.extractors.world.levels import Levels
from ffxi_extractors.extractors.world.spawns import KESU, Spawns

S = 1000  # drive() puts packet i at i seconds; these tests give times themselves


def at(ts, op, d, direction=0):
    return ts, op, d, direction


def run(x, *steps):
    """steps: (ts_ms, opcode, fields, direction)."""
    return drive(
        x, *((op, d) for _, op, d, _ in steps), times=[s[0] for s in steps], directions=[s[3] for s in steps]
    )


def update(x, y, z=0.0, d=0, status=0, uid=MOB):
    return 0x00E, {"UniqueNo": uid, "ActIndex": uid & 0xFFF, "SendFlg.Position": 1, "x": x, "y": y, "z": z,
                   "dir": d, "server_status": status}  # fmt: skip


def test_a_mob_defeated_and_back():
    rows = run(
        Spawns,
        at(0, *update(10.0, 20.0)),
        at(1 * S, 0x029, {"UniqueNoTar": MOB, "MessageNum": 6}),
        at(2 * S, 0x029, {"UniqueNoTar": MOB, "MessageNum": 20}),  # the same death again
        at(9 * S, 0x038, {"UniqueNoTar": MOB, "ident": KESU}),
        at(10 * S, *update(10.0, 20.0, status=3)),  # still dead
        at(300 * S, *update(50.0, 60.0)),
    )["spawns"]
    assert [(r["kind"], r["x"], r["since_defeat_ms"], r["since_despawn_ms"]) for r in rows] == [
        ("defeated", 10.0, None, None),
        ("despawned", 10.0, 8 * S, None),
        ("spawned", 50.0, 299 * S, 291 * S),
    ]


def test_a_widescan_list_and_a_check():
    zone_in = (0x00A, {"ZoneNo": 0x0A3})
    t = "TrackingListTbl."
    scan = [(0x0F4, {t + "ActIndex": 0x010, t + "Level": lv, t + "Type": 2, t + "sName": "Goblin"})
            for lv in (30, 30, 32)]  # fmt: skip
    npc = (0x0F4, {t + "ActIndex": 0x011, t + "Level": 1, t + "Type": 1})
    check = (0x029, {"UniqueNoTar": MOB, "MessageNum": 173, "Data": 31})
    # A mob whose level /check cannot gauge answers 0xFFFFFFFF.
    unknown = (0x029, {"UniqueNoTar": MOB + 1, "MessageNum": 174, "Data": 0xFFFFFFFF})
    rows = drive(Levels, zone_in, *scan, npc, check, unknown)["levels"]
    assert [(r["entity_id"], r["level"], r["source"], r["name"]) for r in rows] == [
        (MOB, 30, "widescan", "Goblin"),
        (MOB, 32, "widescan", "Goblin"),
        (MOB, 31, "check", None),
    ]


def test_levels_by_life():
    zone_in = (0x00A, {"ZoneNo": 0x0A3})
    t = "TrackingListTbl."

    def scan(lv):
        return 0x0F4, {t + "ActIndex": 0x010, t + "Level": lv, t + "Type": 2, t + "sName": "Goblin"}

    def defeat():
        return 0x029, {"UniqueNoTar": MOB, "MessageNum": 6}

    gone = (0x00E, {"UniqueNo": MOB, "ActIndex": 0x010, "SendFlg.Despawn": 1})
    check = (0x029, {"UniqueNoTar": MOB, "MessageNum": 173, "Data": 5})
    # 5 (twice), defeated; 6, defeated; 5, out of view; 5 again, then a zone change and a /check.
    steps = [zone_in, scan(5), scan(5), defeat(), scan(6), defeat(), scan(5), gone, scan(5), zone_in, check]
    rows = drive(Levels, *steps)["levels"]
    assert [(r["level"], r["source"], r["idx"], r["end_idx"]) for r in rows] == [
        (5, "widescan", 1, 3),
        (6, "widescan", 4, 5),
        (5, "widescan", 6, 7),
        (5, "widescan", 8, 9),
        (5, "check", 10, None),
    ]
