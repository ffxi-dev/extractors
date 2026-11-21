from collections import Counter

import pyarrow as pa

from ffxi_extractors import combat
from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World
from ffxi_extractors.vana import EPOCH_S

# 0x063's expiry counts 60ths of a second from the Vana'diel epoch.
WRAP = 1 << 32
FOREVER = 0x7FFFFFFF  # an expiry that never comes
EMPTY = (0xFF, 0xFFFF)  # an unused slot
SAME_MS = 2000  # the zone resends an expiry up to about 1 s apart; one moved further is a new application
BEFORE_MS = 3000  # the action that applied an effect arrives at most this long before its icon
AFTER_MS = 1000  # or this long after it
RELIST_MS = 60_000  # an effect without an end that leaves the list and comes back this soon is the same one
# Time spent zoning does not count against an effect: the zone lists it again after a zone-in with its expiry
# pushed later by up to that long. A listing this soon after a zone-in matches an icon by its status alone.
ZONED_MS = 10_000
PAUSE_MS = 60_000
# Results whose value is the effect they gave. A job ability's or item's result whose value matches the icon
# (its 100, its 0) comes second; in other categories a value is damage or HP.
ABILITY = (5, 6, 14, 15)
LANDED = frozenset({82, 127, 141, 186, 194, 230, 236, 237, 242, 243, 266, 267, 268, 269, 270, 271, 272, 277,
                    278, 279, 280, 319, 320, 375, 412, 645, 754, 755, 804})  # fmt: skip
PROC = (160, 164)  # "Additional effect: <status>" on the target
# A mob's TP move or spell often gives its effect silently: its result says only the damage. With no result
# naming the status by AFTER_MS after it, a new icon takes the latest such that landed on the character
# under SILENT_MS before it, unless the status is a buff, or a player, trust, or pet gave the character that
# status by name in the capture.
MOVE = -1
KO = 0
SILENT_MS = 1500
# The statuses the client lets a player click off (flag 128 in its status table, retail-resources 30261006_0):
# buffs, which a mob's move never gives the character silently.
BUFFS = frozenset(i for a, b in (
    (32, 118), (126, 127), (150, 150), (152, 152), (163, 166), (169, 173), (176, 176), (178, 185),
    (190, 191), (227, 231), (258, 258), (274, 275), (277, 282), (284, 284), (286, 286), (288, 291),
    (293, 297), (340, 357), (360, 371), (376, 377), (403, 403), (405, 421), (431, 433), (435, 447),
    (453, 462), (467, 470), (472, 472), (477, 478), (480, 480), (482, 488), (490, 495), (497, 505),
    (507, 508), (510, 510), (513, 513), (517, 517), (519, 519), (522, 522), (531, 535), (537, 538),
    (568, 570), (573, 575), (581, 582), (584, 584), (586, 587), (589, 596), (598, 599), (601, 601),
    (604, 611), (615, 615), (617, 617), (619, 619), (621, 623), (626, 628),
) for i in range(a, b + 1))  # fmt: skip
HOUR_MS = 3_600_000


def clock_offset(rows: list[dict]) -> int:
    """How far the server's clock, which the list's expiries count by, ran ahead of the capture's, in whole
    hours: a log stamped in local time, as PacketViewer's are, is off by its time zone. An icon that wears
    off leaves the list at its expiry, so most icons' expiry less their end is the offset; one dispelled or
    cleared ends early. 0 unless 3 or more ended icons, and 80% of them, agree to within a minute."""
    ended = [r for r in rows if r["status_id"] != KO and None not in (r["expires_ms"], r["ended_ms"])]
    gaps = [r["expires_ms"] - r["ended_ms"] for r in ended]
    hours = Counter(round(g / HOUR_MS) for g in gaps if abs(g - round(g / HOUR_MS) * HOUR_MS) <= 60_000)
    if not hours:
        return 0
    h, n = hours.most_common(1)[0]
    return h * HOUR_MS if n >= 3 and n >= 0.8 * len(gaps) else 0


def expiry_ms(raw: int, now_ms: int) -> int | None:
    """0x063's expiry in Unix ms. It counts 60ths of a second since LSB's vanadiel_epoch in 32 bits, so it
    wraps every 2.3 years: read it as the nearest to the packet's time. None for FOREVER."""
    if raw == FOREVER:
        return None
    base = (now_ms / 1000 - EPOCH_S) * 60
    return int(((raw + round((base - raw) / WRAP) * WRAP) / 60 + EPOCH_S) * 1000)


