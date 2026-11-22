//! battle/hp.py, line for line: captain's hptrackv2, the damage each mob took from everything the capture
//! shows, narrowed by its HP% updates, and its HP range when it dies. Its Python twin keeps the docs, and this
//! keeps its name, version, reads, and columns.

use std::collections::HashMap;

use xc_core::combat::{self, Action, Resends};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::packet::Field;
use xc_core::{Decoded, Packet, S2C, World, py, row};

/// hptrackv2's MSG_TYPES: [category][message] -> 1 damage, -1 healing, 0 neither; None is skipped.
fn sign(cat: Option<i64>, message: Option<i64>) -> Option<i8> {
    const D: Option<i8> = Some(1);
    const H: Option<i8> = Some(-1);
    const N: Option<i8> = Some(0);
    match (cat?, message?) {
        (1, 1 | 67) => D,
        (1, 15 | 30 | 31 | 32 | 33 | 70) => N,
        (2, 157 | 352 | 353 | 576 | 577) => D,
        (2, 382) => H,
        (2, 31 | 354) => N,
        (3, 135 | 185 | 187 | 197 | 264 | 317 | 379) => D,
        (3, 102 | 103 | 238 | 263 | 318 | 539) => H,
        (3, 158 | 186 | 188 | 189 | 194 | 224 | 225 | 226 | 323 | 324) => N,
        (4, 2 | 227 | 252 | 262 | 264 | 274 | 648 | 650) => D,
        (4, 7 | 263 | 651) => H,
        (7, 43) => N,
        (6, 110 | 264 | 317) => D,
        (6, 263 | 318) => H,
        (6, 158 | 323 | 324) => N,
        (11, 185 | 187 | 197 | 264) => D,
        (11, 238 | 263) => H,
        (11, 43 | 186 | 188 | 189 | 194) => N,
        (13, 110 | 185 | 264 | 317) => D,
        (13, 238 | 263) => H,
        (13, 188 | 189 | 323 | 324) => N,
        (14, 110 | 264) => D,
        (14, 102 | 103 | 263) => H,
        (14, 158 | 319 | 323) => N,
        (15, 2 | 110 | 252 | 264) => D,
        (15, 323) => N,
        _ => None,
    }
}

/// Skillchains, enspells and runes, added damage.
fn is_proc(message: Option<i64>) -> bool {
    matches!(message, Some(288..=302 | 767 | 768 | 229 | 163))
}

/// Spikes, Dread Spikes, counter, retaliation.
fn is_react(message: Option<i64>) -> bool {
    matches!(message, Some(44 | 132 | 33 | 536))
}

/// An HP% fall with no damage seen since the last update, and none in this long after it, is silent.
const SILENT_MS: i64 = 1500;

static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static HPP: Field = Field::new(S2C, 0x00E, "Hpp");
static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static GENERAL: Field = Field::new(S2C, 0x00E, "SendFlg.General");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");

pub static META: Meta = Meta {
    name: "hp",
    version: 7,
    sparse: true,
    reads: &[(S2C, 0x028), (S2C, 0x029), (S2C, 0x00E), (S2C, 0x00A)],
    tables: &[Table {
        name: "mob_hp",
        columns: &[
            ("mob_id", I64),
            ("damage", I64),
            ("healing", I64),
            ("hits", I32),
            ("hp_min", I64),
            ("hp_max", I64),
            ("start_hpp", I32),
            ("contradictions", I32),
            ("regen", I32),
            ("regen_rate", F64),
            ("zone_id", I32),
        ],
    }],
};

/// hp.py's _Mob.
#[derive(Clone, Debug, Default)]
pub struct Mob {
    damage: i64,
    hits: i64,
    healing: i64,
    last: i64,
    extra: i64,
    start_hpp: i64,
    hpp: i64,
    hp_min: i64,
    hp_max: Option<i64>,
    contradictions: i64,
    base: i64,
    healed: bool,
    regen: i64,
    run_pts: i64,
    run_ms: i64,
    /// (when, hits then, healing then)
    last_rise: Option<(i64, i64, i64)>,
    windows: Vec<(i64, i64)>,
    lag: i64,
    hits_at: i64,
    falling: Option<i64>,
    silent: bool,
}

