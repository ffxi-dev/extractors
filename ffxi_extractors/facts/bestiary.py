from ffxi_extractors.extract import COARSE, ONE, Column, Derived, Table, ordered
from ffxi_extractors.extractors.world.character import SLOTS

# Treasure Hunter on the recorder's gear, by item id, from the client's item text: "Treasure Hunter"+n.
TH_GEAR = {
    10695: 2, 11149: 1, 14914: 1, 15107: 1, 16480: 1, 20618: 1, 21573: 1, 21574: 2, 21575: 3, 22299: 1,
    23202: 3, 23358: 4, 23537: 4, 23693: 5, 23713: 1, 23717: 2, 23721: 1, 23725: 1, 23729: 1, 24013: 4,
    25679: 1, 26197: 1, 26236: 2, 26986: 2, 26987: 3, 27421: 2, 27422: 3, 27585: 1, 28450: 1,
}  # fmt: skip
# Herculean, Valorous, Odyssean, Chironic, and Merlinic armor, whose augments can add Treasure Hunter: the
# capture keeps no augments, so a fight the recorder wore one in has no known level.
TH_AUGMENTABLE = (
    25640, 25641, 25642, 25643, 25644, 25717, 25718, 25719, 25720, 25840, 25841, 25842, 25843, 25844,
    27138, 27139, 27140, 27141, 27142, 27494, 27495, 27496, 27497, 27498,
)  # fmt: skip
# Trusts on THF or /THF, and the jug pets with the trait, as the packets name them: each brings TH I.
TH_PALS = (
    "Aldo", "Chacharoon", "Fablinix", "Jakoh", "LehkoHabhoka", "Lion", "Maximilian", "NanaaMihgo",
    "RomaaMihgo", "ArkMR", "Maat", "Margret", "ThreestarLynn", "DipperYuly", "FaithfulFalcorr",
)  # fmt: skip
# Abyssea, where atma add it, and Adoulin's areas, where a Kupower can: no known level there.
TH_ZONES = (15, 45, 132, 215, 216, 217, 218, 253, 254, *range(256, 276))

# A spell cast: its id, cast time, and wait since the last (cg).
CAST = ordered("tuple(a.action_id AS id, a.ready_ms AS ready, g.gap AS gap)", "a.idx")

