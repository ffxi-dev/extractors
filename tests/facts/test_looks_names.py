from conftest import rows
from fill import put

from ffxi_extractors.index import run

MOB = 0x01000000 | (100 << 12) | 0x010


def test_a_reused_id_names_each_look_by_its_own_mob(con):
    """A zone may hand one id to another mob: every look took the capture's last name for the id."""
    put(con, "captures", [{"capture_id": "a", "client_version": "v", "retail": True, "packets": 1}])
    put(con, "entity_changes", [{"capture_id": "a", "idx": i, "ts_ms": i, "entity_id": MOB, "name": n}
                                for i, n in ((1, "Goblin Smithy"), (5, "Goblin Tinkerer"))])  # fmt: skip
    put(con, "entity_looks", [{"capture_id": "a", "idx": i, "ts_ms": i, "entity_id": MOB, "zone_id": 100,
                               "flags": ["Flags1.MonsterFlag=1"]} for i in (2, 6)])  # fmt: skip
    run(con, None, "a", units={"bestiary_looks"})
    got = rows(con, "SELECT idx, mob_name FROM bestiary_looks ORDER BY idx")
    assert got == [(2, "Goblin Smithy"), (6, "Goblin Tinkerer")]
