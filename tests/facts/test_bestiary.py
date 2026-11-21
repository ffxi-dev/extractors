"""The bestiary, one test per task in vault's scholar-bestiary: the derived unit, its facts, the party-copy
rule, the trust filter, and the mob page's figures on hand-built rows and on the fixtures."""

from conftest import CAPTAIN, rows, value
from fill import put, records

from ffxi_extractors import store
from ffxi_extractors.facts.bestiary_mobs import BestiaryMobs
from ffxi_extractors.index import run

ZONE = 0xA3
MOB = 0x01000000 | (ZONE << 12) | 0x010
S = 1000


def capture(con, cid, character=None, number=0):
    put(
        con,
        "captures",
        [
            {
                "capture_id": cid,
                "client_version": "v",
                "retail": True,
                "packets": 0,
                "character": character or cid,
                "character_id": number,
                "start_ms": 0,
            }
        ],
    )


# 1.1 A derived unit


def test_one_row_per_fight(con):
    """The derived unit reads its inputs' rows in ClickHouse: one row per fight."""
    run(con, CAPTAIN, "c")
    fights = value(con, "SELECT count() FROM fights")
    assert fights > 10 and value(con, "SELECT count() FROM bestiary_fights") == fights
    assert value(con, "SELECT uniqExact(mob_id) FROM bestiary_fights") > 1


# 1.3 Drops, claim, Treasure Hunter, and respawn on each fight's row


def test_drops_and_a_respawn_join_their_fight(con):
    capture(con, "h")
    kill = {
        "capture_id": "h",
        "mob_id": MOB,
        "message": 6,
        "zone_id": ZONE,
        "claimed_by_party": True,
        "th_level": 2,
    }
    fight = {"capture_id": "h", "mob_id": MOB, "outcome": "defeated", "actions": 4, "zone_id": ZONE}
    put(
        con,
        "fights",
        [
            {"idx": 1, "ts_ms": 0, "end_idx": 2, "end_ms": 10 * S, **fight},
            {"idx": 10, "ts_ms": 400 * S, "end_idx": 11, "end_ms": 410 * S, **fight},
        ],
    )
    put(con, "kills", [{"idx": 2, "ts_ms": 10 * S, **kill}, {"idx": 11, "ts_ms": 410 * S, **kill}])
    put(
        con,
        "drops",
        [
            {
                "capture_id": "h",
                "idx": 3,
                "ts_ms": 60 * S,
                "item_id": 100,
                "mob_id": MOB,
                "slot": 0,
                "start_time": 1,
            },
            {
                "capture_id": "h",
                "idx": 12,
                "ts_ms": 480 * S,
                "item_id": 101,
                "mob_id": MOB,
                "slot": 0,
                "start_time": 2,
            },
        ],
    )
    put(
        con,
        "spawns",
        [
            {
                "capture_id": "h",
                "idx": 5,
                "ts_ms": 340 * S,
                "kind": "spawned",
                "entity_id": MOB,
                "x": 10.4,
                "y": -3.6,
                "z": 0.2,
                "since_defeat_ms": 330 * S,
                "zone_id": ZONE,
            }
        ],
    )
    run(con, None, "h", units={"bestiary"})
    first, second = records(con, "SELECT * FROM bestiary_fights ORDER BY idx")
    assert (first["claimed"], first["th_level"]) == (True, 2)
    assert [d["item"] for d in first["drops"]] == [100], "a drop 50 s after the kill"
    assert second["drops"] == [], "one 70 s after joins no kill"
    assert first["respawn_ms"] == 330 * S and round(first["respawn_x"], 1) == 10.4
    assert second["respawn_ms"] is None, "never seen again"


