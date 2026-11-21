import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World
from ffxi_extractors.extractors.items.gathering import PLACE, WINDOW_MS, Held, Place

CAST = 14  # c2s 0x01A's ActionID for a cast
ROD, BAIT = 2, 3  # 0x050's EquipKind: the range and ammo slots
# 0x037's server_status once a hooked fight ends, as LSB's animation.yaml names them.
OUTCOME = {58: "caught", 59: "rod break", 60: "line break", 61: "monster", 62: "lost"}
# The zone's fishing messages, from its own offset, as LSB's FISHMESSAGEOFFSET numbers them; retail's agree.
NOTHING, KEEN, ONE, MANY, GAVE_UP = 0x04, 0x35, 0x27, 0x0E, 200
HOOK = {0x08: "small fish", 0x32: "large fish", 0x33: "item", 0x34: "monster"}
FEELING = {0x29: "good", 0x2A: "bad", 0x2B: "terrible", 0x2C: "no skill", 0x2D: "no skill sure",
           0x2E: "no skill positive", 0x36: "epic"}  # fmt: skip
GAME = ("stamina", "arrow_delay", "regen", "move_frequency", "arrow_damage", "arrow_regen", "time",
        "angler_sense", "intuition")  # fmt: skip


class Fishing(Extractor):
    """The character's fishing: each cast (c2s 0x01A, action 14), the minigame the zone sends for a bite
    (0x115), how the client ended it (c2s 0x110 mode 3), how the zone took it (0x037's animation), and the
    catch it names (0x027). The zone's fishing messages (0x036) have ids that differ by zone; they are kept
    as sent."""

    name = "fishing"
    # 2: the zone's offset is the one that explains the most casts, not a refusal's; 3: an emptied slot holds
    # no rod or bait
    version = 3
    doc = "Each cast the character made: where, with what rod and bait, what bit, its minigame, its outcome."
    reads = Place.reads | Held.reads | {
        (1, 0x01A), (1, 0x110), (0, 0x115), (0, 0x027), (0, 0x02A), (0, 0x036), (0, 0x037), (0, 0x050)
    }  # fmt: skip
    tables = (
        Table(
            "fishing",
            "One row per cast (c2s 0x01A, action 14), and per minigame (0x115) the capture holds no cast for."
            " The minigame columns are empty when nothing bit.",
            (
                *PLACE,
                Column("rod_id", pa.int32(), "The item in the range slot (0x050) at the cast."),
                Column("bait_id", pa.int32(), "The item in the ammo slot (0x050) at the cast."),
                Column("hook_ms", pa.int64(), "When the minigame (0x115) came, Unix milliseconds."),
                Column("end_ms", pa.int64(), "When the outcome's animation (0x037) came, Unix milliseconds."),
                Column(
                    "stamina",
                    pa.int32(),
                    "0x115 stamina: the fish's HP. LSB sends rand(95, 105) * ((skill_level + 36) / 2) for one"
                    " fish (CalculateStamina).",
                ),
                Column(
                    "arrow_delay",
                    pa.int32(),
                    "0x115 arrow_delay. LSB: base_delay plus the rod's sm/lg_delay_bonus, at most 15.",
                ),
                Column("regen", pa.int32(), "0x115 regen: from the character's skill against skill_level."),
                Column(
                    "move_frequency",
                    pa.int32(),
                    "0x115 move_frequency. LSB: base_move plus the rod's sm/lg_move_bonus, at most 15.",
                ),
                Column(
                    "arrow_damage",
                    pa.int32(),
                    "0x115 arrow_damage. LSB: difficulty * fish_attack / 100 * 20 (fishing_rod.fish_attack).",
                ),
                Column(
                    "arrow_regen",
                    pa.int32(),
                    "0x115 arrow_regen. LSB: arrow_damage / 20 * fish_recovery / 100, times 10.",
                ),
                Column("time", pa.int32(), "0x115 time, in seconds. LSB: the rod's fish_time, with bonuses."),
                Column(
                    "angler_sense",
                    pa.int32(),
                    "0x115 angler_sense. LSB: 0 a small fish, 1 a large one, 2 and 3 the same with a keen"
                    " angler's sense (fishing_fish.size_type).",
                ),
                Column("intuition", pa.int32(), "0x115 intuition: LSB's lucky timing."),
                Column(
                    "hook",
                    pa.string(),
                    "What bit, from the zone's message: small fish, large fish, item, or monster. Empty when"
                    " the capture's zone has no cast that caught nothing to read the zone's messages by.",
                ),
                Column(
                    "feeling",
                    pa.string(),
                    "The message after the bite: good, bad, terrible, no skill, no skill sure, no skill"
                    " positive, keen, or epic, as LSB's FISHMESSAGEOFFSET names them.",
                ),
                Column(
                    "sensed_id",
                    pa.int32(),
                    "The fish a keen angler's sense named (0x02A), whether or not it was caught.",
                ),
                Column(
                    "reel",
                    pa.int32(),
                    "How the client ended the minigame (c2s 0x110 mode 3, para): 0 reeled in, 200 gave up,"
                    " 300 out of time, else the fish's stamina left.",
                ),
                Column(
                    "outcome",
                    pa.string(),
                    "nothing when nothing bit; else the character's animation (0x037) after the minigame:"
                    " caught, rod break, line break, monster, gave up (reel 200), or lost.",
                ),
                Column("item_id", pa.int32(), "What was caught, as the catch message (0x027) names it."),
                Column(
                    "count", pa.int32(), "How many were caught: more than one only by the zone's own message."
                ),
                Column(
                    "messages",
                    pa.list_(pa.int32()),
                    "The zone's fishing messages (0x036) to the character during the cast, as sent.",
                ),
            ),
        ),
    )

    def __init__(self):
        self.place = Place()
        self.held = Held()
        self.equip: dict[int, tuple[int, int]] = {}  # EquipKind -> (container, slot)
        self.row: dict | None = None  # the cast now
        self.seen: list[tuple[dict, dict]] = []  # each row, with the messages finish() names it by

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if self.place.see(p, f):
            if p.opcode == 0x00A:
                self.row = None
            return
        key = (p.direction, p.opcode)
        me = world.character_id
        if key in Held.reads:
            item = self.held.gained(p, f)
            if item is not None and self.row is not None and self.row["hook_ms"] is not None:
                self.seen[-1][1].setdefault("gained", []).append((p.ts_ms, item))
        elif key == (0, 0x050):
            self.equip[f("EquipKind")] = (f("Category"), f("PropertyItemIndex"))
        elif key == (1, 0x01A):
            if f("ActionID") == CAST:
                self._cast(p, world, emit)
        elif key == (0, 0x115):
            if self.row is None or self.row["hook_ms"] is not None:
                self._cast(p, world, emit)
            self.row.update({g: f(g) for g in GAME}, hook_ms=p.ts_ms)
        elif self.row is None or (p.direction == 0 and me and f("UniqueNo") != me):
            return
        elif key == (1, 0x110):
            if f("mode") == 3:
                self.row["reel"] = f("para")
        elif key == (0, 0x036):
            self.row["messages"].append(f("MesNum"))
        elif self.row["hook_ms"] is None:
            return
        elif key == (0, 0x037):
            if (status := OUTCOME.get(f("server_status"))) and not self.row["outcome"]:
                self.row.update(outcome=status, end_ms=p.ts_ms)
        elif key == (0, 0x02A):
            self.seen[-1][1].setdefault("sense", (f("MesNum"), f("num[0]")))
        elif key == (0, 0x027):
            self.seen[-1][1].setdefault("catch", (f("MesNum"), f("Num1[0]"), f("Num1[1]"), p.ts_ms))

    def _cast(self, p, world, emit):
        # Index 0 empties a slot; (0, 0) is the gil.
        rod, bait = (world.items.get(e) if (e := self.equip.get(k)) and e[1] else None for k in (ROD, BAIT))
        self.row = emit(
            "fishing", p, **self.place.row(p, world), rod_id=rod, bait_id=bait, hook_ms=None, end_ms=None,
            **dict.fromkeys(GAME), hook=None, feeling=None, sensed_id=None, reel=None, outcome=None,
            item_id=None, count=None, messages=[],
        )  # fmt: skip
        self.seen.append((self.row, {}))

    def finish(self, world: World, emit: Emit) -> None:
        """Name what each cast's messages say. A zone numbers its fishing messages from an offset of its own:
        the one that explains the most of its casts, a cast that caught nothing by its one message (offset +
        4), a bite by its first two (what bit, then the feeling). A cast refused for want of bait (offset + 2)
        explains no offset, and neither does a tie."""
        base = {}
        for zone in {r["zone_id"] for r, _ in self.seen}:
            casts = [(r["hook_ms"] is not None, r["messages"]) for r, _ in self.seen if r["zone_id"] == zone]
            tried = {said[0] - h for bit, said in casts if said for h in (HOOK if bit else (NOTHING,))}
            scored = sorted((sum(_explains(at, bit, said) for bit, said in casts), at) for at in tried)[::-1]
            if scored and scored[0][0] and (len(scored) == 1 or scored[1][0] < scored[0][0]):
                base[zone] = scored[0][1]
        for r, seen in self.seen:
            if r["hook_ms"] is None:
                r["outcome"] = "nothing"
                continue
            if r["outcome"] == "lost" and r["reel"] == GAVE_UP:
                r["outcome"] = "gave up"
            at = base.get(r["zone_id"])
            said = [m - at for m in r["messages"]] if at is not None else []
            r["hook"] = next((HOOK[m] for m in said if m in HOOK), None)
            r["feeling"] = next((FEELING[m] for m in said if m in FEELING), None)
            if (sense := seen.get("sense")) and at is not None and sense[0] - at == KEEN:
                r["feeling"], r["sensed_id"] = "keen", sense[1]
            if (catch := seen.get("catch")) and _caught(at, catch, seen.get("gained", [])):
                r["item_id"] = catch[1]
                r["count"] = catch[2] if at is not None and catch[0] - at == MANY else 1


def _explains(at: int, bit: bool, said: list[int]) -> bool:
    """Whether offset at reads a cast's messages as LSB numbers them: 'nothing', or what bit and a feeling."""
    if not said:
        return False
    if not bit:
        return len(said) == 1 and said[0] - at == NOTHING
    return said[0] - at in HOOK and (len(said) < 2 or said[1] - at in FEELING)


def _caught(at: int | None, catch: tuple, gained: list[tuple[int, int]]) -> bool:
    """Whether a 0x027 names this cast's catch: the zone's catch message by its offset; with no offset, the
    item the main inventory gained since the bite, up to 3 s after it. A zone's other 0x027 lines (a
    quest's) name items it never gave."""
    message, item, _, ts = catch
    if at is not None:
        return message - at in (ONE, MANY)
    return any(g == item and t <= ts + WINDOW_MS for t, g in gained)
