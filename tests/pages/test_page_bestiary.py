"""The bestiary, one test per task in vault's scholar-bestiary: the derived unit, its facts, the party-copy
rule, the trust filter, and the mob page's figures on hand-built rows and on the fixtures."""

import json
import re

import pytest
from conftest import CAPTAIN, rows, value
from fill import ask, put, records

from ffxi_extractors import store
from ffxi_extractors.facts.bestiary_mobs import BestiaryMobs
from ffxi_extractors.index import run

ZONE = 0xA3
MOB = 0x01000000 | (ZONE << 12) | 0x010
S = 1000
VALLEY = 128  # Valley of Sorrows, where the captain fixture fights Velociraptors


def page(con, name, zone, mob):
    return ask(con, name, zone=zone, name=mob)


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


# 1.3 Drops, claim, Treasure Hunter, and respawn on each fight's row


def test_a_fight_keeps_the_spells_its_mob_cast_idle_before_it(con):
    capture(con, "i")
    fight = {"capture_id": "i", "mob_id": MOB, "outcome": "defeated", "actions": 4, "zone_id": ZONE}
    put(con, "fights", [{"idx": 5, "ts_ms": 5 * S, "end_idx": 8, "end_ms": 8 * S, **fight},
                        {"idx": 20, "ts_ms": 20 * S, "end_idx": 25, "end_ms": 25 * S, **fight}])  # fmt: skip
    kill = {"capture_id": "i", "mob_id": MOB, "message": 6, "zone_id": ZONE}
    # The second defeat is out of view, with no fight: what the slot cast before it was another life's.
    put(con, "kills", [{"idx": 8, "ts_ms": 8 * S, **kill}, {"idx": 14, "ts_ms": 14 * S, **kill}])
    cast = {"capture_id": "i", "actor_id": MOB, "category": 4, "zone_id": ZONE, "targets": 1, "resend": False}
    put(con, "actions", [{"idx": i, "ts_ms": i * S, "action_id": spell, "ready_ms": ready, **cast}
                         for i, spell, ready in ((3, 249, 1000), (6, 144, 2000), (12, 145, None),
                                                 (16, 249, None), (22, 144, 2000))])  # fmt: skip
    run(con, None, "i", units={"bestiary"})
    first, second = records(con, "SELECT spells, idle_spells, cast_times FROM bestiary_fights ORDER BY idx")
    assert (first["spells"], first["idle_spells"]) == ([144], [249]), "Blaze Spikes before the pull is idle"
    assert (second["spells"], second["idle_spells"]) == ([144], [249]), "only after the unseen defeat"
    # Each cast's time and the wait since that spell's last finish: 16 s less 3 s; 22 s less 2 s less 6 s.
    assert [tuple(t.values()) for t in first["cast_times"]] == [(249, 1000, None), (144, 2000, None)]
    assert [tuple(t.values()) for t in second["cast_times"]] == [(249, None, 13000), (144, 2000, 14000)]

    times = [{"id": 249, "ready": 1000, "gap": None}, {"id": 249, "ready": 1010, "gap": 40000},
             {"id": 144, "ready": 2000, "gap": 30000}]  # fmt: skip
    later = [{"id": 144, "ready": 2500, "gap": 25000}]
    facts(con, [defeat("j", 100, spells=[144], idle_spells=[249, 249], cast_times=times),
                defeat("j", 200, spells=[144], cast_times=later)])  # fmt: skip
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    got = [
        {k: t[k] for k in ("id", "n", "idle", "ready_n", "ready_q", "recast", "recast_n")}
        for t in mob["casts"]
    ]
    assert got == [
        {
            "id": 144,
            "n": 2,
            "idle": 0,
            "ready_n": 2,
            "ready_q": [2125, 2250, 2375],
            "recast": 25000,
            "recast_n": 2,
        },
        {
            "id": 249,
            "n": 2,
            "idle": 2,
            "ready_n": 2,
            "ready_q": [1002.5, 1005, 1007.5],
            "recast": 40000,
            "recast_n": 1,
        },
    ]


def test_a_rare_items_rate_leaves_out_the_kills_it_was_held_or_unknown_at(con):
    pole, scale = 21173, 640
    put(con, "names", [{"release": "r", "kind": "item_rare", "log_id": 0, "id": pole, "name": "Rare"}])
    kill = {"claimed": True, "th": 0}

    def dropped(*items):
        return [{"item": i, "slot": k, "start_time": 0, "idx": 0} for k, i in enumerate(items)]

    facts(con, [defeat("q", 100, **kill, held_known=True, held=[pole]),
                defeat("q", 200, **kill, held_known=True, drops=dropped(pole)),
                defeat("q", 300, **kill, held_known=False),
                defeat("q", 400, **kill, held_known=True, drops=dropped(scale))])  # fmt: skip
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    (th0,) = mob["drops"]
    got = {x["item"]: (x["n"], x["of"]) for x in th0["items"]}
    assert th0["kills"] == 4
    assert got == {pole: (1, 2), scale: (1, 4)}, (
        "the pole's rate leaves out a kill it was held at and one unknown"
    )


