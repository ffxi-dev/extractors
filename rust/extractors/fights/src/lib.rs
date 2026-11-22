//! battle/fights.py: one row per mob life the capture saw fight, from the first action between it and a
//! player, Trust, or pet to its defeat, despawn, a zone change, three minutes idle, or the capture's end. Its
//! Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat::{Resends, is_defeat, is_mob};
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

/// A fight with no action between its mob and a player, Trust, or pet for this long is over.
const IDLE_MS: i64 = 180_000;

static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");

pub static META: Meta = Meta {
    name: "fights",
    version: 3,
    reads: &[(S2C, 0x028), (S2C, 0x029), (S2C, 0x00E), (S2C, 0x00A)],
    tables: &[Table {
        name: "fights",
        columns: &[
            ("mob_id", I64),
            ("end_idx", I64),
            ("end_ms", I64),
            ("outcome", Str),
            ("actions", I32),
            ("actions_by", I32),
            ("zone_id", I32),
        ],
    }],
    sparse: true,
};

/// An open fight: its row, and what the row will say when it closes.
struct Fight {
    row: RowId,
    end_idx: i64,
    end_ms: i64,
    actions: i64,
    actions_by: i64,
}

#[derive(Default)]
pub struct Fights {
    /// Mob -> its open fight.
    open: HashMap<i64, Fight>,
    resends: Resends,
    /// The last packet's time, to tell at the capture's end which fights went idle.
    last_ms: i64,
    /// This packet's mobs, kept between packets.
    mobs: Vec<i64>,
}

fn write(out: &mut Out, f: &Fight, outcome: &str) {
    out.set(f.row, "end_idx", f.end_idx);
    out.set(f.row, "end_ms", f.end_ms);
    out.set(f.row, "actions", f.actions);
    out.set(f.row, "actions_by", f.actions_by);
    out.set(f.row, "outcome", outcome);
}

impl Fights {
    /// Close a fight at p; it ends at p only when end is set, else at its last action. A fight already idle
    /// for IDLE_MS was disengaged, whatever closes it now.
    fn close(&mut self, mob: i64, mut outcome: &str, p: (u64, i64), mut end: bool, out: &mut Out) {
        let mut f = self.open.remove(&mob).unwrap();
        if p.1 - f.end_ms > IDLE_MS {
            (outcome, end) = ("disengaged", false);
        }
        if end {
            (f.end_idx, f.end_ms) = (p.0 as i64, p.1);
        }
        write(out, &f, outcome);
    }

    fn expire(&mut self, mob: i64, p: (u64, i64), out: &mut Out) {
        if self.open.get(&mob).is_some_and(|f| p.1 - f.end_ms > IDLE_MS) {
            self.close(mob, "disengaged", p, false, out);
        }
    }

    fn start(&mut self, mob: i64, p: &Packet, world: &World, out: &mut Out) {
        let row = out.emit(
            "fights",
            Some(p),
            row! {
                mob_id: mob,
                end_idx: p.idx as i64,
                end_ms: p.ts_ms,
                outcome: "open",
                actions: 0,
                actions_by: 0,
                zone_id: world.zone,
            },
        );
        let f = Fight { row, end_idx: p.idx as i64, end_ms: p.ts_ms, actions: 0, actions_by: 0 };
        self.open.insert(mob, f);
    }
}

impl Extractor for Fights {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        self.last_ms = p.ts_ms;
        let at = (p.idx, p.ts_ms);
        match p.opcode {
            0x00A => {
                let mobs: Vec<i64> = self.open.keys().copied().collect();
                for mob in mobs {
                    self.close(mob, "zoned", at, false, out);
                }
            }
            0x00E => {
                if let Some(uid) = UID.int(f)
                    && DESPAWN.flag(f)
                    && self.open.contains_key(&uid)
                {
                    self.close(uid, "despawned", at, false, out);
                }
            }
            0x029 => {
                let mob = TARGET.int(f);
                if is_defeat(MESSAGE.int(f))
                    && is_mob(mob)
                    && !self.resends.is_resend(p)
                    && let Some(mob) = mob
                {
                    self.expire(mob, at, out);
                    if !self.open.contains_key(&mob) {
                        self.start(mob, p, world, out);
                    }
                    self.close(mob, "defeated", at, true, out);
                }
            }
            _ => self.action(p, f, world, out),
        }
    }

    fn finish(&mut self, _world: &World, out: &mut Out) {
        let mobs: Vec<i64> = self.open.keys().copied().collect();
        for mob in mobs {
            self.expire(mob, (0, self.last_ms), out);
        }
        for f in self.open.values() {
            write(out, f, "open");
        }
    }
}

