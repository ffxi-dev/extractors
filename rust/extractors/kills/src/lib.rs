//! battle/kills.py: each mob defeat the capture saw, with its claim, its Treasure Hunter level, and the gil
//! its treasure pool entry carried. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat::{Resends, is_defeat, is_mob};
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static CLAIMED: Field = Field::new(S2C, 0x00E, "SendFlg.ClaimStatus");
static CLAIM: Field = Field::new(S2C, 0x00E, "BtTargetID");
static POOL_MOB: Field = Field::new(S2C, 0x0D2, "TargetUniqueNo");
static GOLD: Field = Field::new(S2C, 0x0D2, "Gold");
static ENTRY: Field = Field::new(S2C, 0x0D2, "Entry");
static CASTER: Field = Field::new(S2C, 0x029, "UniqueNoCas");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");
static DATA: Field = Field::new(S2C, 0x029, "Data");

/// LSB msg_basic TreasureHunterUp.
const TH_UP: i64 = 603;
/// A pool entry this long after a defeat is not its gil.
const GIL_MS: i64 = 60_000;

pub static META: Meta = Meta {
    name: "kills",
    version: 5,
    reads: &[(S2C, 0x028), (S2C, 0x029), (S2C, 0x00E), (S2C, 0x00A), (S2C, 0x0D2)],
    tables: &[Table {
        name: "kills",
        columns: &[
            ("mob_id", I64),
            ("killer_id", I64),
            ("claim_id", I64),
            ("claimed_by_party", Bool),
            ("th_level", I32),
            ("gil", I64),
            ("message", I32),
            ("zone_id", I32),
        ],
    }],
    sparse: true,
};

type Id = Option<i64>;

#[derive(Default)]
pub struct Kills {
    /// Mob -> the highest Treasure Hunter level seen.
    th: HashMap<Id, i64>,
    /// Mob -> its last claimer.
    claims: HashMap<Id, i64>,
    resends: Resends,
    /// Mob -> its last defeat by the character, its party, or their claim: (row, ts_ms).
    ours: HashMap<Id, (RowId, i64)>,
}

impl Kills {
    fn raise(&mut self, mob: Id, level: Option<i64>) {
        let th = self.th.entry(mob).or_insert(0);
        *th = (*th).max(level.unwrap_or(0));
    }
}