def test_a_chains_first_skillchain_gives_the_mobs_resistance_rank(con):
    """A level 1 Liquefaction closed by a 149 damage Fire for 74: 74.5 / (149 x 0.5) reads 100%. Another 5 s
    later goes on with the chain and is left out; so are an absorbed one, a start packet's, and one that dealt
    under 10, which the floor leaves loose. A Detonation a weapon skill closed for 1000 and 650 reads 130%."""
    capture(con, "s")
    put(con, "fights", [{"capture_id": "s", "idx": 5, "ts_ms": 5 * S, "end_idx": 90, "end_ms": 90 * S,
                         "mob_id": MOB, "outcome": "defeated", "actions": 9, "zone_id": ZONE}])  # fmt: skip
    hit = {"capture_id": "s", "actor_id": 0x1234, "target_id": MOB}

    def sc(idx, at_s, category, closing, chain, damage, message=None):
        return {"idx": idx, "ts_ms": at_s * S, "category": category, "value": closing, "proc_kind": chain,
                "proc_value": damage, "proc_message": message or 287 + chain, **hit}  # fmt: skip

    put(con, "action_results", [
        sc(10, 10, 4, 149, 8, 74),
        sc(12, 15, 3, 300, 8, 150),  # the chain's second: its rank was lowered
        sc(20, 30, 4, 120, 12, 70, message=396),  # absorbed
        sc(22, 50, 8, 24, 1, 2542),  # a spell start's bits, not a skillchain
        sc(30, 70, 4, 6, 12, 2),
        sc(40, 85, 3, 1000, 13, 650),
    ])  # fmt: skip
    run(con, None, "s", units={"bestiary"})
    (fight,) = records(con, "SELECT skillchains FROM bestiary_fights")
    assert [(s["idx"], s["chain"], s["category"]) for s in fight["skillchains"]] == [(10, 8, 4), (40, 13, 3)]

    chains = [{"idx": 10, "chain": 8, "category": 4, "closing": 149, "damage": 74},
              {"idx": 40, "chain": 13, "category": 3, "closing": 1000, "damage": 650}]  # fmt: skip
    facts(con, [defeat("t", 100, skillchains=chains)])
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    got = {(g["chain"], g["spell"]): (g["tiers"], round(g["lo"], 3)) for g in mob["skillchains"]}
    assert got == {(8, True): ([[100, 1]], 1.0), (13, False): ([[130, 1]], 1.301)}
    (ev,) = page(con, "bestiary_evidence", ZONE, "Goblin")
    assert ev["skillchains"] == [[10, 8, 4, 149, 74], [40, 13, 3, 1000, 650]]


def test_a_mob_that_attacks_with_tp_moves_has_their_intervals_as_its_delay(con):
    """A mob with no auto-attacks uses TP moves with no readies in their place, one of several: the time
    between two in a row is its delay. A spell or a readied move between starts it again. The mob page
    leaves out whole-second captures."""
    capture(con, "r")
    put(con, "fights", [{"capture_id": "r", "idx": 5, "ts_ms": 5 * S, "end_idx": 90, "end_ms": 90 * S,
                         "mob_id": MOB, "outcome": "defeated", "actions": 6, "zone_id": ZONE}])  # fmt: skip
    act = {"capture_id": "r", "actor_id": MOB, "zone_id": ZONE, "targets": 1, "resend": False}
    put(con, "actions", [
        {"idx": 10, "ts_ms": 10_001, "category": 11, "action_id": 2962, "ready_ms": None, **act},
        {"idx": 11, "ts_ms": 17_501, "category": 11, "action_id": 2964, "ready_ms": None, **act},  # 450
        {"idx": 12, "ts_ms": 25_001, "category": 11, "action_id": 2963, "ready_ms": None, **act},  # 450
        {"idx": 13, "ts_ms": 30_001, "category": 11, "action_id": 2965, "ready_ms": 2000, **act},  # readied
        {"idx": 14, "ts_ms": 36_001, "category": 11, "action_id": 2962, "ready_ms": None, **act},
        {"idx": 15, "ts_ms": 40_001, "category": 4, "action_id": 1, "ready_ms": 1000, **act},  # a spell
        {"idx": 16, "ts_ms": 46_001, "category": 11, "action_id": 2962, "ready_ms": None, **act},
        {"idx": 17, "ts_ms": 54_001, "category": 11, "action_id": 2963, "ready_ms": None, **act},  # 480
    ])  # fmt: skip
    run(con, None, "r", units={"bestiary"})
    (fight,) = records(con, "SELECT skill_delays FROM bestiary_fights")
    assert fight["skill_delays"] == [450, 450, 480]

    facts(con, [defeat("a", 1000, coarse=False, skill_delays=[450, 460]),
                defeat("b", 2000, coarse=True, skill_delays=[600])])  # fmt: skip
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    assert (mob["delay"], mob["skill_delay"]["n"], mob["skill_delay"]["median"]) == (None, 2, 455)


