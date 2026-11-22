import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

DRAWN_IN = 232  # "<target> is drawn in!": actor and target are both the player drawn in
LEARNED = 419  # "<target> learns <spell>!": blue magic, sent to the learner once a mob it saw is defeated
NEAR = 10  # yalms: a draw-in leaves the player beside its mob
WAIT_MS = 3000  # a drawn player's next position comes within this


class MobMessages(Extractor):
    """Draw-ins and blue magic learned, from 0x029. A draw-in's message names only the player drawn in: retail
    moves the player beside the mob first (0x05B), so the mob is the one nearest the player's next position,
    the character's own (c2s 0x015), another player's (0x00D), or a trust's (0x00E). Trusts and pets are no
    candidates: only a zone's own monsters draw in."""

    name = "mob_messages"
    version = 2  # 2: a trust drawn in lands by its 0x00E; trusts and pets draw no one in
    doc = "Each draw-in, with the mob nearest where the player landed, and each blue magic spell learned."
    reads = frozenset({(0, 0x029), (0, 0x00E), (0, 0x00D), (1, 0x015), (0, 0x00A)})
    tables = (
        Table(
            "mob_messages",
            f"One row per draw-in (0x029 {DRAWN_IN}) and per blue magic spell learned (0x029 {LEARNED}),"
            " resends skipped.",
            (
                Column("kind", pa.string(), "drawn_in or learned."),
                Column("player_id", pa.int64(), "The player drawn in, or who learned the spell."),
                Column(
                    "mob_id",
                    pa.int64(),
                    f"For a draw-in: the monster nearest the player's next position, within {NEAR} yalms and"
                    f" {WAIT_MS // 1000} s; none when no position came or no monster was near.",
                ),
                Column("distance", pa.float32(), "Yalms from that monster's last position, in 3D."),
                Column("spell_id", pa.int32(), "For a spell learned: the spell."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
