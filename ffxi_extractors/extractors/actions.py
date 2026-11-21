import math

import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

FRESH_MS = 2000  # a mob's heading older than this at its TP move is unknown
NEAR = 30.0  # yalms: bystanders farther from the mob than this are not kept; targets always are
INTERRUPT = 28787  # a start's cmd_arg low half when it stops what began (LSB's interrupt); 24931 begins it
STALE_MS = 30000  # a start older than this is not the finish's: pairs past it were a later mob's
FINISH = {11: 7, 4: 8, 2: 12}  # a finish's category -> its start's


class Places:
    """The last position, heading, size, and HP% the packets sent of each entity, and the character's own
    position: NPCs, mobs, and trusts (0x00E), other players (0x00D), the character (0x015, zone-in), HP% from
    those and the party's (0x0DD, 0x0DF)."""

    READS = frozenset({(0, 0x00A), (0, 0x00E), (0, 0x00D), (0, 0x0DD), (0, 0x0DF), (1, 0x015)})

    def __init__(self):
        self.pos: dict[int, tuple[float, float, float]] = {}  # entity id -> last x, y, z
        self.at: dict[int, int] = {}  # entity id -> when its position came
        self.dir: dict[int, tuple[int, int]] = {}  # entity id -> (heading, when)
        self.size: dict[int, float] = {}  # entity id -> yalms
        self.hpp: dict[int, int] = {}  # entity id -> last HP%
        self.me: tuple | None = None  # the character's last position
        self.me_at = 0

    def update(self, p, f) -> bool:
        """Keep what p says; True when p is one of READS."""
        key = (p.direction, p.opcode)
        if key == (0, 0x00A):
            for d in (self.pos, self.at, self.dir, self.size, self.hpp):
                d.clear()
            self.me, self.me_at = (f("PosHead.x"), f("PosHead.y"), f("PosHead.z")), p.ts_ms
        elif key == (1, 0x015):
            self.me, self.me_at = (f("x"), f("y"), f("z")), p.ts_ms
        elif key in ((0, 0x0DD), (0, 0x0DF)):
            if f("UniqueNo") is not None and f("Hpp") is not None:
                self.hpp[f("UniqueNo")] = f("Hpp")
        elif key in ((0, 0x00D), (0, 0x00E)):
            uid = f("UniqueNo")
            if f("SendFlg.Despawn"):
                self.pos.pop(uid, None)
                return True
            if f("SendFlg.Position"):
                x, y, z = f("x"), f("y"), f("z")
                if uid is not None and None not in (x, y, z):
                    self.pos[uid], self.at[uid] = (x, y, z), p.ts_ms
                if p.opcode == 0x00E and f("dir") is not None:
                    self.dir[uid] = (f("dir"), p.ts_ms)
            if f("SendFlg.General"):
                if f("Hpp") is not None:
                    self.hpp[uid] = f("Hpp")
                if p.opcode == 0x00E and f("Flags2.g"):
                    self.size[uid] = f("Flags2.g") / 10
        else:
            return False
        return True