def test_a_tp_moves_ready_time_leaves_out_whole_second_captures(con):
    """Each use keeps its ready time, and a fight its capture's coarse flag: whether every action came on a
    whole second. The mob page takes the median and middle half of the fine captures' uses, to 10 ms, and
    counts the coarse captures' uses apart."""
    capture(con, "r")
    put(con, "fights", [{"capture_id": "r", "idx": 5, "ts_ms": 5 * S, "end_idx": 90, "end_ms": 90 * S,
                         "mob_id": MOB, "outcome": "defeated", "actions": 2, "zone_id": ZONE}])  # fmt: skip
    tp = {"capture_id": "r", "actor_id": MOB, "category": 11, "action_id": 500, "zone_id": ZONE, "targets": 1,
          "resend": False}  # fmt: skip
    put(con, "actions", [{"idx": 10, "ts_ms": 10 * S + 1, "ready_ms": 1504, **tp},
                         {"idx": 20, "ts_ms": 20 * S, "ready_ms": None, **tp}])  # fmt: skip
    run(con, None, "r", units={"bestiary"})
    (fight,) = records(con, "SELECT coarse, tp FROM bestiary_fights")
    assert (fight["coarse"], [u["ready"] for u in fight["tp"]]) == (False, [1504, None])

    def use(ready):
        return {"idx": 1, "id": 500, "targets": 1, "reach": None, "spread": None, "size": None, "hit": True,
                "crit": False, "kb": 0, "ready": ready, "near": [], "rules_out": [0, 0, 0, 0],
                **UNSHADOWED}  # fmt: skip

    facts(con, [defeat("a", 1000, coarse=False, tp=[use(904), use(1032), use(786), use(None)]),
                defeat("b", 2000, coarse=False, tp=[use(1139)]),
                defeat("c", 3000, coarse=True, tp=[use(1000), use(2000)])])  # fmt: skip
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    (t,) = mob["tp"]
    assert (t["n"], t["ready_n"], t["ready_coarse"]) == (7, 4, 2)
    assert t["ready_q"] == [872.5, 965, 1057.5]
    assert t["ready_v"] == [[790, 1], [900, 1], [1030, 1], [1140, 1]]


# 2.1 to 2.4 The bestiary view and the mob page on hand-built facts


# A TP use's shadow fields when no shadow took part.
UNSHADOWED = {"shadows": None, "shadow_exact": None, "through": None}


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


def test_a_fight_counts_once_and_flagged_captures_stay_out(con):
    fights = [
        defeat("a", 1000, fight_key=1),
        defeat("b", 1003, fight_key=1, actions=50),  # a's copy: the lower capture id counts it
        defeat("c", 2000),
        defeat("e", 3000),  # Flagged: gone
        defeat("f", 4000),  # no level yet: counts
    ]
    facts(con, fights, {"a": "plain", "b": "gold", "c": "plain", "e": "flagged"})
    got = rows(con, "SELECT capture_id, kept, copies FROM bestiary ORDER BY ts_ms, capture_id")
    assert "e" not in {r[0] for r in got}
    assert got[:2] == [("a", True, ["a", "b"]), ("b", False, ["a", "b"])], "no pick by trust or actions"
    (card,) = page(con, "bestiary_mob", ZONE, "Goblin")
    assert (card["fights"], card["defeated"], card["captures"]) == (3, 3, 4)
    ev = page(con, "bestiary_evidence", ZONE, "Goblin")
    first = next(r for r in ev if r["capture_id"] == "a")
    assert sorted(first["copies"]) == ["a", "b"] and first["kept"], "the evidence names both captures"
    assert "e" not in {r["capture_id"] for r in ev}


def test_a_flagged_capture_leaves_the_bestiary_at_once(con):
    run(con, CAPTAIN, "c")
    assert value(con, "SELECT count() FROM bestiary WHERE capture_id = 'c'") > 10
    assert page(con, "bestiary_mob", VALLEY, "Velociraptor")
    store.trust(con, [("c", "flagged")])
    assert value(con, "SELECT count() FROM bestiary") == 0
    assert value(con, "SELECT count() FROM bestiary_list") == 0
    assert page(con, "bestiary_mob", VALLEY, "Velociraptor") == []
    assert page(con, "bestiary_evidence", VALLEY, "Velociraptor") == []


# fight_key on the extractors' rows: party members' copies of a fight share it


def seen(con, cid, ends=(1000,), server=None, roster=None):
    """Defeats of the mob in capture cid, ending at these seconds, in world Asura: after a zone-in on this
    zone server, and with this 0x0C8 roster, when given. Then the capture's bestiary and roll-up."""
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "retail": True, "packets": 0,
                           "character": cid, "start_ms": 0, "world": "Asura"}])  # fmt: skip
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


def fights(con):
    cards = page(con, "bestiary_mob", ZONE, "Goblin")
    return sum(c["fights"] for c in cards)


