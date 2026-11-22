//! battle/delay.py, ported from captain's attackdelay: the time between an actor's auto-attack rounds, what
//! each round's swings did, and the recorder's TP gain from a mob's hit. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat::{ActResult, Resends, is_defeat, is_mob};
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

/// AttackHits, AttackCrit.
const HIT: [i64; 2] = [1, 67];
/// Reactions: a counter, and a counter a shadow absorbed.
const COUNTER: [i64; 2] = [33, 14];
/// A player was defeated.
const PLAYER_DEFEATED: i64 = 97;
const CUT_SHORT_MS: i64 = 1000;

static TP_UID: Field = Field::new(S2C, 0x0DF, "UniqueNo");
static TP: Field = Field::new(S2C, 0x0DF, "Tp");
static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");

pub static META: Meta = Meta {
    name: "delay",
    version: 5,
    reads: &[(S2C, 0x028), (S2C, 0x029), (S2C, 0x0DF), (S2C, 0x00A), (S2C, 0x00E)],
    tables: &[Table {
        name: "attack_rounds",
        columns: &[
            ("actor_id", I64),
            ("actor_is_mob", Bool),
            ("target_id", I64),
            ("interval_ms", I64),
            ("swings", I32),
            ("hits", I32),
            ("main_hand", I32),
            ("off_hand", I32),
            ("kicks", I32),
            ("targets", I32),
            ("cut_short", Bool),
            ("at_character", Bool),
            ("crits", I32),
            ("misses", I32),
            ("parried", I32),
            ("absorbed", I32),
            ("anticipated", I32),
            ("countered", I32),
            ("dodged", I32),
            ("blocked", I32),
            ("guarded", I32),
            ("other", I32),
            ("tp_gain", I32),
            ("zone_id", I32),
        ],
    }],
    sparse: true,
};

/// The outcome columns, in Python's OUTCOMES order.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Outcome {
    Crits,
    Misses,
    Parried,
    Absorbed,
    Anticipated,
    Countered,
    Dodged,
    Blocked,
    Guarded,
    Other,
}

/// A swing's outcome, in the order LSB resolves a swing; None for a plain hit.
fn outcome(r: &ActResult) -> Option<Outcome> {
    use Outcome::*;
    let (msg, react) = (r.message, r.react.as_ref().and_then(|e| e.message));
    match msg {
        Some(32) => return Some(Dodged),
        Some(70) => return Some(Parried),
        Some(31) => return Some(Absorbed),
        Some(30) => return Some(Anticipated),
        _ => {}
    }
    if react.is_some_and(|m| COUNTER.contains(&m)) {
        return Some(Countered);
    }
    if msg.is_some_and(|m| HIT.contains(&m)) {
        return match r.miss {
            Some(4) => Some(Blocked),
            Some(2) => Some(Guarded),
            _ => (msg == Some(67)).then_some(Crits),
        };
    }
    Some(if msg == Some(15) { Misses } else { Other })
}

type Id = Option<i64>;

#[derive(Default)]
pub struct Delay {
    /// Actor -> the time of its last round, None while paused.
    last: HashMap<Id, Option<i64>>,
    /// Target -> its last round's (row, ts_ms).
    recent: HashMap<Id, (RowId, i64)>,
    /// The character's TP in its last 0x0DF.
    tp: Option<i64>,
    /// A round whose TP gain the next 0x0DF gives.
    waiting: Option<RowId>,
    /// Something else touched the character since its last 0x0DF.
    spoiled: bool,
    resends: Resends,
}