impl Mob {
    pub fn new(start_hpp: i64, hpp: i64) -> Mob {
        Mob { start_hpp, hpp, hp_min: 1, ..Mob::default() }
    }

    fn hit(&mut self, damage: i64, side: bool, ts_ms: i64) {
        if self.falling.is_some_and(|f| ts_ms - f <= SILENT_MS) {
            self.falling = None;
        }
        self.damage += damage;
        self.hits += 1;
        if side {
            self.extra += damage;
        } else {
            (self.last, self.extra) = (damage, 0);
        }
    }

    fn net(&self) -> i64 {
        self.damage - self.healing
    }

    fn update(&mut self, hpp: i64, ts_ms: i64) {
        self.settle(ts_ms);
        if hpp < self.hpp && self.hits == self.hits_at && self.falling.is_none() {
            self.falling = Some(ts_ms);
        }
        if hpp != self.hpp {
            self.hits_at = self.hits;
        }
        if hpp > self.hpp && self.hpp > 0 && !self.healed {
            self.regen += hpp - self.hpp;
            if let Some((at, hits, healing)) = self.last_rise
                && (hits, healing) == (self.hits, self.healing)
            {
                self.run_pts += hpp - self.hpp;
                self.run_ms += ts_ms - at;
            }
            self.last_rise = Some((ts_ms, self.hits, self.healing));
            (self.start_hpp, self.base) = (hpp, self.net());
        } else {
            if hpp != self.hpp {
                self.last_rise = None;
            }
            let (d_hpp, net) = (self.start_hpp - hpp, self.net() - self.base);
            if d_hpp > 0 && hpp > 1 {
                self.windows.push((
                    (((net - self.lag) * 100) as f64 / (d_hpp + 1) as f64).ceil() as i64,
                    ((net * 100) as f64 / (d_hpp as f64 - 0.99999)).floor() as i64,
                ));
            }
        }
        (self.hpp, self.healed, self.lag) = (hpp, false, 0);
    }

    fn settle(&mut self, ts_ms: i64) {
        if self.falling.is_some_and(|f| ts_ms - f > SILENT_MS) {
            (self.silent, self.falling) = (true, None);
        }
    }

    fn regen_rate(&self) -> Option<f64> {
        (self.run_ms != 0).then(|| py::round_to((self.run_pts * 3000) as f64 / self.run_ms as f64, 4))
    }

    fn refine(&mut self, round_damage: i64) {
        self.lag = round_damage;
        let d_hpp = self.start_hpp - self.hpp;
        if d_hpp <= 0 || self.hpp <= 1 {
            return;
        }
        let net = self.net() - self.base;
        let lo = (((net - round_damage) * 100) as f64 / d_hpp as f64).ceil() as i64;
        let hi = ((net * 100) as f64 / (d_hpp as f64 - 0.99999)).floor() as i64;
        if hi < self.hp_min || self.hp_max.is_some_and(|m| lo > m) {
            self.contradictions += 1;
            return;
        }
        self.hp_min = self.hp_min.max(lo);
        self.hp_max = Some(self.hp_max.map_or(hi, |m| m.min(hi)));
    }

