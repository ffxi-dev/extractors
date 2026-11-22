import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

STATS = ("str", "dex", "vit", "agi", "int", "mnd", "chr")
SLOTS = ("main", "sub", "range", "ammo", "head", "body", "hands", "legs", "feet", "neck", "waist",
         "ear1", "ear2", "ring1", "ring2", "back")  # fmt: skip


class Character(Extractor):
    name = "character"
    version = 7  # 3: a captain log names the character by its 0x037; 4: 0x01E empties a slot; 5: no slot
    # is null, not "None"; 6: a resent /checkparam reply gives one row; 7: attack and defence
    doc = "Who recorded the capture: job, levels, stats, gear, and /checkparam replies as they changed."
    # The inventory lists (0x01F, 0x020) can come after the gear at login, so they fill in its items.
    reads = frozenset({(0, 0x061), (0, 0x050), (0, 0x01F), (0, 0x020), (0, 0x029)})

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
