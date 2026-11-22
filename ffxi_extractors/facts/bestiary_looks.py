from ffxi_extractors.extract import MATERIALIZE, NAMES, ONE, Column, Derived, Table

# A monster's looks, named as the bestiary names it, with whether the capture's widescan listed it: a mob page
# sums them by zone and name. A look takes the name its entity had at that packet, as every fact does, since a
# zone may hand one id to another mob (Limbus, Dynamis); one seen before any name takes its first. Widescan
# lists enemies only (levels): a capture that widescanned the zone and never listed a mob it saw says widescan
# may hide it, or that it stood out of range.
SQL = f"""
WITH
ce AS MATERIALIZED {NAMES},
nm AS (SELECT capture_id, entity_id, argMin(entity_name, idx) AS first_name FROM ce
  GROUP BY capture_id, entity_id),
ws AS (SELECT capture_id, zone_id, groupUniqArray(entity_id) AS listed FROM levels
  WHERE {ONE} AND source = 'widescan' GROUP BY capture_id, zone_id)
SELECT l.capture_id AS capture_id, l.idx AS idx, l.ts_ms AS ts_ms, l.client_version AS client_version,
  l.zone_id AS zone_id, coalesce(a.entity_name, n.first_name) AS mob_name, l.entity_id AS entity_id,
  l.speed AS speed,
  l.speed_base AS speed_base, l.animation AS animation, l.flags AS flags, l.sub_kind AS sub_kind,
  l.status AS status, l.model_id AS model_id, l.look AS look, l.updates AS updates,
  notEmpty(w.listed) AS scanned, has(w.listed, l.entity_id) AS listed
FROM (SELECT * FROM entity_looks WHERE {ONE} AND has(flags, 'Flags1.MonsterFlag=1')) l
JOIN nm n ON n.capture_id = l.capture_id AND n.entity_id = l.entity_id
ASOF LEFT JOIN ce a ON a.capture_id = l.capture_id AND a.entity_id = l.entity_id AND a.idx <= l.idx
LEFT JOIN ws w ON w.capture_id = l.capture_id AND w.zone_id = l.zone_id
{MATERIALIZE}
"""


class BestiaryLooks(Derived):
    name = "bestiary_looks"
    version = 2  # 2: a look takes its entity's name at that packet, not its last
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