def test_a_defeats_treasure_hunter_comes_from_who_acted_on_it(con):
    """The recorder's TH is its THF trait and gear once a zone-in sent its gear; a THF trust brings 1; a party
    member's is unknown, unless a TH message showed the level."""
    capture(con, "h")
    me, member, trust = 0x0001_0001, 0x0001_0002, 0x01000000 | (ZONE << 12) | 0x710
    mobs = [MOB + i for i in range(5)]
    war = {"capture_id": "h", "character_id": me, "main_job": "WAR", "main_level": 99, "sub_level": 49}
    put(con, "character", [{**war, "idx": 0, "ts_ms": 0, "sub_job": "THF"},
                           {**war, "idx": 45, "ts_ms": 45 * S, "sub_job": "NIN"}])  # fmt: skip
    put(con, "zones", [{"capture_id": "h", "idx": 5, "ts_ms": 5 * S, "zone_id": ZONE}])
    put(con, "character_gear", [
        {"capture_id": "h", "idx": 6, "ts_ms": 6 * S, "character_id": me, "slot": "waist", "item_id": 28450},
        {"capture_id": "h", "idx": 51, "ts_ms": 51 * S, "character_id": me, "slot": "waist", "item_id": None},
    ])  # fmt: skip
    put(
        con,
        "entity_changes",
        [{"capture_id": "h", "idx": 1, "ts_ms": 0, "entity_id": trust, "name": "NanaaMihgo"}],
    )
    windows = list(zip(mobs, [(1, 4), (10, 20), (30, 40), (50, 60), (70, 80)], strict=True))
    put(con, "fights", [{"capture_id": "h", "idx": a, "ts_ms": a * S, "end_idx": b, "end_ms": b * S,
                         "mob_id": m, "outcome": "defeated", "actions": 2, "zone_id": ZONE}
                        for m, (a, b) in windows])  # fmt: skip
    put(con, "kills", [{"capture_id": "h", "idx": b, "ts_ms": b * S, "mob_id": m, "claimed_by_party": True,
                        "th_level": 5 if m == mobs[4] else None, "message": 6, "zone_id": ZONE}
                       for m, (_, b) in windows])  # fmt: skip
    acted = [
        (2, me, 0),
        (12, me, 1),
        (32, me, 2),
        (33, member, 2),
        (52, trust, 3),
        (53, me, 3),
        (72, member, 4),
    ]
    put(con, "action_results", [{"capture_id": "h", "idx": i, "ts_ms": i * S, "actor_id": a,
                                 "target_id": mobs[k], "category": 1} for i, a, k in acted])  # fmt: skip
    run(con, None, "h", units={"bestiary"})
    got = [r["th"] for r in records(con, "SELECT th FROM bestiary_fights ORDER BY idx")]
    # Before the zone-in; /THF 49 and Chaac Belt; a party member too; belt off, /NIN, and Nanaa; a message.
    assert got == [None, 3, None, 1, 5]


def test_a_defeat_keeps_the_rare_items_the_recorder_held(con):
    """Its bags' slots as they stood at the defeat, once a zone-in listed them; only items flagged Rare. A
    slot emptied, or its Rare item swapped for another, holds what it held last."""
    capture(con, "r")
    pole, scale, crystal = 21173, 20000, 4096
    put(con, "names", [{"release": "r", "kind": "item_rare", "log_id": 0, "id": i, "name": "Rare"}
                       for i in (pole, scale)])  # fmt: skip
    put(con, "zones", [{"capture_id": "r", "idx": 5, "ts_ms": 5 * S, "zone_id": ZONE}])
    slots = ((6, 0, 1, pole), (6, 0, 2, crystal), (6, 0, 3, scale), (30, 0, 1, None), (31, 17, 3, pole),
             (32, 0, 3, crystal), (35, 0, 2, scale))  # fmt: skip
    put(con, "holdings", [{"capture_id": "r", "idx": i, "ts_ms": i * S, "container": bag, "item_index": slot,
                           "item_id": item} for i, bag, slot, item in slots])  # fmt: skip
    windows = list(zip([MOB, MOB + 1, MOB + 2], [(1, 4), (10, 20), (40, 50)], strict=True))
    put(con, "fights", [{"capture_id": "r", "idx": a, "ts_ms": a * S, "end_idx": b, "end_ms": b * S,
                         "mob_id": m, "outcome": "defeated", "actions": 2, "zone_id": ZONE}
                        for m, (a, b) in windows])  # fmt: skip
    put(con, "kills", [{"capture_id": "r", "idx": b, "ts_ms": b * S, "mob_id": m, "claimed_by_party": True,
                        "message": 6, "zone_id": ZONE} for m, (_, b) in windows])  # fmt: skip
    run(con, None, "r", units={"bestiary"})
    got = [
        (r["held"], r["held_known"])
        for r in records(con, "SELECT held, held_known FROM bestiary_fights ORDER BY idx")
    ]
    # Before the zone-in; the pole and scale held; the pole gone, its copy in the Recycle Bin not held, the
    # scale moved to the crystal's slot.
    assert got == [([], False), ([scale, pole], True), ([scale], True)]


