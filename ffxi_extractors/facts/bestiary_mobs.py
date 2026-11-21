from ffxi_extractors.extract import LENS, ONE, Column, Derived, Table

FLAGGED = "(SELECT capture_id FROM capture_trust FINAL WHERE trust = 'flagged')"
MOVE = "{move:UInt32}"  # tp_move_figures' parameter: 0 for every move
# Of the copies of a fight that Flagged captures leave, the capture with the lowest id counts it. Arrival
# order would differ between parallel workers, a rerun, and a rebuild; the lowest id does not.
OWNERS = (
    "SELECT fight_key, min(capture_id) AS owner FROM bestiary_fights WHERE capture_id NOT IN "
    + FLAGGED
    + " AND fight_key IN (SELECT fight_key FROM bestiary_fights WHERE "
    + ONE
    + ") GROUP BY fight_key"
)

# The mob pages' figures over a capture's bestiary_fights (every capture's when it is ''), one row per zone,
# mob, model, and capture: each a ClickHouse aggregate state, which a page merges over every capture. A fight
# another capture counts (kept false) adds only to accuracy, since each recorder's swings at itself are its
# own. A median keeps each value with its count, which repeats enough to stay small: a mob page takes the
# exact median from them, with reach rounded to 0.01 yalm and respawn to 0.1 s.
# fmt: off
SQL = f"""
SELECT zone_id, mob_name, model, capture_id, now64(9) AS at,
  countIfState(kept) AS fights, countIfState(kept AND won) AS defeated,
  minState(level) AS level_lo, maxState(level) AS level_hi,
  sumIfState(length(delays), kept) AS delay_n,
  quantilesExactWeightedInterpolatedArrayIfState(0.25, 0.5, 0.75)(delays, arrayMap(x -> 1, delays), kept)
    AS delay_q,
  sumMapIfState(arrayMap(x -> round(assumeNotNull(x) / 5) * 5, delays), arrayMap(x -> toUInt64(1), delays),
    kept) AS delay_bins,
  -- The same for a mob that attacks with TP moves, from captures with millisecond times.
  sumIfState(length(skill_delays), timed) AS skill_delay_n,
  quantilesExactWeightedInterpolatedArrayIfState(0.25, 0.5, 0.75)(skill_delays,
    arrayMap(x -> 1, skill_delays), timed) AS skill_delay_q,
  sumMapIfState(arrayMap(x -> round(x / 5) * 5, skill_delays), arrayMap(x -> toUInt64(1), skill_delays),
    timed) AS skill_delay_bins,
  sumMapIfState(arrayMap(g -> floor(assumeNotNull(g) * 240 / 21 / 10) * 10, tp_gains),
    arrayMap(g -> toUInt64(1), tp_gains), kept) AS gain_bins,
  sumMapIfState(arrayMap(g -> round(assumeNotNull(g) * 240 / 21 / 5) * 5, tp_gains),
    arrayMap(g -> toUInt64(1), tp_gains), kept) AS gain_hist,
  sumIfState(length(rounds), kept) AS round_n,
  sumIfState(arraySum(r -> coalesce(r.off_hand, 0), rounds), kept) AS off_hands,
  sumIfState(arraySum(r -> coalesce(r.kicks, 0), rounds), kept) AS kick_n,
  sumMapIfState(arrayMap(r -> assumeNotNull(r.main_hand), rounds), arrayMap(r -> toUInt64(1), rounds), kept)
    AS main_hands,
  sumState(arraySum(r -> coalesce(r.passed, 0), swings_at_recorder)) AS passed,
  sumState(arraySum(r -> coalesce(r.missed, 0), swings_at_recorder)) AS missed,
  sumState(arraySum(r -> coalesce(r.hits, 0), swings_at_recorder)) AS hit_n,
  minArrayState(arrayMap(r -> if(r.corr, 4 * greatest(0, r.lo - r.clv), NULL), swings_at_recorder)) AS lmin,
  maxArrayState(arrayMap(r -> if(r.corr, 4 * greatest(0, r.hi - r.clv), NULL), swings_at_recorder)) AS lmax,
  maxArrayState(arrayMap(r -> r.corr, swings_at_recorder)) AS corrected,
  maxArrayState(arrayMap(r -> r.corr AND (r.lo IS NULL OR r.clv IS NULL), swings_at_recorder))
    AS level_unknown,
  sumState(length(swings_at_recorder)) AS swung,
  countArrayState(arrayMap(r -> r.eva, swings_at_recorder)) AS eva_seen,
  minArrayState(arrayMap(r -> r.eva, swings_at_recorder)) AS eva_min,
  maxArrayState(arrayMap(r -> r.eva, swings_at_recorder)) AS eva_max,
  countArrayState(arrayMap(r -> r.eva_floor, swings_at_recorder)) AS floor_seen,
  minArrayState(arrayMap(r -> r.eva_floor, swings_at_recorder)) AS floor_min,
  sumMapIfState(ids, arrayMap(u -> toUInt64(1), tp), arrayMap(u -> toUInt64(coalesce(u.hit, 0)), tp),
    arrayMap(u -> toUInt64(coalesce(u.crit, 0)), tp), arrayMap(u -> toUInt64(u.reach IS NOT NULL), tp),
    arrayMap(u -> toUInt64(coalesce(u.kb, 0) > 0), tp), kept) AS moves,
  maxMapIfState(mapFromArrays(ids, arrayMap(u -> u.targets, tp)), kept) AS move_targets,
  maxMapIfState(mapFromArrays(ids, arrayMap(u -> u.reach, tp)), kept) AS move_reach,
  sumMapIfState(arrayMap(u -> (assumeNotNull(u.id), round(assumeNotNull(u.reach), 2)), reached),
    arrayMap(u -> toUInt64(1), reached), kept) AS move_reaches,
  maxMapIfState(mapFromArrays(ids, arrayMap(u -> u.spread, tp)), kept) AS move_spread,
  maxMapIfState(mapFromArrays(ids, arrayMap(u -> u.kb, tp)), kept) AS move_kb,
  -- Per move, each ready time to 10 ms with its count, from captures with millisecond times; the uses from
  -- whole-second captures are only counted.
  sumMapIfState(arrayMap(u -> (assumeNotNull(u.id), round(assumeNotNull(u.ready), -1)), readied),
    arrayMap(u -> toUInt64(1), readied), kept AND NOT coalesce(coarse, false)) AS move_ready,
  sumMapIfState(arrayMap(u -> assumeNotNull(u.id), readied), arrayMap(u -> toUInt64(1), readied),
    kept AND coalesce(coarse, false)) AS move_ready_coarse,
  -- Per move, each count of shadows it took and whether that take left the recorder some, and the uses that
  -- landed on the recorder through its shadows: wiping them, and leaving them.
  sumMapIfState(arrayMap(u -> (assumeNotNull(u.id), toInt64(assumeNotNull(u.shadows)),
    toUInt8(coalesce(u.shadow_exact, false))), absorbed), arrayMap(u -> toUInt64(1), absorbed), kept)
    AS move_shadows,
  sumMapIfState(arrayMap(u -> assumeNotNull(u.id), pierced), arrayMap(u -> toUInt64(u.through), pierced),
    arrayMap(u -> toUInt64(NOT u.through), pierced), kept) AS move_through,
  -- Per move, how far its first target stood from the mob, to 0.1 yalm, with how many uses: the distance
  -- it is used from, apart from its area's range.
  sumMapIfState(firsts, arrayMap(x -> toUInt64(1), firsts), kept) AS move_distances,
  sumMapIfState(arrayMap(x -> assumeNotNull(x), spells), arrayMap(x -> toUInt64(1), spells), kept) AS casts,
  sumMapIfState(arrayMap(x -> assumeNotNull(x), idle_spells), arrayMap(x -> toUInt64(1), idle_spells), kept)
    AS idle_casts,
  -- Per spell, each cast time to 10 ms with its count, and the shortest wait between two casts, with how many
  -- waits; from captures with millisecond times.
  sumMapIfState(arrayMap(u -> (assumeNotNull(u.id), round(assumeNotNull(u.ready), -1)), cast_timed),
    arrayMap(u -> toUInt64(1), cast_timed), kept AND NOT coalesce(coarse, false)) AS cast_ready,
  minMapIfState(arrayMap(u -> assumeNotNull(u.id), cast_waited),
    arrayMap(u -> assumeNotNull(u.gap), cast_waited), kept AND NOT coalesce(coarse, false)) AS recast,
  sumMapIfState(arrayMap(u -> assumeNotNull(u.id), cast_waited), arrayMap(u -> toUInt64(1), cast_waited),
    kept AND NOT coalesce(coarse, false)) AS recast_n,
  sumMapIfState(arrayMap(x -> assumeNotNull(x.spell), taken), arrayMap(x -> toUInt64(1), taken),
    arrayMap(x -> toUInt64(coalesce(x.outcome IN ('resist', 'trait_resist'), 0)), taken),
    arrayMap(x -> toUInt64(coalesce(x.outcome = 'immune', 0)), taken),
    arrayMap(x -> toUInt64(coalesce(x.outcome = 'no_effect', 0)), taken), kept) AS results,
  countIfState(hp_seen) AS hp_n,
  sumMapIfState([coalesce(level, -1)], [toUInt64(1)], hp_seen) AS hp_levels,
  sumMapIfState([(coalesce(level, -1), assumeNotNull(hp_min))], [toUInt64(1)], hp_seen AND hp_min IS NOT NULL)
    AS hp_level_lo,
  sumMapIfState([(coalesce(level, -1), assumeNotNull(hp_max))], [toUInt64(1)], hp_seen AND hp_max IS NOT NULL)
    AS hp_level_hi,
  sumMapIfState([assumeNotNull(mob_id)], [toUInt64(1)], [toUInt64(won)], [toUInt64(respawn_ms IS NOT NULL)],
    kept) AS slot_counts,
  minMapIfState(map(assumeNotNull(mob_id), level), kept) AS slot_lo,
  maxMapIfState(map(assumeNotNull(mob_id), level), kept) AS slot_hi,
  minMapIfState(map(assumeNotNull(mob_id), respawn_ms), kept) AS respawn_least,
  sumMapIfState([(assumeNotNull(mob_id), round(assumeNotNull(respawn_ms), -2))], [toUInt64(1)],
    kept AND respawn_ms IS NOT NULL) AS respawns,
  sumMapIfState([coalesce(th, -1)], [toUInt64(1)], claimed_kill) AS th_kills,
  sumMapIfState(arrayMap(i -> (coalesce(th, -1), i), items), arrayMap(i -> toUInt64(1), items),
    claimed_kill) AS th_items,
  -- Per level and Rare item, the claimed kills the recorder held it at; per level, those its holdings were
  -- unknown at: a Rare item's rate leaves both out.
  sumMapIfState(arrayMap(i -> (coalesce(th, -1), i), held), arrayMap(i -> toUInt64(1), held),
    claimed_kill AND held_known) AS th_held,
  sumMapIfState([coalesce(th, -1)], [toUInt64(1)], claimed_kill AND NOT held_known) AS th_blind,
  -- Per move, the uses that rule out each shape: single, around the mob, around its first target, breath.
  sumMapIfState(ids, arrayMap(u -> toUInt64(u.rules_out[1] > 0), tp),
    arrayMap(u -> toUInt64(u.rules_out[2] > 0), tp), arrayMap(u -> toUInt64(u.rules_out[3] > 0), tp),
    arrayMap(u -> toUInt64(u.rules_out[4] > 0), tp), kept) AS shapes_out,
  -- Per move and shape (move * 4 + shape), the use that rules it out by the widest margin, for its figure.
  groupArraySortedMapIfState(1)(mapFromArrays(arrayMap(p -> p.1, proofs), arrayMap(p -> p.2, proofs)), kept)
    AS shape_proofs,
  -- Per move and centre (move * 2, + 1 for its first target), the two uses that hit farthest from it, and
  -- the party members missed by their distance from it, to 0.1 yalm: the move's range.
  groupArraySortedMapIfState(2)(mapFromArrays(arrayMap(r -> r.1, reaches), arrayMap(r -> r.2, reaches)), kept)
    AS range_uses,
  sumMapIfState(missed, arrayMap(x -> toUInt64(1), missed), kept) AS range_missed,
  -- Per skillchain and closer (a spell or not), how many first skillchains read as each resistance rank, and
  -- their ratios' least and most.
  sumMapIfState(arrayMap(s -> (s.1, s.2, s.4, assumeNotNull(eem_tier(s.3))), scs),
    arrayMap(s -> toUInt64(1), scs), kept) AS sc_tiers,
  minMapIfState(arrayMap(s -> (s.1, s.2, s.4), scs), arrayMap(s -> s.3, scs), kept) AS sc_lo,
  maxMapIfState(arrayMap(s -> (s.1, s.2, s.4), scs), arrayMap(s -> s.3, scs), kept) AS sc_hi
FROM (
  SELECT *, coalesce(model_id, -1) AS model, coalesce(outcome = 'defeated', false) AS won,
    coalesce(capture_id = owner, false) AS kept,
    kept AND NOT coalesce(coarse, false) AS timed,
    kept AND hp_shaky IS NOT NULL AS hp_seen, kept AND won AND coalesce(claimed, false) AS claimed_kill,
    arrayDistinct(arrayMap(x -> toInt64(assumeNotNull(x.item)), arrayFilter(x -> x.item IS NOT NULL, drops)))
      AS items,
    arrayMap(u -> assumeNotNull(u.id), tp) AS ids, arrayFilter(u -> u.reach IS NOT NULL, tp) AS reached,
    arrayFilter(u -> u.ready IS NOT NULL, tp) AS readied,
    arrayFilter(u -> u.shadows IS NOT NULL, tp) AS absorbed,
    arrayFilter(u -> u.through IS NOT NULL, tp) AS pierced,
    arrayFlatten(arrayMap(u -> arrayMap(
      x -> (assumeNotNull(u.id), round(toFloat64(assumeNotNull(x.distance)), 1)),
      arrayFilter(x -> x.hit AND x.distance IS NOT NULL AND coalesce(x.from_target, 1) < 0.05, u.near)),
      tp)) AS firsts,
    arrayFilter(u -> u.ready IS NOT NULL, cast_times) AS cast_timed,
    arrayFilter(u -> coalesce(u.gap > 0, false), cast_times) AS cast_waited,
    arrayFlatten(arrayMap(u -> arrayMap(k -> (assumeNotNull(u.id) * 4 + k - 1,
      (-u.rules_out[k], capture_id, u.idx, u.near)), arrayFilter(k -> u.rules_out[k] > 0, [1, 2, 3, 4])), tp))
      AS proofs,
    -- How far each use hit from the mob and from its first target, the first target left out: a move takes it
    -- wherever it stands.
    arrayFilter(r -> r.2.1 < 0, arrayFlatten(arrayMap(u -> arrayMap(k -> (assumeNotNull(u.id) * 2 + k,
      (-arrayMax(arrayMap(x -> toFloat64(coalesce(if(x.hit AND x.from_target > 0.05,
        if(k = 0, x.distance, x.from_target), 0), 0)), u.near)), capture_id, u.idx, u.near)), [0, 1]), tp)))
      AS reaches,
    arrayFlatten(arrayMap(u -> arrayFlatten(arrayMap(k -> arrayMap(x -> (assumeNotNull(u.id) * 2 + k,
      round(toFloat64(if(k = 0, x.distance, assumeNotNull(x.from_target))), 1)),
      arrayFilter(x -> NOT x.hit AND (k = 0 OR x.from_target IS NOT NULL), u.near)), [0, 1])), tp)) AS missed,
    arrayMap(s -> (assumeNotNull(s.chain), coalesce(s.category = 4, false),
      assumeNotNull(sc_ratio(s.chain, s.closing, s.damage)), coalesce(s.exposed, false)), skillchains) AS scs
  FROM (SELECT * FROM bestiary_fights WHERE {ONE}) b LEFT JOIN ({OWNERS}) o USING (fight_key)
  WHERE mob_name IS NOT NULL
)
GROUP BY zone_id, mob_name, model, capture_id
"""
# fmt: on
# The captures holding a copy of any of these captures' fights.
PARTNERS = (
    "SELECT DISTINCT capture_id FROM bestiary_fights WHERE capture_id NOT IN {c:Array(String)}"
    " AND fight_key IN (SELECT fight_key FROM bestiary_fights WHERE capture_id IN {c:Array(String)})"
)


