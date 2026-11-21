import math

import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat
from .actions import Places, bearing
from .digs import vana

BEFORE_MS = 30_000  # an action on the mob this long before its engage counts as what started it
AFTER_MS = 60_000  # the mob's first action and its claim are looked for this long after
NEAR = 15.0  # yalms: the character within this of an idle mob is a pass
FAR = 17.0  # and the pass ends past this, so a step back and forth stays one pass
SCAN_MS = 500  # the character's moves are checked against every mob at most this often
LINKED_MS = 30_000  # a fellow mob that engaged this long before can be the one this one linked to
STRANGER_NEAR = 15.0  # yalms: a stranger's fight this near can be the one it linked to
INVISIBLE, DEODORIZE, SNEAK = 69, 70, 71
RESTING = 33  # 0x037 server_status while the character rests (LSB ANIMATION_HEALING)


def friendly(uid, world) -> bool:
    """The character, its party and alliance, or a trust or pet: an id of the zone's dynamic range."""
    if uid is None:
        return False
    # ponytail: any trust or pet counts, a stranger's too; the party list would tell them apart.
    return uid == world.character_id or uid in world.party or (uid >> 24 == 1 and (uid & 0xFFF) >= 0x700)


# The character's state and the world's at a moment: both tables carry it.
STATE = (
    Column("zone_id", pa.int32(), "The zone."),
    Column("mob_id", pa.int64(), "The mob."),
    Column(
        "distance",
        pa.float32(),
        "Yalms from the mob to the character, centre to centre, in 3D, from the last positions sent. None"
        " when one is unknown.",
    ),
    Column("dz", pa.float32(), "The character's height above the mob, in yalms."),
    Column(
        "facing",
        pa.float32(),
        "Degrees from the mob's heading to the character, -180 to 180: 0 ahead, 180 behind. None when the"
        " heading is unknown.",
    ),
    Column("mob_x", pa.float32(), "The mob's last position, as XiPackets names it."),
    Column("mob_y", pa.float32(), "Position."),
    Column("mob_z", pa.float32(), "Height."),
    Column("mob_dir", pa.int32(), "The mob's last heading, 0 to 255, as actions.actor_dir."),
    Column(
        "mob_age_ms", pa.int64(), "How old the mob's position was. An idle mob sends one only when it moves."
    ),
    Column("me_age_ms", pa.int64(), "How old the character's position was (c2s 0x015)."),
    Column("since_seen_ms", pa.int64(), "Since the mob was first seen alive in this life."),
    Column(
        "invisible",
        pa.bool_(),
        "Whether the character had Invisible (status 69), from its last 0x037; None before one.",
    ),
    Column("sneak", pa.bool_(), "Whether it had Sneak (71)."),
    Column("deodorize", pa.bool_(), "Whether it had Deodorize (70)."),
    Column("hpp", pa.int32(), "The character's HP%, from its last 0x037, 0x0DD or 0x0DF."),
    Column("resting", pa.bool_(), "Whether it was resting (0x037 status 33)."),
    Column(
        "recorder_status", pa.int32(), "The character's 0x037 server_status: 0 idle, 1 engaged, 33 resting."
    ),
    Column("vana_hour", pa.int32(), "The Vana'diel hour, 0 to 23, as LSB counts it."),
    Column(
        "weather_id",
        pa.int32(),
        "The weather the last zone-in or 0x057 named; none before the first. From 4 on, ids pair by"
        " element, the odd one double. Names are in weather_names.",
    ),
)