@pytest.mark.parametrize("a, b", [
    ({"server": "1.2.3.4:54288"}, {"server": "1.2.3.4:54288", "ends": (1001,)}),  # the same zone server
    ({"roster": [7, 8]}, {"roster": [8, 7]}),  # no server: the same alliance
    ({"roster": [7], "server": "1.2.3.4:54288"}, {"roster": [9], "server": "1.2.3.4:54288"}),  # a bystander
])  # fmt: skip
def test_party_members_copies_of_a_fight_count_once(con, a, b):
    seen(con, "a", **a)
    seen(con, "b", **b)
    assert value(con, "SELECT uniqExact(fight_key) FROM bestiary_fights") == 1
    assert fights(con) == 1


@pytest.mark.parametrize("a, b", [
    ({"server": "1.2.3.4:54288"}, {"server": "1.2.3.4:54289"}),  # parallel instances of the zone
    ({"roster": [7, 8]}, {"roster": [9]}),  # no server: two parties
    ({}, {}),  # neither: each capture counts its own
    # One started inside the zone, so has no server: the server comes first, so they split. 18 pairs on the
    # archive, against 33,004 a roster-first key split.
    ({"roster": [7, 8]}, {"roster": [7, 8], "server": "1.2.3.4:54288"}),
])  # fmt: skip
def test_fights_on_other_instances_or_with_nothing_to_match_count_apart(con, a, b):
    seen(con, "a", **a)
    seen(con, "b", **b)
    assert fights(con) == 2


def test_a_removed_or_flagged_copy_leaves_the_other_counted(con):
    """a counts the fight both hold, as the lower id. Flag or remove a: b's copy counts, with no refresh."""
    seen(con, "a", ends=(1000, 2000), server="1.2.3.4:54288")  # the second fight a's own
    seen(con, "b", server="1.2.3.4:54288")
    assert fights(con) == 2
    store.trust(con, [("a", "flagged")])
    assert fights(con) == 1
    store.trust(con, [("a", None)])
    assert fights(con) == 2
    store.drop(con, "a")
    assert fights(con) == 1
    (card,) = page(con, "bestiary_mob", ZONE, "Goblin")
    assert card["captures"] == 1
    assert [(r["capture_id"], r["kept"]) for r in page(con, "bestiary_evidence", ZONE, "Goblin")] == [
        ("b", True)
    ]


def test_a_fight_its_owner_no_longer_holds_counts_in_the_other_copy(con):
    """a's run again lost the fight both held: b, found only through a's old rows, kept leaving it out
    (Codex's review, 6)."""
    seen(con, "a", ends=(1000, 2000), server="1.2.3.4:54288")
    seen(con, "b", server="1.2.3.4:54288")
    assert fights(con) == 2
    con.command("DELETE FROM fights WHERE capture_id = 'a' AND idx = 10")
    run(con, None, "a", units={"bestiary", "bestiary_mobs"})
    assert fights(con) == 2


def swings(n, passed, eva):
    return [{"passed": int(i < passed), "missed": int(i >= passed), "hits": int(i < passed), "corr": False,
             "lo": 10, "hi": 10, "clv": 75, "eva": eva, "eva_floor": None} for i in range(n)]  # fmt: skip


@pytest.mark.parametrize("eva_b, overlap", [(310, True), (400, False)])
def test_accuracy_per_recorder(con, eva_b, overlap):
    """80 of 100 swings passed puts ACC - EVA at -6 to 23: evasion 300 and 310 agree on ACC 304 to 323, 300
    and 400 do not. Both copies of one fight count, as each recorder's swings are its own."""
    fights = [defeat("a", 1000, fight_key=1, swings_at_recorder=swings(100, 80, 300)),
              defeat("b", 1002, fight_key=1, swings_at_recorder=swings(100, 80, eva_b))]  # fmt: skip
    facts(con, fights, characters={"a": "Ann", "b": "Bob"})
    acc = page(con, "bestiary_mob", ZONE, "Goblin")[0]["accuracy"]
    assert (acc["passed"], acc["missed"]) == (160, 40)
    each = {r["who"]: (r["acc_lo"], r["acc_hi"]) for r in acc["recorders"]}
    assert each == {"Ann": (294, 323), "Bob": (eva_b - 6, eva_b + 23)}
    assert (acc["acc_lo"], acc["acc_hi"]) == ((304, 323) if overlap else (None, None))


def test_a_mob_page_sums_what_each_capture_rules_out(con):
    """A rules out a single target and a breath once each; B rules out a breath by more, and the area around
    the mob. The page counts each shape's uses over both and draws the use with the widest margin."""

    def use(idx, out):
        near = [{"distance": 3.0, "bearing": 0.0, "from_target": 0.0, "hit": True}]
        return {"idx": idx, "id": 500, "targets": 1, "reach": 3.0, "spread": None, "size": 2.0, "hit": True,
                "crit": False, "kb": 0, "near": near, "rules_out": out,
                **UNSHADOWED}  # fmt: skip

    fights = [
        defeat("a", 1000, tp=[use(11, [1, 0, 0, 5])]),
        defeat("b", 5000, tp=[use(21, [0, 2, 0, 30]), use(22, [0, 0, 0, 0])]),
    ]
    facts(con, fights)
    (geo,) = page(con, "bestiary_geometry", ZONE, "Goblin")
    assert (geo["uses"], geo["shapes_out"]) == (3, [1, 1, 0, 2])
    assert [p and (p[1], int(p[2])) for p in geo["proofs"]] == [("a", 11), ("b", 21), None, ("b", 21)]