impl Fights {
    fn action(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if self.resends.is_resend(p) {
            return;
        }
        let a = f.action();
        let actor = a.actor_id;
        let targets = || a.targets.iter().filter_map(|t| t.id);
        // Only actions between a mob and someone else open or extend a fight: a mob buffing itself or a
        // fellow mob is not fighting. Mid-fight, such a buff still counts.
        let mut mobs = std::mem::take(&mut self.mobs);
        mobs.clear();
        if let Some(actor) = actor.filter(|_| is_mob(actor)) {
            if targets().all(|t| is_mob(Some(t))) {
                if let Some(fight) = self.open.get_mut(&actor)
                    && p.ts_ms - fight.end_ms <= IDLE_MS
                {
                    fight.actions += 1;
                    fight.actions_by += 1;
                }
                self.mobs = mobs;
                return;
            }
            mobs.push(actor);
        } else {
            for t in targets().filter(|&t| is_mob(Some(t))) {
                if !mobs.contains(&t) {
                    mobs.push(t);
                }
            }
            if mobs.len() > 1 {
                // Python opens them in the order it iterates {mob for mob in {targets}}.
                let all = py_set_order(targets());
                mobs = py_set_order(all.into_iter().filter(|&t| is_mob(Some(t))));
            }
        }
        for &mob in &mobs {
            self.expire(mob, (p.idx, p.ts_ms), out);
            if !self.open.contains_key(&mob) {
                self.start(mob, p, world, out);
            }
            let fight = self.open.get_mut(&mob).unwrap();
            (fight.end_idx, fight.end_ms) = (p.idx as i64, p.ts_ms);
            fight.actions += 1;
            fight.actions_by += (Some(mob) == actor) as i64;
        }
        self.mobs = mobs;
    }
}

