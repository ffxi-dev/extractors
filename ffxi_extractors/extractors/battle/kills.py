import pyarrow as pa

from ffxi_extractors import combat
from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World

TH_UP = (
    603  # LSB msg_basic TreasureHunterUp: "Treasure Hunter effectiveness against <target> increases to <n>"
)


class Kills(Extractor):
    name = "kills"
    version = 3  # 2: a captain log names the character by its 0x037; 3: a despawn clears the claim and TH,
    # and the party follows 0x0E2 and 0x0C8
    doc = "Each mob defeat the capture saw, with its claim and Treasure Hunter level."
    reads = frozenset({(0, 0x028), (0, 0x029), (0, 0x00E), (0, 0x00A)})
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
                Column("message", pa.int32(), "6 (defeats) or 20 (falls to the ground)."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )

    def __init__(self):
        self.th: dict[int, int] = {}  # mob id -> highest Treasure Hunter level seen
        self.claims: dict[int, int] = {}  # mob id -> last claimer; an update may clear it before the defeat
        self.resends = combat.Resends()

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x00A:
            self.th.clear()
            self.claims.clear()
            return
        if p.opcode == 0x00E:
            uid = f("UniqueNo")
            if f("SendFlg.Despawn"):  # it may die and respawn out of view, unclaimed
                self.claims.pop(uid, None)
                self.th.pop(uid, None)
            elif f("SendFlg.ClaimStatus") and (claim := f("BtTargetID")):
                self.claims[uid] = claim
            return
        if self.resends.is_resend(p):
            return
        if p.opcode == 0x028:
            for target_id, results in combat.action(f)["targets"]:
                for r in results:
                    for x in (r, r["proc"]):
                        if x and x["message"] == TH_UP and combat.is_mob(target_id):
                            self.th[target_id] = max(self.th.get(target_id, 0), x["value"] or 0)
            return
        mob_id, msg = f("UniqueNoTar"), f("MessageNum")
        if not combat.is_mob(mob_id):
            return
        if msg == TH_UP:
            self.th[mob_id] = max(self.th.get(mob_id, 0), f("Data") or 0)
        elif msg in combat.DEFEAT:
            killer = f("UniqueNoCas")
            claim = self.claims.pop(mob_id, None)
            emit("kills", p, mob_id=mob_id, killer_id=killer if msg == 6 and killer != mob_id else None,
                 claim_id=claim, claimed_by_party=world.claimed_by_party(claim) if claim else None,
                 th_level=self.th.pop(mob_id, None), message=msg, zone_id=world.zone)  # fmt: skip
