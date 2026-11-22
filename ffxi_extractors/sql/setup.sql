-- Functions, name views, and constants the derived facts and queries over them share. store.setup runs
-- each statement; functions are server-wide.

-- The Wilson interval of k successes in n at z (1.96 for 95%), as fractions; none when n is 0.
CREATE OR REPLACE FUNCTION wilson AS (k, n, z) -> if(n > 0, CAST((
  greatest(0, (k / n + z * z / (2 * n) - z * sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n))) / (1 + z * z / n)),
  least(1, (k / n + z * z / (2 * n) + z * sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n))) / (1 + z * z / n))),
  'Tuple(lo Float64, hi Float64)'), NULL);

-- Mogsafe's trust levels, highest first: trust_rank(trust) >= trust_rank('silver') keeps live captures.
CREATE OR REPLACE FUNCTION trust_rank AS (level) -> multiIf(level = 'gold', 4, level = 'silver', 3,
  level = 'bronze', 2, level = 'plain', 1, level = 'flagged', 0, NULL);

-- The distance a move is used from. dm sums its first targets' distances, ((move, distance), uses): of the move's,
-- each counted once per use, the second farthest, so one odd use does not set it; the only one when there is one.
CREATE OR REPLACE FUNCTION move_distances AS (dm, id) -> arrayReverseSort(arrayFlatten(arrayMap(
  i -> arrayWithConstant(least(dm.2[i], 2), dm.1[i].2), arrayFilter(i -> dm.1[i].1 = id, arrayEnumerate(dm.1)))));
CREATE OR REPLACE FUNCTION move_distance AS (dm, id) -> if(empty(move_distances(dm, id)), NULL,
  move_distances(dm, id)[least(2, length(move_distances(dm, id)))]);

-- A name as a packet squashes it, to compare with the client's spelling.
CREATE OR REPLACE FUNCTION squash AS (s) -> lower(replaceAll(s, ' ', ''));

-- A log change's quest or mission, as retail-resources numbers them: log_id as LSB's xi.questLog and
-- xi.mission.log_id, id the bit or the value 0x056 sends. Quest ports run 0x50 + 8 * log (under way) and
-- 0x90 + 8 * log (done) for logs 0 to 7, then Abyssea, Adoulin, and Coalition in pairs.
CREATE OR REPLACE FUNCTION quest_log AS (log, port) -> multiIf(log NOT IN ('quests_current', 'quests_done'), NULL,
  port BETWEEN 80 AND 200, intDiv((port - 80) % 64, 8), port IN (224, 232), 8, port IN (240, 248), 9,
  port IN (256, 264), 10, NULL);

-- Port 0xD0 keeps two words of bits per log for San d'Oria, Bastok, Windurst, and Zilart; 0x38 holds Campaign
-- 256 to 511. A main field holds a current mission; field 5 packs ACP, AMK, and ASA in four bits each.
CREATE OR REPLACE FUNCTION mission_addon AS (old, new) -> multiIf(bitAnd(bitXor(old, new), 15) != 0, 0,
  bitAnd(bitXor(old, new), 240) != 0, 1, 2);

CREATE OR REPLACE FUNCTION mission_log AS (log, port, area, field, old, new, id) -> multiIf(
  log = 'missions_done', multiIf(port = 208, intDiv(id, 64), port = 216, if(area = 'ToAU', 4, 5), 8),
  log = 'progress', if(field BETWEEN 4 AND 7, [7, 4, 5, 8][field - 3], NULL),  -- an index past the array read 0
  log = 'main', multiIf(field = 2, 3, field = 3, 6, field = 5, 9 + mission_addon(old, new), field = 6, 12,
    field = 7, 13, NULL),
  log = 'tvr' AND field = 0, 14, NULL);

CREATE OR REPLACE FUNCTION mission_id AS (log, port, field, old, new, id) -> multiIf(
  log = 'missions_done', multiIf(port = 208, id % 64, port = 56, id + 256, id),
  log = 'main' AND field = 5, bitAnd(bitShiftRight(new, 4 * mission_addon(old, new)), 15), new);

