import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

TH_UP = (
    603  # LSB msg_basic TreasureHunterUp: "Treasure Hunter effectiveness against <target> increases to <n>"
)
# A defeated mob's gil comes with its treasure pool entry (0x0D2's Gold, LSB: "Gil Found"), whole, before the
# party splits it, and goes into the bags with no message. The pool comes with the defeat or soon after.
GIL_MS = 60_000


class Kills(Extractor):
    name = "kills"
    version = 5  # 2: a captain log names the character by its 0x037; 3: a despawn clears the claim and TH,
    # and the party follows 0x0E2 and 0x0C8; 4: gil and players, from 565; 5: gil from the pool's Gold, which
    # is the whole find (565 after a defeat is a training regime's reward), so no players
    doc = "Each mob defeat the capture saw, with its claim and Treasure Hunter level."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x00E), (0, 0x00A), (0, 0x0D2)})
    tables = (
        Table(
            "kills",
            "One row per mob defeat (0x029 6 or 20). Claims come from the mob's updates (0x00E), so a mob"
            " whose claim the capture never saw has none.",
            (
                Column("mob_id", pa.int64(), "The mob."),
                Column(
                    "killer_id",
                    pa.int64(),
                    "Who defeated it, for message 6; none for 20 (falls to the ground).",
                ),
                Column(
                    "claim_id",
                    pa.int64(),
                    "Who last claimed it since it last despawned, from the last update that named a claimer.",
                ),
                Column(
                    "claimed_by_party",
                    pa.bool_(),
                    "Whether that was the character or its party or alliance; none if no claim was seen.",
                ),
                Column(
                    "th_level",
                    pa.int32(),
                    "The highest Treasure Hunter level the battle messages showed on this mob since it last"
                    f" died, despawned, or the character zoned (message {TH_UP}); none if they showed none.",
                ),
                Column(
                    "gil",
                    pa.int64(),
                    "The gil it gave, whole, before the party splits it: the Gold of its treasure pool entry"
                    f" (0x0D2) within {GIL_MS // 1000} s of a defeat by the character, its party, or their"
                    " claim. None if no entry carried any.",
                ),
                Column("message", pa.int32(), "6 (defeats) or 20 (falls to the ground)."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