    pub fn range(&self) -> (i64, i64) {
        if self.regen != 0 && !self.windows.is_empty() {
            let mut edges: Vec<(i64, i64)> = self
                .windows
                .iter()
                .map(|&(lo, _)| (lo, 1))
                .chain(self.windows.iter().map(|&(_, hi)| (hi + 1, -1)))
                .collect();
            edges.sort_unstable();
            let mut sums = Vec::with_capacity(edges.len());
            let mut cur = 0;
            for &(_, e) in &edges {
                cur += e;
                sums.push(cur);
            }
            let best = *sums.iter().max().unwrap();
            let (mut first, mut last, mut at) = (None, None, None);
            for (&(x, _), &cur) in edges.iter().zip(&sums) {
                if cur == best && at.is_none() {
                    at = Some(x);
                } else if cur < best
                    && let Some(a) = at.take()
                {
                    first.get_or_insert(a);
                    last = Some(x - 1);
                }
            }
            if let (Some(lo), Some(hi)) = (first, last) {
                return (lo, hi);
            }
        }
        let total = self.net();
        if self.hits == 1 {
            return (self.hp_min.max(1), total.min(self.hp_max.unwrap_or(total)));
        }
        let (lo, hi) = (total - (self.last + self.extra) + 1, total);
        let nlo = lo.max(self.hp_min);
        let nhi = self.hp_max.map_or(hi, |m| hi.min(m));
        if nlo > nhi { (lo, hi) } else { (nlo, nhi) }
    }
}

#[derive(Default)]
pub struct Hp {
    pub mobs: HashMap<i64, Mob>,
    hpp: HashMap<i64, i64>,
    prev_hpp: HashMap<i64, i64>,
    resends: Resends,
    /// An action's net damage by mob, kept between packets for its allocation.
    dealt: Vec<(i64, i64)>,
}

impl Extractor for Hp {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.opcode {
            0x00A => {
                self.mobs.clear();
                self.hpp.clear();
                self.prev_hpp.clear();
            }
            0x00E => {
                let (uid, hpp) = (UID.int(f), HPP.int(f));
                if DESPAWN.flag(f) {
                    if let Some(uid) = uid {
                        self.mobs.remove(&uid);
                        self.hpp.remove(&uid);
                        self.prev_hpp.remove(&uid);
                    }
                } else if GENERAL.flag(f)
                    && let (Some(uid), Some(hpp)) = (uid, hpp)
                {
                    if let Some(&was) = self.hpp.get(&uid)
                        && was != hpp
                    {
                        self.prev_hpp.insert(uid, was);
                    }
                    self.hpp.insert(uid, hpp);
                    if let Some(m) = self.mobs.get_mut(&uid) {
                        m.update(hpp, p.ts_ms);
                    }
                }
            }
            0x029 => {
                let mob_id = TARGET.int(f);
                if !combat::is_defeat(MESSAGE.int(f)) {
                    return;
                }
                let Some(mut m) = mob_id.and_then(|id| self.mobs.remove(&id)) else { return };
                m.settle(p.ts_ms);
                if m.hits == 0 || m.silent {
                    return;
                }
                let (lo, hi) = m.range();
                out.emit(
                    "mob_hp",
                    Some(p),
                    row! {
                        mob_id: mob_id,
                        damage: m.damage,
                        healing: m.healing,
                        hits: m.hits,
                        hp_min: lo,
                        hp_max: hi,
                        start_hpp: m.start_hpp,
                        contradictions: m.contradictions,
                        regen: m.regen,
                        regen_rate: m.regen_rate(),
                        zone_id: world.zone,
                    },
                );
            }
            0x028 if !self.resends.is_resend(p) => self.action(f.action(), p.ts_ms),
            _ => {}
        }
    }
}

impl Hp {
    fn mob(&mut self, mob_id: i64) -> &mut Mob {
        let (hpp, prev) = (&self.hpp, &self.prev_hpp);
        self.mobs.entry(mob_id).or_insert_with(|| {
            let hpp = hpp.get(&mob_id).copied().unwrap_or(100);
            // The current HP% may already count damage from an action not yet seen: take the higher.
            Mob::new(hpp.max(prev.get(&mob_id).copied().unwrap_or(0)), hpp)
        })
    }

    fn deal(&mut self, mob_id: i64, d: i64) {
        match self.dealt.iter_mut().find(|(m, _)| *m == mob_id) {
            Some((_, x)) => *x += d,
            None => self.dealt.push((mob_id, d)),
        }
    }

