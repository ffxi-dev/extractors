from ..extract import ONE, Column, Derived, Table

# A monster's looks, named as the bestiary names it, with whether the capture's widescan listed it: a mob page
# sums them by zone and name. Widescan lists enemies only (levels): a capture that widescanned the zone and
# never listed a mob it saw says widescan may hide it, or that it stood out of range.
SQL = f"""
WITH
nm AS (SELECT capture_id, entity_id, argMax(entity_name, idx) AS mob_name
  FROM capture_entities(capture = {{capture:String}}) WHERE entity_name IS NOT NULL
  GROUP BY capture_id, entity_id),
ws AS (SELECT capture_id, zone_id, groupUniqArray(entity_id) AS listed FROM levels
  WHERE {ONE} AND source = 'widescan' GROUP BY capture_id, zone_id)
SELECT l.capture_id AS capture_id, l.idx AS idx, l.ts_ms AS ts_ms, l.client_version AS client_version,
  l.zone_id AS zone_id, n.mob_name AS mob_name, l.entity_id AS entity_id, l.speed AS speed,
  l.speed_base AS speed_base, l.animation AS animation, l.flags AS flags, l.sub_kind AS sub_kind,
  l.status AS status, l.model_id AS model_id, l.look AS look, l.updates AS updates,
  notEmpty(w.listed) AS scanned, has(w.listed, l.entity_id) AS listed
FROM (SELECT * FROM entity_looks WHERE {ONE} AND has(flags, 'Flags1.MonsterFlag=1')) l
JOIN nm n ON n.capture_id = l.capture_id AND n.entity_id = l.entity_id
LEFT JOIN ws w ON w.capture_id = l.capture_id AND w.zone_id = l.zone_id
"""


class BestiaryLooks(Derived):
    name = "bestiary_looks"
    version = 1
    doc = "Each monster's looks (entity_looks), named as the bestiary names it, for the mob pages."
    reads = frozenset({"looks", "entity_changes", "levels", "decode"})
    order = "zone_id, mob_name, capture_id"  # a mob page reads its mob's rows
    sql = SQL
    tables = (
        Table(
            "bestiary_looks",
            "One row per entity_looks row of a named monster (Flags1.MonsterFlag), so a mob page sums its"
            " speeds, models, and flags over every capture. Party copies are in each recorder's capture.",
            (
                Column("zone_id", None, "The zone."),
                Column("mob_name", None, "The mob's name as the client spells it, as the bestiary's."),
                Column("entity_id", None, "The mob."),
                Column("speed", None, "Speed, as entity_looks."),
                Column("speed_base", None, "SpeedBase, as entity_looks."),
                Column("animation", None, "server_status, as entity_looks."),
                Column("flags", None, "Each flag set, name=value, as entity_looks."),
                Column("sub_kind", None, "SubKind, as entity_looks."),
                Column("status", None, "Status, as entity_looks."),
                Column("model_id", None, "The model, as entity_looks."),
                Column("look", None, "The humanoid look, as entity_looks."),
                Column("updates", None, "Updates that came in this state, as entity_looks."),
                Column("scanned", None, "Whether the capture's widescan listed any enemy in the zone."),
                Column("listed", None, "Whether it listed this mob."),
            ),
        ),
    )
