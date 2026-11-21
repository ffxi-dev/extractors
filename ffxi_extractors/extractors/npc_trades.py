from ..extract import ONE, Column, Derived, Table

# Each capture's trades folded by NPC, what was handed over, and how the NPC answered.
# fmt: off
SQL = f"""
SELECT f.capture_id AS capture_id, f.first_idx AS idx, f.first_ts AS ts_ms,
  f.client_version AS client_version, c.release AS release, f.zone_id AS zone_id, f.npc_id AS npc_id,
  nm.name AS npc_name, f.item_ids AS item_ids, f.quantities AS quantities, f.gil AS gil,
  f.event_id AS event_id, f.message AS message, f.n AS n
FROM (
  SELECT capture_id, client_version, zone_id, npc_id, item_ids, quantities, gil, event_id, message,
    min(idx) AS first_idx, min(ts_ms) AS first_ts, count() AS n
  FROM trades WHERE {ONE} GROUP BY ALL
) f
LEFT JOIN (SELECT capture_id, release FROM captures WHERE {ONE}) c ON c.capture_id = f.capture_id
LEFT JOIN (SELECT capture_id, entity_id, any(entity_name) AS name
  FROM capture_entities(capture = {{capture:String}})
  WHERE entity_name IS NOT NULL GROUP BY capture_id, entity_id) nm
  ON nm.capture_id = f.capture_id AND nm.entity_id = f.npc_id
"""
# fmt: on


class NpcTrades(Derived):
    name = "npc_trades"
    version = 1
    doc = "Each capture's trades to NPCs folded by NPC, items, and the NPC's answer."
    reads = frozenset({"decode", "trades", "entity_changes"})
    order = "zone_id, npc_name"  # the NPC catalog reads a zone's rows
    sql = SQL
    tables = (
        Table(
            "npc_trades",
            "One row per capture, NPC, items and gil handed over, and answer: the trades (trades) that share"
            " them, counted. The NPC catalog sums them across captures.",
            (
                Column("release", None, "The capture's release: the client version its ids are from."),
                Column("zone_id", None, "The zone."),
                Column("npc_id", None, "The NPC traded to."),
                Column("npc_name", None, "The NPC's name, as capture_entities names it."),
                Column("item_ids", None, "The items handed over, as trades keeps them."),
                Column("quantities", None, "How many of each."),
                Column("gil", None, "The gil handed over."),
                Column("event_id", None, "The event the NPC answered with: onTrade's startEvent."),
                Column("message", None, "The NPC's first message after, when it sent one."),
                Column("n", None, "How many trades these are."),
            ),
        ),
    )
