import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table

DRAWN_IN = 232  # "<target> is drawn in!": actor and target are both the player drawn in
LEARNED = 419  # "<target> learns <spell>!": blue magic, sent to the learner once a mob it saw is defeated
NEAR = 12  # yalms: a draw-in leaves the player beside its mob, up to 12 from a large one's centre
WAIT_MS = 3000  # a drawn player's next position comes within this


class MobMessages(Extractor):
    """Draw-ins and blue magic learned, from 0x029. A draw-in's message names only the player drawn in:
    retail moves the player beside the mob first (0x05B), so the mob is the engaged one nearest the player's
    next position, the character's own (c2s 0x015), another player's (0x00D), or a trust's (0x00E). Only a
    monster in a fight draws in: an idle or dead one can stand nearer where the player lands than a large
    mob's centre (1eVb5J7AbyY- packet 1529008: Tiamat 8.6 yalms off, idle Bifrons 6.8; 1BqD_8h03mOF packet
    724257: the Diabolos fought 5.7, a dead one 1.8). Trusts and pets are no candidates: only a zone's own
    monsters draw in."""

    name = "mob_messages"
    # 2: a trust drawn in lands by its 0x00E; trusts and pets draw no one in; 3: only an engaged monster,
    # within 12 yalms
    version = 3
    doc = "Each draw-in, with the engaged mob nearest where the player landed, and each blue spell learned."
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
                    f"For a draw-in: the engaged monster (0x00E server_status 1) nearest the player's"
                    f" next position, within {NEAR} yalms and {WAIT_MS // 1000} s; none when no position"
                    " came or no engaged monster was near.",
                ),
                Column("distance", pa.float32(), "Yalms from that monster's last position, in 3D."),
                Column("spell_id", pa.int32(), "For a spell learned: the spell."),
                Column("zone_id", pa.int32(), "The zone the character was in."),
            ),
        ),
    )
