from ffxi_extractors.extract import NAMES, ONE, Column, Derived, Table

# Steal (41), Mug (45), and Despoil (228) come as category 3 actions, their ids as the action packet sends
# them (ability_names lists them 512 on). Category 3 is weapon skills too, so the messages pick them out:
# 125 steals an item, 453 an effect, 133 Petras; 129 mugs gil; 593 to 599 despoil an item and inflict an
# effect; 153 fails to steal (Steal, Despoil); 244 fails to mug.
WON = (125, 129, 133, 453, 593, 594, 595, 596, 597, 598, 599)
# Despoil's effect by message, 593 on: Attack Down, Defense Down, Magic Atk. Down, Magic Def. Down,
# Evasion Down, Accuracy Down, Slow.
DESPOILED = (147, 149, 175, 167, 148, 146, 13)

SQL = f"""
SELECT r.capture_id AS capture_id, r.idx AS idx, r.ts_ms AS ts_ms, r.client_version AS client_version,
  r.actor_id AS actor_id, r.target_id AS target_id, n.entity_name AS mob_name, a.zone_id AS zone_id,
  multiIf(r.action_id = 41, 'steal', r.action_id = 45, 'mug', 'despoil') AS ability,
  r.message IN {WON} AS success,
  if(r.message = 125 OR r.message BETWEEN 593 AND 599, toInt32(r.value), NULL) AS item_id,
  if(r.message = 129, r.value, NULL) AS gil,
  multiIf(r.message = 453, toInt32(r.value), r.message BETWEEN 593 AND 599,
    toInt32({list(DESPOILED)}[r.message - 592]), NULL) AS status_id,
  r.message AS message
FROM (SELECT * FROM action_results WHERE {ONE} AND category = 3 AND action_id IN (41, 45, 228)
  AND message IN {(*WON, 153, 244)}) r
JOIN (SELECT capture_id, idx, zone_id FROM actions WHERE {ONE} AND category = 3 AND NOT resend) a
  ON a.capture_id = r.capture_id AND a.idx = r.idx
ASOF LEFT JOIN {NAMES} n
  ON n.capture_id = r.capture_id AND n.entity_id = r.target_id AND n.idx <= r.idx
"""


class Steals(Derived):
    name = "steals"
    version = 1
    doc = "Each Steal, Mug, and Despoil, by anyone in view, with what it took."
    reads = frozenset({"decode", "actions", "entity_changes"})
    order = "zone_id, mob_name, ts_ms"  # a mob page reads its mob's rows
    sql = SQL
    tables = (
        Table(
            "steals",
            "One row per Steal, Mug, or Despoil result (action_results, category 3, resends skipped), by"
            " anyone in view. Party copies of one steal are in each recorder's capture.",
            (
                Column("actor_id", None, "Who used it."),
                Column("target_id", None, "The mob."),
                Column("mob_name", None, "The mob's name as the client spells it, as the bestiary's."),
                Column("zone_id", None, "The zone."),
                Column("ability", None, "steal, mug, or despoil."),
                Column("success", None, "Whether it took something."),
                Column("item_id", None, "The item stolen or despoiled."),
                Column("gil", None, "The gil mugged."),
                Column(
                    "status_id",
                    None,
                    "The effect: for Steal (453) the one stolen; for Despoil the one it inflicted.",
                ),
                Column(
                    "message",
                    None,
                    "The result's message: 125 item, 453 effect, 133 Petras, 129 gil, 593 to 599 despoiled"
                    " item, 153 or 244 failed.",
                ),
            ),
        ),
    )
