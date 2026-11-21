from ..extract import ONE, Column, Derived, Table

KILL_MS = 5000  # the gain's kill: the mob's defeat under this before the gain, which comes in the same ms

SQL = f"""
WITH
g AS (SELECT * FROM exp_gains WHERE {ONE} AND mob_id IS NOT NULL),
kl AS (SELECT capture_id, mob_id, idx, ts_ms FROM kills WHERE {ONE}),
lr AS (SELECT capture_id, entity_id, idx, end_idx, level FROM levels WHERE {ONE}),
cl AS (SELECT capture_id, idx, main_level FROM character WHERE {ONE} AND main_level IS NOT NULL),
x AS (
  SELECT g.capture_id AS capture_id, g.idx AS idx, g.ts_ms AS ts_ms, g.client_version AS client_version,
    g.mob_id AS mob_id, g.zone_id AS zone_id, g.own AS own, g.kind AS kind, g.points AS points,
    g.chain AS chain, g.party_size AS party_size, g.effects AS effects, g.key_items AS key_items,
    if(g.ts_ms - k.ts_ms < {KILL_MS}, k.idx, NULL) AS kill_idx,
    if(l.end_idx IS NULL OR l.end_idx >= coalesce(kill_idx, g.idx), l.level, NULL) AS mob_level,
    c.main_level AS char_level
  FROM g
  ASOF LEFT JOIN kl k ON k.capture_id = g.capture_id AND k.mob_id = g.mob_id AND k.idx <= g.idx
  ASOF LEFT JOIN lr l ON l.capture_id = g.capture_id AND l.entity_id = g.mob_id AND l.idx <= g.idx
  ASOF LEFT JOIN cl c ON c.capture_id = g.capture_id AND c.idx <= g.idx
)
SELECT x.capture_id AS capture_id, x.idx AS idx, x.ts_ms AS ts_ms, x.client_version AS client_version,
  x.mob_id AS mob_id, n.entity_name AS mob_name, x.zone_id AS zone_id, x.kill_idx AS kill_idx,
  x.mob_level AS mob_level, x.char_level AS char_level, x.mob_level - x.char_level AS level_diff,
  x.kind AS kind, x.points AS points, x.chain AS chain, x.party_size AS party_size, x.effects AS effects,
  x.key_items AS key_items,
  x.own AND x.kind = 'exp' AND x.chain = 0 AND x.party_size = 1 AND empty(x.effects) AND empty(x.key_items)
    AND x.kill_idx IS NOT NULL AND x.mob_level IS NOT NULL AND x.char_level IS NOT NULL AS clean
FROM x
ASOF LEFT JOIN (SELECT capture_id, entity_id, idx, entity_name
  FROM capture_entities(capture = {{capture:String}}) WHERE entity_name IS NOT NULL) n
  ON n.capture_id = x.capture_id AND n.entity_id = x.mob_id AND n.idx <= x.idx
WHERE x.own
"""


class ExpKills(Derived):
    name = "exp_kills"
    version = 1
    doc = "Each of the character's point gains from a kill, with the mob's level and its own."
    reads = frozenset({"decode", "experience", "kills", "levels", "character", "entity_changes"})
    order = "zone_id, mob_name, ts_ms"  # a mob page reads its mob's rows
    sql = SQL
    tables = (
        Table(
            "exp_kills",
            "One row per point gain of the character's that names a mob (exp_gains), with the levels LSB's"
            " baseTable is read by.",
            (
                Column("mob_id", None, "The mob."),
                Column("mob_name", None, "The mob's name as the client spells it, as the bestiary's."),
                Column("zone_id", None, "The zone."),
                Column("kill_idx", None, f"The mob's defeat (kills) under {KILL_MS // 1000} s before."),
                Column(
                    "mob_level", None, "The level widescan or /check last gave this life of the mob (levels)."
                ),
                Column("char_level", None, "The character's main level then (character)."),
                Column("level_diff", None, "mob_level - char_level, as LSB's baseTable is keyed."),
                Column("kind", None, "exp, limit, capacity, or exemplar."),
                Column("points", None, "The points."),
                Column("chain", None, "The chain number; 0 for none."),
                Column("party_size", None, "As exp_gains."),
                Column("effects", None, "As exp_gains: the status effects that change the points."),
                Column("key_items", None, "As exp_gains: the key items that raise them."),
                Column(
                    "clean",
                    None,
                    "EXP at chain 0, alone, with no effect or key item that changes it, from a kill seen, and"
                    " both levels known: what baseTable predicts, before the per-monster cap.",
                ),
            ),
        ),
    )