/// CPython's iteration order of a set of non-negative ints added in this order (setobject.c, 3.7 to 3.13):
/// an int hashes to itself, slots are probed linearly 9 past the first, then by perturbation, and the table
/// grows to hold 4 times its entries once 3/5 full.
fn py_set_order(xs: impl Iterator<Item = i64>) -> Vec<i64> {
    fn slot(table: &[Option<i64>], x: i64) -> (usize, bool) {
        let mask = table.len() - 1;
        let mut perturb = x as u64;
        let mut i = x as usize & mask;
        loop {
            let probes = if i + 9 <= mask { 9 } else { 0 };
            for (e, &slot) in table.iter().enumerate().skip(i).take(probes + 1) {
                match slot {
                    None => return (e, false),
                    Some(y) if y == x => return (e, true),
                    _ => {}
                }
            }
            perturb >>= 5;
            i = (i as u64).wrapping_mul(5).wrapping_add(1).wrapping_add(perturb) as usize & mask;
        }
    }
    let mut table: Vec<Option<i64>> = vec![None; 8];
    let mut used = 0;
    for x in xs {
        let (e, found) = slot(&table, x);
        if found {
            continue;
        }
        table[e] = Some(x);
        used += 1;
        if used * 5 >= (table.len() - 1) * 3 {
            let min = if used > 50000 { used * 2 } else { used * 4 };
            let mut size = 8;
            while size <= min {
                size <<= 1;
            }
            let old = std::mem::replace(&mut table, vec![None; size]);
            for x in old.into_iter().flatten() {
                let (e, _) = slot(&table, x);
                table[e] = Some(x);
            }
        }
    }
    table.into_iter().flatten().collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::packets::{act, at, message, r};
    use xc_core::testing::{MOB, PLAYER, raw};

    const MOB2: i64 = MOB + 1;
    const OTHER: i64 = 0x0001_0002;

    fn fights(packets: Vec<(i64, (u16, Vec<u8>))>) -> Vec<Vec<V>> {
        let out = raw(Box::new(Fights::default()), packets.into_iter().map(|(t, p)| at(t, p)).collect(), PLAYER);
        let x = out.rows("fights");
        let cols = ["mob_id", "idx", "end_idx", "end_ms", "outcome", "actions", "actions_by"];
        (0..x.len()).map(|i| cols.iter().map(|c| x.get(i, c)).collect()).collect()
    }

    fn row(vals: (i64, i64, i64, i64, &str, i64, i64)) -> Vec<V> {
        let (m, i, e, ms, o, a, b) = vals;
        vec![V::Int(m), V::Int(i), V::Int(e), V::Int(ms), V::Str(o.into()), V::Int(a), V::Int(b)]
    }

    fn swing(actor: i64, target: i64) -> (u16, Vec<u8>) {
        act(actor, 1, 0, &[(target, vec![r(1, 10)])])
    }

    #[test]
    fn fights_end_at_defeat_and_a_defeat_alone_is_a_fight() {
        let got = fights(vec![
            (0, swing(PLAYER, MOB)),
            (3000, swing(MOB, PLAYER)),
            (6000, message(PLAYER, MOB, 6, 0, 0)),
            (7000, message(OTHER, MOB2, 6, 0, 0)),
            (8000, swing(PLAYER, MOB)), // the same id again: its next life
        ]);
        assert_eq!(
            got,
            [
                row((MOB, 0, 2, 6000, "defeated", 2, 1)),
                row((MOB2, 3, 3, 7000, "defeated", 0, 0)),
                row((MOB, 4, 4, 8000, "open", 1, 0))
            ]
        );
    }

    #[test]
    fn a_resent_defeat_is_one_fight() {
        let defeat = message(PLAYER, MOB, 6, 0, 0);
        let got = fights(vec![(0, swing(PLAYER, MOB)), (3000, defeat.clone()), (3000, defeat)]);
        assert_eq!(got, [row((MOB, 0, 1, 3000, "defeated", 1, 0))]);
    }

    #[test]
    fn a_mob_buffing_itself_or_another_mob_is_no_fight() {
        let got = fights(vec![
            (0, act(MOB, 4, 250, &[(MOB, vec![r(230, 0)])])),
            (5000, act(MOB, 4, 108, &[(MOB2, vec![r(230, 0)])])),
        ]);
        assert!(got.is_empty());
    }

    #[test]
    fn a_fight_left_alone_closes_and_the_next_action_opens_another() {
        let later = 3000 + 180_001;
        let got = fights(vec![
            (0, swing(PLAYER, MOB)),
            (3000, swing(MOB, PLAYER)),
            (100_000, act(MOB, 4, 250, &[(MOB, vec![r(230, 0)])])), // its own spikes: counted, but no extension
            (later, swing(PLAYER, MOB)),
            (later + 180_001, act(MOB2, 4, 250, &[(MOB2, vec![r(230, 0)])])), // the capture goes on, then ends
        ]);
        assert_eq!(got, [row((MOB, 0, 1, 3000, "disengaged", 3, 2)), row((MOB, 3, 3, later, "disengaged", 1, 0))]);
    }

    /// Python iterates {0x010, 0x018, 0x011, 0x020} as 0x010, 0x018, 0x020, 0x011: 0x018 and 0x020 collide
    /// with 0x010 and probe past 0x011's slot.
    #[test]
    fn an_area_attack_opens_its_fights_in_pythons_set_order() {
        let base = MOB & !0xFFF;
        let targets: Vec<_> = [0x010, 0x018, 0x011, 0x020].iter().map(|&i| (base | i, vec![r(1, 10)])).collect();
        let got = fights(vec![(0, act(PLAYER, 3, 1, &targets))]);
        let order: Vec<V> = got.iter().map(|r| r[0].clone()).collect();
        assert_eq!(order, [0x010, 0x018, 0x020, 0x011].map(|i| V::Int(base | i)));
    }

    /// CPython 3.13's list() of a set these were added to in order.
    #[test]
    fn set_order_matches_cpython() {
        assert_eq!(py_set_order([16, 8, 0, 24].into_iter()), [16, 8, 0, 24]);
        assert_eq!(py_set_order([24, 17, 16, 25].into_iter()), [24, 17, 16, 25]);
        let many = (0..40).map(|i| 0x0100_0000 + i * 37);
        assert_eq!(py_set_order(many), CPYTHON_40);
    }

    const CPYTHON_40: [i64; 40] = [
        16777216, 16777475, 16777734, 16777993, 16778252, 16778511, 16777364, 16777623, 16777882, 16778141, 16778400,
        16778659, 16777253, 16777512, 16777771, 16778030, 16778289, 16778548, 16777401, 16777660, 16777919, 16778178,
        16778437, 16777290, 16777549, 16777808, 16778067, 16778326, 16778585, 16777438, 16777697, 16777956, 16778215,
        16778474, 16777327, 16777586, 16777845, 16778104, 16778363, 16778622,
    ];
}
