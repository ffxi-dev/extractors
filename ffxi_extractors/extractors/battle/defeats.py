import pyarrow as pa

from ffxi_extractors import combat
from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World


class Defeats(Extractor):
    name = "defeats"
    version = 1
    doc = "Each time the character was defeated, and by whom (0x029 97 or 20)."
    reads = frozenset({(0, 0x029)})
    tables = (
        Table(
            "defeats",
            "One row per defeat of the character: 0x029 message 97 ('was defeated by') or 20 ('falls to"
            " the ground'), resends skipped.",
            (
                Column("killer_id", pa.int64(), "Who defeated it, for message 97; none for 20."),
                Column(
                    "killer_name",
                    pa.string(),
                    "A mob or NPC killer's name as the client spells it (0x00E), as the bestiary names mobs.",
                ),
                Column("message", pa.int32(), "97 (defeated by) or 20 (falls to the ground)."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.resends = combat.Resends()

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        msg = f("MessageNum")
        if msg not in (20, 97) or f("UniqueNoTar") != world.character_id or self.resends.is_resend(p):
            return
        killer = f("UniqueNoCas") if msg == 97 else None
        name = world.name(killer) if combat.is_mob(killer) else None
        emit("defeats", p, killer_id=killer, killer_name=name,
             message=msg, zone_id=world.zone)  # fmt: skip
