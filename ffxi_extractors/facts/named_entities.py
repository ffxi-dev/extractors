from ffxi_extractors.extract import ONE, Column, Derived, Table

# capture_entities' rows, kept: a query that reads them by capture_id plans and reads a few hundred
# rows, where the view plans its names lookups again each time, about 25 ms on one capture. The view
# stays, for queries across every capture and for what still reads it.
SQL = f"""
SELECT e.capture_id AS capture_id, e.idx AS idx, e.ts_ms AS ts_ms, c.client_version AS client_version,
  e.entity_id AS entity_id, e.packet_name AS packet_name, e.entity_name AS entity_name,
  e.model_id AS model_id, e.monster AS monster, e.x AS x, e.y AS y, e.z AS z, e.release AS release
FROM capture_entities(capture = {{capture:String}}) e
JOIN (SELECT capture_id, client_version FROM captures WHERE {ONE}) c ON c.capture_id = e.capture_id
"""


class NamedEntities(Derived):
    name = "named_entities"
    version = 1
    doc = "Each entity change with its name as the client spells it: capture_entities, kept per capture."
    reads = frozenset({"decode", "entity_changes"})
    order = "capture_id, entity_id, idx"  # as entity_changes, so a capture's rows come in the view's order
    sql = SQL
    tables = (
        Table(
            "named_entities",
            "One row per entity change (entity_changes), as capture_entities names it. Its names are the"
            " release's as loaded when it ran.",
            (
                Column("entity_id", None, "The entity."),
                Column("packet_name", None, "The name the packet sent, often squashed or cut short."),
                Column("entity_name", None, "The name as the client spells it (capture_entities)."),
                Column("model_id", None, "Its model, when the packet sent one."),
                Column("monster", None, "Whether it is a monster."),
                Column("x", None, "Its position, when the packet sent one."),
                Column("y", None, "Its position."),
                Column("z", None, "Its position."),
                Column("release", None, "The capture's release, whose names these are."),
            ),
        ),
    )