def test_no_ratio_has_no_rank(con):
    """An outside agent's median over no spell-closed readings came back NaN, and eem_tier read it 150%."""
    sql = "SELECT eem_tier(NULL), eem_tier(nan), eem_tier(0.0), eem_tier(1.0), eem_tier(0.7), eem_tier(9.0)"
    assert rows(con, sql) == [(None, None, None, 100, 70, 150)]


def test_a_skillchain_the_day_or_weather_may_have_moved_is_kept_apart(con):
    """The owner's Stone Golem: one Detonation on Iceday in Snow read Wind 60%, the rest 70%. A day or weather
    of a skillchain's element, or of the one that beats it, moves its damage a third of the time (LSB)."""
    day = 3_456_000  # a Vana'diel day, in ms
    iceday, firesday = 1009810800000 + 4 * day + 60_000, 1009810800000 + 8 * day + 60_000
    sql = (
        "SELECT sc_exposed(13, {i:Int64}, 0), sc_exposed(13, {f:Int64}, 0), sc_exposed(13, {f:Int64}, 12),"
        " sc_exposed(13, {f:Int64}, 10), sc_exposed(9, {i:Int64}, 0), sc_exposed(5, {i:Int64}, 12)"
    )
    assert rows(con, sql, {"i": iceday, "f": firesday}) == [(1, 0, 1, 1, 1, 0)], (
        "Wind on Iceday, not on Firesday, in Snow, in Wind; Ice on Iceday; no level 2 chain"
    )
    capture(con, "s")
    put(con, "fights", [{"capture_id": "s", "idx": 5, "ts_ms": iceday, "end_idx": 90, "mob_id": MOB,
                         "end_ms": iceday + 90 * S, "outcome": "defeated", "actions": 9,
                         "zone_id": ZONE}])  # fmt: skip
    put(con, "weather", [{"capture_id": "s", "idx": 1, "ts_ms": firesday, "zone_id": ZONE, "weather_id": 12}])
    sc = {"capture_id": "s", "actor_id": 0x1234, "target_id": MOB, "category": 4, "value": 149,
          "proc_value": 74}  # fmt: skip
    put(con, "action_results", [{**sc, "idx": 10, "ts_ms": iceday, "proc_kind": 13, "proc_message": 300},
                                {**sc, "idx": 20, "ts_ms": iceday + 60 * S, "proc_kind": 8,
                                 "proc_message": 295}])  # fmt: skip
    run(con, None, "s", units={"bestiary"})
    (fight,) = records(con, "SELECT skillchains FROM bestiary_fights")
    assert [(s["chain"], s["exposed"]) for s in fight["skillchains"]] == [(13, True), (8, False)]


# 2.1 to 2.4 The bestiary view and the mob page on hand-built facts