class Actions(Extractor):
    """Ported from captain's actionview: every action packet, by anyone, in every category. actionview
    shows only mobs and some categories, and drops message 84; this keeps all and leaves the choice to
    the query. Ready time is measured from packet times rather than the client's clock. A mob TP move's
    range and spread are measured as actionview does, from the last positions the packets sent rather than
    the client's memory. Who stood near a TP move and whether it hit them follows the method Skold177 set
    out in phoenixffxi/xi-ai#13: each entity's distance and bearing from the mob, and its distance from the
    first target, so a query can bound a move's radius and arc."""

    name = "actions"
    version = 5  # 2: a mob TP move's max_range and max_spread; 3: actor_dir, actor_size, tp_nearby; 4: the
    # party follows 0x0E2 and 0x0C8; 5: ready_ms pairs a finish with its own start only, and an interrupt
    # carries what it stopped
    doc = "Each action (0x028): who acted, what they did, and what it did to each target."
    # Places' positions and HP%, so a fallen bystander is not taken for one missed.
    reads = frozenset({(0, 0x028)}) | Places.READS
    tables = (
        Table(
            "actions",
            "One row per action packet (0x028), by anyone. A mob TP move (category 11) carries its mob skill"
            " id; retail-resources has no mob skill names yet, so ability_names does not name it.",
            (
                Column("actor_id", pa.int64(), "Who acted: a player, trust, pet, NPC, or mob id."),
                Column(
                    "actor_is_mob", pa.bool_(), "Whether the actor is one of the zone's own NPCs or mobs."
                ),
                Column(
                    "category",
                    pa.int32(),
                    "cmd_no: 1 melee, 2 ranged, 3 weapon skill or damaging ability, 4 spell, 5 item,"
                    " 6 job ability, 7 TP move start, 8 spell start, 9 item start, 11 mob TP move,"
                    " 12 ranged start, 13 pet TP move, 14 dance, 15 rune fencer ability.",
                ),
                Column(
                    "action_id",
                    pa.int64(),
                    "What was used: the spell, ability, item, or mob skill id (cmd_arg). For a start (7, 8,"
                    " 9) the id of what is starting, which the packet carries in its first result; for an"
                    " interrupt (cmd_arg's low half 28787), the id of the start it stopped, else 0.",
                ),
                Column("cmd_arg", pa.int64(), "cmd_arg as sent."),
                Column("targets", pa.int32(), "How many targets the action had."),
                Column("message", pa.int32(), "The first result's message, an LSB msg_basic id."),
                Column("animation", pa.int32(), "The first result's sub_kind, which actionview calls Anim."),
                Column(
                    "ready_ms",
                    pa.int64(),
                    "For a mob TP move, spell, or ranged attack (11, 4, 2): ms since the same actor's start"
                    " of it (7, 8, 12; for 11 and 4 the same id), as actionview's ready time. None when the"
                    " actor's last start was another's, was interrupted, or is over 30 s old. For an"
                    " interrupt: ms since the start it stopped.",
                ),
                Column(
                    "max_range",
                    pa.float32(),
                    "For a mob TP move (11): how far its farthest target stood from the mob, in yalms, from"
                    " the last positions sent. None when a position is unknown. actionview's Range.",
                ),
                Column(
                    "max_spread",
                    pa.float32(),
                    "For a mob TP move with two or more targets: how far apart the two farthest targets"
                    " stood, in yalms. actionview's Spread.",
                ),
                Column(
                    "actor_dir",
                    pa.int32(),
                    "For a mob TP move: the mob's heading, 0 to 255, from its own update at most 2 s before."
                    " None when older. Headings run as LSB's worldAngle: 0 faces +x, 64 faces -y.",
                ),
                Column(
                    "actor_size",
                    pa.float32(),
                    "For a mob TP move: the mob's size in yalms, from its last full update (0x00E Flags2.g,"
                    " in tenths), where LSB sends its modelHitboxSize. None when not sent.",
                ),
                Column("zone_id", pa.int32(), "The zone the character was in."),
                Column(
                    "resend",
                    pa.bool_(),
                    "Whether the same packet arrived within 500 ms before: a resend, not a second action."
                    " The combat tables skip resends.",
                ),
            ),
        ),
        Table(
            "action_results",
            "One row per result of an action on a target. A target can take several results, such as the"
            " hits of a multi-hit round. Join actions on capture_id and idx.",
            (
                Column("actor_id", pa.int64(), "Who acted."),
                Column("category", pa.int32(), "The action's category, as in actions."),
                Column("action_id", pa.int64(), "The action's id, as in actions."),
                Column("target_id", pa.int64(), "The target."),
                Column("target_index", pa.int32(), "The target's place in the packet, from 0."),
                Column("result_index", pa.int32(), "The result's place for that target, from 0."),
                Column("miss", pa.int32(), "miss, as sent."),
                Column("kind", pa.int32(), "kind, as sent."),
                Column(
                    "sub_kind",
                    pa.int32(),
                    "sub_kind: the animation; for melee 0 main hand, 1 off hand, 2 and 3 kicks.",
                ),
                Column(
                    "info", pa.int32(), "info, as sent: 2 marks a critical hit, a TP move's too; 1 a defeat."
                ),
                Column(
                    "scale",
                    pa.int32(),
                    "scale, as sent: LSB packs a hit distortion in its low 2 bits and the knockback, 0 to 7,"
                    " in its high 3 (scale >> 2).",
                ),
                Column(
                    "value", pa.int64(), "The amount: damage, healing, or a status or item id, by message."
                ),
                Column("message", pa.int32(), "The result's message, an LSB msg_basic id."),
                Column("bit", pa.int64(), "bit, as sent; for a resisted spell, 2 marks a trait resist."),
                Column("proc_kind", pa.int32(), "The added effect's kind, when there is one."),
                Column("proc_info", pa.int32(), "The added effect's info."),
                Column("proc_value", pa.int64(), "The added effect's amount, such as skillchain damage."),
                Column(
                    "proc_message",
                    pa.int32(),
                    "The added effect's message: 288 to 302 and 767, 768 skillchains, 229 enspell or rune,"
                    " 163 additional effect damage.",
                ),
                Column("react_kind", pa.int32(), "The reaction's kind, when there is one."),
                Column("react_info", pa.int32(), "The reaction's info."),
                Column("react_value", pa.int64(), "The reaction's amount, such as spikes or counter damage."),
                Column(
                    "react_message",
                    pa.int32(),
                    "The reaction's message: 44 spikes, 132 Dread Spikes, 33 counter, 536 retaliation. Its"
                    " damage lands on the actor.",
                ),
            ),
        ),
        Table(
            "tp_nearby",
            "For each mob TP move (category 11), one row per entity placed near the mob: each target, and"
            " everyone else with a known position within 30 yalms not known to be at 0 HP. Join actions on"
            " capture_id and idx. After Skold177's method in phoenixffxi/xi-ai#13.",
            (
                Column("actor_id", pa.int64(), "The mob."),
                Column("action_id", pa.int64(), "The mob skill."),
                Column("entity_id", pa.int64(), "The entity near it: a player, trust, pet, NPC, or mob."),
                Column("hit", pa.bool_(), "Whether it was a target, a miss or a shadow taken included."),
                Column("party", pa.bool_(), "Whether it is the character or in its party or alliance."),
                Column("distance", pa.float32(), "Yalms from the mob, centre to centre, in 3D."),
                Column(
                    "bearing",
                    pa.float32(),
                    "Degrees off the mob's heading (actor_dir), -180 to 180: 0 ahead, 180 behind; the sign"
                    " gives the side. None when the heading is unknown.",
                ),
                Column(
                    "from_target",
                    pa.float32(),
                    "Yalms from the move's first target, in 3D. None when its position is unknown.",
                ),
                Column("age_ms", pa.int64(), "How old the entity's position was, in ms."),
            ),
        ),
    )

    def __init__(self):
        self.starts: dict[int, int] = {}
        self.resends = combat.Resends()
        self.places = Places()

    def packet(self, p, f, world, emit):
        if self.places.update(p, f):
            if p.opcode == 0x00A:
                self.starts.clear()
            return
        a = combat.read(f)
        cat, actor = a["cmd_no"], a["actor_id"]
        first = a["targets"][0][1][0] if a["targets"] and a["targets"][0][1] else {}
        action_id = first.get("value") if cat in (7, 8, 9) and first else a["cmd_arg"]
        resend = self.resends.is_resend(p)
        ready = None
        if not resend and cat in (7, 8, 12) and (a["cmd_arg"] or 0) & 0xFFFF == INTERRUPT:
            c, i, t = self.starts.pop(actor, (None, None, None))
            if c == cat and p.ts_ms - t <= STALE_MS:
                action_id, ready = i, p.ts_ms - t
        elif not resend and cat in (7, 8, 12):
            self.starts[actor] = (cat, action_id, p.ts_ms)
        elif not resend and cat in FINISH and actor in self.starts:
            c, i, t = self.starts.pop(actor)
            # A ranged start carries no id of its finish's.
            if c == FINISH[cat] and (cat == 2 or i == action_id) and p.ts_ms - t <= STALE_MS:
                ready = p.ts_ms - t
        reach = spread = heading = size = None
        if cat == 11 and not resend:
            me = world.character_id
            places = self.places
            if me and places.me and None not in places.me:
                places.pos[me], places.at[me] = places.me, places.me_at
            reach, spread = self._measure(actor, [t for t, _ in a["targets"] if t != actor])
            d, at = places.dir.get(actor, (None, None))
            heading = d if at is not None and p.ts_ms - at <= FRESH_MS else None
            size = places.size.get(actor)
            self._nearby(p, actor, action_id, [t for t, _ in a["targets"]], heading, world, emit)
        emit(
            "actions",
            p,
            actor_id=actor,
            actor_is_mob=combat.is_mob(actor),
            category=cat,
            action_id=action_id,
            cmd_arg=a["cmd_arg"],
            targets=len(a["targets"]),
            message=first.get("message"),
            animation=first.get("sub_kind"),
            ready_ms=ready,
            max_range=reach,
            max_spread=spread,
            actor_dir=heading,
            actor_size=size,
            zone_id=world.zone,
            resend=resend,
        )
        for t, (target_id, results) in enumerate(a["targets"]):
            for i, r in enumerate(results):
                proc, react = r["proc"] or {}, r["react"] or {}
                emit(
                    "action_results",
                    p,
                    actor_id=actor,
                    category=cat,
                    action_id=action_id,
                    target_id=target_id,
                    target_index=t,
                    result_index=i,
                    **{k: r[k] for k in combat.RESULT},
                    **{f"proc_{k}": proc.get(k) for k in combat.EXTRA},
                    **{f"react_{k}": react.get(k) for k in combat.EXTRA},
                )

    def _nearby(self, p, actor, action_id, targets, heading, world, emit):
        """A tp_nearby row for each target placed and each other placed entity within NEAR of the mob."""
        places = self.places
        here = places.pos.get(actor)
        if here is None:
            return
        hit, party = set(targets), {world.character_id, *world.party}
        first = places.pos.get(targets[0]) if targets else None
        for uid, there in places.pos.items():
            if uid == actor:
                continue
            far = math.dist(here, there)
            if uid not in hit and (far > NEAR or places.hpp.get(uid) == 0):
                continue
            emit(
                "tp_nearby",
                p,
                actor_id=actor,
                action_id=action_id,
                entity_id=uid,
                hit=uid in hit,
                party=uid in party,
                distance=far,
                bearing=bearing(here, there, heading),
                from_target=math.dist(first, there) if first else None,
                age_ms=p.ts_ms - places.at[uid],
            )

    def _measure(self, actor: int, targets: list[int]) -> tuple[float | None, float | None]:
        """The farthest target from the actor and the farthest two targets apart. A target that is the
        actor is left out; any unknown position leaves its measure unknown rather than short."""
        here, there = self.places.pos.get(actor), [self.places.pos.get(t) for t in targets]
        if None in there or not there:
            return None, None
        reach = max(math.dist(here, t) for t in there) if here else None
        spread = max((math.dist(a, b) for i, a in enumerate(there) for b in there[i + 1 :]), default=None)
        return reach, spread


def bearing(here, there, heading: int | None) -> float | None:
    """Degrees from the heading to there, -180 to 180. A heading counts 256ths of a turn as LSB's worldAngle
    does: -atan2(dy, dx) on the ground plane, which XiPackets names x and y."""
    dx, dy = there[0] - here[0], there[1] - here[1]
    if heading is None or math.hypot(dx, dy) < 0.1:
        return None
    return (-math.degrees(math.atan2(dy, dx)) - heading * 360 / 256 + 180) % 360 - 180