class BestiaryMobs(Derived):
    name = "bestiary_mobs"
    # 2: party copies by fight_key; 3: HP with regen (hp 3); 4: HP by vote (hp 5); 5: idle_casts;
    # 6: shapes_out and shape_proofs in place of geo_*; 7: sc_tiers, sc_lo, sc_hi; 8: move_ready,
    # move_ready_coarse; 9: range_uses, range_missed; 10: cast_ready, recast, recast_n;
    # 11: th_kills and th_items by bestiary's th; 12: th_held, th_blind; 13: skill_delay_*; 14: move_shadows,
    # move_through; 15: move_distances; 16: no kick_rounds, swing_counts, hp_lo/hi/shakes, respawn_most,
    # spots, or per-level shakes: no page read them
    version = 17
    doc = "Each capture's share of every mob page's figures, as aggregate states the page merges."
    reads = frozenset({"bestiary"})
    order = "zone_id, mob_name, model, capture_id"
    # Writing a capture's rows again (a partner's copy came or went) replaces them: read it with FINAL.
    engine = "ReplacingMergeTree(at)"
    sql = SQL
    tables = (
        Table(
            "bestiary_mobs",
            "One row per zone, mob, model, and capture: the capture's fights summed into aggregate states"
            " (counts, sums, values with their counts for medians, per-move and per-slot maps), so a mob"
            " page merges a row per capture instead of reading every fight. Read a column with its -Merge"
            " function, and FINAL, as the page does. A fight another capture holds a copy of counts in"
            " the capture with the lowest id, Flagged ones left out.",
            (
                Column("zone_id", None, "The zone."),
                Column(
                    "at",
                    None,
                    "When the row was written: of a capture's rows written again, FINAL keeps the last.",
                ),
                Column("model", None, "model_id, or -1: a mob page's card."),
                Column("fights", None, "countIf state: fights."),
                Column(
                    "sc_tiers",
                    None,
                    "Elemental resistance (EEM) from first skillchains (bestiary_fights.skillchains): a map "
                    "from (chain, closed by a spell, exposed, rank in % taken) to how many read so.",
                ),
                Column("sc_lo", None, "The least ratio (sc_ratio) per (chain, closed by a spell, exposed)."),
                Column("sc_hi", None, "The most ratio (sc_ratio) per (chain, closed by a spell, exposed)."),
                Column("defeated", None, "countIf state: defeats."),
            ),
        ),
    )