# One row per fight, from the capture view's mobs and tp_geometry queries cut to a fight instead of a capture:
# the rows each figure counts, kept raw (an interval, a round, a swing at the recorder, a TP use), so a mob
# page sums them over every capture as the capture's mob card does over one.
# fmt: off
SQL = f"""
WITH
fs AS (SELECT * FROM fights WHERE {ONE}),
fk AS (SELECT capture_id, mob_id, idx AS fidx, end_idx FROM fs),
ce AS (SELECT capture_id, entity_id, idx, packet_name, entity_name
  FROM capture_entities(capture = {{capture:String}})),
-- The release names a mob by its id from its first sighting, often before the packets send its name.
ent AS (SELECT * FROM ce WHERE packet_name IS NOT NULL),
nm AS (SELECT * FROM ce WHERE entity_name IS NOT NULL),
mdl AS (SELECT capture_id, entity_id, idx, model_id FROM entity_changes WHERE {ONE} AND model_id IS NOT NULL),
lr AS (SELECT capture_id, entity_id, idx, end_idx, level FROM levels WHERE {ONE}),
zs AS (SELECT capture_id, idx, server FROM zones WHERE {ONE}),
-- 0x0C8 lists the whole party and alliance alike to each member: one roster for every copy of a fight.
al AS (SELECT capture_id, idx, arraySort(groupArray(member_id)) AS roster FROM party
  WHERE {ONE} AND list = 'alliance' GROUP BY capture_id, idx),
fx AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.idx AS fidx, n.packet_name AS name,
    r.entity_name AS mob_name, m.model_id AS model_id,
    if(l.end_idx IS NULL OR f.end_idx <= l.end_idx, l.level, NULL) AS level,
    -- One fight seen by several recorders: the same zone, mob, and minute it ended, on the same instance of
    -- the zone. The instance is the zone server, else the alliance roster, else the capture (never merged).
    -- The server comes first: recorders outside the claiming party share it. A capture that starts inside
    -- the zone has no zone change to name the server, and keeps the roster. Neither needs the world, which
    -- most captures do not record: a zone server's address and a player's id each belong to one world.
    cityHash64(f.zone_id, f.mob_id, intDiv(f.end_ms, 60000), multiIf(
      z.server IS NOT NULL, concat('server ', z.server),
      notEmpty(a.roster), concat('roster ', toString(cityHash64(a.roster))),
      concat('capture ', f.capture_id))) AS fight_key
  FROM fs f
  ASOF LEFT JOIN zs z ON z.capture_id = f.capture_id AND z.idx <= f.end_idx
  ASOF LEFT JOIN al a ON a.capture_id = f.capture_id AND a.idx <= f.end_idx
  ASOF LEFT JOIN ent n ON n.capture_id = f.capture_id AND n.entity_id = f.mob_id AND n.idx <= f.end_idx
  ASOF LEFT JOIN nm r ON r.capture_id = f.capture_id AND r.entity_id = f.mob_id AND r.idx <= f.end_idx
  ASOF LEFT JOIN mdl m ON m.capture_id = f.capture_id AND m.entity_id = f.mob_id AND m.idx <= f.end_idx
  ASOF LEFT JOIN lr l ON l.capture_id = f.capture_id AND l.entity_id = f.mob_id AND l.idx <= f.end_idx
),
rounds AS (SELECT * FROM attack_rounds WHERE {ONE}),
d AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx,
    {ordered("r.interval_ms * 60 / 1000", "r.idx")} AS delays
  FROM rounds r
  JOIN fk f ON r.capture_id = f.capture_id AND r.actor_id = f.mob_id AND r.idx BETWEEN f.fidx AND f.end_idx
  WHERE r.interval_ms IS NOT NULL GROUP BY f.capture_id, f.mob_id, f.fidx
),
-- Whether the recorder was SAM, main or sub: its Store TP trait raises the TP it gains when hit (1.13 to 1.32
-- times the gain its attack intervals give), so those gains leave TP delay. Gear and Samurai Roll
-- add Store TP too, which a capture does not say; the mob page flags a TP delay its intervals disagree with.
rj AS (SELECT capture_id, idx, coalesce(main_job, '') = 'SAM' OR coalesce(sub_job, '') = 'SAM' AS sam
  FROM character WHERE {ONE} AND main_job IS NOT NULL),
-- The rounds with a TP gain while the recorder was SAM: the latest status update before each says.
rsam AS (SELECT capture_id, idx FROM (
  SELECT r.capture_id AS capture_id, r.idx AS idx, j.sam AS sam
  FROM (SELECT capture_id, idx FROM rounds WHERE tp_gain IS NOT NULL) r
  ASOF JOIN rj j ON j.capture_id = r.capture_id AND j.idx <= r.idx) WHERE sam),
ar AS (
  SELECT f.mob_id AS mob_id, f.fidx AS fidx, r.* FROM rounds r
  JOIN fk f ON r.capture_id = f.capture_id AND r.actor_id = f.mob_id AND r.idx BETWEEN f.fidx AND f.end_idx
  WHERE r.actor_is_mob AND r.main_hand IS NOT NULL
),
rd AS (
  SELECT capture_id, mob_id, fidx,
    {ordered("tp_gain", "idx", "tp_gain BETWEEN 9 AND 53 AND (capture_id, idx) NOT IN rsam")} AS tp_gains,
    {ordered("tuple(swings AS swings, main_hand AS main_hand, off_hand AS off_hand, kicks AS kicks)", "idx",
             "targets = 1 AND NOT cut_short")} AS rounds
  FROM ar GROUP BY capture_id, mob_id, fidx
),
rr AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx, e.idx AS idx,
    tuple(e.passed AS passed, e.missed AS missed, e.hits AS hits, e.corr AS corr, e.lo AS lo, e.hi AS hi,
      e.clv AS clv, e.eva AS eva, e.eva_floor AS eva_floor) AS v
  FROM round_evasion(capture = {{capture:String}}) e
  JOIN fk f ON e.capture_id = f.capture_id AND e.actor_id = f.mob_id AND e.idx BETWEEN f.fidx AND f.end_idx
),
acc AS (SELECT capture_id, mob_id, fidx, {ordered("v", "idx")} AS swings_at_recorder FROM rr
  GROUP BY capture_id, mob_id, fidx),
results AS (SELECT * FROM action_results WHERE {ONE}),
rs AS (
  SELECT capture_id, idx, max(message IN (185, 264)) AS hit, max(bitAnd(info, 2) != 0) AS crit,
    max(bitShiftRight(scale, 2)) AS kb, nullIf(maxIf(coalesce(value, 0), message = 31), 0) AS shadows
  FROM results WHERE category = 11 GROUP BY capture_id, idx
),
-- The recorder's shadows, by its Copy Image icon: 66 for one, 444 to 446 for two, three, and four or more.
ci AS (
  SELECT capture_id, ts_ms AS on_ms, ended_ms,
    multiIf(status_id = 66, 1, status_id = 444, 2, status_id = 445, 3, 4) AS held,
    leadInFrame(toNullable(ts_ms)) OVER (PARTITION BY capture_id ORDER BY ts_ms
      ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) AS next_on
  FROM effects WHERE {ONE} AND status_id IN (66, 444, 445, 446)
),
-- A TP move on the recorder while it held shadows. A take (message 31) is exact when it left some: the use's
-- most is exact when the recorder's exact take was it. A move
-- that landed instead went through them: it wiped them when the icon left within 1.5 s and none came back
-- within 0.5 s of that, else it left them.
rh AS (
  SELECT r.capture_id AS capture_id, r.idx AS idx,
    max(if(r.message = 31 AND coalesce(r.value, 0) < c.held, r.value, 0)) AS exact_take,
    maxIf(c.ended_ms IS NOT NULL AND c.ended_ms - r.ts_ms <= 1500
      AND (c.next_on IS NULL OR c.next_on > c.ended_ms + 500), coalesce(r.miss, 0) = 0) AS wiped,
    countIf(coalesce(r.miss, 0) = 0) > 0 AS landed
  FROM results r
  JOIN (SELECT capture_id, character_id FROM captures WHERE {ONE}) me
    ON me.capture_id = r.capture_id AND r.target_id = me.character_id
  ASOF JOIN ci c ON c.capture_id = r.capture_id AND c.on_ms < r.ts_ms
  WHERE r.category = 11 AND (c.ended_ms IS NULL OR c.ended_ms > r.ts_ms)
  GROUP BY r.capture_id, r.idx
),
-- A mob's area hits only its target's party and alliance, trusts and pets included: a bystander counts when
-- it is in the recorder's party and the move hit the party. A bystander's position over 5 s old may be of
-- someone gone; a target's is kept at any age, as a position is sent again only when it moves.
x AS (
  SELECT x.*, x.hit OR (x.party AND max(x.hit AND x.party) OVER (PARTITION BY x.capture_id, x.idx)) AS present
  FROM (SELECT * FROM tp_nearby WHERE {ONE}) x
),
nb AS (
  SELECT capture_id, idx,
    {ordered("tuple(distance AS distance, bearing AS bearing, from_target AS from_target, hit AS hit)",
             "(distance, bearing, from_target, hit)")} AS near
  FROM x WHERE present AND (hit OR age_ms <= 5000) GROUP BY capture_id, idx
),
-- How far past the slack positions allow (0.5 yalm, 5°) a use rules out each area: around the mob (a
-- bystander nearer it than a hit), around the first target (nearer that target than a hit, or within 3
-- yalms of it), and breath. A breath takes its first target wherever it stands and the rest only inside its
-- cone ahead: a hit other than the first target behind the mob, or a bystander inside the cone (the other
-- hits' bearing, at least ±20°) nearer than a hit, rules it out. 0 rules nothing out.
-- ponytail: a rear cone (Dark Ixion) reads as no breath.
sh AS (
  SELECT capture_id, idx, near, arrayFilter(x -> x.hit, near) AS h, arrayFilter(x -> NOT x.hit, near) AS m,
    arrayFilter(x -> coalesce(x.from_target, 0) > 0.05, h) AS side,
    arrayMax(arrayMap(x -> x.distance, h)) AS hd,
    arrayMax(arrayMap(x -> coalesce(x.from_target, 0), h)) AS hft,
    greatest(20, arrayMax(arrayMap(x -> abs(coalesce(x.bearing, 0)), side))) AS arc,
    arrayMap(v -> toFloat32(greatest(0, v)), [
      arrayMax(arrayMap(x -> hd - x.distance - 0.5, m)),
      arrayMax(arrayMap(x -> if(x.from_target IS NULL, 0, greatest(hft, 3) - x.from_target - 0.5), m)),
      greatest(
        arrayMax(arrayMap(x -> if(x.bearing IS NULL OR x.distance <= 1, 0, abs(x.bearing) - 90), side)),
        arrayMax(arrayMap(x -> if(x.bearing IS NULL OR x.distance + 0.5 >= hd, 0, arc - abs(x.bearing) - 5),
          m)))
    ]) AS areas
  FROM nb
),
acts AS (SELECT * FROM actions WHERE {ONE} AND NOT resend AND category IN (4, 11)),
-- Each spell a mob finished, with the wait from its previous finish of that spell in the capture to this
-- cast's start (its finish less its cast time): its recast is no longer than the shortest.
cg AS (
  SELECT capture_id, idx, ts_ms - coalesce(ready_ms, 0) - lagInFrame(toNullable(ts_ms)) OVER (
      PARTITION BY capture_id, actor_id, action_id ORDER BY idx ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
    AS gap
  FROM acts WHERE category = 4
),
tp AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx, {ordered(
    "tuple(a.idx AS idx, a.action_id AS id, a.targets AS targets, a.max_range AS reach,"
    " a.max_spread AS spread, a.actor_size AS size, r.hit AS hit, r.crit AS crit, r.kb AS kb,"
    " a.ready_ms AS ready, sh.near AS near,"
    " arrayConcat([toFloat32(greatest(0, a.targets - 1))], coalesce(sh.areas, [0, 0, 0])) AS rules_out,"
    " r.shadows AS shadows, h.exact_take = r.shadows AS shadow_exact,"
    " if(h.landed, h.wiped, NULL) AS through)",
    "a.idx")} AS tp
  FROM acts a
  JOIN fk f ON a.capture_id = f.capture_id AND a.actor_id = f.mob_id AND a.idx BETWEEN f.fidx AND f.end_idx
  LEFT JOIN rs r ON r.capture_id = a.capture_id AND r.idx = a.idx
  LEFT JOIN sh ON sh.capture_id = a.capture_id AND sh.idx = a.idx
  LEFT JOIN rh h ON h.capture_id = a.capture_id AND h.idx = a.idx
  WHERE a.category = 11 GROUP BY f.capture_id, f.mob_id, f.fidx
),
-- A mob that attacks with TP moves sends no "readies" before them: the time between two such moves in a row,
-- with no spell or readied move between, in delay units. Whole-second captures leave it out in bestiary_mobs.
sa AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx, a.idx AS idx, a.ts_ms AS ts_ms,
    a.category = 11 AND a.ready_ms IS NULL AS instant
  FROM acts a
  JOIN fk f ON a.capture_id = f.capture_id AND a.actor_id = f.mob_id AND a.idx BETWEEN f.fidx AND f.end_idx
),
sd AS (
  SELECT capture_id, mob_id, fidx, {ordered("gap * 60 / 1000", "idx", "gap IS NOT NULL")} AS skill_delays
  FROM (
    SELECT *, if(instant AND lagInFrame(instant) OVER w, ts_ms - lagInFrame(ts_ms) OVER w, NULL) AS gap
    FROM sa
    WINDOW w AS (PARTITION BY capture_id, mob_id, fidx ORDER BY idx ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
  ) GROUP BY capture_id, mob_id, fidx
),
c AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx,
    {ordered("a.action_id", "a.idx")} AS spells, {CAST} AS times
  FROM acts a
  JOIN fk f ON a.capture_id = f.capture_id AND a.actor_id = f.mob_id AND a.idx BETWEEN f.fidx AND f.end_idx
  LEFT JOIN cg g ON g.capture_id = a.capture_id AND g.idx = a.idx
  WHERE a.category = 4 GROUP BY f.capture_id, f.mob_id, f.fidx
),
-- Each skillchain on the mob over 12 s after any other on it (the window to go on with a chain, Helix's 2 s
-- included): a chain's first, so two steps long and at a resistance no skillchain lowered. Its damage over
-- the closing damage times the level's multiplier gives the mob's resistance rank (sc_ratio, setup.sql),
-- unless the day or the weather may have moved its damage (exposed: sc_exposed, setup.sql).
-- Under 10 damage the floor alone moves the ratio over 5%, near the gap between ranks: those are left out.
scr AS (
  SELECT r.capture_id AS capture_id, r.idx AS idx, r.target_id AS target_id, r.category AS category,
    r.value AS value, r.proc_kind AS proc_kind, r.proc_value AS proc_value, r.proc_message AS proc_message,
    r.ts_ms - lagInFrame(toNullable(r.ts_ms)) OVER (PARTITION BY r.capture_id, r.target_id ORDER BY r.idx
      ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS gap,
    sc_exposed(r.proc_kind, r.ts_ms, w.weather_id) AS exposed
  FROM (SELECT * FROM results WHERE category IN (3, 4, 11, 13) AND (proc_message BETWEEN 288 AND 302
    OR proc_message BETWEEN 385 AND 399 OR proc_message IN (767, 768))) r
  ASOF LEFT JOIN (SELECT capture_id, idx, weather_id FROM weather WHERE {ONE}) w
    ON w.capture_id = r.capture_id AND w.idx <= r.idx
),
sc AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx, {ordered(
    "tuple(s.idx AS idx, s.proc_kind AS chain, s.category AS category, s.value AS closing,"
    " s.proc_value AS damage, s.exposed AS exposed)", "s.idx")} AS skillchains
  FROM scr s
  JOIN fk f ON s.capture_id = f.capture_id AND s.target_id = f.mob_id AND s.idx BETWEEN f.fidx AND f.end_idx
  WHERE coalesce(s.gap > 12000, true) AND s.value > 0 AND s.proc_value >= 10
    AND (s.proc_message BETWEEN 288 AND 301 OR s.proc_message IN (767, 768))
  GROUP BY f.capture_id, f.mob_id, f.fidx
),
kl AS (SELECT * FROM kills WHERE {ONE}),
-- A mob's casts while it fought no one: since its previous fight or defeat, before this fight. A buff it
-- casts once it has aggroed, before its first action with anyone, counts here too.
-- ponytail: casts after a mob's last fight in a capture, or by a mob never fought, go uncounted; a row per
-- capture and mob would need its own key to count party copies once.
pv AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx,
    greatest(f.prev_end, coalesce(k.idx, toInt64(-1))) AS since
  FROM (SELECT capture_id, mob_id, idx AS fidx, lagInFrame(end_idx, 1, toInt64(-1)) OVER (
      PARTITION BY capture_id, mob_id ORDER BY idx ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS prev_end
    FROM fs) f
  ASOF LEFT JOIN kl k ON k.capture_id = f.capture_id AND k.mob_id = f.mob_id AND k.idx < f.fidx
),
ic AS (
  SELECT p.capture_id AS capture_id, p.mob_id AS mob_id, p.fidx AS fidx,
    {ordered("a.action_id", "a.idx")} AS idle_spells, {CAST} AS times
  FROM acts a
  JOIN pv p ON a.capture_id = p.capture_id AND a.actor_id = p.mob_id AND a.idx > p.since AND a.idx < p.fidx
  LEFT JOIN cg g ON g.capture_id = a.capture_id AND g.idx = a.idx
  WHERE a.category = 4 GROUP BY p.capture_id, p.mob_id, p.fidx
),
s AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx,
    {ordered("tuple(s.spell_id AS spell, s.outcome AS outcome)", "s.idx")} AS taken
  FROM (SELECT * FROM spell_results WHERE {ONE}) s
  JOIN fk f ON s.capture_id = f.capture_id AND s.target_id = f.mob_id AND s.idx BETWEEN f.fidx AND f.end_idx
  GROUP BY f.capture_id, f.mob_id, f.fidx
),
k AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.fidx AS fidx, k.idx AS kill_idx,
    k.ts_ms AS kill_ms, k.claimed_by_party AS claimed_by_party, k.th_level AS th_level
  FROM fk f ASOF JOIN kl k ON k.capture_id = f.capture_id AND k.mob_id = f.mob_id AND k.idx <= f.end_idx
  WHERE k.idx >= f.fidx
),
-- Treasure Hunter on a defeat, where the capture can tell it: the highest level a TH message showed, else the
-- highest any one who acted on it brought, if each one's is known. The recorder's is its THF trait (main or
-- support level) and its gear, capped at 8 on THF and 4 else, known once a zone-in sent every slot it wore. A
-- trust's or pet's is 1 for those in TH_PALS, else 0. A party member's or a stranger's is unknown.
-- ponytail: a THF proc no message showed, and BLU's set spells at 98, are unseen; the latter counts unknown.
ta AS (
  SELECT DISTINCT k.capture_id AS capture_id, k.mob_id AS mob_id, k.fidx AS fidx, r.idx AS idx,
    r.actor_id AS actor
  FROM k JOIN results r ON r.capture_id = k.capture_id AND r.target_id = k.mob_id
    AND r.idx BETWEEN k.fidx AND k.kill_idx
  WHERE r.actor_id != k.mob_id
),
tw AS (
  SELECT a.capture_id AS capture_id, a.mob_id AS mob_id, a.fidx AS fidx, a.idx AS idx, a.actor AS actor,
    c.character_id = a.actor AS me, c.main_job AS mj, c.main_level AS ml, c.sub_job AS sj, c.sub_level AS sl,
    coalesce(z.capture_id, '') != '' AS zoned, n.entity_name AS name
  FROM ta a
  ASOF LEFT JOIN (SELECT capture_id, idx, character_id, main_job, main_level, sub_job, sub_level
    FROM character WHERE {ONE} AND main_job IS NOT NULL) c ON c.capture_id = a.capture_id AND c.idx <= a.idx
  ASOF LEFT JOIN zs z ON z.capture_id = a.capture_id AND z.idx <= a.idx
  ASOF LEFT JOIN nm n ON n.capture_id = a.capture_id AND n.entity_id = a.actor AND n.idx <= a.idx
),
tg AS (
  SELECT w.capture_id AS capture_id, w.idx AS idx,
    sum(transform(g.item_id, {list(TH_GEAR)}, {list(TH_GEAR.values())}, 0)) AS gear,
    max(g.item_id IN {TH_AUGMENTABLE}) AS augmentable
  FROM (SELECT DISTINCT capture_id, idx, slot FROM tw ARRAY JOIN {list(SLOTS)} AS slot WHERE me) w
  ASOF LEFT JOIN (SELECT capture_id, slot, idx, item_id FROM character_gear WHERE {ONE}) g
    ON g.capture_id = w.capture_id AND g.slot = w.slot AND g.idx <= w.idx
  GROUP BY w.capture_id, w.idx
),
te AS (
  SELECT w.capture_id AS capture_id, w.mob_id AS mob_id, w.fidx AS fidx, multiIf(
    w.me AND (NOT w.zoned OR g.augmentable OR (w.mj = 'BLU' AND w.ml >= 98)), NULL,
    w.me, toNullable(toInt64(least(if(w.mj = 'THF', 8, 4), g.gear + multiIf(
      w.mj = 'THF' AND w.ml >= 90, 3, w.mj = 'THF' AND w.ml >= 45, 2, w.mj = 'THF' AND w.ml >= 15, 1,
      w.sj = 'THF' AND w.sl >= 45, 2, w.sj = 'THF' AND w.sl >= 15, 1, 0)))),
    bitShiftRight(w.actor, 24) = 1 AND bitAnd(w.actor, 0xFFF) >= 0x700 AND w.name IS NOT NULL,
      toNullable(toInt64(arrayExists(p -> startsWith(w.name, p), {list(TH_PALS)}))),
    NULL) AS th
  FROM tw w LEFT JOIN tg g ON g.capture_id = w.capture_id AND g.idx = w.idx AND w.me
),
tf AS (
  SELECT capture_id, mob_id, fidx, if(countIf(th IS NULL) > 0, NULL, max(th)) AS th FROM te
  GROUP BY capture_id, mob_id, fidx
),
-- The Rare items the recorder held at each defeat, its bags' slots as they stood then, the Recycle Bin (17)
-- left out: none could drop to a party that held it whole. Known once a zone-in listed the bags (held_known).
-- Only the slots that ever held one count: each defeat takes each such slot's last change before it.
hd AS (SELECT capture_id, idx, container, item_index, item_id FROM holdings WHERE {ONE} AND container != 17),
ho AS (
  SELECT w.capture_id AS capture_id, w.mob_id AS mob_id, w.fidx AS fidx, h.item_id AS item
  FROM (
    SELECT k.capture_id AS capture_id, k.mob_id AS mob_id, k.fidx AS fidx, k.kill_idx AS kill_idx,
      s.container AS container, s.item_index AS item_index
    FROM k JOIN (SELECT DISTINCT capture_id, container, item_index FROM hd
                 WHERE item_id IN (SELECT id FROM item_rare)) s ON s.capture_id = k.capture_id
  ) w
  ASOF JOIN hd h ON h.capture_id = w.capture_id AND h.container = w.container AND h.item_index = w.item_index
    AND h.idx <= w.kill_idx
),
hh AS (
  SELECT capture_id, mob_id, fidx, arraySort(groupUniqArrayIf(assumeNotNull(item),
    item IN (SELECT id FROM item_rare))) AS held
  FROM ho GROUP BY capture_id, mob_id, fidx
),
-- A pool entry belongs to the mob's last defeat under 60 s before it (the README's drop rate rule).
dr AS (
  SELECT capture_id, mob_id, fidx,
    {ordered("tuple(item_id AS item, slot AS slot, start_time AS start_time, idx AS idx)",
             "(idx, slot)")} AS drops
  FROM (
    SELECT DISTINCT k.capture_id AS capture_id, k.mob_id AS mob_id, k.fidx AS fidx, d.item_id AS item_id,
      d.slot AS slot, d.start_time AS start_time, d.idx AS idx
    FROM (SELECT * FROM drops WHERE {ONE}) d
    ASOF JOIN kl ON kl.capture_id = d.capture_id AND kl.mob_id = d.mob_id AND kl.ts_ms <= d.ts_ms
    JOIN k ON k.capture_id = kl.capture_id AND k.mob_id = kl.mob_id AND k.kill_idx = kl.idx
    WHERE d.ts_ms - kl.ts_ms < 60000
  ) GROUP BY capture_id, mob_id, fidx
),
sp AS (SELECT * FROM spawns WHERE {ONE} AND kind = 'spawned' AND since_defeat_ms IS NOT NULL),
-- The mob's next appearance alive, if it was this defeat's.
rp AS (
  SELECT f.capture_id AS capture_id, f.mob_id AS mob_id, f.idx AS fidx, s.since_defeat_ms AS since_defeat_ms,
    s.x AS x, s.y AS y, s.z AS z, s.idx AS idx
  FROM fs f ASOF JOIN sp s ON s.capture_id = f.capture_id AND s.entity_id = f.mob_id AND s.idx > f.end_idx
  WHERE f.outcome = 'defeated' AND abs(s.ts_ms - s.since_defeat_ms - f.end_ms) < 5000
)
SELECT f.capture_id AS capture_id, f.idx AS idx, f.ts_ms AS ts_ms, f.client_version AS client_version,
  f.end_idx AS end_idx, f.end_ms AS end_ms, f.mob_id AS mob_id, f.zone_id AS zone_id, fx.name AS name,
  fx.mob_name AS mob_name, fx.model_id AS model_id, fx.level AS level, f.outcome AS outcome,
  fx.fight_key AS fight_key,
  f.actions AS actions, ck.coarse AS coarse,
  k.claimed_by_party AS claimed, k.th_level AS th_level,
  coalesce(k.th_level, if(f.zone_id IN {TH_ZONES}, NULL, t.th)) AS th,
  coalesce(hh.held, []) AS held, coalesce(hz.capture_id, '') != '' AS held_known,
  h.hp_min AS hp_min, h.hp_max AS hp_max, h.contradictions > 0 AS hp_shaky,
  h.regen AS hp_regen, h.regen_rate AS hp_regen_rate, h.healing AS hp_healing,
  d.delays AS delays, rd.tp_gains AS tp_gains, rd.rounds AS rounds,
  acc.swings_at_recorder AS swings_at_recorder,
  tp.tp AS tp, coalesce(sd.skill_delays, []) AS skill_delays,
  c.spells AS spells, ic.idle_spells AS idle_spells,
  arrayConcat(ic.times, c.times) AS cast_times,
  s.taken AS taken, dr.drops AS drops,
  sc.skillchains AS skillchains,
  rp.since_defeat_ms AS respawn_ms, rp.x AS respawn_x, rp.y AS respawn_y, rp.z AS respawn_z,
  rp.idx AS respawn_idx
FROM fs f
JOIN fx ON fx.capture_id = f.capture_id AND fx.mob_id = f.mob_id AND fx.fidx = f.idx
LEFT JOIN {COARSE} ck ON ck.capture_id = f.capture_id
LEFT JOIN (SELECT * FROM mob_hp WHERE {ONE}) h
  ON h.capture_id = f.capture_id AND h.mob_id = f.mob_id AND h.idx = f.end_idx
LEFT JOIN d ON d.capture_id = f.capture_id AND d.mob_id = f.mob_id AND d.fidx = f.idx
LEFT JOIN rd ON rd.capture_id = f.capture_id AND rd.mob_id = f.mob_id AND rd.fidx = f.idx
LEFT JOIN acc ON acc.capture_id = f.capture_id AND acc.mob_id = f.mob_id AND acc.fidx = f.idx
LEFT JOIN tp ON tp.capture_id = f.capture_id AND tp.mob_id = f.mob_id AND tp.fidx = f.idx
LEFT JOIN sd ON sd.capture_id = f.capture_id AND sd.mob_id = f.mob_id AND sd.fidx = f.idx
LEFT JOIN c ON c.capture_id = f.capture_id AND c.mob_id = f.mob_id AND c.fidx = f.idx
LEFT JOIN ic ON ic.capture_id = f.capture_id AND ic.mob_id = f.mob_id AND ic.fidx = f.idx
LEFT JOIN s ON s.capture_id = f.capture_id AND s.mob_id = f.mob_id AND s.fidx = f.idx
LEFT JOIN k ON k.capture_id = f.capture_id AND k.mob_id = f.mob_id AND k.fidx = f.idx
LEFT JOIN tf t ON t.capture_id = f.capture_id AND t.mob_id = f.mob_id AND t.fidx = f.idx
LEFT JOIN hh ON hh.capture_id = f.capture_id AND hh.mob_id = f.mob_id AND hh.fidx = f.idx
ASOF LEFT JOIN zs hz ON hz.capture_id = f.capture_id AND hz.idx <= f.end_idx
LEFT JOIN dr ON dr.capture_id = f.capture_id AND dr.mob_id = f.mob_id AND dr.fidx = f.idx
LEFT JOIN sc ON sc.capture_id = f.capture_id AND sc.mob_id = f.mob_id AND sc.fidx = f.idx
LEFT JOIN rp ON rp.capture_id = f.capture_id AND rp.mob_id = f.mob_id AND rp.fidx = f.idx
"""
# fmt: on


