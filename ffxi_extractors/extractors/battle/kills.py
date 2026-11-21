import pyarrow as pa

from ffxi_extractors import combat
from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World

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

    def __init__(self):
        self.th: dict[int, int] = {}  # mob id -> highest Treasure Hunter level seen
        self.claims: dict[int, int] = {}  # mob id -> last claimer; an update may clear it before the defeat
        self.resends = combat.Resends()
        self.ours: dict[int, dict] = {}  # mob id -> its last defeat by the character, its party, their claim

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
        # One entry of a defeat's pool carries the gold; one seen again at a zone-in is old (Entry 1).
        if p.opcode == 0x0D2:
            row = self.ours.get(f("TargetUniqueNo"))
            if (gold := f("Gold")) and not f("Entry") and row and p.ts_ms - row["ts_ms"] <= GIL_MS:
                row["gil"] = gold
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
            killer = killer if msg == 6 and killer != mob_id else None
            row = emit("kills", p, mob_id=mob_id, killer_id=killer, claim_id=claim,
                       claimed_by_party=world.claimed_by_party(claim) if claim else None,
                       th_level=self.th.pop(mob_id, None), gil=None, message=msg,
                       zone_id=world.zone)  # fmt: skip
            if world.claimed_by_party(killer) or world.claimed_by_party(claim):
                self.ours[mob_id] = row