def test_a_mob_page_keeps_the_uses_that_hit_farthest_and_the_party_members_missed(con):
    """For the mob and for its first target, the two uses over every capture whose farthest target hit stood
    farthest from it, the first target left out, and each party member missed by its distance from it."""

    def use(idx, far, miss):
        near = [
            {"distance": 3.0, "bearing": 0.0, "from_target": 0.0, "hit": True},
            {"distance": miss, "bearing": 180.0, "from_target": None, "hit": False},
        ]
        if far:
            near.append({"distance": far, "bearing": 90.0, "from_target": far - 1, "hit": True})
        return {"idx": idx, "id": 500, "targets": 2, "reach": None, "spread": None, "size": None, "hit": True,
                "crit": False, "kb": 0, "near": near, "rules_out": [1, 0, 0, 0], **UNSHADOWED}  # fmt: skip

    # Two uses in one fight; one that hit only its first target tells no range.
    facts(con, [defeat("a", 1000, tp=[use(11, 9.6, 12.0), use(12, 14.0, 12.04)]),
                defeat("b", 5000, tp=[use(21, 8.0, 3.0), use(22, None, 5.0)])])  # fmt: skip
    (geo,) = page(con, "bestiary_geometry", ZONE, "Goblin")
    assert [[(round(-u[0], 1), u[1], int(u[2])) for u in k] for k in geo["reach"]] == [
        [(14.0, "a", 12), (9.6, "a", 11)],
        [(13.0, "a", 12), (8.6, "a", 11)],
    ]
    assert geo["missed"] == [[[3.0, 1.0], [5.0, 1.0], [12.0, 2.0]], []]


def test_a_moves_page_sums_its_uses_over_every_mob_that_used_it(con):
    """tp-move-page 1.1: two mobs' uses of one move sum, as do the uses that rule out each shape; each mob
    keeps its own row, and the list has the move once, ordered by id."""

    def use(idx, out, crit=False, ready=1000):
        near = [{"distance": 3.0, "bearing": 0.0, "from_target": 0.0, "hit": True}]
        return {"idx": idx, "id": 951, "targets": 1, "reach": 3.0, "spread": None, "size": None, "hit": True,
                "crit": crit, "kb": 0, "ready": ready, "near": near, "rules_out": out,
                **UNSHADOWED}  # fmt: skip

    fafnir = [use(11, [1, 0, 0, 0], crit=True), use(12, [1, 0, 0, 1])]
    other = {**use(31, [0, 0, 0, 0]), "id": 900}  # a lower id, used less
    facts(con, [defeat("a", 1000, mob_name="Fafnir", tp=fafnir),
                defeat("b", 5000, mob_name="Nidhogg", tp=[use(21, [0, 0, 0, 1], ready=1200)]),
                defeat("b", 9000, mob_name="Nidhogg", tp=[other])])  # fmt: skip
    learned = {"client_version": "v", "zone_id": ZONE, "kind": "learned", "skill_id": 951, "spell_id": 652}
    put(con, "mob_events", [{"capture_id": "a", "idx": 40, "ts_ms": 1000 * S, "player_id": p, **learned}
                            for p in (1, 2)])  # fmt: skip
    moves = ask(con, "tp_moves")
    assert [(t["id"], t["uses"]) for t in moves] == [(900, 1), (951, 3)], "by id, not by uses"
    assert [t["blu"] and (t["blu"]["spell"], t["blu"]["learned"]) for t in moves] == [None, (652, 2)]
    listed = moves[1]
    (move,) = ask(con, "tp_move", move=951)
    for t in (listed, move):
        assert (t["id"], t["uses"], t["mobs"], t["hits"], t["crits"]) == (951, 3, 2, 3, 1)
        assert t["shapes_out"] == [2, 0, 0, 2]
        assert (t["ready_n"], t["ready_q"]) == (3, [1000, 1000, 1100])
    assert [(m["mob"], m["n"], m["crits"], m["ready_n"]) for m in move["by_mob"]] == [
        ("Fafnir", 2, 1, 2),
        ("Nidhogg", 1, 0, 1),
    ]
    assert ask(con, "tp_move", move=952) == []


