from ffxi_extractors.extract import COARSE, COMMON, NAMES, ONE, Column, Derived, Table
from ffxi_extractors.extractors.battle.engages import Engages

# The c2s 0x01A actions that provoke a mob: engage, cast, weapon skill, job ability, change target, ranged.
PROVOKE = (2, 3, 7, 9, 15, 16)


def engage_columns(table: str) -> tuple[Column, ...]:
    """An engages table's own columns, as a derived table lists them."""
    (t,) = (t for t in Engages.tables if t.name == table)
    return tuple(Column(c.name, None, c.doc) for c in t.columns)


def with_context(table: str) -> str:
    """table's rows with the mob's name as the bestiary spells it, the mob's level in that life, the
    character's level, the zone's type, and whether the capture's times are whole seconds (COARSE)."""
    life = "l.end_idx IS NULL OR l.end_idx >= e.idx"
    cols = ", ".join(f"e.{c.name} AS {c.name}" for c in (*COMMON, *engage_columns(table)))
    return f"""
SELECT {cols}, n.entity_name AS mob_name, n.model_id AS model_id, if({life}, l.level, NULL) AS mob_level,
  if({life}, l.source, NULL) AS level_source, c.main_level AS recorder_level,
  coalesce(z.type, 'other') AS zone_type, coalesce(k.coarse, false) AS coarse
FROM (SELECT * FROM {table} WHERE {ONE}) e
ASOF LEFT JOIN {NAMES} n
  ON n.capture_id = e.capture_id AND n.entity_id = e.mob_id AND n.idx <= e.idx
ASOF LEFT JOIN (SELECT capture_id, entity_id, idx, end_idx, level, source FROM levels WHERE {ONE}) l
  ON l.capture_id = e.capture_id AND l.entity_id = e.mob_id AND l.idx <= e.idx
ASOF LEFT JOIN (SELECT capture_id, idx, main_level FROM character WHERE {ONE} AND main_level IS NOT NULL) c
  ON c.capture_id = e.capture_id AND c.idx <= e.idx
LEFT JOIN {COARSE} k ON k.capture_id = e.capture_id
LEFT JOIN zone_types z ON z.zone_id = e.zone_id"""


def links_to(x: str, k: str) -> str:
    """x engaged under 10 s after k, within 15 yalms of it, and k is of its name or model."""
    return (
        f"{x}.link_ms < 10000 AND {x}.link_distance < 15"
        f" AND coalesce({k}.mob_name = {x}.mob_name OR {k}.model_id = {x}.model_id, false)"
    )


# What started each engage, first match wins: the character's own action on the mob in the 30 s before; a
# party member's, trust's, or pet's; a stranger's, or the mob already fighting someone; or a claim that came
# with the engage, someone's pull the character did not see: a mob that aggroes is claimed when it hits or
# is hit, after it engaged (0.3% of aggros on the character start claimed, 62% of its pulls). Else the mob
# started it: a link when a mob of its name or model engaged under 10 s before within 15 yalms, in a fight
# someone pulled or a link joined (k.started), and it went for someone; else an aggro on whomever it acted on
# first, if before anyone answered it and not claimed by the other side. Mobs that aggro side by side are
# each an aggro, not a link.
KIND = f"""multiIf(
  me_action_id IN {PROVOKE}, 'pull_recorder',
  party_ms IS NOT NULL, 'pull_party',
  other_ms IS NOT NULL OR mob_acted_ms IS NOT NULL, 'other',
  claim_ms = 0, 'other',
  coalesce(k.started AND {links_to("a", "k")}, false)
    AND (first_ms IS NOT NULL OR claimer_id IS NOT NULL), 'link',
  first_ms IS NULL OR first_ms > coalesce(answered_ms, first_ms), 'other',
  claimer_party != first_target_party, 'other',
  first_target_recorder, 'aggro_recorder',
  first_target_party, 'aggro_party',
  'aggro_other')"""


# Whether an engage's fight was one a mob could link to: someone pulled it, or it linked to a pulled one.
# ponytail: two steps of links; a longer chain needs a recursive CTE.
PULLED = f"(me_action_id IN {PROVOKE} OR party_ms IS NOT NULL OR other_ms IS NOT NULL)"


def link_join(k: str, x: str) -> str:
    """k is the engage x took for the one it linked to."""
    return (
        f"{k}.capture_id = {x}.capture_id AND {k}.mob_id = {x}.link_mob_id"
        f" AND {k}.ts_ms = {x}.ts_ms - {x}.link_ms"
    )


