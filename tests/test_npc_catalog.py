"""The NPC catalog: each capture's event starts folded (npc_events), the catalog across captures, and the
timeline's events with their parameters and options."""

from fill import put, records

from ffxi_extractors.index import run

ZONE = 245  # Lower Jeuno
NPC = 0x0100_0000 | (ZONE << 12) | 100
OTHER = NPC + 1


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


def test_starts_fold_by_npc_event_parameters_options_and_what_follows(con):
    capture(con, "a", "r1", {NPC: "Moogle", OTHER: "Guard"})
    chain(con, "a", NPC)
    got = records(con, "SELECT npc_name, event_id, params, options, followed_by, n, idx FROM npc_events"
                       " ORDER BY idx")  # fmt: skip
    assert [tuple(r.values()) for r in got] == [
        ("Moogle", 10, [1, 2, 0, 0, 0, 0, 0, 0], [2, 5], 11, 1, 1),
        ("Moogle", 11, [], [0], None, 1, 6),
        ("Guard", 12, [], [], None, 1, 8),
        (None, 5, [], [], None, 1, 9),
    ]