-- A chain's first skillchain (proc_kind 1 Light to 16 Umbra): its damage over its closing damage times the
-- level's multiplier for two steps (BG Wiki, Skillchain: 0.5 level 1, 0.6 level 2, 1.0 Light and Darkness, 1.5
-- Radiance and Umbra). That leaves the target's resistance rank, times whatever else bore on it: the closer's
-- skillchain bonus, Magic Damage, day and weather, and the target's magic damage taken. The damage is floored,
-- so its middle, damage + 0.5, is taken.
CREATE OR REPLACE FUNCTION sc_ratio AS (chain, closing, damage) -> (damage + 0.5) / (closing * multiIf(
  chain BETWEEN 7 AND 14, 0.5, chain BETWEEN 3 AND 6, 0.6, chain IN (1, 2), 1.0, 1.5));

-- Whether a level 1 skillchain at this time and weather may have had its damage moved by the day or the weather: one
-- of its element raises it, one of the element that beats it lowers it, on a third of skillchains (LSB's
-- xi.spells.damage.calculateDayAndWeather and xi.data.element). Elements go as weekdays: Fire 0, Earth 1, Water 2,
-- Wind 3, Ice 4, Thunder 5, Light 6, Dark 7; the weekday is Vana'diel days from LSB's vanadiel_epoch, 25 Vana'diel
-- minutes a minute; a weather's element is its id's pair, Hot spell and Heat wave Fire and so on.
-- The Vana'diel minute at a Unix time in ms: 25 to an Earth minute, from Vana'diel's epoch.
CREATE OR REPLACE FUNCTION vana_minute AS (ts_ms) -> intDiv((ts_ms - 1009810800000) * 25, 60000);
CREATE OR REPLACE FUNCTION sc_element AS (chain) -> transform(chain, [8, 12, 10, 13, 9, 14, 11, 7], [0, 1, 2, 3, 4, 5, 6, 7], -1);
CREATE OR REPLACE FUNCTION sc_exposed AS (chain, ts_ms, weather) -> sc_element(chain) >= 0 AND hasAny(
  [sc_element(chain), transform(sc_element(chain), [0, 1, 2, 3, 4, 5, 6, 7], [2, 3, 5, 4, 0, 1, 7, 6], -1)],
  [intDiv(vana_minute(ts_ms), 1440) % 8,
   transform(intDiv(coalesce(weather, 0), 2), [2, 3, 4, 5, 6, 7, 8, 9], [0, 2, 1, 3, 4, 5, 6, 7], -1)]);

-- A party member's name from each packet the party list gave it on, so a slot a trust held and another took after
-- names each in its turn (Tenzen, then Joachim, in one id); the first name it had from the capture's start, and the
-- capture's own character from its start. A query takes the name at its row with an ASOF join on (member_id, idx).
CREATE OR REPLACE VIEW party_names AS
SELECT capture_id, member_id, idx, name FROM party WHERE name != ''
UNION ALL SELECT capture_id, member_id, toInt64(0), argMin(name, idx) FROM party WHERE name != ''
  GROUP BY capture_id, member_id
UNION ALL SELECT capture_id, character_id, toInt64(0), character FROM captures WHERE character != '';

-- The resistance rank, in percent, nearest a ratio by factor (BG Wiki, Resist: Resistance Ranks); NULL for no ratio,
-- one not above 0, or NaN, which an aggregate over no rows gives. 150 is also any ratio past it.
CREATE OR REPLACE FUNCTION eem_tier AS (r) -> if(r > 0 AND NOT isNaN(r), arraySort(t -> abs(log(t / (100 * r))),
  [150, 130, 115, 100, 85, 70, 60, 50, 40, 30, 25, 20, 15, 10, 5])[1], NULL);

-- A mob's accuracy over the recorder's evasion from its hit rate's interval ci (BG Wiki, Hit Rate: 75% + (ACC -
-- EVA) / 2, held within 20% and 95%) and the level correction's least and most: the bounds the rate sets, none at
-- a limit, and which limits it meets.
CREATE OR REPLACE FUNCTION acc_diff_lo AS (ci, lmax) -> if(tupleElement(ci, 'lo') > 0.2,
  least(40, 2 * (ceil(tupleElement(ci, 'lo') * 100) - 75)) - lmax, NULL);