def test_a_moves_distance_is_its_second_farthest_first_target(con):
    """The owner's review note 8: how far a move's first target stood when it was used, apart from its area's
    range: the second farthest, as range takes, so one odd use does not set it."""

    def use(idx, distance):
        near = [{"distance": distance, "bearing": 0.0, "from_target": 0.0, "hit": True},
                {"distance": distance + 2, "bearing": 10.0, "from_target": 2.0, "hit": True}]  # fmt: skip
        return {"idx": idx, "id": 500, "targets": 2, "reach": None, "spread": None, "size": None, "hit": True,
                "crit": False, "kb": 0, "ready": None, "near": near, "rules_out": [0, 0, 0, 0],
                **UNSHADOWED}  # fmt: skip

    facts(con, [defeat("a", 1000, tp=[use(1, 3.0), use(2, 6.2)]), defeat("b", 2000, tp=[use(3, 5.5)])])
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    (listed,) = ask(con, "tp_moves")
    (move,) = ask(con, "tp_move", move=500)
    assert [t["distance"] for t in (*mob["tp"], listed, move)] == [5.5, 5.5, 5.5], "6.2 once; 5.5 the next"


# 2.2, 2.5, 2.6 On the fixtures: the bestiary agrees with the capture view's card


def same(v, k):
    """A figure as JSON; lists the queries order by count, whose ties fall either way, in a fixed order."""
    if k in ("tp", "taken") and v:
        v = sorted(v, key=lambda x: json.dumps(x, default=str))
    return json.dumps(v, default=str, sort_keys=True)


def test_every_figure_leads_to_fights(both):
    (raptor,) = page(both, "bestiary_mob", VALLEY, "Velociraptor")
    ev = [e for e in page(both, "bestiary_evidence", VALLEY, "Velociraptor") if e["kept"]]
    assert len(ev) == raptor["fights"] == 10
    assert sum(e["delays"] for e in ev) == raptor["delay"]["n"]
    assert sum(e["rounds"] for e in ev) == raptor["multi"]["rounds"]
    assert sum(e["swings"] or 0 for e in ev) == raptor["accuracy"]["passed"] + raptor["accuracy"]["missed"]
    for t in raptor["tp"]:
        assert sum(1 for e in ev for i, _ in e["tp"] or [] if i == t["id"]) == t["n"]
    assert sum(1 for e in ev if e["hp_min"] is not None) == raptor["hp"]["n"]
    for slot in raptor["slots"]:
        assert set(slot) == {"id", "lo", "hi", "respawn"}
        seen = [e["respawn_ms"] for e in ev if e["mob_id"] == slot["id"] and e["respawn_ms"]]
        assert slot["respawn"] == (min(seen) if seen else None)
    for th in raptor["drops"]:
        kills = [e for e in ev if e["claimed"] and e["outcome"] == "defeated" and e["th"] == th["th"]]
        assert len(kills) == th["kills"]
        for item in th["items"] or []:
            assert sum(1 for e in kills if item["item"] in [i for i, _ in e["drops"] or []]) == item["n"]
    assert all(e["capture_id"] == "c" and e["lens_url"] for e in ev)


def test_a_double_attack_counts_rounds_whose_first_swing_hit_and_zanshin_those_that_missed(con):
    """Yagudo Parivir's card read a 31.7% double attack: of its 3,230 rounds whose first swing hit, none had a
    second, and of the 363 whose first missed, 40.8% did. That is Zanshin, which swings again only after a
    single swing that missed. The card takes the double attack from rounds whose first swing hit."""
    hit = [{"main_hand": 1, "first_missed": False}] * 6
    missed = [{"main_hand": 2, "first_missed": True}] * 2 + [{"main_hand": 1, "first_missed": True}] * 2
    swings = hit + missed
    rounds = [
        {"swings": x["main_hand"], "main_hand": x["main_hand"], "off_hand": 0, "kicks": 0} for x in swings
    ]
    facts(con, [defeat("a", 1000, rounds=rounds, first_swings=swings)])
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    multi = mob["multi"]
    assert (multi["rounds"], [x["n"] for x in multi["main_hand"]][:2]) == (10, [8, 2])
    after_hit, after_miss = multi["after_hit"], multi["after_miss"]
    assert (after_hit["hit_rounds"], after_hit["hit_doubles"]) == (6, 0)
    assert (after_miss["miss_rounds"], after_miss["miss_doubles"]) == (4, 2)


def test_setup_brings_an_older_bestiary_to_this_schema(con):
    """A store from before fight_key: bestiary_fights gains the column, and bestiary_mobs, a MergeTree then,
    is made again as a ReplacingMergeTree, so the reruns its new version brings can write them."""
    con.command("ALTER TABLE bestiary_fights DROP INDEX fight")
    con.command("ALTER TABLE bestiary_fights DROP COLUMN fight_key")
    con.command("DROP TABLE bestiary_mobs SYNC")
    con.command("CREATE TABLE bestiary_mobs (capture_id String) ENGINE = MergeTree ORDER BY capture_id")
    store.setup(con)
    assert value(con, "SELECT count() FROM system.columns WHERE database = currentDatabase()"
                      " AND table = 'bestiary_fights' AND name = 'fight_key'") == 1  # fmt: skip
    assert value(con, "SELECT engine FROM system.tables WHERE database = currentDatabase()"
                      " AND name = 'bestiary_mobs'") == "ReplacingMergeTree"  # fmt: skip
    run(con, CAPTAIN, "c")
    assert page(con, "bestiary_mob", VALLEY, "Velociraptor")


