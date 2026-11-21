from ffxi_extractors.extract import ONE, Column, Derived, Table

FLAGGED = "(SELECT capture_id FROM capture_trust FINAL WHERE trust = 'flagged')"
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
