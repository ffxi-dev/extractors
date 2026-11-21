"""The NPC catalog: each capture's event starts folded (npc_events), the catalog across captures, and the
timeline's events with their parameters and options."""

from fill import ask, put

from ffxi_extractors import store
from ffxi_extractors.index import run

ZONE = 245  # Lower Jeuno
NPC = 0x0100_0000 | (ZONE << 12) | 100
OTHER = NPC + 1
RENUMBERED = NPC + 7  # the same NPC in a later client version


def capture(con, cid, release, entities):
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "release": release, "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": cid, "idx": 0, "ts_ms": 0, "client_version": "v",
                                 "entity_id": e, "name": n} for e, n in entities.items()])  # fmt: skip


def events(con, cid, rows):
    """rows: (idx, ts, kind, npc, event, params, option, event_idx)."""
    keys = ("idx", "ts_ms", "kind", "npc_id", "event_id", "params", "option", "event_idx")
    base = {"capture_id": cid, "client_version": "v", "zone_id": ZONE}
    put(con, "events", [{**base, **dict(zip(keys, r, strict=True))} for r in rows])
    run(con, None, cid, units={"npc_events"})


def chain(con, cid, npc, at=0):
    """Event 10 with an update (option 2) and an end (option 5), then event 11 that it chains to, then another
    NPC's event under 2 s after: that one follows nothing."""
    events(con, cid, [
        (at + 1, at + 1000, "start", npc, 10, [1, 2, 0, 0, 0, 0, 0, 0], None, at + 1),
        (at + 2, at + 2000, "reply", npc, 10, [], 2, at + 1),
        (at + 3, at + 2100, "update", None, None, [9], None, at + 1),
        (at + 4, at + 3000, "reply", npc, 10, [], 5, at + 1),
        (at + 5, at + 3100, "release", None, None, [], None, at + 1),
        (at + 6, at + 4000, "start", npc, 11, [], None, at + 6),
        (at + 7, at + 5000, "reply", npc, 11, [], 0, at + 6),
        (at + 8, at + 5500, "start", OTHER, 12, [], None, at + 8),
        (at + 9, at + 9000, "start", None, 5, [], None, at + 9),  # a zone-in's event
    ])  # fmt: skip


def test_the_catalog_sums_captures_by_npc_name_across_renumbered_ids(con):
    capture(con, "a", "r1", {NPC: "Moogle", OTHER: "Guard"})
    capture(con, "b", "r2", {RENUMBERED: "Moogle", OTHER: "Guard"})
    capture(con, "e", "r1", {NPC: "Moogle"})
    chain(con, "a", NPC)
    chain(con, "b", RENUMBERED, at=100)
    chain(con, "e", NPC)
    store.trust(con, [("e", "flagged")])
    put(con, "names", [{"release": "r1", "kind": "zone", "log_id": 0, "id": ZONE, "name": "Lower Jeuno"}])

    (zone,) = ask(con, "npc_zones")
    assert (zone["zone_name"], zone["npcs"], zone["events"], zone["starts"], zone["captures"]) == (
        "Lower Jeuno", 2, 4, 8, 2,
    )  # fmt: skip
    got = {(r["who"], r["npc_name"], r["event_id"]): r for r in ask(con, "npc_zone", zone=ZONE)}
    assert list(got) == [
        ("zone-in", "", 5),
        ("npc", "Guard", 12),
        ("npc", "Moogle", 10),
        ("npc", "Moogle", 11),
    ]
    moogle = got["npc", "Moogle", 10]
    ids = [{"npc_id": NPC, "release": "r1"}, {"npc_id": RENUMBERED, "release": "r2"}]
    assert (moogle["n"], moogle["captures"], moogle["ids"]) == (2, 2, ids)
    assert [(x["v"], x["k"]) for x in moogle["params"]] == [([1, 2, 0, 0, 0, 0, 0, 0], 2)]
    assert [(x["v"], x["k"]) for x in moogle["options"]] == [([2, 5], 2)]
    assert [(x["v"], x["k"]) for x in moogle["followed_by"]] == [(11, 2)]
    assert moogle["params"][0]["seen"] == {"capture_id": "b", "ts_ms": 1100}, "the latest capture, and when"