class Bestiary(Derived):
    name = "bestiary"
    # 2: ClickHouse, evasion skill, mob_name; 3: sorted by time; 4: mob_name by id; 5: fight_key; 6: regen;
    # 7: hp v4; 8: hp v5; 9: idle_spells; 10: party bystanders under 5 s, rules_out; 11: targets at any age;
    # 12: skillchains; 13: tp ready, coarse; 14: cast_times; 15: th; 16: held, held_known; 17: skill_delays;
    # 18: tp shadows; 19: skillchains apart by capture; 20: skillchains exposed to the day or weather;
    # 21: no tp_gains while the recorder was SAM, main or sub; 22: the instance is the zone server first;
    # 23: no world in fight_key
    version = 23
    doc = (
        "One row of facts per fight, from the combat, mob, and loot tables, for the mob pages: HP, delay, TP"
        " moves, spells, drops, and elemental resistance (EEM) from skillchains."
    )
    reads = frozenset(
        {"decode", "entity_changes", "fights", "delay", "actions", "immunity", "hp", "levels", "character",
         "evasion_skill", "kills", "drops", "spawns", "zones", "party", "holdings", "effects", "weather"}
    )  # fmt: skip
    order = "zone_id, mob_name, ts_ms"  # a mob page reads its latest fights and stops
    sql = SQL
    tables = (
        Table(
            "bestiary_fights",
            "One row per fight in fights, with what the mob card counts from it, so a mob page sums small"
            " rows instead of every packet table. The bestiary view keeps one copy of a fight two party"
            " members uploaded and leaves out Flagged captures.",
            (
                Column("end_idx", None, "The packet that ended the fight."),
                Column("end_ms", None, "That packet's time."),
                Column("mob_id", None, "The mob: its spawn slot, id 0x01ZZZIII."),
                Column("zone_id", None, "The zone the character was in."),
                Column("name", None, "The mob's name as the packets last sent it before the fight ended."),
                Column(
                    "mob_name",
                    None,
                    "The mob's name as the client spells it (capture_entities); by its id before the packets"
                    " name it.",
                ),
                Column("model_id", None, "Its model, as the updates last sent it before the fight ended."),
                Column("level", None, "The level widescan or /check last gave this life of the mob."),
                Column("outcome", None, "As fights: defeated, despawned, zoned, disengaged, or open."),
                Column(
                    "fight_key",
                    None,
                    "The fight, whoever recorded it: party members' copies share it. A hash of the zone, mob,"
                    " minute it ended, and the zone's instance: the zone server, else the alliance roster"
                    " (0x0C8), else the capture, so a copy with neither is never merged.",
                ),
                Column("actions", None, "As fights: action packets it gave or took."),
                Column(
                    "coarse",
                    None,
                    "Whether the capture's times are whole seconds (a PacketViewer or early captain log), so"
                    " a TP move's ready time is good only to a second.",
                ),
                Column(
                    "claimed", None, "For a defeat: whether the character's party or alliance held the claim."
                ),
                Column(
                    "th_level", None, "For a defeat: the Treasure Hunter level the messages showed on it."
                ),
                Column(
                    "held",
                    None,
                    "For a defeat: the Rare items (item_rare) the recorder held then, in its bags but the"
                    " Recycle Bin, from holdings.",
                ),
                Column(
                    "held_known", None, "Whether a zone-in had listed the recorder's bags before the defeat."
                ),
                Column(
                    "th",
                    None,
                    "For a defeat: its Treasure Hunter level where the capture tells it: th_level, else the"
                    " highest that the recorder (THF trait and gear), its trusts, and its pets brought when"
                    " no one else acted on it. None when unknown.",
                ),
                Column("hp_min", None, "The kill's least max HP (mob_hp)."),
                Column("hp_max", None, "The kill's most max HP."),
                Column("hp_shaky", None, "Whether its HP% readings contradict each other."),
                Column("hp_regen", None, "HP% points it regained with no heal seen (mob_hp.regen)."),
                Column("hp_regen_rate", None, "HP% it regained per 3 s, from back-to-back rises."),
                Column("hp_healing", None, "HP it recovered from heals the capture saw."),
                Column(
                    "delays", None, "Each auto-attack interval the mob made, in delay units (60 a second)."
                ),
                Column(
                    "tp_gains",
                    None,
                    "TP the recorder gained from one of its rounds, 9 to 53, per round;"
                    " none while the recorder was SAM, main or sub (Store TP).",
                ),
                Column(
                    "rounds",
                    None,
                    "Its auto-attack rounds against one target that lived through them: swings, main hand,"
                    " off hand, and kicks.",
                ),
                Column(
                    "swings_at_recorder",
                    None,
                    "Its rounds at the recorder, kicks left out: swings passed, missed, and hit, whether"
                    " level correction applies, the mob's levels, the recorder's level, evasion, and evasion"
                    " floor.",
                ),
                Column(
                    "tp",
                    None,
                    "Each TP move: packet, skill, targets, reach, spread, mob size, hit, crit, knockback,"
                    " ready time in ms from its start (actions.ready_ms), the party near it, its targets and"
                    " the bystanders placed under 5 s ago (distance, bearing, from the first target, hit),"
                    " and rules_out: how far the use rules out a single target, an area around the mob, one"
                    " around its first target, and a breath, past the slack positions allow; 0 for none;"
                    " the most shadows it took from a target (message 31), whether that take left the"
                    " recorder some (shadow_exact), and through: on a recorder holding shadows it landed on,"
                    " whether it wiped them (true) or left them (false).",
                ),
                Column(
                    "skill_delays",
                    None,
                    "Each interval between two TP moves in a row that came with no readies, in delay units:"
                    " a mob that attacks with TP moves instead of auto-attacks. A spell or a readied move"
                    " between starts it again.",
                ),
                Column("spells", None, "Each spell it cast during the fight, by id."),
                Column(
                    "idle_spells",
                    None,
                    "Each spell it cast before the fight while it fought no one, since its previous fight or"
                    " defeat in the capture, by id.",
                ),
                Column(
                    "cast_times",
                    None,
                    "Each spell it cast, idle before the fight or in it: the spell, its cast time in ms from"
                    " its start (actions.ready_ms), and the ms from its previous finish of that spell in the"
                    " capture to this one's start.",
                ),
                Column("taken", None, "Each spell result on it: the spell and its outcome (spell_results)."),
                Column("drops", None, "For a defeat: the pool entries under 60 s after it, from drops."),
                Column(
                    "skillchains",
                    None,
                    "Each skillchain on it that came over 12 s after any other on it, so a chain's first: "
                    "its packet (idx; Lens opens it at https://lens.sruon.dev/c/<capture_id>#packet=<idx>), "
                    "skillchain (proc_kind: 1 Light to 16 Umbra), the closing action's category (3 a weapon "
                    "skill, 4 a spell, 6 a job ability, 11 a trust's or pet's move), the closing damage, the "
                    "skillchain's damage, and exposed. Absorbed ones and those that dealt under 10 are left "
                    "out. They give the mob's elemental resistance (EEM): the rank, in % taken, is "
                    "eem_tier(sc_ratio(chain, closing, damage)), both SQL functions: the ratio is damage "
                    "over closing times the level's multiplier (0.5 for level 1), and the rank its nearest "
                    "of 150, 130, 115, 100, 85, 70, 60, 50, 40, 30, 25, 20, 15, 10, 5 (150 also any ratio "
                    "past it; NULL for no ratio). Only a level 1 chain names one element: 7 Compression "
                    "Dark, 8 Liquefaction Fire, 9 Induration Ice, 10 Reverberation Water, 11 Transfixion "
                    "Light, 12 Scission Earth, 13 Detonation Wind, 14 Impaction Thunder; a level 2 or 3 one "
                    "reads the element of its pair the mob resists least. A spell's close (category 4) reads "
                    "true; any other carries an unknown Skillchain Bonus that only raises the ratio. "
                    "exposed: it fell on a day, or in weather, of its element or of the one that beats it, "
                    "which moves its damage a third of the time. The mob card reads a clear, spell-closed "
                    "one first, and an element's rank as its readings' most common, the lower on a tie.",
                ),
                Column(
                    "respawn_ms", None, "For a defeat: time to its next appearance alive in view (spawns)."
                ),
                Column("respawn_x", None, "Where it appeared."),
                Column("respawn_y", None, "Where it appeared."),
                Column("respawn_z", None, "Where it appeared."),
                Column("respawn_idx", None, "The packet it appeared in."),
            ),
            indexes=(
                "capture capture_id TYPE bloom_filter GRANULARITY 1",
                "fight fight_key TYPE bloom_filter GRANULARITY 1",
            ),
        ),
    )