    fn action(&mut self, a: &Action, ts_ms: i64) {
        let (cat, actor) = (a.cmd_no, a.actor_id);
        self.dealt.clear();
        for t in &a.targets {
            let mob = combat::is_mob(t.id);
            for r in &t.results {
                let sign = sign(cat, r.message);
                let value = r.value.unwrap_or(0);
                let react = r.react.as_ref().filter(|x| is_react(x.message));
                if sign == Some(-1) && value != 0 {
                    if mob {
                        let id = t.id.unwrap();
                        let m = self.mob(id);
                        m.healing += value;
                        m.healed = true;
                        self.deal(id, -value);
                    }
                } else if (sign == Some(1) && value != 0) || react.is_some() {
                    let damage = if sign == Some(1) { value } else { 0 };
                    // A countered swing does no damage: it is no hit.
                    if mob && damage != 0 {
                        let id = t.id.unwrap();
                        self.mob(id).hit(damage, false, ts_ms);
                        self.deal(id, damage);
                        if let Some(proc) = &r.proc
                            && is_proc(proc.message)
                            && let Some(v) = proc.value.filter(|&v| v != 0)
                        {
                            self.mob(id).hit(v, true, ts_ms);
                            self.deal(id, v);
                        }
                    }
                    if let Some(v) = react.and_then(|x| x.value).filter(|&v| v != 0)
                        && combat::is_mob(actor)
                    {
                        let id = actor.unwrap();
                        self.mob(id).hit(v, true, ts_ms);
                        self.deal(id, v);
                    }
                }
            }
        }
        for i in 0..self.dealt.len() {
            let (mob_id, d) = self.dealt[i];
            if let Some(m) = self.mobs.get_mut(&mob_id) {
                m.refine(d.max(0));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::rc::Rc;

    use super::*;
    use xc_core::V;
    use xc_core::testing::packets::{R, act, at, message, r};
    use xc_core::testing::{MEMBER, MOB, PLAYER, raw};

    type Pk = (u16, Vec<u8>);

    fn hit(actor: i64, cat: i64, targets: &[(i64, Vec<R>)]) -> Pk {
        act(actor, cat, 0, targets)
    }

    fn defeat(target: i64) -> Pk {
        message(PLAYER, target, 6, 0, 0)
    }

    /// A 0x00E entity update: who, SendFlg's bits, and its HP%.
    fn entity(who: i64, flags: u8, pct: u8) -> Pk {
        let mut data = vec![0u8; 48];
        (data[0], data[1]) = (0x0E, (48 / 4) << 1);
        data[4..8].copy_from_slice(&(who as u32).to_le_bytes());
        data[8..10].copy_from_slice(&((who & 0xFFF) as u16).to_le_bytes());
        (data[10], data[0x1E]) = (flags, pct);
        (0x00E, data)
    }

    /// SendFlg.General: who's HP%.
    fn hpp(who: i64, pct: u8) -> Pk {
        entity(who, 0x04, pct)
    }

    fn rows(x: Box<dyn Extractor>, steps: Vec<(i64, Pk)>) -> Vec<HashMap<&'static str, V>> {
        let out = raw(x, steps.into_iter().map(|(ts, p)| at(ts, p)).collect(), PLAYER);
        let rows = out.rows("mob_hp");
        (0..rows.len()).map(|i| META.tables[0].columns.iter().map(|&(c, _)| (c, rows.get(i, c))).collect()).collect()
    }

    fn run(steps: Vec<(i64, Pk)>) -> Vec<HashMap<&'static str, V>> {
        rows(Box::new(Hp::default()), steps)
    }

    fn get(m: &HashMap<&str, V>, ks: &[&str]) -> Vec<V> {
        ks.iter().map(|k| m[k].clone()).collect()
    }

    fn ints(xs: &[i64]) -> Vec<V> {
        xs.iter().map(|&x| V::Int(x)).collect()
    }

    #[test]
    fn a_defeated_mob_took_melee_a_weapon_skill_and_a_skillchain() {
        let rows = run(vec![
            (0, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1000, hit(PLAYER, 3, &[(MOB, vec![R { proc: Some((300, 288)), ..r(185, 500) }])])),
            (2000, defeat(MOB)),
        ]);
        assert_eq!(rows.len(), 1);
        assert_eq!(get(&rows[0], &["mob_id", "damage", "hits", "hp_min", "hp_max"]), ints(&[MOB, 900, 3, 101, 900]));
    }

    #[test]
    fn a_despawn_ends_the_damage_count() {
        let rows = run(vec![
            (0, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1000, entity(MOB, 0x20, 0)), // SendFlg.Despawn
            (2000, hit(PLAYER, 1, &[(MOB, vec![r(1, 200)])])),
            (3000, defeat(MOB)),
        ]);
        assert_eq!(rows.iter().map(|m| get(m, &["damage", "hits"])).collect::<Vec<_>>(), vec![ints(&[200, 1])]);
    }

    #[test]
    fn regen_restarts_the_hp_window_and_gives_its_rate() {
        // 1000 HP: 100 damage takes the bar to 90, regen brings it back 1% a tick, then 300 damage takes 30%.
        let rows = run(vec![
            (0, hpp(MOB, 100)),
            (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1100, hpp(MOB, 90)),
            (4000, hpp(MOB, 91)),
            (7000, hpp(MOB, 92)),
            (10000, hpp(MOB, 93)),
            (11000, hit(PLAYER, 1, &[(MOB, vec![r(1, 300)])])),
            (11100, hpp(MOB, 63)),
            (12000, hit(PLAYER, 1, &[(MOB, vec![r(1, 700)])])),
            (13000, defeat(MOB)),
        ]);
        let m = &rows[0];
        assert_eq!(get(m, &["regen", "regen_rate", "healing"]), vec![V::Int(3), V::Float(1.0), V::Int(0)]);
        let (V::Int(lo), V::Int(hi)) = (&m["hp_min"], &m["hp_max"]) else { panic!() };
        assert!(*lo <= 1000 && 1000 <= *hi, "the damage before the regen no longer counts");
    }

    #[test]
    fn slow_regen_gives_its_rate_and_a_hit_between_rises_breaks_the_run() {
        let rows = run(vec![
            (0, hpp(MOB, 100)),
            (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1100, hpp(MOB, 90)),
            (20000, hpp(MOB, 91)),
            (110000, hpp(MOB, 92)),
            (200000, hpp(MOB, 93)),
            (250000, hit(PLAYER, 1, &[(MOB, vec![r(1, 1)])])),
            (290000, hpp(MOB, 94)),
            (300000, hit(PLAYER, 1, &[(MOB, vec![r(1, 940)])])),
            (301000, defeat(MOB)),
        ]);
        // round(2 * 3000 / 180000, 4) in Python.
        assert_eq!(get(&rows[0], &["regen", "regen_rate"]), vec![V::Int(4), V::Float(0.0333)]);
    }

    #[test]
    fn under_regen_the_hp_most_windows_allow_wins_over_the_first() {
        // One window thrown off by regen the bar didn't show yet comes first; the rest agree on 980-1,020.
        let mut m = Mob::new(100, 100);
        m.regen = 1;
        m.windows = vec![(1300, 1400), (900, 1100), (950, 1050), (980, 1020), (970, 1200)];
        assert_eq!(m.range(), (980, 1020));
    }

    #[test]
    fn a_rise_after_a_heal_is_not_regen() {
        let rows = run(vec![
            (0, hpp(MOB, 100)),
            (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1100, hpp(MOB, 90)),
            (2000, hit(MOB, 4, &[(MOB, vec![r(7, 50)])])),
            (2100, hpp(MOB, 95)),
            (3000, hit(PLAYER, 1, &[(MOB, vec![r(1, 950)])])),
            (4000, defeat(MOB)),
        ]);
        assert_eq!(get(&rows[0], &["regen", "regen_rate", "healing"]), vec![V::Int(0), V::Null, V::Int(50)]);
    }

    #[test]
    fn a_kill_whose_hp_fell_with_no_damage_seen_gives_no_hp() {
        let dot = run(vec![
            (0, hpp(MOB, 100)),
            (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (1100, hpp(MOB, 90)),
            (5000, hpp(MOB, 80)), // a tick: no action before or soon after
            (9000, hit(PLAYER, 1, &[(MOB, vec![r(1, 900)])])),
            (9100, defeat(MOB)),
        ]);
        assert!(dot.is_empty());
        let late = run(vec![
            (0, hpp(MOB, 100)),
            (500, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (600, hpp(MOB, 90)),
            (2000, hpp(MOB, 80)), // the bar before the action that moved it
            (2400, hit(PLAYER, 1, &[(MOB, vec![r(1, 100)])])),
            (3000, hit(PLAYER, 1, &[(MOB, vec![r(1, 800)])])),
            (3100, defeat(MOB)),
        ]);
        assert_eq!(late.iter().map(|m| m["damage"].clone()).collect::<Vec<_>>(), ints(&[1000]));
    }

    #[test]
    fn spikes_damage_the_attacker() {
        let rows = run(vec![
            (0, hit(MOB, 1, &[(PLAYER, vec![R { react: Some((40, 44)), ..r(1, 30) }])])),
            (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 60)])])),
            (2000, defeat(MOB)),
        ]);
        assert_eq!(rows[0]["damage"], V::Int(100));
    }

    #[test]
    fn a_countered_swing_is_no_hit_on_the_mob() {
        let rows = run(vec![
            (0, hit(PLAYER, 1, &[(MOB, vec![r(1, 500)])])),
            (1000, hit(PLAYER, 1, &[(MOB, vec![R { react: Some((50, 33)), ..r(33, 0) }])])),
            (2000, defeat(MOB)),
        ]);
        assert_eq!(get(&rows[0], &["hits", "hp_min", "hp_max"]), ints(&[1, 1, 500]));
    }

    #[test]
    fn a_trust_that_falls_is_no_mob() {
        let trust = MOB | 0x700;
        assert!(run(vec![(0, hit(MOB, 1, &[(trust, vec![r(1, 300)])])), (1000, defeat(trust))]).is_empty());
    }

    #[test]
    fn regen_with_no_window_left_standing_falls_back_on_the_damage() {
        let mut m = Mob::new(100, 100);
        (m.regen, m.windows) = (1, vec![(10, 5)]); // healed, then hit by a tick: every window inverted
        m.hit(300, false, 0);
        assert_eq!(m.range(), (1, 300));
    }

    /// An Hp the test can look into after raw() has run it.
    struct Spy(Rc<RefCell<Hp>>);

    impl Extractor for Spy {
        fn meta(&self) -> &'static Meta {
            &META
        }

        fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
            self.0.borrow_mut().packet(p, f, world, out);
        }
    }

    #[test]
    fn hp_tracks_no_player_and_ends_on_the_last_hit_and_its_procs() {
        let hp = Rc::new(RefCell::new(Hp::default()));
        let rows = rows(
            Box::new(Spy(hp.clone())),
            vec![
                (0, hit(MOB, 1, &[(PLAYER, vec![R { react: Some((40, 44)), ..r(1, 30) }])])),
                (500, hit(MEMBER, 4, &[(PLAYER, vec![r(7, 20)])])),
                (1000, hit(PLAYER, 1, &[(MOB, vec![r(1, 60)]), (MOB, vec![R { proc: Some((7, 163)), ..r(1, 5) }])])),
                (2000, defeat(MOB)),
            ],
        );
        assert!(hp.borrow().mobs.is_empty(), "the player hit and healed has no tracker");
        assert_eq!(rows.len(), 1);
        assert_eq!(get(&rows[0], &["damage", "hits", "hp_min", "hp_max"]), ints(&[112, 4, 101, 112]));
    }
}