impl Extractor for Kills {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.opcode {
            0x00A => {
                self.th.clear();
                self.claims.clear();
                return;
            }
            0x00E => {
                let uid = UID.int(f);
                if DESPAWN.flag(f) {
                    self.claims.remove(&uid);
                    self.th.remove(&uid);
                } else if CLAIMED.flag(f)
                    && let Some(claim) = CLAIM.int(f).filter(|&c| c != 0)
                {
                    self.claims.insert(uid, claim);
                }
                return;
            }
            // One entry of a defeat's pool carries the gold; one seen again at a zone-in is old (Entry 1).
            0x0D2 => {
                if let Some(&(row, ts)) = self.ours.get(&POOL_MOB.int(f))
                    && let Some(gold) = GOLD.int(f).filter(|&g| g != 0)
                    && !ENTRY.flag(f)
                    && p.ts_ms - ts <= GIL_MS
                {
                    out.set(row, "gil", gold);
                }
                return;
            }
            _ => {}
        }
        if self.resends.is_resend(p) {
            return;
        }
        if p.opcode == 0x028 {
            for t in &f.action().targets {
                if !is_mob(t.id) {
                    continue;
                }
                for r in &t.results {
                    if r.message == Some(TH_UP) {
                        self.raise(t.id, r.value);
                    }
                    if let Some(x) = &r.proc
                        && x.message == Some(TH_UP)
                    {
                        self.raise(t.id, x.value);
                    }
                }
            }
            return;
        }
        let (mob, msg) = (TARGET.int(f), MESSAGE.int(f));
        if !is_mob(mob) {
            return;
        }
        if msg == Some(TH_UP) {
            self.raise(mob, DATA.int(f));
        } else if is_defeat(msg) {
            let killer = CASTER.int(f);
            let claim = self.claims.remove(&mob);
            let killer = if msg == Some(6) && killer != mob { killer } else { None };
            let row = out.emit(
                "kills",
                Some(p),
                row! {
                    mob_id: mob,
                    killer_id: killer,
                    claim_id: claim,
                    claimed_by_party: claim.map(|c| world.claimed_by_party(Some(c))),
                    th_level: self.th.remove(&mob),
                    message: msg,
                    zone_id: world.zone,
                },
            );
            if world.claimed_by_party(killer) || world.claimed_by_party(claim) {
                self.ours.insert(mob, (row, p.ts_ms));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::combat::P;
    use xc_core::testing::{Drive, MEMBER, MOB, MapFields, PLAYER, STRANGER, drive};

    fn claim(by: i64) -> (u16, MapFields) {
        (
            0x00E,
            MapFields::new()
                .int("UniqueNo", MOB)
                .int("ActIndex", 0x010)
                .int("SendFlg.ClaimStatus", 1)
                .int("BtTargetID", by),
        )
    }

    fn defeat(by: i64, message: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("UniqueNoCas", by).int("UniqueNoTar", MOB).int("ActIndexTar", 0x010);
        (0x029, f.int("MessageNum", message))
    }

    /// A melee hit whose added effect raises Treasure Hunter.
    fn treasure_hunter(level: i64) -> (u16, MapFields) {
        let f = MapFields::new()
            .int(&format!("{P}actor_id"), PLAYER)
            .int(&format!("{P}target_count"), 1)
            .int(&format!("{P}targets[0].target_id"), MOB)
            .int(&format!("{P}targets[0].result_count"), 1)
            .int(&format!("{P}targets[0][0].message"), 1)
            .int(&format!("{P}targets[0][0].value"), 30)
            .int(&format!("{P}targets[0][0].proc.message"), 603)
            .int(&format!("{P}targets[0][0].proc.value"), level);
        (0x028, f)
    }

    fn pool(gold: i64, item: i64, entry: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("TargetUniqueNo", MOB).int("TrophyItemNo", item).int("TrophyItemNum", 1);
        (0x0D2, f.int("Gold", gold).int("Entry", entry).int("TrophyItemIndex", 0))
    }

    fn message(n: i64, value: i64) -> (u16, MapFields) {
        (
            0x029,
            MapFields::new()
                .int("UniqueNoCas", PLAYER)
                .int("UniqueNoTar", PLAYER)
                .int("MessageNum", n)
                .int("Data", value),
        )
    }

    fn kills(steps: Vec<(u16, MapFields)>) -> Vec<Vec<V>> {
        rows(&drive(&mut Kills::default(), steps, Drive::default()))
    }

    fn rows(out: &xc_core::Out) -> Vec<Vec<V>> {
        let k = out.rows("kills");
        let cols = ["mob_id", "killer_id", "claim_id", "claimed_by_party", "th_level", "gil"];
        (0..k.len()).map(|i| cols.iter().map(|c| k.get(i, c)).collect()).collect()
    }

    // test_loot.py
    #[test]
    fn a_party_kill() {
        let k = kills(vec![claim(MEMBER), claim(0), defeat(PLAYER, 6)]);
        assert_eq!(k[0][..4], [V::Int(MOB), V::Int(PLAYER), V::Int(MEMBER), V::Bool(true)]);
    }

    #[test]
    fn a_despawn_ends_the_claim_and_treasure_hunter() {
        let despawn = (0x00E, MapFields::new().int("UniqueNo", MOB).int("ActIndex", 0x010).int("SendFlg.Despawn", 1));
        let k = kills(vec![claim(PLAYER), treasure_hunter(4), despawn, defeat(STRANGER, 6)]);
        assert_eq!((k.len(), &k[0][2..5]), (1, &[V::Null, V::Null, V::Null][..]));
    }

    #[test]
    fn someone_elses_kill() {
        let k = kills(vec![claim(STRANGER), defeat(STRANGER, 6)]);
        assert_eq!((&k[0][1], &k[0][3]), (&V::Int(STRANGER), &V::Bool(false)));
    }

    #[test]
    fn treasure_hunter_goes_up() {
        let k = kills(vec![
            treasure_hunter(2),
            treasure_hunter(4),
            treasure_hunter(3),
            defeat(PLAYER, 6),
            defeat(PLAYER, 20),
        ]);
        let got: Vec<_> = k.iter().map(|r| (r[4].clone(), r[1].clone())).collect();
        assert_eq!(got, [(V::Int(4), V::Int(PLAYER)), (V::Null, V::Null)]);
    }

    #[test]
    fn a_defeats_gil_is_its_pool_entrys_gold() {
        let regime = || vec![message(558, 2), message(559, 0), message(565, 575)];
        let gil = |mut steps: Vec<(u16, MapFields)>, tail: Vec<(u16, MapFields)>| {
            steps.extend(tail);
            let k = kills(steps);
            assert_eq!(k.len(), 1);
            k[0][5].clone()
        };
        let mut tail = regime();
        tail.push(pool(114, 0, 0));
        assert_eq!(gil(vec![claim(MEMBER), defeat(MEMBER, 6)], tail), V::Int(114));
        assert_eq!(gil(vec![claim(PLAYER), defeat(PLAYER, 6)], regime()), V::Null);
        // Another's kill, and the pool sent again at a zone-in, give none.
        assert_eq!(gil(vec![claim(STRANGER), defeat(STRANGER, 6)], vec![pool(500, 0, 0)]), V::Null);
        assert_eq!(gil(vec![claim(PLAYER), defeat(PLAYER, 6)], vec![pool(80, 4097, 1)]), V::Null);
    }

    /// test_world.py's test_a_captain_log_counts_the_characters_claims_and_checkparam: no zone-in names
    /// the character; its status (0x037) does.
    #[test]
    fn a_captain_log_names_the_character_by_its_status() {
        let steps = vec![
            (0x037, MapFields::new().int("UniqueNo", PLAYER)),
            claim(PLAYER),
            (0x029, MapFields::new().int("UniqueNoCas", PLAYER).int("UniqueNoTar", MOB).int("MessageNum", 6)),
        ];
        let k = rows(&drive(&mut Kills::default(), steps, Drive { me: 0, ..Drive::default() }));
        assert_eq!(k.iter().map(|r| r[3].clone()).collect::<Vec<_>>(), [V::Bool(true)]);
    }
}