impl Extractor for Delay {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let me = world.character_id;
        match p.opcode {
            0x00A => {
                self.last.clear();
                self.recent.clear();
                (self.tp, self.waiting, self.spoiled) = (None, None, false);
                return;
            }
            0x0DF => {
                let Some(tp) = TP.int(f).filter(|_| TP_UID.int(f) == me) else { return };
                if let (Some(row), false, Some(before)) = (self.waiting, self.spoiled, self.tp) {
                    out.set(row, "tp_gain", tp - before);
                }
                (self.tp, self.waiting, self.spoiled) = (Some(tp), None, false);
                return;
            }
            0x00E => {
                if DESPAWN.flag(f) {
                    self.last.remove(&UID.int(f));
                }
                return;
            }
            0x029 => {
                let msg = MESSAGE.int(f);
                if is_defeat(msg) || msg == Some(PLAYER_DEFEATED) {
                    let target = TARGET.int(f);
                    self.last.remove(&target); // as attackdelay forgets a defeated mob
                    if let Some((row, ts)) = self.recent.remove(&target) {
                        out.set(row, "cut_short", p.ts_ms - ts <= CUT_SHORT_MS);
                    }
                }
                return;
            }
            _ => {}
        }
        if self.resends.is_resend(p) {
            return;
        }
        let a = f.action();
        let (actor, cat) = (a.actor_id, a.cmd_no);
        let me_known = me.is_some_and(|m| m != 0);
        let mut on_me = a.targets.iter().filter(|t| me_known && t.id == me);
        let first_on_me = on_me.next();
        // A TP gain counts only when one mob swing that hit is all that touched the character since its
        // last 0x0DF: anything else (its own actions, other hits, spells on it) moves its TP too.
        let mut wait = false;
        if first_on_me.is_some() || (me_known && actor == me) {
            let one_hit = match (first_on_me, on_me.next()) {
                (Some(t), None) => {
                    t.results.len() == 1 && matches!(outcome(&t.results[0]), None | Some(Outcome::Crits))
                }
                _ => false,
            };
            if cat == Some(1) && is_mob(actor) && one_hit && self.waiting.is_none() && !self.spoiled {
                wait = true;
            } else {
                self.spoiled = true;
            }
        }
        if matches!(cat, Some(4 | 8 | 11)) {
            // A spell or TP move: the next round's interval includes it.
            if let Some(t) = self.last.get_mut(&actor) {
                *t = None;
            }
            return;
        }
        let Some(target) = a.targets.first().filter(|_| cat == Some(1)) else { return };
        let results = &target.results;
        let before = self.last.insert(actor, Some(p.ts_ms)).flatten();
        let mut n = [0i32; 10];
        for r in results {
            if let Some(o) = outcome(r) {
                n[o as usize] += 1;
            }
        }
        let count = |pred: &dyn Fn(&ActResult) -> bool| results.iter().filter(|r| pred(r)).count();
        let row = out.emit(
            "attack_rounds",
            Some(p),
            row! {
                actor_id: actor,
                actor_is_mob: is_mob(actor),
                target_id: target.id,
                interval_ms: before.map(|b| p.ts_ms - b),
                swings: results.len(),
                hits: count(&|r| r.message.is_some_and(|m| HIT.contains(&m))),
                main_hand: count(&|r| r.sub_kind == Some(0)),
                off_hand: count(&|r| r.sub_kind == Some(1)),
                kicks: count(&|r| matches!(r.sub_kind, Some(2 | 3))),
                targets: a.targets.len(),
                cut_short: false,
                at_character: me_known && target.id == me,
                crits: n[Outcome::Crits as usize],
                misses: n[Outcome::Misses as usize],
                parried: n[Outcome::Parried as usize],
                absorbed: n[Outcome::Absorbed as usize],
                anticipated: n[Outcome::Anticipated as usize],
                countered: n[Outcome::Countered as usize],
                dodged: n[Outcome::Dodged as usize],
                blocked: n[Outcome::Blocked as usize],
                guarded: n[Outcome::Guarded as usize],
                other: n[Outcome::Other as usize],
                zone_id: world.zone,
            },
        );
        self.recent.insert(target.id, (row, p.ts_ms));
        if wait {
            self.waiting = Some(row);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::combat::P;
    use xc_core::testing::packets::{R, act, at, message, r, status, vitals};
    use xc_core::testing::{Drive, MOB, MapFields, PLAYER, drive, raw};

    const MOB2: i64 = MOB + 1;
    const OTHER: i64 = 0x0001_0002;

    fn rounds_of(packets: Vec<(i64, (u16, Vec<u8>))>, me: i64) -> xc_core::Out {
        raw(Box::new(Delay::default()), packets.into_iter().map(|(t, p)| at(t, p)).collect(), me)
    }

    fn col(out: &xc_core::Out, c: &str) -> Vec<V> {
        let r = out.rows("attack_rounds");
        (0..r.len()).map(|i| r.get(i, c)).collect()
    }

    fn hit(actor: i64, target: i64, results: Vec<R>) -> (u16, Vec<u8>) {
        act(actor, 1, 0, &[(target, results)])
    }

    /// rounds(): the packets 3 s apart.
    fn rounds(packets: Vec<(u16, Vec<u8>)>) -> xc_core::Out {
        rounds_of(packets.into_iter().enumerate().map(|(i, p)| (3000 * i as i64, p)).collect(), PLAYER)
    }

    const NONE: V = V::Null;

    fn ints(xs: &[i64]) -> Vec<V> {
        xs.iter().map(|&x| V::Int(x)).collect()
    }

    #[test]
    fn a_mobs_ten_attacks_give_nine_intervals() {
        let hits = (0..10)
            .map(|i| {
                let mut rs = vec![r(1, 20)];
                rs.extend((0..i % 2).map(|_| r(15, 0)));
                (1000 + 3000 * i as i64, hit(MOB, PLAYER, rs))
            })
            .collect();
        let out = rounds_of(hits, PLAYER);
        let mut want = vec![NONE];
        want.extend(ints(&[3000; 9]));
        assert_eq!(col(&out, "interval_ms"), want);
        assert_eq!(col(&out, "swings")[..2], ints(&[1, 2]));
        assert!(col(&out, "hits").iter().all(|h| *h == V::Int(1)));
    }

    #[test]
    fn a_tp_move_pauses_the_delay() {
        let out = rounds_of(
            vec![
                (0, hit(MOB, PLAYER, vec![r(1, 5)])),
                (1000, act(MOB, 11, 2000, &[(PLAYER, vec![r(185, 5)])])),
                (4000, hit(MOB, PLAYER, vec![r(1, 5)])),
                (7000, hit(MOB, PLAYER, vec![r(1, 5)])),
            ],
            PLAYER,
        );
        assert_eq!(col(&out, "interval_ms"), [NONE, NONE, V::Int(3000)]);
    }

    #[test]
    fn a_resend_counts_once() {
        let p = hit(MOB, PLAYER, vec![r(1, 10)]);
        assert_eq!(rounds_of(vec![(0, p.clone()), (200, p)], PLAYER).rows("attack_rounds").len(), 1);
    }

    const OUTCOMES: [&str; 10] =
        ["crits", "misses", "parried", "absorbed", "anticipated", "countered", "dodged", "blocked", "guarded", "other"];

    /// Each row's outcome columns that are not 0.
    fn outcomes(out: &xc_core::Out) -> Vec<Vec<(&'static str, V)>> {
        let r = out.rows("attack_rounds");
        (0..r.len())
            .map(|i| OUTCOMES.iter().map(|&c| (c, r.get(i, c))).filter(|(_, v)| *v != V::Int(0)).collect())
            .collect()
    }

    #[test]
    fn each_swing_counts_under_one_outcome() {
        let swings = vec![
            r(1, 20), // a plain hit: no outcome column
            r(67, 40),
            r(15, 0),
            r(70, 0),
            r(31, 0),
            r(30, 0),
            r(32, 0),
            R { miss: 4, ..r(1, 15) },
            R { miss: 2, ..r(1, 15) },
            R { react: Some((30, 33)), ..r(1, 20) },
            R { react: Some((0, 14)), ..r(1, 0) }, // a counter a shadow absorbed, not an evasion
            R { miss: 4, ..r(67, 40) },            // a blocked critical hit is blocked
            r(999, 0),
        ];
        let out = rounds(swings.into_iter().map(|s| hit(MOB, PLAYER, vec![s])).collect());
        let one = |k: &'static str| vec![(k, V::Int(1))];
        let want = vec![
            vec![],
            one("crits"),
            one("misses"),
            one("parried"),
            one("absorbed"),
            one("anticipated"),
            one("dodged"),
            one("blocked"),
            one("guarded"),
            one("countered"),
            one("countered"),
            one("blocked"),
            one("other"),
        ];
        assert_eq!(outcomes(&out), want);
        assert_eq!(col(&out, "hits"), ints(&[1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0]));
        assert!(col(&out, "at_character").iter().all(|v| *v == V::Bool(true)));
        assert!(col(&out, "targets").iter().all(|v| *v == V::Int(1)));
        assert!(col(&out, "cut_short").iter().all(|v| *v == V::Bool(false)));
    }

    #[test]
    fn a_double_attack_into_shadows() {
        let out = rounds(vec![hit(MOB, PLAYER, vec![r(31, 0), r(1, 20)])]);
        let got = [col(&out, "swings"), col(&out, "main_hand"), col(&out, "hits")].concat();
        assert_eq!((got, outcomes(&out)), (ints(&[2, 2, 1]), vec![vec![("absorbed", V::Int(1))]]));
    }

    #[test]
    fn hands_kicks_and_targets() {
        let results = vec![r(1, 9), R { sub_kind: 1, ..r(1, 9) }, R { sub_kind: 2, ..r(15, 0) }];
        let out = rounds(vec![act(MOB, 1, 0, &[(OTHER, results), (PLAYER, vec![])])]);
        let got: Vec<V> =
            ["main_hand", "off_hand", "kicks", "targets", "at_character"].iter().flat_map(|c| col(&out, c)).collect();
        assert_eq!(got, [V::Int(1), V::Int(1), V::Int(1), V::Int(2), V::Bool(false)]);
    }

    #[test]
    fn a_round_that_kills_is_cut_short() {
        let out = rounds_of(
            vec![
                (0, hit(MOB, PLAYER, vec![r(1, 20)])),
                (500, message(MOB, PLAYER, 97, 0, 0)), // the character falls within the second
                (3000, hit(MOB2, OTHER, vec![r(1, 20)])),
                (6000, message(MOB2, OTHER, 97, 0, 0)), // three seconds on: another cause
            ],
            PLAYER,
        );
        assert_eq!(col(&out, "cut_short"), [V::Bool(true), V::Bool(false)]);
    }

    #[test]
    fn a_respawn_starts_a_new_interval() {
        let h = || hit(MOB, PLAYER, vec![r(1, 20)]);
        let out =
            rounds_of(vec![(0, h()), (2000, message(PLAYER, MOB, 6, 0, 0)), (302_000, h()), (305_000, h())], PLAYER);
        assert_eq!(col(&out, "interval_ms"), [NONE, NONE, V::Int(3000)]);
    }

    #[test]
    fn a_mob_out_of_view_starts_a_new_interval() {
        let t = format!("{P}targets[0]");
        let h = MapFields::new()
            .int(&format!("{P}actor_id"), MOB)
            .int(&format!("{P}cmd_no"), 1)
            .int(&format!("{P}target_count"), 1)
            .int(&format!("{t}.target_id"), PLAYER)
            .int(&format!("{t}.result_count"), 1)
            .int(&format!("{t}[0].message"), 1);
        let gone = MapFields::new().int("UniqueNo", MOB).int("ActIndex", MOB & 0xFFF).int("SendFlg.Despawn", 1);
        let out = drive(
            &mut Delay::default(),
            vec![(0x028, h.clone()), (0x028, h.clone()), (0x00E, gone), (0x028, h)],
            Drive { times: Some(vec![0, 3000, 4000, 90_000]), ..Drive::default() },
        );
        assert_eq!(col(&out, "interval_ms"), [NONE, V::Int(3000), NONE]);
    }

    #[test]
    fn a_hit_worth_21_tp_is_a_240_delay() {
        let out = rounds_of(
            vec![
                (0, vitals(100, PLAYER)),
                (1000, hit(MOB, PLAYER, vec![r(1, 20)])),
                (1100, vitals(500, OTHER)), // a party member's update does not count
                (1200, vitals(121, PLAYER)),
            ],
            PLAYER,
        );
        assert_eq!(col(&out, "tp_gain"), [V::Int(21)]);
    }

    #[test]
    fn tp_gains_that_cannot_be_told_apart() {
        let out = rounds_of(
            vec![
                (0, vitals(100, PLAYER)),
                (1000, hit(MOB, PLAYER, vec![r(1, 20)])),
                (2000, hit(MOB2, PLAYER, vec![r(1, 20)])), // a second hit before the update
                (2100, vitals(142, PLAYER)),
                (3000, hit(MOB, PLAYER, vec![r(1, 20), r(1, 20)])), // a double attack
                (3100, vitals(184, PLAYER)),
                (4000, hit(MOB, PLAYER, vec![r(15, 0)])), // a miss gives no TP
                (4100, vitals(184, PLAYER)),
                (5000, hit(PLAYER, MOB, vec![r(1, 30)])), // the character's own swing first
                (6000, hit(MOB, PLAYER, vec![r(1, 20)])),
                (6100, vitals(260, PLAYER)),
                (9000, hit(MOB, PLAYER, vec![r(1, 20)])),
                (9100, vitals(300, PLAYER)), // 40 more: counted
            ],
            PLAYER,
        );
        let mobs = col(&out, "actor_is_mob");
        let gains: Vec<V> =
            col(&out, "tp_gain").into_iter().zip(mobs).filter(|(_, m)| *m == V::Bool(true)).map(|(g, _)| g).collect();
        assert_eq!(gains, [NONE, NONE, NONE, NONE, NONE, V::Int(40)]);
    }

    /// No zone-in names the character in a captain log: 0x037 does.
    #[test]
    fn rounds_at_the_character_in_a_captain_log() {
        let h = || hit(MOB, PLAYER, vec![r(1, 5)]);
        let out = rounds_of(vec![(0, status(PLAYER)), (1000, h()), (4000, h())], 0);
        assert_eq!(col(&out, "at_character"), [V::Bool(true), V::Bool(true)]);
    }
}