CREATE OR REPLACE FUNCTION acc_diff_hi AS (ci, lmin) -> if(tupleElement(ci, 'hi') < 0.95,
  greatest(-109, 2 * (floor(tupleElement(ci, 'hi') * 100) - 75) + 1) - lmin, NULL);
CREATE OR REPLACE FUNCTION acc_state AS (ci) -> multiIf(tupleElement(ci, 'hi') >= 0.95 AND tupleElement(ci, 'lo') <= 0.2,
  'wide', tupleElement(ci, 'hi') >= 0.95, 'cap', tupleElement(ci, 'lo') <= 0.2, 'floor', 'range');

-- Names by release, as retail-resources publishes them (resources.py loads them). A spell's id is
-- its index, as packets send it; a quest's or mission's is its bit or value in its log.
-- One name per release and id: a release may list an id twice, as Whitegate's two entity DATs do.
CREATE OR REPLACE VIEW zone_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'zone' GROUP BY release, id;
CREATE OR REPLACE VIEW entity_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'entity' GROUP BY release, id;
CREATE OR REPLACE VIEW item_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'item' GROUP BY release, id;
CREATE OR REPLACE VIEW item_rare AS SELECT DISTINCT id FROM names WHERE kind = 'item_rare';
CREATE OR REPLACE VIEW keyitem_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'keyitem' GROUP BY release, id;
CREATE OR REPLACE VIEW spell_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'spell' GROUP BY release, id;
CREATE OR REPLACE VIEW ability_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'ability' GROUP BY release, id;
CREATE OR REPLACE VIEW status_names AS SELECT release, id, any(name) AS name, any(name_passive) AS name_passive FROM names WHERE kind = 'status' GROUP BY release, id;
CREATE OR REPLACE VIEW mob_skill_names AS SELECT release, id, any(name) AS name FROM names WHERE kind = 'mob_skill' GROUP BY release, id;
CREATE OR REPLACE VIEW quest_names AS SELECT release, log_id, any(log) AS log, id, any(name) AS name FROM names WHERE kind = 'quest' GROUP BY release, log_id, id;
CREATE OR REPLACE VIEW mission_names AS SELECT release, log_id, any(log) AS log, id, any(name) AS name FROM names WHERE kind = 'mission' GROUP BY release, log_id, id;
-- The client's text for each message id 0x028 and 0x029 send, its blanks as tokens ("{actor}"): the grammar is
-- retail-resources' docs/FORMATS.md.
CREATE OR REPLACE VIEW battle_messages AS SELECT release, id, any(name) AS text FROM names WHERE kind = 'battle_message' GROUP BY release, id;

-- The zones where a mob above the character's level gains accuracy for it, copied from LSB's
-- scripts/data/level_correction.lua (LandSandBoat/server commit 4d311b4, 216 zones). The bestiary stores what
-- it says, so a change here bumps Bestiary.version.
CREATE OR REPLACE VIEW level_corrected_zones AS SELECT arrayJoin([
  1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 19, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
  36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 51, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67,
  68, 69, 71, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97,
  98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120,
  121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 132, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144,
  145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166,
  167, 168, 169, 170, 172, 173, 174, 175, 176, 177, 178, 180, 181, 182, 183, 184, 185, 186, 187, 188, 191, 192,
  193, 194, 195, 196, 197, 198, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 211, 212, 213, 215, 216, 217,
  218, 220, 221, 222, 223, 224, 225, 226, 227, 228, 253, 254, 255, 279, 294, 295, 296, 297, 298]) AS zone_id;

