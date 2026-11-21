from ffxi_extractors.extract import COARSE, ONE, Column, Derived, Table

SQL = f"""
SELECT a.capture_id AS capture_id, a.idx AS idx, a.ts_ms AS ts_ms, a.client_version AS client_version,
  c.start_ms AS start_ms, c.character AS character, c.release AS release, a.action_id AS action_id,
  a.actor_id AS actor_id, a.ready_ms AS ready_ms, k.coarse AS coarse
FROM (SELECT * FROM actions WHERE {ONE} AND category = 11 AND NOT resend) a
JOIN (SELECT capture_id, start_ms, character, release FROM captures WHERE {ONE}) c
  ON c.capture_id = a.capture_id
JOIN {COARSE} k ON k.capture_id = a.capture_id
"""


class TpUses(Derived):
    name = "tp_uses"
    version = 2  # 2: ready_ms, coarse
    doc = "Each TP move, newest capture first, for Search."
    reads = frozenset({"decode", "actions"})
    # Search lists hits newest capture first: in this order it reads the first page and stops.
    order = "-start_ms, capture_id, idx"
    sql = SQL
    tables = (
        Table(
            "tp_uses",
            "One row per TP move (actions, category 11, resends skipped), with its capture's start, recorder,"
            " and release, sorted newest capture first so Search reads a page of hits without the rest.",
            (
                Column("start_ms", None, "The capture's first packet, Unix ms UTC."),
                Column("character", None, "The recording character."),
                Column("release", None, "The capture's release, for names."),
                Column("action_id", None, "The move."),
                Column("actor_id", None, "Who used it."),
                Column("ready_ms", None, "ms from its start (actions.ready_ms); None when they do not pair."),
                Column(
                    "coarse",
                    None,
                    "Whether the capture's times are whole seconds, so ready_ms is good only to a second.",
                ),
            ),
        ),
    )
