from ..extract import ONE, Column, Derived, Table, ordered

NEXT_MS = 2000  # a start from the same NPC this soon after an event's last packet follows from it

# Each capture's event starts folded by what LSB's scripts branch on: the NPC, the event, the start's
# parameters, the options the replies sent, and the event that followed. A start's own row and every packet
# after it carry its idx as event_idx; the replies' options are in packet order.
# fmt: off
SQL = f"""
WITH s AS (
  SELECT capture_id, idx, ts_ms, client_version, zone_id, npc_id, event_id, params
  FROM events WHERE {ONE} AND kind = 'start'
),
r AS (
  SELECT capture_id, event_idx, {ordered("option", "idx", "kind = 'reply'")} AS options, max(ts_ms) AS last
  FROM events WHERE {ONE} AND event_idx IS NOT NULL GROUP BY capture_id, event_idx
),
j AS (
  SELECT s.*, r.options AS options, r.last AS last,
    leadInFrame(s.idx) OVER w AS next_idx, leadInFrame(s.ts_ms) OVER w AS next_ts,
    leadInFrame(s.npc_id) OVER w AS next_npc, leadInFrame(s.event_id) OVER w AS next_event
  FROM s LEFT JOIN r ON r.capture_id = s.capture_id AND r.event_idx = s.idx
  WINDOW w AS (PARTITION BY s.capture_id ORDER BY s.idx ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING)
),
f AS (
  SELECT capture_id, client_version, zone_id, npc_id, event_id, params, options,
    if(next_idx > idx AND coalesce(next_npc, -1) = coalesce(npc_id, -1)
      AND next_ts - greatest(ts_ms, coalesce(last, ts_ms)) <= {NEXT_MS}, next_event, NULL) AS followed_by,
    min(idx) AS first_idx, min(ts_ms) AS first_ts, count() AS n
  FROM j GROUP BY ALL
)
SELECT f.capture_id AS capture_id, f.first_idx AS idx, f.first_ts AS ts_ms,
  f.client_version AS client_version, c.release AS release, f.zone_id AS zone_id, f.npc_id AS npc_id,
  nm.name AS npc_name, f.event_id AS event_id, f.params AS params, f.options AS options,
  f.followed_by AS followed_by, f.n AS n
FROM f
LEFT JOIN (SELECT capture_id, release FROM captures WHERE {ONE}) c ON c.capture_id = f.capture_id
LEFT JOIN (SELECT capture_id, entity_id, any(entity_name) AS name
  FROM capture_entities(capture = {{capture:String}})
  WHERE entity_name IS NOT NULL GROUP BY capture_id, entity_id) nm
  ON nm.capture_id = f.capture_id AND nm.entity_id = f.npc_id
"""
# fmt: on


class NpcEvents(Derived):
    name = "npc_events"
    version = 1
    doc = "Each capture's NPC events folded by NPC, event, parameters, options, and the event that followed."
    reads = frozenset({"decode", "events", "entity_changes"})
    order = "zone_id, npc_name, event_id"  # the NPC catalog reads a zone's rows
    sql = SQL
    tables = (
        Table(
            "npc_events",
            "One row per capture, NPC, event, start parameters, replies' options, and following event: the"
            " starts (events, kind start) that share them, counted. The NPC catalog sums them across"
            " captures. Retail renumbers NPC ids between client versions: release says which numbering an id"
            " is in.",
            (
                Column("release", None, "The capture's release: the client version its NPC ids are from."),
                Column("zone_id", None, "The zone."),
                Column(
                    "npc_id",
                    None,
                    "The NPC; none for a zone-in's event, the character's own id for an event on itself.",
                ),
                Column("npc_name", None, "The NPC's name, as capture_entities names it."),
                Column("event_id", None, "The event (EventPara): LSB's startEvent id."),
                Column("params", None, "The start's parameters, as startEvent sends them."),
                Column(
                    "options",
                    None,
                    "The options the client's replies sent, in order: the last ends the event"
                    " (onEventFinish), any before it asked for an update (onEventUpdate).",
                ),
                Column(
                    "followed_by",
                    None,
                    f"The event the same NPC started under {NEXT_MS / 1000:g} s after this one's last packet,"
                    " as onEventFinish chains one.",
                ),
                Column("n", None, "How many starts these are."),
            ),
        ),
    )
