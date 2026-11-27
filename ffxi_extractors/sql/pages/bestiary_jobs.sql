-- A mob page's job signs: what the mob did that points to a job, a row per card (model), sign, and what it
-- names, with the jobs that give it at the mob's top level, its count n of its chances, and up to 3 packets.
-- double: rounds whose first swing hit that swung twice (Double Attack), of those rounds; triple: rounds of 3
-- or more swings (Triple Attack); zanshin: a second swing after a missed first, clearly more often than
-- after a hit (Zanshin, the mob card's Possible Zanshin rule); two_hands: rounds with an off-hand swing,
-- fists or two weapons (Martial Arts, Dual Wield); kicks: rounds with a kick (Kick Attacks); guard and
-- counter: swings at it it guarded or countered (Guard, Counter), of the swings at it; resist: a
-- "Resist!" (trait_resist) to a status, of the casts of its spells, jobs none when no job has the trait
-- (gear or the mob's kind); spell: a spell it cast, idle or in a fight, id the spell, jobs those that learn
-- it by its level; fast_cast: the fast_cast view's mob, id the percent faster, n its spells, of its casts;
-- ranged: its ranged attacks (3 or more), n the shots; pet: the entity after it in a capture, named as a
-- mob's wyvern, avatar or elemental, or automaton (status), whose id is a pet's slot, n the captures that saw
-- it; two_hour and ability: a job's two-hour or ability used as a TP move, id the mob skill, which a mob of
-- another job can use too. A double or triple in over 60% of rounds is the mob's kind's attack, no trait.
-- Thresholds: 30 rounds and 3 doubles, 2 triples, 3 kicks at 3%; off hands in half of 20 rounds; 3 guards
-- or counters at 1% of 200 swings at it.
WITH
f AS (SELECT capture_id, idx, end_idx, mob_id, model, level, rounds, first_swings, spells, idle_spells, taken, tp
  FROM bestiary WHERE zone_id = {zone:Int64} AND mob_name = {name:String} AND kept),
lv AS (SELECT model, max(level) AS top FROM f GROUP BY model),
-- Each trait, the status a resist trait guards, and the jobs that hold it from a level (BG Wiki's job
-- traits; blue magic's left out).
tr AS (SELECT * FROM VALUES('sign String, status String, job String, level Int32',
  ('double', '', 'WAR', 25), ('triple', '', 'THF', 55), ('zanshin', '', 'SAM', 20), ('kicks', '', 'MNK', 51),
  ('two_hands', '', 'MNK', 1), ('two_hands', '', 'PUP', 1), ('two_hands', '', 'NIN', 10),
  ('two_hands', '', 'DNC', 20), ('two_hands', '', 'THF', 83), ('fast_cast', '', 'RDM', 15),
  ('guard', '', 'MNK', 1), ('guard', '', 'PUP', 1), ('counter', '', 'MNK', 10),
  ('ranged', '', 'RNG', 1), ('ranged', '', 'COR', 1), ('ranged', '', 'NIN', 1), ('ranged', '', 'THF', 1),
  ('pet', 'wyvern', 'DRG', 1), ('pet', 'avatar', 'SMN', 1), ('pet', 'automaton', 'PUP', 1),
  ('resist', 'sleep', 'PLD', 20), ('resist', 'poison', 'RNG', 20), ('resist', 'paralyze', 'DRK', 20),
  ('resist', 'paralyze', 'COR', 5), ('resist', 'blind', 'SAM', 5), ('resist', 'silence', 'BRD', 5),
  ('resist', 'silence', 'SCH', 10), ('resist', 'petrify', 'RDM', 10), ('resist', 'virus', 'WAR', 5),
  ('resist', 'bind', 'NIN', 10), ('resist', 'gravity', 'THF', 20), ('resist', 'slow', 'BST', 15),
  ('resist', 'slow', 'PUP', 10), ('resist', 'slow', 'SMN', 20), ('resist', 'slow', 'DNC', 20),
  ('resist', 'stun', '', 0))),
mel AS (SELECT model, sum(length(rounds)) AS rn, sum(arrayCount(r -> r.main_hand >= 3, rounds)) AS r3,
    sum(arrayCount(r -> r.off_hand > 0, rounds)) AS r_off, sum(arrayCount(r -> r.kicks > 0, rounds)) AS r_kick,
    sum(arrayCount(x -> NOT x.first_missed, first_swings)) AS hn,
    sum(arrayCount(x -> NOT x.first_missed AND x.main_hand = 2, first_swings)) AS h2,
    sum(arrayCount(x -> x.first_missed, first_swings)) AS mn,
    sum(arrayCount(x -> x.first_missed AND x.main_hand = 2, first_swings)) AS m2
  FROM f GROUP BY model),
-- Swings at it, by anyone but the zone's own mobs.
at AS (SELECT f.model AS model, r.capture_id AS capture_id, r.idx AS idx, r.swings AS swings, r.guarded AS guarded,
    r.countered AS countered
  FROM attack_rounds r JOIN f ON f.capture_id = r.capture_id AND f.mob_id = r.target_id
  WHERE r.capture_id IN (SELECT capture_id FROM f) AND r.idx BETWEEN f.idx AND f.end_idx AND NOT r.actor_is_mob),
dr AS (SELECT model, sum(swings) AS sw, sum(guarded) AS gu, sum(countered) AS co FROM at GROUP BY model),
ms AS (
  SELECT model, 'double' AS sign, h2 AS n, hn AS of FROM mel WHERE hn >= 30 AND h2 >= 3 AND h2 <= 0.6 * hn
  UNION ALL SELECT model, 'triple', r3, rn FROM mel WHERE rn >= 30 AND r3 >= 2 AND r3 <= 0.6 * rn
  UNION ALL SELECT model, 'zanshin', m2, mn FROM mel
    WHERE m2 > 0 AND tupleElement(wilson(m2, mn, 1.96), 'lo') > tupleElement(wilson(h2, hn, 1.96), 'hi')
  UNION ALL SELECT model, 'two_hands', r_off, rn FROM mel WHERE rn >= 20 AND r_off >= 0.5 * rn
  UNION ALL SELECT model, 'kicks', r_kick, rn FROM mel WHERE rn >= 30 AND r_kick >= 3 AND r_kick >= 0.03 * rn
  UNION ALL SELECT model, 'guard', gu, sw FROM dr WHERE sw >= 200 AND gu >= 3 AND gu >= 0.01 * sw
  UNION ALL SELECT model, 'counter', co, sw FROM dr WHERE sw >= 200 AND co >= 3 AND co >= 0.01 * sw),
-- A round as one sign's example: one at a time, kicks before off hands before swings.
ar AS (SELECT f.model AS model, r.capture_id AS capture_id, r.idx AS idx, r.main_hand AS mh, r.off_hand AS oh,
    r.kicks AS k
  FROM attack_rounds r JOIN f ON f.capture_id = r.capture_id AND f.mob_id = r.actor_id
  WHERE r.capture_id IN (SELECT capture_id FROM f) AND r.idx BETWEEN f.idx AND f.end_idx AND r.actor_is_mob
    AND r.targets = 1 AND NOT r.cut_short),
m1 AS (SELECT capture_id, idx, any(miss) != 0 AS missed FROM action_results
  WHERE capture_id IN (SELECT capture_id FROM f) AND (capture_id, idx) IN (SELECT capture_id, idx FROM ar WHERE mh = 2)
    AND category = 1 AND target_index = 0 AND result_index = 0 GROUP BY capture_id, idx),
mp AS (SELECT model, sign, arraySlice(arraySort(x -> cityHash64(x), groupArray(url)), 1, 3) AS proofs FROM (
    SELECT ar.model AS model, multiIf(ar.k > 0, 'kicks', ar.oh > 0, 'two_hands', ar.mh >= 3, 'triple',
        ar.mh = 2 AND m1.missed, 'zanshin', ar.mh = 2, 'double', '') AS sign,
      concat('https://lens.sruon.dev/c/', ar.capture_id, '#packet=', toString(ar.idx)) AS url
    FROM ar LEFT JOIN m1 ON m1.capture_id = ar.capture_id AND m1.idx = ar.idx
    UNION ALL SELECT model, if(countered > 0, 'counter', 'guard'),
      concat('https://lens.sruon.dev/c/', capture_id, '#packet=', toString(idx)) FROM at
    WHERE guarded > 0 OR countered > 0) WHERE sign != ''
  GROUP BY model, sign),
tk AS (SELECT model, multiIf(
      t.spell IN (98, 253, 259, 273, 274, 363, 364, 376, 377, 463, 471, 576, 584, 598, 678), 'sleep',
      t.spell IN (220, 221, 222, 225, 226, 227, 350, 351, 352), 'poison',
      t.spell IN (58, 80, 341, 342, 343, 356), 'paralyze', t.spell IN (254, 276, 347, 348, 349, 361), 'blind',
      t.spell IN (59, 359), 'silence', t.spell IN (255, 365, 575), 'petrify', t.spell IN (588), 'virus',
      t.spell IN (258, 362), 'bind', t.spell IN (216, 217, 366), 'gravity',
      t.spell IN (56, 79, 344, 345, 346, 357, 421, 422, 423), 'slow', t.spell IN (252), 'stun', '') AS status,
    countIf(t.outcome = 'trait_resist') AS n, count() AS of,
    arraySlice(arraySort(x -> cityHash64(x), groupArrayIf(concat('https://lens.sruon.dev/c/', capture_id,
      '#packet=', toString(t.idx)), t.outcome = 'trait_resist')), 1, 3) AS proofs
  FROM f ARRAY JOIN taken AS t GROUP BY model, status HAVING status != '' AND n > 0),
-- Each spell's jobs: the least level any release lists.
sj AS (SELECT id, job, min(level) AS level FROM spell_jobs
  WHERE id IN (SELECT arrayJoin(arrayConcat(spells, idle_spells)) FROM f) GROUP BY id, job),
sp AS (SELECT model, s AS id, count() AS n FROM f ARRAY JOIN arrayConcat(spells, idle_spells) AS s
  WHERE s > 0 GROUP BY model, id),
ca AS (SELECT f.model AS model, a.action_id AS id,
    arraySlice(arraySort(x -> cityHash64(x), groupArray(concat('https://lens.sruon.dev/c/', a.capture_id,
      '#packet=', toString(a.idx)))), 1, 3) AS proofs
  FROM actions a JOIN f ON f.capture_id = a.capture_id AND f.mob_id = a.actor_id
  WHERE a.capture_id IN (SELECT capture_id FROM f) AND a.idx BETWEEN f.idx AND f.end_idx AND a.category = 4
    AND NOT a.resend GROUP BY model, id),
rg AS (SELECT f.model AS model, count() AS n,
    arraySlice(arraySort(x -> cityHash64(x), groupArray(concat('https://lens.sruon.dev/c/', a.capture_id,
      '#packet=', toString(a.idx)))), 1, 3) AS proofs
  FROM actions a JOIN f ON f.capture_id = a.capture_id AND f.mob_id = a.actor_id
  WHERE a.capture_id IN (SELECT capture_id FROM f) AND a.idx BETWEEN f.idx AND f.end_idx AND a.category = 2
    AND NOT a.resend GROUP BY model HAVING n >= 3),
-- A mob's pet holds the next id: Mamool Ja Spearman's is Mamool Ja's Wyvern. A mob named as a pet has none.
pe AS (SELECT f.model AS model, multiIf(e.entity_name ILIKE '%''s %wyvern', 'wyvern',
      e.entity_name ILIKE '%''s %avatar' OR e.entity_name ILIKE '%''s %elemental', 'avatar',
      e.entity_name ILIKE '%''s %automaton', 'automaton', '') AS kind,
    uniqExact(e.capture_id) AS n, uniqExact(f.capture_id) AS of,
    arraySlice(arraySort(x -> cityHash64(x), groupUniqArray(concat('https://lens.sruon.dev/c/', e.capture_id,
      '#packet=', toString(e.first)))), 1, 3) AS proofs
  FROM (SELECT DISTINCT capture_id, mob_id, model FROM f WHERE mob_id IS NOT NULL) f
  JOIN (SELECT capture_id, entity_id, any(entity_name) AS entity_name, min(idx) AS first FROM named_entities
      WHERE capture_id IN (SELECT capture_id FROM f) AND entity_name IS NOT NULL GROUP BY capture_id, entity_id) e
    ON e.capture_id = f.capture_id AND e.entity_id = f.mob_id + 1
  WHERE {name:String} NOT LIKE '%''s %' GROUP BY model, kind HAVING kind != ''),
fcp AS (SELECT model, arraySlice(arraySort(x -> cityHash64(x), groupArray(u)), 1, 3) AS proofs
  FROM ca ARRAY JOIN proofs AS u GROUP BY model),
fc AS (SELECT toInt64(round((1 - ratio) * 100)) AS id, spells, casts FROM fast_cast
  WHERE zone_id = {zone:Int64} AND mob_name = {name:String}),
-- A job's two-hour or ability, by the mob skill ids retail sends for it.
ab AS (SELECT model, t.id AS id, count() AS n,
    arraySlice(arraySort(x -> cityHash64(x), groupArray(concat('https://lens.sruon.dev/c/', capture_id, '#packet=',
      toString(t.idx)))), 1, 3) AS proofs
  FROM f ARRAY JOIN tp AS t WHERE t.id IN (688, 1008, 689, 1010, 2777, 690, 1009, 303, 2020, 691, 1011, 692, 1012,
    693, 1013, 694, 1014, 695, 1015, 740, 1016, 696, 1018, 711, 712, 735, 736, 737, 738, 739, 1019, 730, 1020,
    3175, 731, 2105, 732, 734, 1933, 3481, 1934, 1935, 2710, 1893, 3482, 3479, 697, 698, 699, 700, 701, 702,
    703, 704, 705, 706, 707, 708, 709, 710, 713, 714, 715, 716, 733, 1017)
  GROUP BY model, id),
gated AS (SELECT sign, status, lv.model AS model,
    arraySort(groupArrayIf(job, job != '' AND (lv.top IS NULL OR level <= lv.top))) AS jobs
  FROM tr CROSS JOIN lv GROUP BY sign, status, model)
SELECT * FROM (
SELECT ms.model AS model, ms.sign AS sign, toInt64(0) AS id, '' AS status, g.jobs AS jobs, toInt64(ms.n) AS n,
  toInt64(ms.of) AS of, coalesce(mp.proofs, []) AS proofs
FROM ms JOIN gated g ON g.model = ms.model AND g.sign = ms.sign AND g.status = ''
LEFT JOIN mp ON mp.model = ms.model AND mp.sign = ms.sign
UNION ALL
SELECT rg.model, 'ranged', 0, '', g.jobs, toInt64(rg.n), toInt64(rg.n), rg.proofs
FROM rg JOIN gated g ON g.model = rg.model AND g.sign = 'ranged' AND g.status = ''
UNION ALL
SELECT pe.model, 'pet', 0, pe.kind, g.jobs, toInt64(pe.n), toInt64(pe.of), pe.proofs
FROM pe JOIN gated g ON g.model = pe.model AND g.sign = 'pet' AND g.status = pe.kind
UNION ALL
SELECT tk.model, 'resist', 0, tk.status, g.jobs, toInt64(tk.n), toInt64(tk.of), tk.proofs
FROM tk JOIN gated g ON g.model = tk.model AND g.sign = 'resist' AND g.status = tk.status
UNION ALL
SELECT sp.model, 'spell', sp.id, '', arraySort(groupArrayIf(sj.job, lv.top IS NULL OR sj.level <= lv.top)),
  toInt64(any(sp.n)), toInt64(any(sp.n)), any(coalesce(ca.proofs, []))
FROM sp JOIN sj ON sj.id = sp.id JOIN lv ON lv.model = sp.model
LEFT JOIN ca ON ca.model = sp.model AND ca.id = sp.id
GROUP BY sp.model, sp.id HAVING notEmpty(groupArrayIf(sj.job, lv.top IS NULL OR sj.level <= lv.top))
UNION ALL
SELECT g.model, 'fast_cast', fc.id, '', g.jobs, toInt64(fc.spells), toInt64(fc.casts), coalesce(fcp.proofs, [])
FROM fc CROSS JOIN gated g LEFT JOIN fcp ON fcp.model = g.model WHERE g.sign = 'fast_cast'
UNION ALL
SELECT ab.model, if(ab.id IN (688, 1008, 689, 1010, 2777, 690, 1009, 303, 2020, 691, 1011, 692, 1012, 693, 1013,
    694, 1014, 695, 1015, 740, 1016, 696, 1018, 735, 736, 737, 738, 739, 1019, 730, 1020, 3175, 731, 2105, 732,
    734, 1933, 3481, 1934, 1935, 2710, 1893, 3482, 3479), 'two_hour', 'ability'), ab.id, '',
  [transform(ab.id, [688, 1008, 697, 698, 699, 689, 1010, 2777, 690, 1009, 303, 2020, 700, 701, 702, 703, 704,
    691, 1011, 692, 1012, 693, 1013, 705, 694, 1014, 706, 707, 695, 1015, 708, 709, 740, 1016, 1017, 710, 696,
    1018, 711, 712, 735, 736, 737, 738, 739, 1019, 713, 714, 715, 716, 730, 1020, 3175, 731, 2105, 732, 733, 1893,
    734, 1933, 3481, 1934, 1935, 2710, 3482, 3479],
   ['WAR', 'WAR', 'WAR', 'WAR', 'WAR', 'WHM', 'WHM', 'WHM', 'MNK', 'MNK', 'MNK', 'MNK', 'MNK', 'MNK', 'MNK', 'MNK',
    'MNK', 'BLM', 'BLM', 'RDM', 'RDM', 'THF', 'THF', 'THF', 'PLD', 'PLD', 'PLD', 'PLD', 'DRK', 'DRK', 'DRK', 'DRK',
    'BST', 'BST', 'BST', 'BST', 'BRD', 'BRD', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG', 'RNG',
    'RNG', 'RNG', 'SAM', 'SAM', 'SAM', 'NIN', 'NIN', 'DRG', 'DRG', 'DRG', 'SMN', 'BLU', 'BLU', 'COR', 'PUP', 'DNC',
    'GEO', 'RUN'], '')], toInt64(ab.n), toInt64(ab.n), ab.proofs
FROM ab)
ORDER BY model, sign, id, status