-- Each zone's type, from the first entry of `type` in LSB's data/zones/<zone>/zone.yaml (LandSandBoat/server
-- commit 3520b75fe4), by the ids sql/zone_settings.sql gives them. A zone listed with none (battlefields, the Mog
-- Garden) is not here. The aggro fact stores it, so a change here bumps Aggro.version.
CREATE OR REPLACE VIEW zone_types AS SELECT toInt32(t.2) AS zone_id, t.1 AS type FROM (SELECT arrayJoin(arrayConcat(
  arrayMap(z -> ('city', z), [
    0, 26, 32, 48, 50, 70, 71, 80, 87, 94, 189, 199, 214, 219, 230, 231, 232, 233, 234, 235, 236, 237, 238,
    239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 256, 257, 280, 284, 285]),
  arrayMap(z -> ('outdoors', z), [
    1, 2, 3, 4, 5, 7, 15, 24, 25, 33, 43, 44, 45, 46, 47, 51, 52, 53, 54, 58, 59, 61, 79, 81, 82, 83, 84, 85,
    88, 89, 90, 91, 95, 97, 98, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114,
    115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 130, 132, 136, 137, 215, 216, 217,
    218, 223, 224, 225, 226, 227, 228, 253, 254, 255, 260, 261, 262, 263, 265, 266, 267, 288, 289]),
  arrayMap(z -> ('dungeon', z), [
    9, 11, 12, 14, 16, 18, 20, 22, 27, 28, 29, 30, 34, 35, 62, 65, 68, 72, 92, 96, 99, 131, 138, 140, 141,
    142, 143, 145, 147, 148, 149, 150, 151, 152, 153, 154, 155, 157, 158, 159, 160, 161, 162, 164, 166, 167,
    169, 171, 172, 173, 174, 175, 176, 177, 178, 184, 190, 191, 192, 193, 194, 195, 196, 197, 198, 200, 204,
    205, 208, 212, 213, 258, 268, 269, 270, 272, 273, 274]),
  arrayMap(z -> ('dynamis', z), [
    39, 40, 41, 42, 134, 135, 185, 186, 187, 188, 294, 295, 296, 297]),
  arrayMap(z -> ('instanced', z), [
    55, 56, 60, 63, 66, 69, 73, 74, 75, 76, 77, 86, 93, 129, 183, 259, 264, 271, 287]))) AS t);

-- Weather by the id 0x00A and 0x057 send, from LSB's data/enums/weather.yaml (LandSandBoat/server commit
-- 2baf9d4a24); retail-resources does not publish them. Every client numbers them the same.
CREATE OR REPLACE VIEW weather_names AS SELECT toInt64(i - 1) AS id, w[i] AS name FROM (SELECT [
  'None', 'Sunshine', 'Clouds', 'Fog', 'Hot spell', 'Heat wave', 'Rain', 'Squall', 'Dust storm', 'Sand storm',
  'Wind', 'Gales', 'Snow', 'Blizzards', 'Thunder', 'Thunderstorms', 'Auroras', 'Stellar glare', 'Gloom',
  'Darkness'] AS w) ARRAY JOIN arrayEnumerate(w) AS i;

