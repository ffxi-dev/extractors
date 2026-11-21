from ..extract import ONE, Column, Derived, Table

# One row per melee swing (action_results of category 1), with who swung and, at the recorder, the recorder's
# stats from its last status update (0x061) before the swing.
SQL = f"""
WITH
c AS (SELECT capture_id, character_id FROM captures WHERE {ONE}),
ent AS (SELECT capture_id, entity_id, idx, entity_name FROM capture_entities(capture = {{capture:String}})
  WHERE entity_name IS NOT NULL),
lv AS (SELECT capture_id, entity_id, idx, end_idx, level FROM levels WHERE {ONE}),
st AS (SELECT capture_id, idx, main_job, main_level, defense, vit + coalesce(vit_bonus, 0) AS vit
  FROM character WHERE {ONE}),
a AS (SELECT capture_id, idx, zone_id, actor_is_mob FROM actions WHERE {ONE} AND category = 1 AND NOT resend)
SELECT r.capture_id AS capture_id, r.idx AS idx, r.ts_ms AS ts_ms, r.client_version AS client_version,
  a.zone_id AS zone_id, r.actor_id AS attacker_id, n.entity_name AS attacker_name,
  a.actor_is_mob AS attacker_is_mob,
  if(l.end_idx IS NULL OR r.idx <= l.end_idx, l.level, NULL) AS attacker_level, r.target_id AS target_id,
  r.target_id = c.character_id AS target_is_recorder, if(target_is_recorder, s.main_job, NULL) AS target_job,
  if(target_is_recorder, s.main_level, NULL) AS target_level,
  if(target_is_recorder, s.defense, NULL) AS target_defense,
  if(target_is_recorder, s.vit, NULL) AS target_vit, r.result_index AS swing, r.sub_kind AS hand,
  r.message AS outcome, r.value AS damage, r.message = 67 AS crit
FROM (SELECT * FROM action_results WHERE {ONE} AND category = 1) r
JOIN a ON a.capture_id = r.capture_id AND a.idx = r.idx
JOIN c ON c.capture_id = r.capture_id
ASOF LEFT JOIN ent n ON n.capture_id = r.capture_id AND n.entity_id = r.actor_id AND n.idx <= r.idx
ASOF LEFT JOIN lv l ON l.capture_id = r.capture_id AND l.entity_id = r.actor_id AND l.idx <= r.idx
ASOF LEFT JOIN st s ON s.capture_id = r.capture_id AND s.idx <= r.idx
"""


class Melee(Derived):
    name = "melee"
    version = 1
    doc = (
        "Each melee swing, with who swung and, at the recorder, the recorder's defence, VIT, and level then."
    )
    reads = frozenset({"decode", "entity_changes", "actions", "levels", "character"})
    order = "attacker_name, zone_id, capture_id, idx"
    sql = SQL
    tables = (
        Table(
            "melee",
            "One row per melee swing (action_results, category 1, resends skipped). A swing at the recorder"
            " carries the recorder's stats from its last status update (0x061) before it; before any, they"
            " are empty. Damage is base times pDIF, and pDIF follows attack over defence, so a mob's top"
            " non-crit hits by target_defense bound its attack.",
            (
                Column("zone_id", None, "The zone the character was in."),
                Column("attacker_id", None, "Who swung."),
                Column("attacker_name", None, "Its name as the client spells it."),
                Column("attacker_is_mob", None, "Whether it is one of the zone's own mobs."),
                Column("attacker_level", None, "The level widescan or /check last gave this life of it."),
                Column("target_id", None, "Who it swung at."),
                Column("target_is_recorder", None, "Whether that is the recording character."),
                Column("target_job", None, "The recorder's main job, at the recorder."),
                Column("target_level", None, "The recorder's main job level."),
                Column("target_defense", None, "The recorder's defence (0x061 statusdata.def)."),
                Column("target_vit", None, "The recorder's VIT, base plus bonus."),
                Column("swing", None, "The swing's place in the round, from 0."),
                Column("hand", None, "sub_kind: 0 main hand, 1 off hand, 2 and 3 kicks."),
                Column("outcome", None, "The result's message: 1 a hit, 67 a crit, 15 a miss, ..."),
                Column("damage", None, "The damage, for a hit."),
                Column("crit", None, "Whether it was a critical hit (message 67)."),
            ),
        ),
    )
