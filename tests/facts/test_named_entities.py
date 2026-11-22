from conftest import rows
from fill import put

from ffxi_extractors.index import run

ZONE = 100
MOB, NPC = (0x01000000 | (ZONE << 12) | i for i in (0x010, 0x020))
CHANGES = (("a", 1, MOB, "GoblinNeckch"), ("a", 2, NPC, None), ("a", 3, MOB, None), ("b", 1, NPC, "Porter"))


def test_named_entities_keeps_the_views_rows(con):
    """One capture's rows are capture_entities', the client's spelling of a squashed name among them."""
    put(con, "captures", [{"capture_id": c, "client_version": "v", "release": "r", "retail": True,
                           "packets": 1} for c in "ab"])  # fmt: skip
    put(con, "names", [{"release": "r", "kind": "entity", "log_id": 0, "id": MOB,
                        "name": "Goblin Neckchopper"}])  # fmt: skip
    put(con, "entity_changes", [{"capture_id": c, "idx": i, "ts_ms": i, "entity_id": e, "name": n,
                                 "model_id": 7, "x": 1.5} for c, i, e, n in CHANGES])  # fmt: skip
    run(con, None, "a", units={"named_entities"})
    cols = "capture_id, entity_id, idx, ts_ms, packet_name, entity_name, model_id, monster, x, y, z, release"
    got = rows(con, f"SELECT {cols}, client_version FROM named_entities")
    view = rows(con, f"SELECT {cols} FROM capture_entities(capture = 'a') ORDER BY entity_id, idx")
    assert got == [(*r, "v") for r in view]
    assert [(r[1], r[2], r[5]) for r in got] == [
        (MOB, 1, "Goblin Neckchopper"),
        (MOB, 3, "Goblin Neckchopper"),
        (NPC, 2, None),
    ]