# A TP use's shadow fields when no shadow took part.
def facts(con, fights, trust=None, characters=None):
    """These bestiary_fights rows (dicts over its columns; each fight its own fight_key unless given), their
    captures, trust, and roll-up."""
    base = {
        "client_version": "v",
        "zone_id": ZONE,
        "name": "Goblin",
        "mob_name": "Goblin",
        "model_id": 7,
        "actions": 5,
    }
    for i, cid in enumerate(sorted({f["capture_id"] for f in fights})):
        capture(con, cid, (characters or {}).get(cid), i + 1)
    for cid, level in (trust or {}).items():
        store.trust(con, [(cid, level)])
    put(con, "bestiary_fights", [{**base, "idx": i, "end_idx": i + 1, "fight_key": 1000 + i, **f}
                                 for i, f in enumerate(fights)])  # fmt: skip
    con.command(f"INSERT INTO bestiary_mobs {BestiaryMobs.sql}", parameters={"capture": ""})
    return con


def defeat(cid, at_s, **more):
    return {
        "capture_id": cid,
        "mob_id": MOB,
        "ts_ms": (at_s - 30) * S,
        "end_ms": at_s * S,
        "outcome": "defeated",
        **more,
    }


# fight_key on the extractors' rows: party members' copies of a fight share it


def seen(con, cid, ends=(1000,), server=None, roster=None, world="Asura"):
    """Defeats of the mob in capture cid, ending at these seconds, in world Asura: after a zone-in on this
    zone server, and with this 0x0C8 roster, when given. Then the capture's bestiary and roll-up."""
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "retail": True, "packets": 0,
                           "character": cid, "start_ms": 0, "world": world}])  # fmt: skip
    if server:
        put(con, "zones", [{"capture_id": cid, "idx": 1, "ts_ms": 0, "zone_id": ZONE, "server": server}])
    if roster:
        put(con, "party", [{"capture_id": cid, "idx": 2, "ts_ms": 0, "member_id": m, "list": "alliance"}
                           for m in roster])  # fmt: skip
    put(con, "fights", [{"capture_id": cid, "mob_id": MOB, "idx": 10 + 2 * i, "end_idx": 11 + 2 * i,
                         "ts_ms": (end - 30) * S, "end_ms": end * S, "outcome": "defeated", "actions": 4,
                         "zone_id": ZONE} for i, end in enumerate(ends)])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": cid, "entity_id": MOB, "idx": 3, "name": "Goblin",
                                 "zone_id": ZONE}])  # fmt: skip
    run(con, None, cid, units={"bestiary", "bestiary_mobs"})


def keys(con) -> set:
    return {r["fight_key"] for r in records(con, "SELECT fight_key FROM bestiary_fights")}


def test_recorders_on_one_zone_server_share_a_fight_whatever_their_rosters(con):
    """On the archive, 33,004 pairs of copies on one zone server had two keys: the roster came first, and a
    recorder outside the claiming party has another."""
    seen(con, "a", server="1.2.3.4:54288", roster=[7, 8])
    seen(con, "b", server="1.2.3.4:54288", roster=[9])
    assert len(keys(con)) == 1


def test_a_party_with_no_zone_server_still_shares_a_fight_by_its_roster(con):
    seen(con, "a", roster=[7, 8])
    seen(con, "b", roster=[7, 8])
    assert len(keys(con)) == 1


def test_a_copy_whose_capture_names_no_world_still_shares_the_fight(con):
    """On the archive, 2,610 pairs of copies on one zone server had two keys: one capture named its world
    and the other none, and the world was in the key."""
    seen(con, "a", server="1.2.3.4:54288")
    seen(con, "b", server="1.2.3.4:54288", world=None)
    assert len(keys(con)) == 1


# 2.2, 2.5, 2.6 On the fixtures: the bestiary agrees with the capture view's card


def test_setup_keeps_a_derived_table_whose_columns_match(con):
    """DESCRIBE spells bestiary_fights' named tuples over several lines and system.columns on one; setup at
    each start must not take that for a retyped column and empty the table."""
    run(con, CAPTAIN, "c")
    fights = value(con, "SELECT count() FROM bestiary_fights")
    store.setup(con)
    assert fights > 0 and value(con, "SELECT count() FROM bestiary_fights") == fights
