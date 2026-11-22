import pytest
import xicap
from conftest import CAPTAIN, MEMORIA, rows, value

from ffxi_extractors import store
from ffxi_extractors.decode import DECODER_VERSION
from ffxi_extractors.extractors import ALL
from ffxi_extractors.facts import DERIVED
from ffxi_extractors.index import run, versions

UNITS = {"decode", *(x.name for x in (*ALL, *DERIVED))}


def counts(con, cid=None) -> dict[str, int]:
    """Rows of every table with captures' rows but runs, by table."""
    where = "WHERE capture_id = {c:String}" if cid else ""
    tables = rows(
        con,
        "SELECT t.name FROM system.tables t"
        " JOIN system.columns c ON c.database = t.database AND c.table = t.name"
        " WHERE t.database = currentDatabase() AND t.engine LIKE '%MergeTree' AND c.name = 'capture_id'"
        " AND t.name != 'runs' AND NOT startsWith(t.name, '.')",
    )
    return {t: value(con, f"SELECT count() FROM {t} {where}", {"c": cid} if cid else None) for (t,) in tables}


def test_a_capture_and_its_runs(con):
    got = run(con, MEMORIA, "AIxeAsqgUD5p")
    total = xicap.Reader(str(MEMORIA)).packet_count
    assert value(con, "SELECT packets FROM captures") == total
    assert value(con, "SELECT client_version FROM captures") == "30261006_0"
    assert value(con, "SELECT sum(packets) FROM sizes") == total
    assert set(got) == UNITS
    units = rows(con, "SELECT unit, state, decoder_version FROM runs FINAL ORDER BY unit")
    assert [u[0] for u in units] == sorted(got) and all(u[1] == "done" for u in units)


def test_stubbed_chat_keeps_no_text(con):
    run(con, CAPTAIN, "c")
    # Chat is 0x017: a stubbed packet keeps only its 4-byte header.
    assert rows(con, "SELECT DISTINCT size FROM sizes WHERE direction = 's2c' AND opcode = 23") == [(4,)]


def test_zone_visits_cover_the_capture_from_its_first_zone(con):
    run(con, MEMORIA, "m")
    (first,) = rows(con, "SELECT idx FROM zones")[0]
    assert rows(con, "SELECT idx, zone_id, zoned_in FROM zone_visits") == [(first, 247, True)]


def test_first_ingest_sends_no_delete(con, monkeypatch):
    sent = []
    command = con.command
    monkeypatch.setattr(con, "command", lambda sql, *a, **k: sent.append(sql) or command(sql, *a, **k))
    run(con, MEMORIA, "m")
    assert not [s for s in sent if s.lstrip().upper().startswith("DELETE")]
    run(con, MEMORIA, "m")
    assert [s for s in sent if s.lstrip().upper().startswith("DELETE")], "a rerun clears the first run's rows"


def test_a_delete_clickhouse_lost_is_sent_again(con, monkeypatch):
    """Two DELETEs on a table at once can lose one on ClickHouse 26.8: capture YdhFrV9DRbWo kept two rows in
    captures, and every page query of it failed."""
    run(con, CAPTAIN, "c")
    want = counts(con, "c")
    command, lost = con.command, []

    def lose_first(sql, *a, **k):
        if sql.startswith("DELETE FROM `captures`") and not lost:
            return lost.append(sql)
        return command(sql, *a, **k)

    monkeypatch.setattr(con, "command", lose_first)
    run(con, CAPTAIN, "c")
    assert lost and counts(con, "c") == want


def deletes(con, monkeypatch) -> list[str]:
    """The DELETEs con sends from now on."""
    sent, command = [], con.command
    monkeypatch.setattr(con, "command", lambda sql, *a, **k: sent.append(sql) or command(sql, *a, **k))
    return sent


def deleted(sent) -> list[str]:
    return [s.split("`")[1] for s in sent if s.startswith("DELETE")]


def test_a_unit_whose_last_run_wrote_no_rows_sends_no_delete(con, monkeypatch):
    run(con, CAPTAIN, "c")
    empty = {u for u, n in rows(con, "SELECT unit, rows FROM runs FINAL") if n == 0}
    assert empty, "the captain capture leaves some units without rows"
    want = counts(con, "c")
    sent = deletes(con, monkeypatch)
    run(con, CAPTAIN, "c")
    assert not set(deleted(sent)) & {t for u in empty for t in store.tables_of(u)}
    assert counts(con, "c") == want


def test_begin_many_clears_each_table_once_and_the_runs_send_none(con, monkeypatch):
    run(con, CAPTAIN, "c")
    run(con, MEMORIA, "m")
    store.begin_many(con, {"new": versions()}, DECODER_VERSION, 1)
    assert not rows(con, "SELECT 1 FROM runs WHERE capture_id = 'new'"), "a capture never run is left alone"
    want = counts(con)
    current = versions()
    sent = deletes(con, monkeypatch)
    store.begin_many(con, dict.fromkeys(("c", "m"), current), DECODER_VERSION, 1)
    tables = deleted(sent)
    assert tables and len(tables) == len(set(tables))
    assert all(n == 0 for n in counts(con, "c").values()) and all(n == 0 for n in counts(con, "m").values())
    states = {
        (c, u): (s, n) for c, u, s, n in rows(con, "SELECT capture_id, unit, state, rows FROM runs FINAL")
    }
    assert all(n == 0 for _, n in states.values()), "every unit as having no rows yet"
    assert states["c", "decode"] == ("attempting", 0)
    sent.clear()
    run(con, CAPTAIN, "c")
    run(con, MEMORIA, "m")
    assert not deleted(sent)
    assert counts(con) == want