-- Each weather a zone had, once however many captures saw it, but Flagged ones'. 0x00A and 0x057 say when it
-- began as a Vana'diel minute of the zone's 2160-day weather cycle, 3,110,400 minutes, which repeats exactly
-- (cocosolos' WeatherWatch), so the cycle that holds it is the one nearest the packet's own time: 25 Vana'diel
-- minutes a minute, from LSB's vanadiel_epoch. A row's previous weather ran from previous_start until it began.
CREATE OR REPLACE VIEW weather_starts AS
WITH w AS (
  SELECT zone_id, weather_id, previous_id, capture_id, ts_ms, vana_minute(ts_ms) AS now_min,
    now_min - ((((now_min - start_time) % 3110400) + 4665600) % 3110400 - 1555200) AS vmin,
    vmin - (((start_time - previous_start) % 3110400) + 3110400) % 3110400 AS prev_vmin
  FROM weather
  WHERE zone_id IS NOT NULL AND capture_id NOT IN (SELECT capture_id FROM capture_trust FINAL WHERE trust = 'flagged')
),
s AS (
  SELECT zone_id, weather_id, vmin, CAST(NULL, 'Nullable(Int64)') AS end_vmin, capture_id, ts_ms FROM w
  UNION ALL
  SELECT zone_id, assumeNotNull(previous_id), assumeNotNull(prev_vmin), vmin, capture_id, ts_ms FROM w
  WHERE previous_id IS NOT NULL AND prev_vmin IS NOT NULL AND prev_vmin < vmin
)
SELECT zone_id, weather_id, vmin, vmin % 3110400 AS tick, intDiv(vmin, 3110400) AS cycle, min(end_vmin) AS end_vmin,
  count() AS seen, uniqExact(capture_id) AS captures, argMin(capture_id, ts_ms) AS first_capture, min(ts_ms) AS first_ms
FROM s GROUP BY zone_id, weather_id, vmin;

-- The zone's timeline: each tick of the cycle a weather was seen to begin at, over every cycle seen, with how
-- long it ran when the next weather's packet named it as the one before. A tick whose cycles disagree on the
-- weather or its length lists each.
CREATE OR REPLACE VIEW weather_timeline AS
SELECT zone_id, tick, argMax(weather_id, seen) AS weather_id, arraySort(groupUniqArray(weather_id)) AS weathers,
  max(end_vmin - vmin) AS minutes, arraySort(groupUniqArrayIf(end_vmin - vmin, end_vmin IS NOT NULL)) AS lengths,
  uniqExact(cycle) AS cycles, sum(seen) AS seen, argMin(first_capture, first_ms) AS first_capture,
  min(first_ms) AS first_ms
FROM weather_starts GROUP BY zone_id, tick;

-- Conquest regions by the index 0x05E sends them in, from LSB's data/enums/region.yaml (LandSandBoat/server
-- commit 2baf9d4a24); retail-resources does not publish them.
CREATE OR REPLACE VIEW conquest_region_names AS SELECT toInt64(i - 1) AS id, w[i] AS name FROM (SELECT [
  'Ronfaure', 'Zulkheim', 'Norvallen', 'Gustaberg', 'Derfland', 'Sarutabaruta', 'Kolshushu', 'Aragoneu',
  'Fauregandi', 'Valdeaunia', 'Qufim', 'Li''Telor', 'Kuzotz', 'Vollbow', 'Elshimo Lowlands', 'Elshimo Uplands',
  'Tu''Lia', 'Movalpolos', 'Tavnazian Archipelago'] AS w) ARRAY JOIN arrayEnumerate(w) AS i;

