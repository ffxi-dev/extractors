from ffxi_extractors.extract import MATERIALIZE, NAMES, ONE, Column, Derived, Table

# A spell learned names no mob: retail sends it a few ms after the defeat of a mob that used the move in the
# recorder's sight. Its mob is the defeat just before it, under 60 s; its move, the TP move that mob used in
# the fight that defeat ended whose name is the spell's. On prod, before this unit, every one of 67 learns in
# 13 captures came 0 to 33 ms after a defeat, and one of that fight's moves bore the spell's name.
SQL = f"""
WITH
m AS MATERIALIZED (SELECT * FROM mob_messages WHERE {ONE}),
kl AS (SELECT capture_id, idx, ts_ms, mob_id FROM kills WHERE {ONE}),
lm AS MATERIALIZED (
  SELECT l.capture_id AS capture_id, l.idx AS idx, l.spell_id AS spell_id, k.mob_id AS mob_id,
    k.idx AS kill_idx
  FROM (SELECT * FROM m WHERE kind = 'learned') l
  ASOF JOIN kl k ON k.capture_id = l.capture_id AND k.idx <= l.idx
  WHERE l.ts_ms - k.ts_ms < 60000
),
mv AS (
  SELECT l.capture_id AS capture_id, l.idx AS idx, a.action_id AS move
  FROM lm l
  JOIN (SELECT capture_id, mob_id, idx, end_idx FROM fights WHERE {ONE}) f
    ON f.capture_id = l.capture_id AND f.mob_id = l.mob_id AND f.end_idx = l.kill_idx
  JOIN (SELECT capture_id, idx, actor_id, action_id FROM actions
    WHERE {ONE} AND category = 11 AND NOT resend) a
    ON a.capture_id = l.capture_id AND a.actor_id = l.mob_id AND a.idx BETWEEN f.idx AND f.end_idx
),
rl AS (SELECT capture_id, release FROM captures WHERE {ONE}),
tie AS (
  SELECT v.capture_id AS capture_id, v.idx AS idx, min(v.move) AS skill_id
  FROM mv v
  JOIN lm l ON l.capture_id = v.capture_id AND l.idx = v.idx
  JOIN rl ON rl.capture_id = v.capture_id
  JOIN spell_names s ON s.release = rl.release AND s.id = l.spell_id
  JOIN mob_skill_names k ON k.release = rl.release AND k.id = v.move
  WHERE squash(s.name) = squash(k.name)
  GROUP BY v.capture_id, v.idx
),
e AS (
  SELECT m.capture_id AS capture_id, m.idx AS idx, m.ts_ms AS ts_ms, m.client_version AS client_version,
    m.kind AS kind, m.player_id AS player_id, coalesce(m.mob_id, lm.mob_id) AS mob, m.zone_id AS zone_id,
    m.distance AS distance, m.spell_id AS spell_id, tie.skill_id AS skill_id
  FROM m
  LEFT JOIN lm ON lm.capture_id = m.capture_id AND lm.idx = m.idx
  LEFT JOIN tie ON tie.capture_id = m.capture_id AND tie.idx = m.idx
)
SELECT e.capture_id AS capture_id, e.idx AS idx, e.ts_ms AS ts_ms, e.client_version AS client_version,
  e.kind AS kind, e.player_id AS player_id, e.mob AS mob_id, n.entity_name AS mob_name, e.zone_id AS zone_id,
  e.distance AS distance, e.spell_id AS spell_id, e.skill_id AS skill_id
FROM e
ASOF LEFT JOIN {NAMES} n
  ON n.capture_id = e.capture_id AND n.entity_id = e.mob AND n.idx <= e.idx
{MATERIALIZE}
"""


class MobEvents(Derived):
    name = "mob_events"
    version = 2  # 2: mob_messages 3, its draw-ins by engaged monsters only
    doc = "Each draw-in and blue magic spell learned, with its mob named as the bestiary names it."
    reads = frozenset({"decode", "mob_messages", "kills", "fights", "actions", "entity_changes"})
    order = "zone_id, mob_name, ts_ms"  # a mob page reads its mob's rows
    sql = SQL
    tables = (
        Table(
            "mob_events",
            "One row per mob_messages row, with its mob: for a draw-in the engaged monster nearest where"
            " the player landed; for a spell learned the defeat just before it, under 60 s. Party copies are"
            " in each recorder's capture.",
            (
                Column("kind", None, "drawn_in or learned."),
                Column("player_id", None, "The player drawn in, or who learned the spell."),
                Column("mob_id", None, "The mob; none when the packets do not tell."),
                Column("mob_name", None, "The mob's name as the client spells it, as the bestiary's."),
                Column("zone_id", None, "The zone."),
                Column("distance", None, "For a draw-in: yalms from where the player landed to the mob."),
                Column("spell_id", None, "For a spell learned: the spell."),
                Column(
                    "skill_id",
                    None,
                    "For a spell learned: the TP move the mob used in the fight whose name is the spell's.",
                ),
            ),
        ),
    )