class Effects(Extractor):
    """The character's status effects, as the zone lists them in 0x063 type 9 with each one's expiry, and the
    action that applied each. Only the character's own list carries expiries: the party's (0x076) has
    icons only, and nothing lists a mob's, so theirs have no row."""

    name = "effects"
    version = 6  # 2: a mob's move or spell that gives its effect silently, and named; a Cure's HP names no
    # status; 3: a renewal no result names has no source; 4: a silent move waits for a naming result and
    # takes no buff a player gave; 5: a silent move lands and gives no buff; the capture's clock offset;
    # 6: the offset from a zone-in's server time, so a capture whose clock runs ahead keeps its sources
    doc = (
        "Each status effect applied to the character: how long the zone said it would last, and what gave it."
    )
    reads = frozenset({(0, 0x063), (0, 0x028), (0, 0x00A)})
    tables = (
        Table(
            "effects",
            "One row per status effect applied to the character: an icon added to its status list (0x063"
            " type 9), or one whose expiry moved over 2 s later. idx and ts_ms are that 0x063's.",
            (
                Column(
                    "status_id",
                    pa.int32(),
                    "The icon, which is the status id (status_names); 0 is KO, which has no source.",
                ),
                Column(
                    "expires_ms",
                    pa.int64(),
                    "When 0x063 said it would wear off, Unix ms by the capture's clock; none for an effect"
                    " without an end. The list counts by the server's clock: a capture whose clock ran whole"
                    " hours off it, as a PacketViewer log stamped in local time does, is set back by them.",
                ),
                Column(
                    "duration_ms",
                    pa.int64(),
                    "expires_ms less when it was applied: the action's time when one applied it, else the"
                    " 0x063's. The duration retail gave it, to within the recorder's clock.",
                ),
                Column(
                    "ended_ms",
                    pa.int64(),
                    "When this application ended: its icon left the list, or a later one renewed it. None if"
                    " the capture ended first. A zone-in that lists the same expiry again does not end it.",
                ),
                Column("renewed", pa.bool_(), "Whether the icon was already listed, and this renewed it."),
                Column(
                    "source_idx",
                    pa.int64(),
                    "The action packet (0x028) whose result on the character applied it: one from 3 s before"
                    " the icon to 1 s after that names the status: by a message that lands an effect, or a"
                    " job ability's or item's value. Else, for a new icon, the latest of an item used on the"
                    " character and a mob's TP move or spell that landed on it under 1.5 s before, unless the"
                    " status is one a player can click off, or a player, trust, or pet gave it that status by"
                    " name in the capture. None when none did, such as"
                    " an effect a 0x029 message gave, a renewal no result named, or an expiry before the"
                    " action.",
                ),
                Column(
                    "named",
                    pa.bool_(),
                    "Whether the source's result names the status. False for an item, and for a mob's move or"
                    " spell whose result gave only damage: it gave the effect silently.",
                ),
                Column("source_ms", pa.int64(), "That action's time."),
                Column("actor_id", pa.int64(), "Who acted: a mob, player, trust, or pet."),
                Column(
                    "actor_name",
                    pa.string(),
                    "A mob or NPC actor's name as the client spells it (0x00E), as the bestiary names mobs.",
                ),
                Column("category", pa.int32(), "The action's category, as in actions."),
                Column("action_id", pa.int64(), "The action's id: spell, ability, item, or mob skill."),
                Column("message", pa.int32(), "The result's message."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.held: list[dict] = []  # rows whose icons the list holds
        self.listed: dict[int, int | None] = {}  # id(row) -> the expiry the list gives it now
        self.gone: list[dict] = []  # rows whose icons left before their expiry: a zone-in lists them again
        self.landed: list[tuple] = []  # (ts, status or None for any, sure, source) of recent results on me
        self.waiting: list[dict] = []  # rows no action has claimed yet
        self.zoned_at = None  # the last zone-in
        self.off: int | None = None  # how far the server's clock runs ahead, from a zone-in's server time
        self.resends = combat.Resends()
        self.given: set[int] = set()  # statuses a player, trust, or pet gave the character by name
        self.rows: list[dict] = []  # every row, kept to the end for the capture's clock offset

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x00A:
            self.zoned_at = p.ts_ms
            if now := f("ntTimeSec"):  # the server's Unix seconds: the offset in whole hours, at once
                self.off = round((now * 1000 - p.ts_ms) / HOUR_MS) * HOUR_MS
        elif p.opcode == 0x028:
            self._results(p, f, world)
        elif f("type") == 9:
            self._icons(p, f, world, emit)

    def _results(self, p, f, world):
        a = combat.action(f)
        cat, me = a["cmd_no"], world.character_id
        if not me or self.resends.is_resend(p):
            return
        src = {"source_idx": p.idx, "source_ms": p.ts_ms, "actor_id": a["actor_id"], "category": cat,
               "action_id": a["cmd_arg"]}  # fmt: skip
        for target, results in a["targets"]:
            if target != me:
                continue
            for r in results:
                # A job ability's or item's value is its effect; other categories' values are damage or HP
                # unless the message lands an effect. A melee or ranged hit's added effect may be a status.
                sure = r["message"] in LANDED
                if sure or cat in ABILITY:
                    self.landed.append((p.ts_ms, r["value"], sure, {**src, "message": r["message"]}))
                if r["proc"] and r["proc"]["message"] in PROC:
                    self.landed.append(
                        (p.ts_ms, r["proc"]["value"], True, {**src, "message": r["proc"]["message"]})
                    )
                if cat == 5:
                    self.landed.append((p.ts_ms, None, False, {**src, "message": r["message"]}))
                elif cat in (4, 11) and combat.is_mob(a["actor_id"]) and not r["miss"]:
                    self.landed.append((p.ts_ms, MOVE, False, {**src, "message": r["message"]}))
        # A row waits AFTER_MS for a result that names it; then it settles for an item or a silent move.
        waiting, self.waiting = self.waiting, []
        for row in waiting:
            late = p.ts_ms - row["ts_ms"] > AFTER_MS
            if not self._claim(row, world, settle=late) and not late:
                self.waiting.append(row)
        self.landed = [x for x in self.landed if p.ts_ms - x[0] <= BEFORE_MS]

    def finish(self, world: World, emit: Emit) -> None:
        for row in self.waiting:
            self._claim(row, world, settle=True)
        off = self.off if self.off is not None else clock_offset(self.rows)
        if off:
            for row in self.rows:
                if row["expires_ms"] is not None:
                    row["expires_ms"] -= off
                    row["duration_ms"] -= off

    def _claim(self, row, world, settle: bool) -> bool:
        """Fill row's source from the results from BEFORE_MS before its icon to AFTER_MS after: the latest
        naming its status by a message that lands an effect, else the latest naming it. Once settled, a new
        icon takes the latest of an item used and a mob's move or spell from SILENT_MS before, unless a
        player, trust, or pet gave the character that status by name: those are buffs, which a move hit
        just before did not give. Some icons renew themselves every few seconds, so a renewal no result
        names has no source; nor has an icon whose expiry came before the action."""
        status, at = row["status_id"], row["ts_ms"]
        if status == KO:  # a defeat, which defeats keeps; no action gave it as an effect
            return False
        near = [x for x in self.landed if at - BEFORE_MS <= x[0] <= at + AFTER_MS]
        named = [x for x in near if x[1] == status]
        if named:
            best = max(named, key=lambda x: (x[2], x[0]))
        elif settle and not row["renewed"]:
            other = [x for x in near if x[1] is None or (
                x[1] == MOVE and x[0] >= at - SILENT_MS and status not in self.given and status not in BUFFS
            )]  # fmt: skip
            if not other:
                return False
            best = max(other, key=lambda x: x[0])
        else:
            return False
        src = best[3]
        if row["expires_ms"] is not None and row["expires_ms"] - (self.off or 0) <= src["source_ms"]:
            return False
        if named and not combat.is_mob(src["actor_id"]):
            self.given.add(status)
        row.update(src, named=bool(named))
        if row["expires_ms"] is not None:
            row["duration_ms"] = row["expires_ms"] - src["source_ms"]
        actor = src["actor_id"]
        e = world.entities.get(actor & 0xFFF, {}) if combat.is_mob(actor) else {}
        row["actor_name"] = e.get("name") if e.get("id") == actor else None
        # The result is spent, and so is an item's claim to any icon; a silent move may give several.
        self.landed = [x for x in self.landed if not (
            (x is best and x[1] != MOVE) or (x[1] is None and x[3]["source_idx"] == src["source_idx"])
        )]  # fmt: skip
        return True

    def _icons(self, p, f, world, emit):
        listed = []
        for k in range(32):
            icon, raw = f(f"data.icon[{k}]"), f(f"data.timestamp[{k}]")
            if icon is not None and icon not in EMPTY and (icon or raw):
                listed.append((icon, expiry_ms(raw or 0, p.ts_ms)))
        held, self.held = self.held, []
        pause = PAUSE_MS if self.zoned_at is not None and p.ts_ms - self.zoned_at <= ZONED_MS else SAME_MS
        for status, expires in listed:
            row = _take(held, self.listed, status, expires, pause) or _take(
                self.gone, self.listed, status, expires, pause
            )
            if row is None:
                old = next((r for r in held if r["status_id"] == status), None)
                if old is not None:
                    held.remove(old)
                    old["ended_ms"] = p.ts_ms
                row = emit("effects", p, status_id=status, expires_ms=expires,
                           duration_ms=None if expires is None else expires - p.ts_ms,
                           renewed=old is not None, zone_id=world.zone)  # fmt: skip
                self.rows.append(row)
                if not self._claim(row, world, settle=False):
                    self.waiting.append(row)
            row["ended_ms"], self.listed[id(row)] = None, expires
            self.held.append(row)
        for row in held:
            row["ended_ms"] = p.ts_ms
        off = self.off or 0  # expiries count by the server's clock, packet times by the capture's

        def until(r: dict) -> int:
            listed = self.listed[id(r)]
            return listed - off if listed else r["ended_ms"] + RELIST_MS

        self.gone = [r for r in self.gone + held if until(r) > p.ts_ms]


def _take(
    rows: list[dict], listed: dict[int, int | None], status: int, expires: int | None, pause: int
) -> dict | None:
    """The row in rows for this icon and expiry, removed from them: listed last with the same expiry to within
    SAME_MS, or up to pause earlier."""
    for r in rows:
        was = listed[id(r)]
        if r["status_id"] == status and (was == expires or (
            None not in (expires, was) and -SAME_MS <= expires - was <= pause
        )):  # fmt: skip
            rows.remove(r)
            return r
    return None