-- One capture's entities (all of them when capture is ''), each change with its name as the client spells it:
-- the release's name when it starts the way the packet's squashed, cut-short one does ("GrognardNeckch");
-- else, where the release reuses the id for another (Limbus), the zone's one name that starts that way. An id a
-- release lists twice (Whitegate's two DATs) is one row, its names together. Names are read for the capture's
-- ids and zones only, by the names table's key: an entity id is 0x01ZZZIII, so a zone's ids share
-- intDiv(id, 4096), and a name's id outside that form is always read.
CREATE OR REPLACE VIEW capture_entities AS
WITH e AS (
  SELECT t.capture_id AS capture_id, t.entity_id AS entity_id, t.idx AS idx, t.ts_ms AS ts_ms, t.name AS name,
    t.model_id AS model_id, t.monster AS monster, t.x AS x, t.y AS y, t.z AS z, c.release AS release,
    bitAnd(bitShiftRight(t.entity_id, 12), 4095) AS zone
  FROM entity_changes t JOIN captures c ON c.capture_id = t.capture_id
  WHERE t.capture_id = {capture:String} OR {capture:String} = ''
),
fn AS (
  SELECT s.release AS release, s.zone AS zone, s.short AS short, argMax(n.name, squash(n.name) = squash(s.short)) AS name
  FROM (SELECT DISTINCT release, zone, name AS short FROM e WHERE name IS NOT NULL) s
  JOIN (SELECT release, name, bitAnd(bitShiftRight(id, 12), 4095) AS zone FROM names
    WHERE kind = 'entity'
      AND release IN (SELECT release FROM captures WHERE capture_id = {capture:String} OR {capture:String} = '')
      AND (intDiv(id, 4096) NOT BETWEEN 4096 AND 8191 OR intDiv(id, 4096) IN (
        SELECT 4096 + bitAnd(bitShiftRight(entity_id, 12), 4095) FROM entity_changes
        WHERE (capture_id = {capture:String} OR {capture:String} = '') AND name IS NOT NULL))) n
    ON n.release = s.release AND n.zone = s.zone
  WHERE startsWith(squash(n.name), squash(s.short))
  GROUP BY s.release, s.zone, s.short
  HAVING uniqExact(n.name) = 1 OR max(squash(n.name) = squash(s.short))
)
SELECT e.capture_id AS capture_id, e.entity_id AS entity_id, e.idx AS idx, e.ts_ms AS ts_ms, e.name AS packet_name,
  multiIf(e.name IS NULL, if(empty(i.names), NULL, i.names[1]),
    arrayExists(x -> startsWith(squash(x), squash(e.name)), i.names),
    arrayFirst(x -> startsWith(squash(x), squash(e.name)), i.names), coalesce(fn.name, e.name)) AS entity_name,
  e.model_id AS model_id, e.monster AS monster, e.x AS x, e.y AS y, e.z AS z, e.release AS release
FROM e
LEFT JOIN (SELECT release, id, arraySort(groupUniqArray(name)) AS names FROM names
  WHERE kind = 'entity'
    AND release IN (SELECT release FROM captures WHERE capture_id = {capture:String} OR {capture:String} = '')
    AND id IN (SELECT entity_id FROM entity_changes WHERE capture_id = {capture:String} OR {capture:String} = '')
  GROUP BY release, id) i
  ON i.release = e.release AND i.id = e.entity_id
LEFT JOIN fn ON fn.release = e.release AND fn.zone = e.zone AND fn.short = e.name;

-- One capture's mob attack rounds at the recorder (every capture's when capture is ''), each with what bounds the
-- mob's accuracy: the swings that passed evasion, missed, and hit; whether the zone corrects for level; the mob's
-- levels and the recorder's; the evasion /checkparam gave, while no gear changed since; and the floor the evasion
-- skill and AGI set. The capture card and the bestiary read it.
CREATE OR REPLACE VIEW round_evasion AS
SELECT r.capture_id AS capture_id, r.actor_id AS actor_id, r.idx AS idx,
  r.swings - r.misses - r.dodged - r.other AS passed, r.misses AS missed, r.hits AS hits,
  r.zone_id IN (SELECT zone_id FROM level_corrected_zones) AS corr, lv.lo AS lo, lv.hi AS hi,
  ch.main_level AS clv, if(p.idx IS NOT NULL AND (g.idx IS NULL OR g.idx < p.idx), p.evasion, NULL) AS eva,
  if(k.skill > 200, 200 + floor(0.9 * (k.skill - 200)), k.skill) + floor(ch.agi / 2) AS eva_floor
FROM (SELECT * FROM attack_rounds WHERE (capture_id = {capture:String} OR {capture:String} = '')
  AND actor_is_mob AND main_hand IS NOT NULL AND at_character AND kicks = 0) r
ASOF LEFT JOIN (SELECT capture_id, idx, main_level, agi + coalesce(agi_bonus, 0) AS agi FROM character
  WHERE (capture_id = {capture:String} OR {capture:String} = '') AND main_level IS NOT NULL) ch
  ON ch.capture_id = r.capture_id AND ch.idx <= r.idx
ASOF LEFT JOIN (SELECT capture_id, idx, skill FROM evasion_skill
  WHERE capture_id = {capture:String} OR {capture:String} = '') k ON k.capture_id = r.capture_id AND k.idx <= r.idx
ASOF LEFT JOIN (SELECT capture_id, idx, evasion FROM character_params
  WHERE (capture_id = {capture:String} OR {capture:String} = '') AND kind = 'defense') p
  ON p.capture_id = r.capture_id AND p.idx <= r.idx
ASOF LEFT JOIN (SELECT capture_id, idx FROM character_gear
  WHERE capture_id = {capture:String} OR {capture:String} = '') g ON g.capture_id = r.capture_id AND g.idx <= r.idx
LEFT JOIN (SELECT capture_id, entity_id, min(level) AS lo, max(level) AS hi FROM levels
  WHERE capture_id = {capture:String} OR {capture:String} = '' GROUP BY capture_id, entity_id) lv
  ON lv.capture_id = r.capture_id AND lv.entity_id = r.actor_id;
