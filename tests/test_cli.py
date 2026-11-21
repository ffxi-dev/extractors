from conftest import CAPTAIN, MEMORIA, SERVER, SESSION, value

from ffxi_extractors import cli


def test_index_writes_every_unit_of_each_capture(con, monkeypatch, capsys):
    monkeypatch.setenv("FFXI_CLICKHOUSE", f"{SERVER}/{SESSION}")
    assert cli.main(["index", "--no-names", str(MEMORIA), str(CAPTAIN)]) == 0
    assert value(con, "SELECT uniqExact(capture_id) FROM runs WHERE state = 'done'") == 2
    assert value(con, "SELECT count() FROM bestiary_fights WHERE capture_id = 'captain'") > 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in out] == ["memoria", "captain"]
