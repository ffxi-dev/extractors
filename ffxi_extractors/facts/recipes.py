from ffxi_extractors.extract import ONE, Column, Derived, Table

# The character's own syntheses (0x06F) folded by crystal and ingredients. Retail sends an ingredient once for
# each one put in, so its count is its quantity. Grade -1 is a break, 0 normal quality, 1 to 3 the HQ tier.
#
# A recipe's level in each craft it trains is bounded by the skill-ups (UpKind, UpLevel) at the crafter's
# skill before them (synths' skills). diff = skill - level, the skill with tenths, which 0x062 drops (S is its
# whole part). Since 2015-05-14 (FFO Wiki, 合成) a craft rises on a success while diff < 11, so
# level >= S - 10; on a break only while -5 <= diff < 0, so S + 1 <= level <= S + 5. No synthesis starts at
# diff < -27: level <= S + 27. An attempt without a skill-up bounds nothing: it is chance, or the rank's cap.
# On the archive's captures the bounds hold every level BG Wiki gives, Zircon's 81 and Orichalcum Ring's 93
# at level_min.
LEVEL = (
    "Tuple(craft Int32, attempts UInt64, skill_ups UInt64, level_min Nullable(Int32), min_n UInt64,"
    " level_max Nullable(Int32), max_n UInt64)"
)
SQL = f"""
WITH s AS (
  SELECT capture_id, idx, ts_ms, client_version, result, grade, item_id, count, crystal_id,
    arrayMap(x -> CAST((x, countEqual(ingredients, x)), 'Tuple(item_id Int32, quantity Int32)'),
      arraySort(arrayDistinct(ingredients))) AS recipe,
    skill_kinds, skill_levels, skills
  FROM synths WHERE {ONE} AND own AND crystal_id IS NOT NULL AND notEmpty(ingredients)
),
lv AS (
  SELECT capture_id, crystal_id, recipe,
    arraySort(groupArray(CAST((craft, attempts, skill_ups, level_min, min_n, level_max, max_n),
      '{LEVEL}'))) AS levels
  FROM (
    SELECT capture_id, crystal_id, recipe, craft, count() AS attempts, countIf(up > 0) AS skill_ups,
      maxIfOrNull(if(grade = -1, skill + 1, greatest(skill - 10, 0)), up > 0 AND skill IS NOT NULL)
        AS level_min,
      countIf(up > 0 AND skill IS NOT NULL) AS min_n,
      minIfOrNull(if(grade = -1 AND up > 0, skill + 5, skill + 27), skill IS NOT NULL) AS level_max,
      countIf(skill IS NOT NULL) AS max_n
    FROM s ARRAY JOIN skill_kinds AS craft, skill_levels AS up, skills AS skill
    WHERE craft BETWEEN 48 AND 57
    GROUP BY capture_id, crystal_id, recipe, craft
  )
  GROUP BY capture_id, crystal_id, recipe
)
SELECT r.capture_id AS capture_id, r.idx AS idx, r.ts_ms AS ts_ms, r.client_version AS client_version,
  c.release AS release, r.crystal_id AS crystal_id, r.recipe AS ingredients, r.desynth AS desynth,
  r.attempts AS attempts, r.nq AS nq, r.hq1 AS hq1, r.hq2 AS hq2, r.hq3 AS hq3, r.breaks AS breaks,
  r.nq_item_id AS nq_item_id, r.nq_count AS nq_count, r.hq1_item_id AS hq1_item_id, r.hq1_count AS hq1_count,
  r.hq2_item_id AS hq2_item_id, r.hq2_count AS hq2_count, r.hq3_item_id AS hq3_item_id,
  r.hq3_count AS hq3_count, l.levels AS levels
FROM (
  SELECT capture_id, assumeNotNull(crystal_id) AS crystal_id, recipe, min(idx) AS idx, min(ts_ms) AS ts_ms,
    any(client_version) AS client_version, countIf(result = 12) > 0 AS desynth, count() AS attempts,
    countIf(grade = 0) AS nq, countIf(grade = 1) AS hq1, countIf(grade = 2) AS hq2, countIf(grade = 3) AS hq3,
    countIf(grade = -1) AS breaks,
    minIfOrNull(item_id, grade = 0) AS nq_item_id, minIfOrNull(count, grade = 0) AS nq_count,
    minIfOrNull(item_id, grade = 1) AS hq1_item_id, minIfOrNull(count, grade = 1) AS hq1_count,
    minIfOrNull(item_id, grade = 2) AS hq2_item_id, minIfOrNull(count, grade = 2) AS hq2_count,
    minIfOrNull(item_id, grade = 3) AS hq3_item_id, minIfOrNull(count, grade = 3) AS hq3_count
  FROM s GROUP BY capture_id, crystal_id, recipe
) r
LEFT JOIN lv l ON l.capture_id = r.capture_id AND l.crystal_id = r.crystal_id AND l.recipe = r.recipe
LEFT JOIN (SELECT capture_id, release FROM captures WHERE {ONE}) c ON c.capture_id = r.capture_id
"""


class Recipes(Derived):
    name = "recipes"
    version = 1
    doc = "Each capture's own syntheses by recipe: how often each grade came, what it made, its craft levels."
    reads = frozenset({"decode", "synths"})
    order = "crystal_id, ingredients"
    sql = SQL
    tables = (
        Table(
            "recipes",
            "One row per capture, crystal, and ingredients the character synthesized with (synths, own)."
            " Across captures, sum the counts, take the largest level_min and the smallest level_max, and sum"
            " their n.",
            (
                Column("release", None, "The capture's release: the client version its ids are from."),
                Column("crystal_id", None, "The crystal (0x06F CrystalNo)."),
                Column(
                    "ingredients",
                    None,
                    "The ingredients, by item id: each with how many went in (0x06F MaterialNo, one entry"
                    " each).",
                ),
                Column("desynth", None, "Whether retail called an attempt a desynthesis (Result 12)."),
                Column("attempts", None, "How many syntheses."),
                Column("nq", None, "How many made normal quality (Grade 0)."),
                Column("hq1", None, "How many made HQ1 (Grade 1)."),
                Column("hq2", None, "How many made HQ2 (Grade 2)."),
                Column("hq3", None, "How many made HQ3 (Grade 3)."),
                Column("breaks", None, "How many broke (Grade -1)."),
                Column("nq_item_id", None, "What normal quality made (ItemNo)."),
                Column("nq_count", None, "How many it made (Count)."),
                Column("hq1_item_id", None, "What HQ1 made."),
                Column("hq1_count", None, "How many HQ1 made."),
                Column("hq2_item_id", None, "What HQ2 made."),
                Column("hq2_count", None, "How many HQ2 made."),
                Column("hq3_item_id", None, "What HQ3 made."),
                Column("hq3_count", None, "How many HQ3 made."),
                Column(
                    "levels",
                    None,
                    "Each craft it trains (UpKind, skill id 48 to 57): its attempts, its skill-ups, and the"
                    " recipe's level in it as far as the skill-ups at the crafter's skill S (synths' skills)"
                    " bound it. level_min: S - 10 (at least 0) for a skill-up on a success, S + 1 on a break;"
                    " min_n how many skill-ups gave a bound. level_max: S + 5 for a skill-up on a break, else"
                    " S + 27, the most below the level a synthesis can start at; max_n how many attempts gave"
                    " a bound. Null with no skill known.",
                ),
            ),
        ),
    )