STARTED = f"""SELECT x.capture_id, x.mob_id, x.ts_ms, x.mob_name, x.model_id,
    x.pulled OR (q.pulled AND {links_to("x", "q")}) AS started
  FROM p x LEFT JOIN p q ON {link_join("q", "x")}"""

# A row the range and facing figures can trust, as a first measure over 875 captures chose them: outside
# instances, a mob seen 5 s or more, the character's position under 1 s old, and times finer than whole
# seconds (COARSE). An engage also has to be an aggro on the character with no other fight on.
PLACED = (
    "zone_type IN ('outdoors', 'dungeon', 'city') AND since_seen_ms >= 5000 AND me_age_ms <= 1000"
    " AND distance IS NOT NULL AND NOT coarse"
)
CLEAN = f"kind = 'aggro_recorder' AND link_mob_id IS NULL AND {PLACED}"

SQL = f"""
WITH a AS ({with_context("mob_engages")}),
p AS (SELECT capture_id, mob_id, ts_ms, mob_name, model_id, link_mob_id, link_ms, link_distance,
  {PULLED} AS pulled FROM a)
SELECT *, {CLEAN} AS clean FROM (
  SELECT a.*, {KIND} AS kind FROM a
  LEFT JOIN ({STARTED}) k ON {link_join("k", "a")}
)
"""


COLUMNS = (
    Column("mob_name", None, "The mob's name as the client spells it, as the bestiary's."),
    Column("model_id", None, "Its model, as entity_changes last gave it."),
    Column(
        "mob_level", None, "The mob's level in this life, from the last widescan or /check before (levels)."
    ),
    Column("level_source", None, "Where mob_level came from: widescan or check."),
    Column("recorder_level", None, "The character's main job level then (character)."),
    Column(
        "zone_type",
        None,
        "The zone's type, from LSB's data/zones: city, outdoors, dungeon, dynamis, instanced, or other.",
    ),
    Column(
        "coarse",
        None,
        "Whether every action packet in the capture came on a whole second, as in a PacketViewer log or a"
        " captain log before 1.7.",
    ),
)


class Aggro(Derived):
    name = "aggro"
    # 3: links only into a pulled fight; aggro_other; 4: an engage that starts claimed is no aggro
    version = 4
    doc = "Each engage of an idle mob, sorted into an aggro, a link, a pull, or another's."
    reads = frozenset({"decode", "engages", "levels", "character", "entity_changes", "actions"})
    order = "zone_id, mob_name, ts_ms"  # a mob page reads its mob's rows
    sql = SQL
    tables = (
        Table(
            "aggro",
            "One row per mob_engages row, with the mob named, the levels, the zone's type, and what started"
            " it. Party copies of one engage are in each recorder's capture, each from its own view.",
            (
                *engage_columns("mob_engages"),
                *COLUMNS,
                Column(
                    "kind",
                    None,
                    "aggro_recorder, aggro_party, or aggro_other (the mob started it and acted first on the"
                    " character; on its party, a trust, or a pet; or on a stranger), link (it started within"
                    " 15 yalms of a mob of its name or model engaged under 10 s before, in a fight someone"
                    " pulled or a link joined), pull_recorder or pull_party (they acted on it in the 30 s"
                    " before), or other (a stranger acted on it first, it started claimed, or no telling).",
                ),
                Column(
                    "clean",
                    None,
                    "Whether the range and facing figures count it: an aggro on the character outside"
                    " instances, by a mob seen 5 s or more, the character's position under 1 s old, no other"
                    " fight on, and not coarse.",
                ),
            ),
        ),
    )


class AggroPasses(Derived):
    name = "aggro_passes"
    version = 2  # 2: coarse as aggro's
    doc = "Each time the character passed an idle mob that did not engage, with the mob named."
    reads = frozenset({"decode", "engages", "levels", "character", "entity_changes", "actions"})
    order = "zone_id, mob_name, ts_ms"
    sql = f"SELECT *, {PLACED} AS clean FROM ({with_context('mob_passes')})"
    tables = (
        Table(
            "aggro_passes",
            "One row per mob_passes row, named as aggro's.",
            (
                *engage_columns("mob_passes"),
                *COLUMNS,
                Column("clean", None, "Whether the figures count it, as aggro's but for the kind."),
            ),
        ),
    )