def test_wanted_lists_every_mob_seen_with_the_counts_its_page_reads(con):
    """A mob fought, and one only seen (its looks, no fight), with what Wanted marks; Flagged left out."""
    seen(con, "a", ends=(1000, 2000))
    looks = {"zone_id": ZONE, "entity_id": MOB + 1}
    put(con, "bestiary_looks", [{**looks, "capture_id": "a", "mob_name": "Bomb"},
                                {**looks, "capture_id": "f", "mob_name": "Hidden"}])  # fmt: skip
    put(con, "capture_trust", [{"capture_id": "f", "trust": "flagged", "at": 0}])
    (zone,) = ask(con, "bestiary_wanted")
    assert zone["zone"] == ZONE
    got = {m["name"]: m for m in zone["mobs"]}
    assert set(got) == {"Goblin", "Bomb"}
    goblin, bomb = got["Goblin"], got["Bomb"]
    assert [goblin[k] for k in ("fights", "captures", "chains", "taken", "passes")] == [2, 1, [], [], 0]
    assert (bomb["fights"], bomb["hp"], bomb["delay"], bomb["moves"], bomb["lo"]) == (0, 0, 0, 0, None)


def test_a_mob_whose_spells_all_run_fast_may_have_fast_cast(con):
    """Each spell against other mobs' casts of it: Goblin casts Fire and Fire II at 0.8 of the five others, so
    it may have Fast Cast; Chainspell's near-instant casts leave its figure alone. Orc is fast on one spell
    only, and a mob with one spell has nothing to compare."""

    def mob(at, name, by_spell):
        times = [{"id": s, "ready": ms, "gap": None} for s, mss in by_spell.items() for ms in mss]
        return defeat("a", at, mob_name=name, name=name, cast_times=times)

    fights = [mob(100 * i, name, {144: [2000] * 3, 145: [3000] * 3})
              for i, name in enumerate(("Bat", "Crab", "Eft", "Hare", "Ram"), 1)]  # fmt: skip
    fights += [mob(900, "Goblin", {144: [1600] * 3 + [100] * 3, 145: [2400] * 3}),
               mob(1000, "Orc", {144: [1400] * 3, 145: [3000] * 3}),
               mob(1100, "Imp", {144: [1000] * 3})]  # fmt: skip
    facts(con, fights)
    got = records(con, "SELECT mob_name, spells, casts, ratio FROM fast_cast ORDER BY mob_name")
    assert got == [{"mob_name": "Goblin", "spells": 2, "casts": 6, "ratio": 0.8}], "Chainspell's 3 left out"
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    assert [tuple(x.values()) for x in mob["fast_cast"]] == [(2, 6, 0.8)]
    (orc,) = page(con, "bestiary_mob", ZONE, "Orc")
    assert orc["fast_cast"] == []


def test_an_items_drop_rate_is_its_mob_cards(con):
    """The owner's Items page: a Dropped by row reads each Treasure Hunter level as the mob card's Drops does,
    a Rare item's kills it was held or unknown at left out."""
    pole, scale = 21173, 640
    put(con, "names", [{"release": "r", "kind": "item_rare", "log_id": 0, "id": pole, "name": "Rare"}])
    kill = {"claimed": True, "th": 0}

    def dropped(*items):
        return [{"item": i, "slot": k, "start_time": 0, "idx": 0} for k, i in enumerate(items)]

    facts(con, [defeat("q", 100, **kill, held_known=True, held=[pole]),
                defeat("q", 200, **kill, held_known=True, drops=dropped(pole)),
                defeat("q", 300, **kill, held_known=False),
                defeat("q", 400, **kill, held_known=True, drops=dropped(scale))])  # fmt: skip
    (mob,) = page(con, "bestiary_mob", ZONE, "Goblin")
    card = {x["item"]: (x["n"], x["of"]) for x in mob["drops"][0]["items"]}
    for item in (pole, scale):
        (row,) = [r for r in ask(con, "item_sources", item=item) if r["kind"] == "drop"]
        assert (row["place"], row["zone"]) == ("Goblin", ZONE)
        assert [(th, n, of) for th, _, n, of in row["rows"]] == [(0, *card[item])], item


