from ffxi_extractors.extract import ONE, Column, Derived, Table

# What a capture showed, for Scholar's capture points (vault's openspec/changes/add-capture-points): one row
# per thing, keyed as a first is, and per fight one row per thin-fact sample. A mob counts only when the
# capture fought, checked, or widescanned it, so walking past one counts nothing. An NPC is a named entity
# under index 0x700, a mob one under 0x400 (above them are pets, trusts, and players' dynamic entities).
FIRSTS = f"""
SELECT capture_id, idx, ts_ms, client_version, 'zone' AS kind, zone_id, '' AS subject, toInt64(0) AS thing,
  toUInt64(0) AS fight_key, toUInt64(1) AS n
FROM zones WHERE {ONE} AND zone_id IS NOT NULL
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, if(monster, 'mob', 'npc'),
  toInt32(intDiv(entity_id, 4096) % 4096), entity_name, 0, 0, 1
FROM named_entities
WHERE {ONE} AND entity_id BETWEEN 0x1000000 AND 0x1FFFFFF AND entity_name != ''
  AND if(monster, entity_id % 4096 < 0x400 AND (capture_id, entity_id) IN (
      SELECT capture_id, mob_id FROM bestiary_fights WHERE {ONE}
      UNION ALL SELECT capture_id, entity_id FROM levels WHERE {ONE}),
    entity_id % 4096 < 0x700)
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'drop', zone_id, mob_name, d.item, 0, 1
FROM bestiary_fights ARRAY JOIN drops AS d WHERE {ONE} AND d.item > 0
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'tp', zone_id, mob_name, t.id, 0, 1
FROM bestiary_fights ARRAY JOIN tp AS t WHERE {ONE} AND t.id IS NOT NULL
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'spell', zone_id, mob_name, s, 0, 1
FROM bestiary_fights ARRAY JOIN arrayConcat(spells, idle_spells) AS s WHERE {ONE} AND s IS NOT NULL
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'recipe', crystal_id, toString(ingredients), r, 0, 1
FROM recipes ARRAY JOIN [nq_item_id, hq1_item_id, hq2_item_id, hq3_item_id] AS r WHERE {ONE} AND r > 0
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'shop', zone_id, concat(npc_name, '|', kind), item_id, 0, 1
FROM npc_shops WHERE {ONE} AND npc_name != ''
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'fish', zone_id, '', item_id, 0, 1
FROM fishing WHERE {ONE} AND outcome = 'caught' AND item_id > 0
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'steal', zone_id, mob_name, item_id, 0, 1
FROM steals WHERE {ONE} AND success AND item_id > 0
"""
# A fight without a key is never merged with another capture's, so its own packet keys it.
FIGHT = "coalesce(fight_key, cityHash64(capture_id, idx))"
SAMPLES = f"""
SELECT capture_id, idx, ts_ms, client_version, 'kill' AS kind, zone_id, mob_name AS subject,
  toInt64(0) AS thing, {FIGHT} AS fight_key, toUInt64(1) AS n
FROM bestiary_fights WHERE {ONE} AND outcome = 'defeated' AND claimed
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'rounds', zone_id, mob_name, 0, {FIGHT}, length(rounds)
FROM bestiary_fights WHERE {ONE} AND notEmpty(rounds)
UNION ALL
SELECT capture_id, idx, ts_ms, client_version, 'tp_ready', zone_id, mob_name, t.id, {FIGHT}, 1
FROM bestiary_fights ARRAY JOIN tp AS t
WHERE {ONE} AND t.id IS NOT NULL AND t.ready IS NOT NULL AND NOT coarse
"""
SQL = f"""
SELECT capture_id, min(idx) AS idx, min(ts_ms) AS ts_ms, any(client_version) AS client_version, kind,
  assumeNotNull(zone_id) AS zone_id, assumeNotNull(subject) AS subject, assumeNotNull(thing) AS thing,
  assumeNotNull(fight_key) AS fight_key, sum(n) AS n
FROM ({FIRSTS} UNION ALL {SAMPLES})
WHERE zone_id IS NOT NULL AND subject IS NOT NULL AND thing IS NOT NULL
GROUP BY capture_id, kind, zone_id, subject, thing, fight_key
"""


class CaptureFinds(Derived):
    name = "capture_finds"
    version = 1
    doc = "What each capture showed, one row per thing, and per fight its samples: the capture points' input."
    # drops: bestiary_fights' drops come from it, and Scholar checks a fact reads every table its SQL joins
    reads = frozenset(
        {
            "zones",
            "named_entities",
            "bestiary",
            "drops",
            "levels",
            "recipes",
            "npc_shops",
            "fishing",
            "steals",
        }
    )
    order = "kind, zone_id, subject, thing"  # the points fill reads each kind across every capture
    sql = SQL
    tables = (
        Table(
            "capture_finds",
            "One row per capture and thing it showed, keyed as a capture point's first is: a zone, a mob it"
            " fought, checked, or widescanned, an NPC, a drop, a TP move, a spell, a recipe's result, a shop"
            " item, a catch, or a stolen item. And per fight, the samples a thin fact counts: a claimed kill,"
            " its auto-attack rounds, and each TP move timed to the millisecond. idx and ts_ms are the first"
            " packet that showed it.",
            (
                Column(
                    "kind",
                    None,
                    "zone, mob, npc, drop, tp, spell, recipe, shop, fish, or steal; kill, rounds, or tp_ready"
                    " for a sample.",
                ),
                Column("zone_id", None, "The zone; for a recipe, its crystal."),
                Column(
                    "subject",
                    None,
                    "The mob or NPC as the client spells it, a shop as its NPC and list (name|kind), or a"
                    " recipe's ingredients; '' for a zone or a catch.",
                ),
                Column(
                    "thing", None, "The item, TP move, or spell; 0 for a zone, mob, NPC, kill, or rounds."
                ),
                Column(
                    "fight_key",
                    None,
                    "For a sample, its fight as bestiary_fights keys it, so a party's copies count once; 0"
                    " otherwise.",
                ),
                Column(
                    "n", None, "How many: a fight's rounds, a capture's catches of an item, else sightings."
                ),
            ),
        ),
    )