def test_a_run_stopped_after_begin_many_is_cleared_by_the_next(con, monkeypatch):
    """begin_many records each attempt as having written nothing; the capture's own begin takes that back
    before it writes, so a run that stops partway leaves rows the next begin_many deletes."""
    run(con, CAPTAIN, "c")
    want = counts(con, "c")
    store.begin_many(con, {"c": versions()}, DECODER_VERSION, 1)
    insert = store.insert

    def stop(c, table, data):
        insert(c, table, data)
        if table == "action_results":
            raise Lost

    monkeypatch.setattr(store, "insert", stop)
    with pytest.raises(Lost):
        run(con, CAPTAIN, "c")
    monkeypatch.setattr(store, "insert", insert)
    store.begin_many(con, {"c": versions()}, DECODER_VERSION, 1)
    run(con, CAPTAIN, "c")
    assert counts(con, "c") == want


def test_indexing_again_replaces(con):
    run(con, CAPTAIN, "c")
    before = counts(con)
    run(con, CAPTAIN, "c")
    assert counts(con) == before
    assert value(con, "SELECT count() FROM runs FINAL") == len(UNITS)


class Lost(Exception):
    pass


@pytest.mark.parametrize("after", [False, True], ids=["crash between tables", "lost acknowledgement"])
def test_a_rerun_after_a_stop_counts_every_row_once(con, monkeypatch, after):
    """actions writes three tables. Stop after its first insert, with the insert landed or not: the run stays
    attempting, so the next run does it again, and the rerun's delete keeps every count single."""
    run(con, CAPTAIN, "c")
    want = counts(con, "c")
    store.drop(con, "c")
    insert = store.insert

    def stop(c, table, data):
        if table == "action_results":
            if after:
                insert(c, table, data)
            raise Lost
        insert(c, table, data)

    monkeypatch.setattr(store, "insert", stop)
    with pytest.raises(Lost):
        run(con, CAPTAIN, "c")
    assert store.runs(con, "c")[("c", "actions")][2] == "attempting"
    monkeypatch.setattr(store, "insert", insert)
    run(con, CAPTAIN, "c")
    assert counts(con, "c") == want


def test_a_failed_unit_keeps_no_rows_of_the_run_it_failed_in(con, monkeypatch):
    """store.fail after a stop mid-write: the unit's partial rows go, and its run says failed."""
    insert = store.insert

    def stop(c, table, data):
        if table == "action_results":
            raise Lost
        insert(c, table, data)

    monkeypatch.setattr(store, "insert", stop)
    started = 1
    with pytest.raises(Lost):
        run(con, CAPTAIN, "c")
    store.fail(con, "c", {"actions": "5"}, "d", "Lost", started)
    assert counts(con, "c").get("actions", 0) == 0
    assert store.runs(con, "c")[("c", "actions")][2] == "failed"


def test_one_unit_only(con):
    run(con, MEMORIA, "m")
    before = dict(rows(con, "SELECT unit, finished_ms FROM runs FINAL"))
    run(con, MEMORIA, "m", units={"zones"})
    after = dict(rows(con, "SELECT unit, finished_ms FROM runs FINAL"))
    assert {u for u in before if before[u] != after[u]} == {"zones"}


def test_a_derived_unit_alone_reads_no_file(con):
    run(con, CAPTAIN, "c")
    want = value(con, "SELECT count() FROM bestiary_fights")
    assert run(con, None, "c", units={"bestiary"}) == {"bestiary": want}
    assert value(con, "SELECT count() FROM bestiary_fights") == want


def test_kills_alone_equal_a_full_run(con):
    run(con, CAPTAIN, "c")
    full = rows(con, "SELECT * EXCEPT lens_url FROM kills ORDER BY idx, mob_id")
    run(con, CAPTAIN, "c", units={"kills"})
    assert rows(con, "SELECT * EXCEPT lens_url FROM kills ORDER BY idx, mob_id") == full


def test_a_table_made_under_another_order_is_sorted_again_with_its_rows(con):
    """entity_changes was sorted by entity first, so each capture's lookup read every capture's rows: setup
    copies a table made under another ORDER BY into one sorted as the code says, rows and all, once."""
    con.command("DROP TABLE IF EXISTS sorting_probe SYNC")
    con.command("CREATE TABLE sorting_probe (a String, b Int64) ENGINE = MergeTree ORDER BY (b, a)")
    con.command("INSERT INTO sorting_probe VALUES ('x', 2), ('y', 1)")
    for _ in range(2):  # the second call finds it sorted and leaves it
        store._create(con, "sorting_probe", "a String, b Int64", "a, b")
        key = "SELECT sorting_key FROM system.tables WHERE name = 'sorting_probe'"
        assert value(con, key) == "a, b"
        assert rows(con, "SELECT a, b FROM sorting_probe ORDER BY a") == [("x", 2), ("y", 1)]
    leftovers = (
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name LIKE 'sorting_probe_%'"
    )
    assert value(con, leftovers) == 0
    con.command("DROP TABLE sorting_probe SYNC")