def test_an_item_lists_each_way_it_came_to_hand(con):
    """Pool loot from a crate, and with no dropper named, a Steal, a dig, a synthesis, a shop, a trade's
    answer, an NPC's event with the quest it advanced, a catch, and a gain with none of those: each its kind,
    Flagged captures left out. The owner's Bat Wing: a pool win, or a guild purchase, while a Home Point's
    menu was open is no gift of the Home Point's."""
    item, npc, at = 4096, 0x01000000 | (ZONE << 12) | 0x050, 1_800_000_000_000
    crate, home = 0x01000000 | (ZONE << 12) | 0x700, 0x01000000 | (ZONE << 12) | 0x060
    cap = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**cap, "capture_id": c} for c in "ix"])
    put(con, "capture_trust", [{"capture_id": "x", "trust": "flagged", "at": 0}])
    put(con, "names", [{"release": "r", "kind": "entity", "log_id": 0, "id": npc, "name": "Rytaal"},
                       {"release": "r", "kind": "entity", "log_id": 0, "id": crate, "name": "Armoury Crate"},
                       {"release": "r", "kind": "entity", "log_id": 0, "id": home, "name": "Home Point #1"},
                       {"release": "r", "kind": "quest", "log_id": 1, "log": "Windurst", "id": 5,
                        "name": "A Quest"}])  # fmt: skip
    one = {"capture_id": "i", "client_version": "v", "zone_id": ZONE}

    def at_(idx, s, **more):
        return {**one, "idx": idx, "ts_ms": at + s * S, **more}

    put(con, "drops", [at_(1, 0, item_id=item, mob_id=None), at_(6, 0, item_id=item, mob_id=crate),
                       {**at_(1, 0, item_id=item, mob_id=None), "capture_id": "x"}])  # fmt: skip
    put(con, "steals", [at_(2, 0, mob_name="Goblin", ability="steal", success=True, item_id=item)])
    put(con, "digs", [at_(3, 0, item_id=item, weather_id=1, vana_weekday=0, vana_hour=6)])
    synth = at_(4, 100, own=True, grade=1, item_id=item, crystal_id=4096, ingredients=[640, 641])
    put(con, "synths", [synth])
    put(con, "npc_shops", [at_(5, 0, release="r", npc_id=npc, npc_name="Rytaal", kind="shop", item_id=item,
                               price=120, n=3, last_ts=at)])  # fmt: skip
    put(con, "events", [at_(10, 200, kind="start", npc_id=npc, event_id=7),
                        at_(20, 300, kind="start", npc_id=npc, event_id=9),
                        at_(50, 950, kind="start", npc_id=home, event_id=8700)])  # fmt: skip
    put(con, "shop_actions", [at_(60, 960, action="guild_buy", item_id=item, quantity=1, bought=1)])
    put(con, "trades", [at_(9, 199, npc_id=npc, item_ids=[640], quantities=[2], event_id=7, event_idx=10)])
    put(con, "log_changes", [at_(21, 301, log="quests_done", area="Windurst", id=5, action="completed",
                                 event_idx=20)])  # fmt: skip
    put(con, "fishing", [at_(30, 400, outcome="caught", item_id=item, rod_id=17386, bait_id=17407)])
    put(con, "obtained", [at_(11, 201, item_id=item, quantity=1, event_idx=10),
                          at_(22, 302, item_id=item, quantity=1, event_idx=20),
                          at_(31, 401, item_id=item, quantity=1),
                          at_(40, 900, item_id=item, quantity=1),
                          at_(51, 951, item_id=item, quantity=1, source="pool", event_idx=50),
                          at_(61, 961, item_id=item, quantity=1, event_idx=50)])  # fmt: skip
    rows = ask(con, "item_sources", item=item)
    got = {r["kind"]: r for r in rows}
    assert set(got) == {"drop", "chest", "steal", "dig", "synth", "shop", "trade", "event", "fish", "other"}
    drop = got["drop"]
    assert (drop["place"], drop["n"], drop["rows"]) == ("", 1, []), "no dropper named; Flagged left out"
    assert (got["chest"]["place"], got["chest"]["n"]) == ("Armoury Crate", 1)
    assert [r["place"] for r in rows if r["kind"] == "event"] == ["Rytaal"], "no gift of the Home Point's"
    assert (got["steal"]["place"], got["steal"]["log"]) == ("Goblin", "steal")
    assert got["synth"]["ids"] == [4096, 640, 641] and got["synth"]["rows"] == [[1, 1]]
    assert (got["shop"]["place"], got["shop"]["rows"]) == ("Rytaal", [[120, -1, -1]])
    assert (got["trade"]["place"], got["trade"]["ids"], got["trade"]["rows"]) == ("Rytaal", [640], [[2]])
    event = got["event"]
    assert (event["place"], event["model"], event["log"]) == ("Rytaal", 9, "completed A Quest")
    assert got["fish"]["ids"] == [17386, 17407]
    assert got["other"]["n"] == 1, "the catch's gain is the catch, not another"
    (listed,) = [r for r in ask(con, "items") if r["id"] == item]
    kinds = ("drops", "chests", "steals", "digs", "synths", "shops", "trades", "events", "fish", "other")
    assert [listed[k] for k in kinds] == [1] * 10


def test_the_moves_list_reads_each_moves_proofs_by_a_join_not_from_one_map_per_row():
    """The moves list ran out of memory on the archive: each of its 1,193 rows read its area's proof from
    one map of every move's proofs, joined to every row, so the map was copied to each. Each move's
    proofs are a row of their own, joined by its id."""
    sql = store.pages()["tp_moves"]
    assert not re.search(r"\bg\.p\[", sql)
    assert "LEFT JOIN pf ON pf.pid = f.id" in sql
