from ffxi_extractors.extract import NPC_NAMES, ONE, Column, Derived, Table

# Each capture's shop lists folded by NPC, list, item, price, and the character's standing: how many openings
# showed it so, and a guild's stock at each.
# fmt: off
SQL = f"""
SELECT f.capture_id AS capture_id, f.first_idx AS idx, f.first_ts AS ts_ms,
  f.client_version AS client_version, c.release AS release, f.zone_id AS zone_id, f.npc_id AS npc_id,
  nm.name AS npc_name, f.kind AS kind, f.item_id AS item_id, f.price AS price, f.nation AS nation,
  f.nation_rank AS nation_rank, f.conquest_rank AS conquest_rank, f.n AS n, f.last_ts AS last_ts,
  f.stocks AS stock
FROM (
  SELECT capture_id, client_version, zone_id, npc_id, kind, item_id, price, nation, nation_rank,
    conquest_rank,
    min(idx) AS first_idx, min(ts_ms) AS first_ts, max(ts_ms) AS last_ts, uniqExact(list_idx) AS n,
    arraySort(t -> t.ts_ms, groupArrayIf((ts_ms, stock, max), stock IS NOT NULL)) AS stocks
  FROM shop_items WHERE {ONE} GROUP BY ALL
) f
LEFT JOIN (SELECT capture_id, release FROM captures WHERE {ONE}) c ON c.capture_id = f.capture_id
LEFT JOIN {NPC_NAMES} nm
  ON nm.capture_id = f.capture_id AND nm.entity_id = f.npc_id
"""
# fmt: on


class NpcShops(Derived):
    name = "npc_shops"
    version = 1
    doc = "Each capture's shop lists folded by NPC, item, price, and standing, with guild stock."
    reads = frozenset({"decode", "shops", "entity_changes"})
    order = "zone_id, npc_name, item_id"  # the NPC catalog reads a zone's rows
    sql = SQL
    tables = (
        Table(
            "npc_shops",
            "One row per capture, shop NPC, list (shop, guild_sells, guild_buys), item, price, and the"
            " character's nation, rank, and conquest standing: how many openings showed it so, and a guild's"
            " stock with the time of each list. The NPC catalog sums them across captures.",
            (
                Column("release", None, "The capture's release: the client version its ids are from."),
                Column("zone_id", None, "The zone."),
                Column("npc_id", None, "The shop's NPC, as shop_items names it."),
                Column("npc_name", None, "The NPC's name, as capture_entities names it."),
                Column("kind", None, "shop, guild_sells, or guild_buys."),
                Column("item_id", None, "The item."),
                Column("price", None, "Its price in gil."),
                Column("nation", None, "The character's nation."),
                Column("nation_rank", None, "The character's rank in its nation."),
                Column("conquest_rank", None, "The character's nation's conquest standing, 1 to 3."),
                Column("n", None, "How many openings of the shop listed it at this price."),
                Column("last_ts", None, "The last of them, Unix ms."),
                Column("stock", None, "A guild's stock and most stock of it at each list, with its time."),
            ),
        ),
    )
