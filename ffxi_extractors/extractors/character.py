import pyarrow as pa

from ..extract import Column, Extractor, Table
from . import combat

JOBS = ("", "WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK", "BST", "BRD", "RNG", "SAM", "NIN", "DRG",
        "SMN", "BLU", "COR", "PUP", "DNC", "SCH", "GEO", "RUN")  # fmt: skip
STATS = ("str", "dex", "vit", "agi", "int", "mnd", "chr")
# /checkparam replies, by message, as captain's checkparam addon reads them
PARAMS = {712: "main", 713: "sub", 714: "ranged", 715: "defense"}
SLOTS = ("main", "sub", "range", "ammo", "head", "body", "hands", "legs", "feet", "neck", "waist",
         "ear1", "ear2", "ring1", "ring2", "back")  # fmt: skip


def job(n):
    return JOBS[n] if n is not None and 0 <= n < len(JOBS) else None


class Character(Extractor):
    name = "character"
    version = 7  # 3: a captain log names the character by its 0x037; 4: 0x01E empties a slot; 5: no slot
    # is null, not "None"; 6: a resent /checkparam reply gives one row; 7: attack and defence
    doc = "Who recorded the capture: job, levels, stats, gear, and /checkparam replies as they changed."
    # The inventory lists (0x01F, 0x020) can come after the gear at login, so they fill in its items.
    reads = frozenset({(0, 0x061), (0, 0x050), (0, 0x01F), (0, 0x020), (0, 0x029)})

    def __init__(self):
        self.unnamed: dict[tuple[int, int], list[dict]] = {}  # (container, index) -> gear rows waiting
        self.resends = combat.Resends()

    tables = (
        Table(
            "character",
            "One row per status update (0x061) of the recording character.",
            (
                Column(
                    "character_id",
                    pa.int64(),
                    "The recording character's id, from its zone-in or, in a captain log, its status"
                    " (0x037).",
                ),
                Column("character", pa.string(), "Its name."),
                Column("main_job", pa.string(), "Main job, as WAR, MNK, ..."),
                Column("main_level", pa.int32(), "Main job level."),
                Column("sub_job", pa.string(), "Support job."),
                Column("sub_level", pa.int32(), "Support job level."),
                Column("hp_max", pa.int32(), "Maximum HP."),
                Column("mp_max", pa.int32(), "Maximum MP."),
                *(Column(s, pa.int32(), f"{s.upper()}, base.") for s in STATS),
                *(Column(s + "_bonus", pa.int32(), f"{s.upper()} added by gear and effects.") for s in STATS),
                Column("attack", pa.int32(), "Attack, as the status update gives it (statusdata.atk)."),
                Column("defense", pa.int32(), "Defence (statusdata.def)."),
            ),
        ),
        Table(
            "character_gear",
            "One row per equipment change (0x050) of the recording character.",
            (
                Column("character_id", pa.int64(), "The recording character's id."),
                Column("slot", pa.string(), "The slot: main, sub, range, ammo, head, body, ..."),
                Column(
                    "item_id",
                    pa.int32(),
                    "The item in the slot, as the inventory lists it then or, at login, just after.",
                ),
                Column("container", pa.int32(), "Where the item is kept: 0 inventory, 8 wardrobe, ..."),
                Column("item_index", pa.int32(), "Its position there; 0 empties the slot."),
            ),
        ),
        Table(
            "character_params",
            "One row per /checkparam reply about the recording character (0x029 712 to 715), as captain's"
            " checkparam addon reads them. A /checkparam sends one per hand it fights with, then 715.",
            (
                Column("character_id", pa.int64(), "The recording character's id."),
                Column(
                    "kind",
                    pa.string(),
                    "main (712), sub (713), ranged (714): accuracy and attack; defense (715): evasion"
                    " and defense.",
                ),
                Column("accuracy", pa.int32(), "Accuracy, for main, sub, and ranged."),
                Column("attack", pa.int32(), "Attack, for main, sub, and ranged."),
                Column("evasion", pa.int32(), "Evasion, for defense."),
                Column("defense", pa.int32(), "Defense, for defense."),
            ),
        ),
    )

    def packet(self, p, f, world, emit):
        if p.opcode == 0x061:
            emit(
                "character",
                p,
                character_id=world.character_id,
                character=world.character,
                main_job=job(f("statusdata.mjob_no")),
                main_level=f("statusdata.mjob_lv"),
                sub_job=job(f("statusdata.sjob_no")),
                sub_level=f("statusdata.sjob_lv"),
                hp_max=f("statusdata.hpmax"),
                mp_max=f("statusdata.mpmax"),
                **{s: f(f"statusdata.bp_base[{i}]") for i, s in enumerate(STATS)},
                **{s + "_bonus": f(f"statusdata.bp_adj[{i}]") for i, s in enumerate(STATS)},
                attack=f("statusdata.atk"),
                defense=f("statusdata.def"),
            )
        elif p.opcode == 0x050:
            slot, container, index = f("EquipKind"), f("Category"), f("PropertyItemIndex")
            row = emit(
                "character_gear",
                p,
                character_id=world.character_id,
                slot=None if slot is None else SLOTS[slot] if slot < len(SLOTS) else str(slot),
                item_id=world.items.get((container, index)) if index else None,
                container=container,
                item_index=index,
            )
            if index and row["item_id"] is None:
                self.unnamed.setdefault((container, index), []).append(row)
        elif p.opcode == 0x029:
            kind = PARAMS.get(f("MessageNum"))
            if kind is None or not world.character_id or f("UniqueNoTar") != world.character_id:
                return
            if self.resends.is_resend(p):
                return
            a, b = f("Data"), f("Data2")
            stats = {"evasion": a, "defense": b} if kind == "defense" else {"accuracy": a, "attack": b}
            emit("character_params", p, character_id=world.character_id, kind=kind, **stats)
        else:
            key = (f("Category"), f("ItemIndex"))
            if key in self.unnamed and (item := world.items.get(key)) is not None:
                for row in self.unnamed.pop(key):
                    row["item_id"] = item
