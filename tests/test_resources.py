from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
from conftest import rows

from ffxi_extractors import resources
from ffxi_extractors.resources import client_day, release_for

KNOWN = ["30260401_0", "30260429_1", "30261006_0"]


def test_client_days():
    assert client_day("30251101_2", None) == date(2025, 11, 1)
    assert client_day("Version 16:42:16 Apr  1 2026", None) == date(2026, 4, 1)  # captain's build
    assert client_day("", 1_528_940_034_000) == date(2018, 6, 14)  # a PacketViewer import: its start


def test_a_folder_that_is_no_release_is_passed_over():
    """A folder in the mirror whose name is no client version raised TypeError for every capture."""
    assert release_for("30261006_0", None, ["30260901_0", "notes"]) == "30260901_0"


def test_a_capture_takes_its_own_release_else_the_nearest_before_else_the_first():
    assert release_for("30261006_0", None, KNOWN) == "30261006_0"
    assert release_for("30260601_0", None, KNOWN) == "30260429_1"
    assert release_for("Version 16:42:16 Apr  1 2026", None, KNOWN) == "30260401_0"
    assert release_for("", 1_528_940_034_000, KNOWN) == "30260401_0", "2018: no release yet, the first"
    assert release_for("30261006_0", None, []) is None


def test_sync_fetches_a_file_an_old_release_lacks(tmp_path, monkeypatch):
    import io
    import json
    import urllib.error

    from ffxi_extractors import resources

    (tmp_path / "30261006_0").mkdir()
    (tmp_path / "30261006_0" / "zones.parquet").write_bytes(b"old")
    served = {"versions.json": json.dumps({"versions": [{"version": "30261006_0"}]}).encode(),
              "versions/30261006_0/mob_skills.parquet": b"new"}  # fmt: skip

    def get(url, timeout):
        path = url.split("/", 3)[3]
        if path not in served:
            raise urllib.error.HTTPError(url, 404, "", None, None)
        return io.BytesIO(served[path])

    monkeypatch.setattr(resources, "_get", get)
    assert resources.sync(tmp_path, base="https://x") == ["30261006_0"]
    assert (tmp_path / "30261006_0" / "mob_skills.parquet").read_bytes() == b"new"
    assert (tmp_path / "30261006_0" / "zones.parquet").read_bytes() == b"old"
    assert resources.sync(tmp_path, base="https://x") == []  # nothing new the second time


def test_sync_fetches_a_file_its_release_rewrote_and_only_once(tmp_path, monkeypatch):
    """retail-resources rewrote keyitems.parquet when it fixed key item ids: the manifest's sha256 changed.
    A manifest that never matches what is served does not count as a change again."""
    import hashlib
    import io
    import json
    import urllib.error

    rel = tmp_path / "30261006_0"
    rel.mkdir()
    (rel / "keyitems.parquet").write_bytes(b"old")
    (rel / "zones.parquet").write_bytes(b"zones")
    files = {"keyitems.parquet": {"sha256": hashlib.sha256(b"fixed").hexdigest()},
             "zones.parquet": {"sha256": "not what is served"}}  # fmt: skip
    v = "versions/30261006_0/"
    served = {"versions.json": json.dumps({"versions": [{"version": "30261006_0"}]}).encode(),
              v + "manifest.json": json.dumps({"files": files}).encode(),
              v + "keyitems.parquet": b"fixed", v + "zones.parquet": b"zones"}  # fmt: skip

    def get(url, timeout):
        path = url.split("/", 3)[3]
        if path not in served:
            raise urllib.error.HTTPError(url, 404, "", None, None)
        return io.BytesIO(served[path])

    monkeypatch.setattr(resources, "_get", get)
    assert resources.sync(tmp_path, base="https://x") == ["30261006_0"]
    assert (rel / "keyitems.parquet").read_bytes() == b"fixed"
    assert resources.sync(tmp_path, base="https://x") == []


def test_names_load_as_each_release_writes_them(con, tmp_path):
    """A struct name gives its english text, a spell its index, a quest its log; a second load replaces."""
    rel = tmp_path / "30261006_0"
    rel.mkdir()
    items = {"id": [20595, 4096], "name": [{"english": "Test Sword"}, {"english": "Fire Crystal"}],
             "flags": [["Rare", "Exclusive"], ["CanSendAccount"]]}  # fmt: skip
    pq.write_table(pa.table(items), rel / "items.parquet")
    pq.write_table(pa.table({"id": [49], "index": [43], "name": ["Protect"]}), rel / "spells.parquet")
    pq.write_table(pa.table({"log_id": [2], "log": ["Windurst"], "id": [5], "name": ["A Quest"]}),
                   rel / "quests.parquet")  # fmt: skip
    resources.load(con, tmp_path)
    resources.load(con, tmp_path)
    assert rows(con, "SELECT release, id, name FROM item_names ORDER BY id") == [
        ("30261006_0", 4096, "Fire Crystal"),
        ("30261006_0", 20595, "Test Sword"),
    ]
    assert rows(con, "SELECT id FROM item_rare") == [(20595,)]
    assert rows(con, "SELECT id, name FROM spell_names") == [(43, "Protect")]
    assert rows(con, "SELECT log_id, log, id, name FROM quest_names") == [(2, "Windurst", 5, "A Quest")]


def test_an_id_a_release_lists_twice_has_one_name(con, tmp_path):
    """Whitegate's entities come from two DATs: a join on its names must not double an event."""
    rel = tmp_path / "30261006_0"
    rel.mkdir()
    ids, names = [16982309, 16982309, 16982171], ["Zasshal", "Zasshal", "Rytaal"]
    pq.write_table(pa.table({"entity_id": ids, "name": names}), rel / "entities.parquet")
    resources.load(con, tmp_path)
    got = rows(con, "SELECT id, name FROM entity_names ORDER BY id")
    assert got == [(16982171, "Rytaal"), (16982309, "Zasshal")]


def test_a_capture_entity_a_release_names_twice_is_one_event_named_as_its_packet_says(con, tmp_path):
    """capture_entities joined each change to every name its id has: an id Whitegate's two DATs both list
    doubled the change (Codex's review, 16). One id can carry two names; the packet's picks between them."""
    from fill import put

    rel = tmp_path / "30261006_0"
    rel.mkdir()
    ids = [16982309, 16982309, 16982310, 16982310]
    names = ["Zasshal", "Zasshal", "Abda-Lurabda", "Taru Guard"]
    pq.write_table(pa.table({"entity_id": ids, "name": names}), rel / "entities.parquet")
    resources.load(con, tmp_path)
    put(con, "captures", [{"capture_id": "w", "client_version": "v", "release": "30261006_0", "retail": True,
                           "packets": 0, "start_ms": 0}])  # fmt: skip
    change = {"capture_id": "w", "ts_ms": 0, "client_version": "v"}
    put(con, "entity_changes", [
        {**change, "idx": 1, "entity_id": 16982309, "name": "Zasshal"},
        {**change, "idx": 2, "entity_id": 16982310, "name": "TaruGuard"},
    ])  # fmt: skip
    got = rows(con, "SELECT idx, entity_name FROM capture_entities(capture = 'w') ORDER BY idx")
    assert got == [(1, "Zasshal"), (2, "Taru Guard")]