def partners(con, captures: list[str]) -> list[str]:
    return [c for (c,) in con.query(PARTNERS, parameters={"c": captures}).result_rows] if captures else []


def reroll(con, captures) -> None:
    for c in captures:
        con.command(f"INSERT INTO bestiary_mobs {SQL}", parameters={"capture": c})


# fmt: off
VIEWS = (
    # Every fight as the mob pages count it, for questions of your own: no Flagged capture, kept on the copy
    # the figures count, and copies listing every capture that holds the fight.
    f"""CREATE OR REPLACE VIEW bestiary AS
SELECT * EXCEPT (zone_release, zone, recorder_number, k_owner, k_copies), coalesce(model_id, -1) AS model,
  capture_id = k_owner AS kept, k_copies AS copies,
  coalesce(toString(nullIf(recorder_number, 0)), capture_id) AS recorder_id,
  concat('{LENS}', capture_id, '#packet=', toString(idx)) AS lens_url
FROM (SELECT * FROM bestiary_fights WHERE capture_id NOT IN {FLAGGED}) b
LEFT JOIN (SELECT fight_key, min(capture_id) AS k_owner, arraySort(groupUniqArray(capture_id)) AS k_copies
  FROM bestiary_fights WHERE capture_id NOT IN {FLAGGED} GROUP BY fight_key) k USING (fight_key)
LEFT JOIN (SELECT capture_id, character AS recorder, character_id AS recorder_number,
  start_ms AS capture_start, release FROM captures) cp USING (capture_id)
LEFT JOIN (SELECT release AS zone_release, id AS zone, name AS zone_name FROM zone_names) z
  ON z.zone_release = cp.release AND z.zone = b.zone_id""",
    # Every mob, by zone and name, with its models: the mob list.
    f"""CREATE OR REPLACE VIEW bestiary_list AS
SELECT r.zone_id AS zone, any(z.zone_name) AS zone_name, r.mob_name AS name,
  arraySort(groupUniqArray(r.model)) AS models,
  countIfMerge(r.fights) AS fights, countIfMerge(r.defeated) AS kills, uniqExact(r.capture_id) AS captures,
  minMerge(r.level_lo) AS lo, maxMerge(r.level_hi) AS hi
FROM (SELECT * FROM bestiary_mobs FINAL WHERE capture_id NOT IN {FLAGGED}) r
LEFT JOIN (SELECT id, any(name) AS zone_name FROM zone_names GROUP BY id) z ON z.id = r.zone_id
GROUP BY r.zone_id, r.mob_name HAVING countIfMerge(r.fights) > 0""",
    # Each TP move's figures over every mob that used it, Flagged captures left out: every move's when move is
    # 0, else that one's. The moves list and a move's page each add their own proofs and reach.
    f"""CREATE OR REPLACE VIEW tp_move_figures AS
WITH r AS (SELECT * FROM bestiary_mobs FINAL WHERE capture_id NOT IN {FLAGGED}),
pm AS (SELECT zone_id, mob_name, sumMapIfMerge(moves) AS mv, sumMapIfMerge(shapes_out) AS o FROM r
  GROUP BY zone_id, mob_name),
pu AS (SELECT id, n, hits, crits, kb_uses,
    [o.2[indexOf(o.1, id)], o.3[indexOf(o.1, id)], o.4[indexOf(o.1, id)], o.5[indexOf(o.1, id)]] AS so
  FROM pm ARRAY JOIN mv.1 AS id, mv.2 AS n, mv.3 AS hits, mv.4 AS crits, mv.6 AS kb_uses
  WHERE n > 0 AND ({MOVE} = 0 OR id = {MOVE})),
u AS (SELECT id, sum(n) AS uses, count() AS mobs, sum(hits) AS hits, sum(crits) AS crits,
  sum(kb_uses) AS kb_uses, arrayMap(k -> arraySum(x -> x[k], groupArray(so)), [1, 2, 3, 4]) AS shapes_out
  FROM pu GROUP BY id),
g AS (SELECT maxMapIfMerge(move_kb) AS kb, sumMapIfMerge(move_ready) AS rd,
  sumMapIfMerge(move_ready_coarse) AS rc, groupArraySortedMapIfMerge(2)(range_uses) AS ru,
  sumMapIfMerge(range_missed) AS rm, sumMapIfMerge(move_shadows) AS sd, sumMapIfMerge(move_distances) AS dm,
  sumMapIfMerge(move_through) AS st FROM r),
rq AS (SELECT k.1 AS rid, sum(c) AS ready_n,
  quantilesExactWeightedInterpolated(0.25, 0.5, 0.75)(k.2, c) AS ready_q,
  arraySort(groupArray([k.2, toInt64(c)])) AS ready_v FROM g ARRAY JOIN rd.1 AS k, rd.2 AS c
  WHERE {MOVE} = 0 OR k.1 = {MOVE} GROUP BY rid),
mi AS (SELECT k.1 AS key, arraySort(groupArray([k.2, toFloat64(c)])) AS l
  FROM g ARRAY JOIN rm.1 AS k, rm.2 AS c WHERE {MOVE} = 0 OR intDiv(k.1, 2) = {MOVE} GROUP BY key),
mj AS (SELECT intDiv(key, 2) AS mid, [anyIf(l, key % 2 = 0), anyIf(l, key % 2 = 1)] AS missed
  FROM mi GROUP BY mid),
nm AS (SELECT id AS nid, argMax(name, release) AS name FROM mob_skill_names
  WHERE {MOVE} = 0 OR id = {MOVE} GROUP BY id),
bl AS (SELECT e.skill_id AS bid, any(e.spell_id) AS spell, any(s.name) AS spell_name,
    uniqExact(e.player_id, intDiv(e.ts_ms, 1000)) AS learned
  FROM mob_events e LEFT JOIN (SELECT id, argMax(name, release) AS name FROM spell_names GROUP BY id) s
    ON s.id = e.spell_id
  WHERE e.kind = 'learned' AND e.skill_id IS NOT NULL AND ({MOVE} = 0 OR e.skill_id = {MOVE})
    AND e.capture_id NOT IN {FLAGGED}
  GROUP BY e.skill_id)
SELECT u.id AS id, nm.name AS name, u.uses AS uses, u.mobs AS mobs, u.hits AS hits, u.crits AS crits,
  g.kb[u.id] AS kb, u.kb_uses AS kb_uses, u.shapes_out AS shapes_out,
  arrayMap(k -> g.ru[u.id * 2 + k], [0, 1]) AS reach, coalesce(mj.missed, [[], []]) AS missed,
  rq.ready_n AS ready_n, rq.ready_q AS ready_q, rq.ready_v AS ready_v,
  g.rc.2[indexOf(g.rc.1, u.id)] AS ready_coarse, move_distance(g.dm, u.id) AS distance,
  arrayMap(i -> [g.sd.1[i].2, toInt64(g.sd.1[i].3), toInt64(g.sd.2[i])],
    arrayFilter(i -> g.sd.1[i].1 = u.id, arrayEnumerate(g.sd.1))) AS shadows,
  g.st.2[indexOf(g.st.1, u.id)] AS wiped, g.st.3[indexOf(g.st.1, u.id)] AS ignored,
  if(bl.learned > 0, tuple(bl.spell AS spell, bl.spell_name AS spell_name, bl.learned AS learned), NULL)
    AS blu
FROM u CROSS JOIN g LEFT JOIN rq ON rq.rid = u.id LEFT JOIN mj ON mj.mid = u.id
LEFT JOIN nm ON nm.nid = u.id LEFT JOIN bl ON bl.bid = u.id""",
    # Mobs whose spells finish faster than other mobs' casts of them, by about the same fraction over two or
    # more: they may have Fast Cast. A spell's reference is the median of each mob's median cast time (one
    # vote a mob, so one well-recorded caster doesn't set it), over 5 or more mobs with 3 or more casts each,
    # and 1 s or longer: a shorter one jitters by about its whole cast time. A cast under 30% of the spell's
    # median is Chainspell or a mis-paired start, left out. Most mobs sit at 1.00 +- 0.05 of the reference;
    # a mob passes at a median ratio of 0.88 or less, two thirds of its spells at 0.92 or less, and its
    # spells' middle half within 0.15 of each other, so one fast spell doesn't carry it. ponytail: every
    # spell's reference on each read, 0.4 s today; a table refreshed with the roll-up if that grows.
    f"""CREATE OR REPLACE VIEW fast_cast AS
WITH cr AS (
  SELECT zone_id, mob_name, k.1 AS spell, k.2 AS ms, n FROM (
    SELECT zone_id, mob_name, sumMapIfMerge(cast_ready) AS m FROM bestiary_mobs FINAL
    WHERE capture_id NOT IN {FLAGGED} GROUP BY zone_id, mob_name)
  ARRAY JOIN m.1 AS k, m.2 AS n
),
rough AS (SELECT spell, quantileExactWeighted(0.5)(ms, n) AS r FROM cr GROUP BY spell),
pm AS (
  SELECT zone_id, mob_name, spell, quantileExactWeighted(0.5)(ms, n) AS med, sum(n) AS casts
  FROM cr JOIN rough USING spell WHERE ms >= 0.3 * r GROUP BY zone_id, mob_name, spell HAVING casts >= 3
),
ref AS (
  SELECT spell, quantileExact(0.5)(med) AS ref, count() AS mobs FROM pm GROUP BY spell
  HAVING mobs >= 5 AND ref >= 1000
),
pr AS (SELECT zone_id, mob_name, spell, casts, med / ref AS r FROM pm JOIN ref USING spell)
SELECT zone_id, mob_name, toUInt64(count()) AS spells, sum(casts) AS casts,
  round(quantileExact(0.5)(r), 2) AS ratio, countIf(r <= 0.92) AS fast,
  round(quantileExact(0.75)(r) - quantileExact(0.25)(r), 2) AS spread
FROM pr GROUP BY zone_id, mob_name
HAVING spells >= 2 AND ratio <= 0.88 AND fast * 3 >= spells * 2 AND spread <= 0.15""",
    # Each way the captures saw an item come to hand, a row per kind and place, Flagged captures left out,
    # item 0 for every item. drop: a mob's claimed kills and items per Treasure Hunter level (-1 unknown) from
    # bestiary_mobs, as its card reads them, rows [th, kills, items, kills a Rare item's rate counts], and
    # pool loot from a mob the capture saw no fight with (a party's kill), or whose packet named no dropper
    # (place ''), with no rows; chest: pool loot from a dropper that is no monster seen in its zone (a chest
    # or crate), place its name; steal; dig, rows [weather, weekday, hour]; synth: a recipe (ids: crystal,
    # then ingredients), rows [grade, results]; shop: an NPC's list, rows [price, nation rank, conquest rank];
    # trade: the event that answered a trade (trades' event_idx) and gave it (ids: items handed over, rows
    # [quantities]); event: an NPC's event that gave it, log the quest or mission change it made, a gain
    # nothing else explains (no pool win, synthesis, dig, catch, or purchase of it): a Home Point's menu open
    # when a pool win or a guild purchase landed is no giver; fish: caught with a rod and bait (ids); other:
    # gained, and none of those.
    # An item gained near a synthesis, dig, catch, or purchase of it: within the same 10 s bucket or the one
    # before. ponytail: buckets, not an exact window; an exact one if gains near a bucket's edge go astray.
    """CREATE OR REPLACE VIEW item_sources AS
WITH fl AS (SELECT capture_id FROM capture_trust FINAL WHERE trust = 'flagged'),
  (SELECT groupArray(id) FROM item_rare) AS rares,
bm AS (
  SELECT zone_id, mob_name, model, sumMapIfMerge(th_kills) AS tk, sumMapIfMerge(th_items) AS ti,
    sumMapIfMerge(th_held) AS th_h, sumMapIfMerge(th_blind) AS th_b, uniqExact(capture_id) AS caps
  FROM bestiary_mobs FINAL WHERE capture_id NOT IN fl GROUP BY zone_id, mob_name, model
),
dr AS (
  SELECT 'drop' AS kind, toInt64(it) AS item_id, b.zone_id AS zone_id, b.mob_name AS place,
    toInt64(b.model) AS model,
    CAST([], 'Array(Int64)') AS ids,
    arrayMap((t, k) -> [toInt64(t), toInt64(k), toInt64(b.ti.2[indexOf(b.ti.1, (t, it))]),
      toInt64(k) - if(has(rares, it),
        toInt64(b.th_h.2[indexOf(b.th_h.1, (t, it))] + b.th_b.2[indexOf(b.th_b.1, t)]), 0)],
      b.tk.1, b.tk.2) AS rows,
    '' AS log, toUInt64(arraySum((x, c) -> if(x.2 = it, c, 0), b.ti.1, b.ti.2)) AS n,
      toUInt64(b.caps) AS captures,
    '' AS capture_id, toInt64(0) AS ts_ms
  FROM bm b ARRAY JOIN arrayDistinct(arrayMap(x -> x.2, b.ti.1)) AS it
  WHERE {item:Int64} IN (0, it)
),
pl AS (
  SELECT d.capture_id AS capture_id, d.ts_ms AS ts_ms, toInt64(d.item_id) AS item_id, d.zone_id AS zone_id,
    coalesce(d.mob_id, 0) AS dropper, c.release AS release
  FROM drops d JOIN captures c ON c.capture_id = d.capture_id
  WHERE {item:Int64} IN (0, d.item_id) AND d.capture_id NOT IN fl
    AND (d.capture_id, coalesce(d.mob_id, 0)) NOT IN (SELECT capture_id, mob_id FROM fights
      WHERE capture_id IN (SELECT capture_id FROM drops WHERE {item:Int64} IN (0, item_id)))
),
ch AS (
  SELECT if(unk OR mob, 'drop', 'chest') AS kind, item_id, zone_id, who AS place, toInt64(-1) AS model,
    CAST([], 'Array(Int64)') AS ids,
    CAST([], 'Array(Array(Int64))') AS rows, '' AS log, count() AS n, uniqExact(cid) AS captures,
    argMax(cid, ts) AS capture_id, max(ts) AS ts_ms
  FROM (SELECT p.capture_id AS cid, p.ts_ms AS ts, p.item_id AS item_id, p.zone_id AS zone_id,
      p.dropper = 0 AS unk, if(p.dropper = 0, '', coalesce(cn.name, 'a chest')) AS who,
      (p.zone_id, who) IN (SELECT zone_id, mob_name FROM bestiary_looks) AS mob
    FROM pl p LEFT JOIN (SELECT release, id, any(name) AS name FROM entity_names GROUP BY release, id) cn
      ON cn.release = p.release AND cn.id = p.dropper)
  GROUP BY item_id, zone_id, unk, mob, who
),
st AS (
  SELECT 'steal' AS kind, toInt64(item_id) AS item_id, zone_id, mob_name AS place, toInt64(-1) AS model,
    CAST([], 'Array(Int64)') AS ids, CAST([], 'Array(Array(Int64))') AS rows, ability AS log, count() AS n,
    uniqExact(capture_id) AS captures, argMax(capture_id, ts_ms) AS capture_id, max(ts_ms) AS ts_ms
  FROM steals WHERE success AND item_id IS NOT NULL AND {item:Int64} IN (0, item_id) AND capture_id NOT
    IN fl
  GROUP BY item_id, zone_id, mob_name, ability
),
dg AS (
  SELECT 'dig' AS kind, toInt64(item_id) AS item_id, zone_id, '' AS place, toInt64(-1) AS model,
    CAST([], 'Array(Int64)') AS ids,
    groupArray([toInt64(coalesce(weather_id, -1)), toInt64(coalesce(vana_weekday, -1)),
      toInt64(coalesce(vana_hour, -1))]) AS rows,
    '' AS log, count() AS n, uniqExact(capture_id) AS captures, argMax(capture_id, ts_ms) AS capture_id,
      max(ts_ms) AS ts_ms
  FROM digs WHERE item_id IS NOT NULL AND {item:Int64} IN (0, item_id) AND capture_id NOT IN fl
  GROUP BY item_id, zone_id
),
sy AS (
  SELECT item_id, recipe, grade, count() AS k, uniqExact(capture_id) AS caps,
    argMax(capture_id, ts_ms) AS cap, max(ts_ms) AS last
  FROM (SELECT *, arrayConcat([toInt64(coalesce(crystal_id, 0))], arrayMap(x -> toInt64(x),
    arraySort(ingredients))) AS recipe
    FROM synths WHERE grade >= 0 AND item_id IS NOT NULL AND {item:Int64} IN (0, item_id)
      AND capture_id NOT IN fl)
  GROUP BY item_id, recipe, grade
),
syn AS (
  SELECT 'synth' AS kind, toInt64(item_id) AS item_id, toInt32(-1) AS zone_id, '' AS place,
    toInt64(-1) AS model, recipe AS ids,
    groupArray([toInt64(grade), toInt64(k)]) AS rows, '' AS log, sum(k) AS n, max(caps) AS captures,
    argMax(cap, last) AS capture_id, max(last) AS ts_ms
  FROM sy GROUP BY item_id, recipe
),
sh AS (
  SELECT 'shop' AS kind, toInt64(item_id) AS item_id, zone_id, npc_name AS place, toInt64(-1) AS model,
    CAST([], 'Array(Int64)') AS ids,
    groupUniqArray([price, toInt64(coalesce(nation_rank, -1)), toInt64(coalesce(conquest_rank,
      -1))]) AS rows,
    kind AS log, sum(n) AS n, uniqExact(capture_id) AS captures, argMax(capture_id, last_ts) AS capture_id,
    max(last_ts) AS ts_ms
  FROM npc_shops WHERE kind IN ('shop', 'guild_sells') AND {item:Int64} IN (0, item_id)
    AND capture_id NOT IN fl
  GROUP BY item_id, zone_id, npc_name, kind
),
near AS (
  SELECT DISTINCT capture_id, item_id, b FROM (
    SELECT capture_id, item_id, ts_ms FROM synths WHERE {item:Int64} IN (0, item_id)
    UNION ALL SELECT capture_id, item_id, ts_ms FROM digs WHERE {item:Int64} IN (0, item_id)
    UNION ALL SELECT capture_id, item_id, ts_ms FROM fishing WHERE outcome = 'caught' AND {item:Int64}
      IN (0, item_id)
    UNION ALL SELECT capture_id, item_id, ts_ms FROM shop_actions WHERE coalesce(bought, 0) > 0
      AND {item:Int64} IN (0, item_id)
  ) ARRAY JOIN [intDiv(ts_ms, 10000), intDiv(ts_ms, 10000) + 1] AS b
),
ob AS (
  SELECT o.capture_id AS capture_id, o.idx AS idx, o.ts_ms AS ts_ms, o.item_id AS item_id,
    o.quantity AS quantity, o.zone_id AS zone_id, o.event_idx AS event_idx, o.source AS source
  FROM obtained o LEFT ANTI JOIN near n ON n.capture_id = o.capture_id AND n.item_id = o.item_id
    AND n.b = intDiv(o.ts_ms, 10000)
  WHERE {item:Int64} IN (0, o.item_id) AND o.capture_id NOT IN fl AND coalesce(o.source, '') != 'pool'
),
evs AS (
  SELECT capture_id, idx, npc_id, event_id FROM events
  WHERE kind = 'start' AND (capture_id, idx) IN (SELECT capture_id,
    assumeNotNull(event_idx) FROM ob WHERE event_idx IS NOT NULL)
),
oe AS (
  SELECT o.capture_id AS capture_id, o.idx AS idx, o.ts_ms AS ts_ms, o.item_id AS item_id,
    o.zone_id AS zone_id,
    o.event_idx AS event_idx, e.npc_id AS npc_id, e.event_id AS event_id, c.release AS release
  FROM ob o JOIN evs e ON e.capture_id = o.capture_id AND e.idx = o.event_idx
  JOIN captures c ON c.capture_id = o.capture_id
),
tr AS (
  SELECT capture_id, event_idx, any(item_ids) AS item_ids, any(quantities) AS quantities FROM trades
  WHERE event_idx IS NOT NULL AND (capture_id, event_idx) IN (SELECT capture_id,
    event_idx FROM oe) GROUP BY capture_id, event_idx
),
ot AS (
  SELECT oe.*, t.item_ids AS handed, t.quantities AS handed_n FROM oe
  LEFT JOIN tr t ON t.capture_id = oe.capture_id AND t.event_idx = oe.event_idx
),
lg AS (
  SELECT l.capture_id AS capture_id, l.event_idx AS event_idx,
    any(concat(l.action, ' ', coalesce(q.name, concat(l.area, ' ', toString(l.id))))) AS step
  FROM log_changes l LEFT JOIN (SELECT log, id, any(name) AS name FROM quest_names GROUP BY log, id) q
    ON q.log = l.area AND q.id = l.id
  WHERE (l.capture_id, l.event_idx) IN (SELECT capture_id, event_idx FROM oe) AND l.id IS NOT NULL
  GROUP BY l.capture_id, l.event_idx
),
nm AS (SELECT release, id, any(name) AS name FROM entity_names GROUP BY release, id),
oen AS (
  SELECT ot.capture_id AS cid, ot.idx AS at, ot.ts_ms AS ts, ot.item_id AS iid, ot.zone_id AS zid,
    ot.event_id AS eid,
    ot.handed AS handed, ot.handed_n AS handed_n, coalesce(nm.name, concat('NPC ',
      toString(ot.npc_id))) AS npc,
    coalesce(lg.step, '') AS step FROM ot
  LEFT JOIN nm ON nm.release = ot.release AND nm.id = ot.npc_id
  LEFT JOIN lg ON lg.capture_id = ot.capture_id AND lg.event_idx = ot.event_idx
),
trd AS (
  SELECT 'trade' AS kind, toInt64(iid) AS item_id, zid AS zone_id, npc AS place, toInt64(-1) AS model,
    arrayMap(x -> toInt64(x), handed) AS ids, [arrayMap(x -> toInt64(x), handed_n)] AS rows,
      any(step) AS log, count() AS n,
    uniqExact(cid) AS captures, argMax(cid, ts) AS capture_id, max(ts) AS ts_ms
  FROM oen WHERE notEmpty(handed) GROUP BY iid, zid, npc, handed, handed_n
),
evt AS (
  SELECT 'event' AS kind, toInt64(iid) AS item_id, zid AS zone_id, npc AS place, toInt64(eid) AS model,
    CAST([], 'Array(Int64)') AS ids, CAST([], 'Array(Array(Int64))') AS rows, any(step) AS log,
      count() AS n,
    uniqExact(cid) AS captures, argMax(cid, ts) AS capture_id, max(ts) AS ts_ms
  FROM oen WHERE empty(handed) GROUP BY iid, zid, npc, eid
),
fi AS (
  SELECT 'fish' AS kind, toInt64(item_id) AS item_id, zone_id, '' AS place, toInt64(-1) AS model,
    [toInt64(coalesce(rod_id, 0)), toInt64(coalesce(bait_id, 0))] AS ids,
    CAST([], 'Array(Array(Int64))') AS rows, '' AS log,
    count() AS n, uniqExact(capture_id) AS captures, argMax(capture_id, ts_ms) AS capture_id,
      max(ts_ms) AS ts_ms
  FROM fishing WHERE outcome = 'caught' AND item_id IS NOT NULL AND {item:Int64} IN (0, item_id)
    AND capture_id NOT IN fl
  GROUP BY item_id, zone_id, rod_id, bait_id
),
oth AS (
  SELECT 'other' AS kind, toInt64(o.item_id) AS item_id, o.zone_id AS zone_id, '' AS place,
    toInt64(-1) AS model,
    CAST([], 'Array(Int64)') AS ids, CAST([], 'Array(Array(Int64))') AS rows, '' AS log, count() AS n,
    uniqExact(o.capture_id) AS captures, argMax(o.capture_id, o.ts_ms) AS capture_id, max(o.ts_ms) AS ts_ms
  FROM ob o WHERE o.event_idx IS NULL
  GROUP BY o.item_id, o.zone_id
)
SELECT * FROM dr UNION ALL SELECT * FROM ch UNION ALL SELECT * FROM st UNION ALL SELECT * FROM dg
UNION ALL SELECT * FROM syn UNION ALL SELECT * FROM sh UNION ALL SELECT * FROM trd UNION ALL SELECT * FROM evt
UNION ALL SELECT * FROM fi UNION ALL SELECT * FROM oth""",
)
# fmt: on