class Engages(Extractor):
    """Mobs that start a fight, and mobs the character walks past. A mob's claim (0x00E BtTargetID) stays 0
    when it aggroes and is set only once the party acts, so the start is its status going from idle to
    engaged (server_status 0 to 1) while unclaimed: in that update its speed jumps and its heading turns to
    its target. What the party did before, and whom the mob acts on first, tell an aggro from a pull: the
    derived aggro fact sorts them."""

    name = "engages"
    version = 2  # 2: a stranger's claimed mob can be the one it linked to
    doc = "Each idle, unclaimed mob that engaged, and each pass the character made by one that did not."
    reads = Places.READS | frozenset({(0, 0x028), (0, 0x037), (0, 0x057), (1, 0x01A)})
    tables = (
        Table(
            "mob_engages",
            "One row per idle, unclaimed mob whose status went to engaged (0x00E server_status 0 to 1), or"
            " that a claim reached first. idx is that update. Position columns are from before it; flip_*"
            " are what it sent.",
            (
                *STATE,
                Column("status_before", pa.int32(), "The mob's server_status before: 0 idle."),
                Column("status", pa.int32(), "Its status in the update: 1 engaged."),
                Column("mob_speed", pa.int32(), "The mob's Speed before the update."),
                Column("flip_dir", pa.int32(), "The heading the update sent, if it sent a position."),
                Column("flip_speed", pa.int32(), "The Speed it sent."),
                Column(
                    "flip_facing",
                    pa.float32(),
                    "Degrees from the heading sent to the character, as facing: near 0 when the mob turned"
                    " to it.",
                ),
                Column(
                    "me_action_id",
                    pa.int32(),
                    "The character's last c2s 0x01A on the mob in the 30 s before: its ActionID.",
                ),
                Column("me_action_ms", pa.int64(), "How long before the engage it was."),
                Column(
                    "party_actor_id",
                    pa.int64(),
                    "The last of the party (trusts and pets too) to act on the mob in the 30 s before.",
                ),
                Column("party_category", pa.int32(), "That action's category."),
                Column("party_ms", pa.int64(), "How long before the engage it was."),
                Column(
                    "other_ms",
                    pa.int64(),
                    "How long before the engage another player last acted on the mob, within 30 s.",
                ),
                Column(
                    "mob_acted_ms",
                    pa.int64(),
                    "How long before the engage the mob last acted on a player, within 30 s.",
                ),
                Column(
                    "first_ms",
                    pa.int64(),
                    "The mob's first action on a player after the engage, within 60 s: ms after.",
                ),
                Column("first_category", pa.int32(), "Its category."),
                Column("first_target_id", pa.int64(), "Its first target."),
                Column("first_target_recorder", pa.bool_(), "Whether that is the character."),
                Column(
                    "first_target_party",
                    pa.bool_(),
                    "Whether that is the character, its party, a trust, or a pet.",
                ),
                Column(
                    "answered_ms",
                    pa.int64(),
                    "The first c2s 0x01A on the mob, or party action on it, after the engage: ms after.",
                ),
                Column(
                    "claim_ms",
                    pa.int64(),
                    "When a claim first reached it after, within 60 s: ms after; 0 in the update itself.",
                ),
                Column("claimer_id", pa.int64(), "Who claimed it."),
                Column(
                    "claimer_party",
                    pa.bool_(),
                    "Whether the claimer is the character, its party, a trust, or a pet.",
                ),
                Column(
                    "link_mob_id",
                    pa.int64(),
                    "The nearest other mob engaged at the time: claimed by the party, by a stranger within 15"
                    " yalms, or itself engaged in the 30 s before unclaimed.",
                ),
                Column("link_distance", pa.float32(), "Yalms between the two mobs."),
                Column(
                    "link_ms",
                    pa.int64(),
                    "How long before the other mob's own engage was; None when not seen.",
                ),
            ),
        ),
        Table(
            "mob_passes",
            "One row per time the character came within 15 yalms of an idle, unclaimed monster that did not"
            " engage, until it was 17 yalms off, the mob changed, or the zone did. idx is the closest moment,"
            " and the columns are as they were then.",
            (*STATE, Column("duration_ms", pa.int64(), "How long the character stayed in range.")),
        ),
    )

    def __init__(self):
        self.places = Places()
        self.resends = combat.Resends()
        self.mobs: dict[int, dict] = {}
        # (engage row, mob): those still waiting for the mob's first action or a claim
        self.pending: list[tuple[dict, int]] = []
        self.passes: dict[int, dict] = {}  # mob -> its open pass
        self.buffs: set[int] | None = None
        self.status: int | None = None
        self.weather: int | None = None
        self.scanned = 0

    def _state(self, p, uid, world, pos, at, heading) -> dict:
        """The STATE columns, the mob at pos since at, facing heading."""
        places, me = self.places, world.character_id
        here = places.me if places.me and None not in places.me else None
        b, m = self.buffs, self.mobs.get(uid, {})
        out = {"zone_id": world.zone, "mob_id": uid, "mob_dir": heading, "hpp": places.hpp.get(me),
               "resting": self.status == RESTING, "recorder_status": self.status,
               "vana_hour": vana(p.ts_ms)[1], "weather_id": self.weather,
               "since_seen_ms": p.ts_ms - m["seen"] if m else None}  # fmt: skip
        if b is not None:
            out.update(invisible=INVISIBLE in b, sneak=SNEAK in b, deodorize=DEODORIZE in b)
        if pos:
            out.update(mob_x=pos[0], mob_y=pos[1], mob_z=pos[2], mob_age_ms=p.ts_ms - at)
        if here:
            out["me_age_ms"] = p.ts_ms - places.me_at
        if pos and here:
            out.update(distance=math.dist(pos, here), dz=here[2] - pos[2], facing=bearing(pos, here, heading))
        return out

    def packet(self, p, f, world, emit):
        key = (p.direction, p.opcode)
        if key == (0, 0x00E):
            uid = f("UniqueNo")
            before = (self.places.pos.get(uid), self.places.at.get(uid), self.places.dir.get(uid, (None,))[0])
            self.places.update(p, f)
            if combat.is_mob(uid):
                self._mob(p, f, uid, before, world, emit)
            return
        if self.places.update(p, f):
            if key == (0, 0x00A):
                for uid in list(self.passes):
                    self._close(uid, emit)
                self.mobs.clear()
                self.weather = f("WeatherNumber")
            elif key == (1, 0x015) and p.ts_ms - self.scanned >= SCAN_MS:
                self.scanned = p.ts_ms
                near = self.passes.keys()
                idle = [u for u, m in self.mobs.items() if (m["status"] == 0 and m["unclaimed"]) or u in near]
                for uid in idle:
                    self._pass(p, uid, world, emit)
        elif key == (0, 0x037):
            self.buffs = {f(f"BufStatus[{i}]") for i in range(32)} - {None, 255}
            self.status = f("server_status")
            if world.character_id and f("Flags0.hpp") is not None:
                self.places.hpp[world.character_id] = f("Flags0.hpp")
        elif key == (0, 0x057):
            self.weather = f("WeatherNumber")
        elif key == (1, 0x01A):
            m = self.mobs.get(f("UniqueNo"))
            if m is not None:
                m["me_act"] = (p.ts_ms, f("ActionID"))
                self._answered(p, f("UniqueNo"))
        elif key == (0, 0x028) and not self.resends.is_resend(p):
            self._action(p, f, world)

    def _mob(self, p, f, uid, before, world, emit):
        if f("SendFlg.Despawn"):
            self._close(uid, emit)
            self.mobs.pop(uid, None)
            return
        m = self.mobs.setdefault(uid, {"status": None, "bt": None, "unclaimed": False, "seen": p.ts_ms,
                                       "monster": None, "speed": None, "engaged": None})  # fmt: skip
        was, speed = m["status"], m["speed"]
        if f("SendFlg.General"):
            if was == 3 and f("server_status") == 0:  # it died and came back: a new life
                m["seen"] = p.ts_ms
            m["status"], m["monster"] = f("server_status"), bool(f("Flags1.MonsterFlag"))
        placed = bool(f("SendFlg.Position"))
        if placed:
            m["speed"] = f("Speed")
        claimed = bool(f("SendFlg.ClaimStatus"))
        bt = f("BtTargetID") if claimed else m["bt"]
        if bt:
            for row, mob in self.pending:
                if mob == uid and row.get("claim_ms") is None:
                    row.update(
                        claim_ms=p.ts_ms - row["ts_ms"], claimer_id=bt, claimer_party=friendly(bt, world)
                    )
        if claimed and not bt and m["status"] in (0, None):
            m["unclaimed"] = True
        fire = m["unclaimed"] and m["status"] != 3 and ((claimed and bt) or (was == 0 and m["status"] == 1))
        if claimed:
            m["bt"] = bt
        if not fire:
            self._pass(p, uid, world, emit)
            return
        m["unclaimed"] = False
        self.passes.pop(uid, None)  # it engaged: no pass
        # Where it stood and faced before the update; seen first in it, where it stands now, heading unknown.
        pos, at, heading = before if before[0] else (self.places.pos.get(uid), self.places.at.get(uid), None)
        state = self._state(p, uid, world, pos, at, heading)
        here = self.places.me if self.places.me and None not in self.places.me else None

        def ago(t):
            return p.ts_ms - t if t is not None and p.ts_ms - t <= BEFORE_MS else None

        me_t, me_id = m.get("me_act", (None, None))
        party_t, party_by, party_cat = m.get("party_act", (None, None, None))
        party = ago(party_t) is not None
        row = emit("mob_engages", p, **state, status_before=was, status=m["status"], mob_speed=speed,
                   flip_dir=f("dir") if placed else None, flip_speed=f("Speed") if placed else None,
                   flip_facing=bearing((f("x"), f("y")), here, f("dir")) if placed and here else None,
                   me_action_id=me_id if ago(me_t) is not None else None, me_action_ms=ago(me_t),
                   party_actor_id=party_by if party else None, party_category=party_cat if party else None,
                   party_ms=ago(party_t), other_ms=ago(m.get("other_act")),
                   mob_acted_ms=ago(m.get("mob_act")), **self._link(p, uid, pos, world))  # fmt: skip
        if bt:
            row.update(claim_ms=0, claimer_id=bt, claimer_party=friendly(bt, world))
        m["engaged"] = p.ts_ms
        self.pending.append((row, uid))

    def _link(self, p, uid, pos, world) -> dict:
        """The nearest other mob engaged now: the party's, a stranger's close by, or itself just engaged
        unclaimed."""
        best = None
        for other, o in self.mobs.items():
            there = self.places.pos.get(other)
            if other == uid or o["status"] != 1 or not pos or not there:
                continue
            recent = o["engaged"] is not None and p.ts_ms - o["engaged"] <= LINKED_MS
            d = math.dist(pos, there)
            ours = friendly(o["bt"], world) or (not o["bt"] and recent)
            if (ours or (o["bt"] and d < STRANGER_NEAR)) and (best is None or d < best[0]):
                best = (d, other, p.ts_ms - o["engaged"] if recent else None)
        if best is None:
            return {}
        return {"link_mob_id": best[1], "link_distance": best[0], "link_ms": best[2]}

    def _answered(self, p, uid):
        for row, mob in self.pending:
            if mob == uid and row.get("answered_ms") is None:
                row["answered_ms"] = p.ts_ms - row["ts_ms"]

    def _action(self, p, f, world):
        a = combat.read(f)
        actor, targets = a["actor_id"], [t for t, _ in a["targets"]]
        self.pending = [(r, m) for r, m in self.pending if p.ts_ms - r["ts_ms"] <= AFTER_MS]
        if combat.is_mob(actor):
            players = [t for t in targets if t is not None and not combat.is_mob(t)]
            if not players:
                return
            if actor in self.mobs:
                self.mobs[actor]["mob_act"] = p.ts_ms
            for row, mob in self.pending:
                if mob == actor and row.get("first_ms") is None:
                    t = players[0]
                    row.update(first_ms=p.ts_ms - row["ts_ms"], first_category=a["cmd_no"], first_target_id=t,
                               first_target_recorder=t == world.character_id,
                               first_target_party=friendly(t, world))  # fmt: skip
            return
        mine = friendly(actor, world)
        for t in targets:
            m = self.mobs.get(t)
            if m is None:
                continue
            if mine:
                m["party_act"] = (p.ts_ms, actor, a["cmd_no"])
                self._answered(p, t)
            elif actor is not None and actor < 0x1000000:
                m["other_act"] = p.ts_ms

    def _pass(self, p, uid, world, emit):
        """Open, follow, or close the character's pass by an idle, unclaimed monster."""
        m, there, me = self.mobs.get(uid), self.places.pos.get(uid), self.places.me
        idle = m and m["monster"] and m["status"] == 0 and m["unclaimed"] and not m["bt"]
        if not idle or not there or not me or None in me:
            self._close(uid, emit)
            return
        d = math.dist(there, me)
        open_ = self.passes.get(uid)
        if d > (FAR if open_ else NEAR):
            self._close(uid, emit)
            return
        if open_ is None:
            open_ = self.passes[uid] = {"start": p.ts_ms, "d": math.inf}
        open_["end"] = p.ts_ms
        if d < open_["d"]:
            heading = self.places.dir.get(uid, (None,))[0]
            open_.update(d=d, p=p, state=self._state(p, uid, world, there, self.places.at[uid], heading))

    def _close(self, uid, emit):
        x = self.passes.pop(uid, None)
        if x and "p" in x:
            emit("mob_passes", x["p"], **x["state"], duration_ms=x["end"] - x["start"])

    def finish(self, world, emit):
        for uid in list(self.passes):
            self._close(uid, emit)
