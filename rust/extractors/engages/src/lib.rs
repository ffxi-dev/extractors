//! battle/engages.py, line for line: each idle, unclaimed mob that engaged, and each pass the character made
//! by one that did not. Its Python twin keeps the docs; this keeps its name, version, reads, and columns.
//! Mobs and passes are IndexMaps: Python's dicts, whose order picks the nearest link on a tie and the order
//! passes close in.

use indexmap::IndexMap;
use xc_core::combat::{self, Resends};
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::positions::{Places, Xyz, bearing};
use xc_core::py::dist3;
use xc_core::vana::vana;
use xc_core::{C2S, Decoded, Field, Packet, S2C, World, row};

/// An action on the mob this long before its engage counts as what started it.
const BEFORE_MS: i64 = 30_000;
/// The mob's first action and its claim are looked for this long after.
const AFTER_MS: i64 = 60_000;
/// Yalms: the character within this of an idle mob is a pass.
const NEAR: f64 = 15.0;
/// And the pass ends past this, so a step back and forth stays one pass.
const FAR: f64 = 17.0;
/// The character's moves are checked against every mob at most this often.
const SCAN_MS: i64 = 500;
/// A fellow mob that engaged this long before can be the one this one linked to.
const LINKED_MS: i64 = 30_000;
/// Yalms: a stranger's fight this near can be the one it linked to.
const STRANGER_NEAR: f64 = 15.0;
const INVISIBLE: i64 = 69;
const DEODORIZE: i64 = 70;
const SNEAK: i64 = 71;
/// 0x037 server_status while the character rests (LSB ANIMATION_HEALING).
const RESTING: i64 = 33;

static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static GENERAL: Field = Field::new(S2C, 0x00E, "SendFlg.General");
static STATUS: Field = Field::new(S2C, 0x00E, "server_status");
static MONSTER: Field = Field::new(S2C, 0x00E, "Flags1.MonsterFlag");
static POSITION: Field = Field::new(S2C, 0x00E, "SendFlg.Position");
static SPEED: Field = Field::new(S2C, 0x00E, "Speed");
static CLAIMED: Field = Field::new(S2C, 0x00E, "SendFlg.ClaimStatus");
static BT: Field = Field::new(S2C, 0x00E, "BtTargetID");
static DIR: Field = Field::new(S2C, 0x00E, "dir");
static X: Field = Field::new(S2C, 0x00E, "x");
static Y: Field = Field::new(S2C, 0x00E, "y");
macro_rules! bufs {
    ($($i:literal)*) => { [$(Field::new(S2C, 0x037, concat!("BufStatus[", $i, "]"))),*] };
}
static BUFS: [Field; 32] = bufs!(0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31);
static ME_STATUS: Field = Field::new(S2C, 0x037, "server_status");
static ME_HPP: Field = Field::new(S2C, 0x037, "Flags0.hpp");
static TARGET: Field = Field::new(C2S, 0x01A, "UniqueNo");
static ACTION_ID: Field = Field::new(C2S, 0x01A, "ActionID");

/// STATE's columns, then a table's own.
macro_rules! state {
    ($($own:tt)*) => {
        &[
            ("zone_id", I32),
            ("mob_id", I64),
            ("distance", F32),
            ("dz", F32),
            ("facing", F32),
            ("mob_x", F32),
            ("mob_y", F32),
            ("mob_z", F32),
            ("mob_dir", I32),
            ("mob_age_ms", I64),
            ("me_age_ms", I64),
            ("since_seen_ms", I64),
            ("invisible", Bool),
            ("sneak", Bool),
            ("deodorize", Bool),
            ("hpp", I32),
            ("resting", Bool),
            ("recorder_status", I32),
            ("vana_hour", I32),
            ("weather_id", I32),
            $($own)*
        ]
    };
}

pub static META: Meta = Meta {
    name: "engages",
    version: 2,
    // A pass needs only the world's sightings.
    sparse: false,
    reads: &[
        (S2C, 0x00A),
        (S2C, 0x00E),
        (S2C, 0x00D),
        (S2C, 0x0DD),
        (S2C, 0x0DF),
        (C2S, 0x015),
        (S2C, 0x028),
        (S2C, 0x037),
        (C2S, 0x01A),
    ],
    tables: &[
        Table {
            name: "mob_engages",
            columns: state![
                ("status_before", I32),
                ("status", I32),
                ("mob_speed", I32),
                ("flip_dir", I32),
                ("flip_speed", I32),
                ("flip_facing", F32),
                ("me_action_id", I32),
                ("me_action_ms", I64),
                ("party_actor_id", I64),
                ("party_category", I32),
                ("party_ms", I64),
                ("other_ms", I64),
                ("mob_acted_ms", I64),
                ("first_ms", I64),
                ("first_category", I32),
                ("first_target_id", I64),
                ("first_target_recorder", Bool),
                ("first_target_party", Bool),
                ("answered_ms", I64),
                ("claim_ms", I64),
                ("claimer_id", I64),
                ("claimer_party", Bool),
                ("link_mob_id", I64),
                ("link_distance", F32),
                ("link_ms", I64),
            ],
        },
        Table { name: "mob_passes", columns: state![("duration_ms", I64)] },
    ],
};

/// What the packets said of one mob so far.
struct Mob {
    /// When this life began: its first update, or its return after a defeat.
    seen: i64,
    /// server_status, as its last general update sent it.
    status: Option<i64>,
    /// Whom its claim names (BtTargetID).
    bt: Option<i64>,
    /// Seen idle and unclaimed: its next claim is an engage.
    unclaimed: bool,
    /// Flags1.MonsterFlag.
    monster: Option<bool>,
    speed: Option<i64>,
    /// When it last engaged.
    engaged: Option<i64>,
    /// (ts, ActionID) of the character's last action on it.
    me_act: Option<(i64, Option<i64>)>,
    /// (ts, actor, category) of the party's last.
    party_act: Option<(i64, Option<i64>, Option<i64>)>,
    /// When a stranger last acted on it.
    other_act: Option<i64>,
    /// When it last acted.
    mob_act: Option<i64>,
}

impl Mob {
    fn new(seen: i64) -> Mob {
        Mob {
            seen,
            status: None,
            bt: None,
            unclaimed: false,
            monster: None,
            speed: None,
            engaged: None,
            me_act: None,
            party_act: None,
            other_act: None,
            mob_act: None,
        }
    }
}

/// STATE's values: the character's state and the world's at a moment.
#[derive(Clone, Copy)]
struct State {
    zone_id: Option<i64>,
    mob_id: i64,
    distance: Option<f64>,
    dz: Option<f64>,
    facing: Option<f64>,
    mob: Option<Xyz>,
    mob_dir: Option<i64>,
    mob_age_ms: Option<i64>,
    me_age_ms: Option<i64>,
    since_seen_ms: Option<i64>,
    /// invisible, sneak, deodorize.
    buffs: Option<(bool, bool, bool)>,
    hpp: Option<i64>,
    recorder_status: Option<i64>,
    vana_hour: i64,
    weather_id: Option<i64>,
}

impl State {
    fn emit(&self, out: &mut Out, table: &str, idx: u64, ts_ms: i64) -> RowId {
        let p = Packet { idx, ts_ms, channel: 0, direction: 0, opcode: 0, flags: 0, data: &[] };
        let b = self.buffs;
        out.emit(
            table,
            Some(&p),
            row! {
                zone_id: self.zone_id,
                mob_id: self.mob_id,
                distance: self.distance,
                dz: self.dz,
                facing: self.facing,
                mob_x: self.mob.map(|m| m.0),
                mob_y: self.mob.map(|m| m.1),
                mob_z: self.mob.map(|m| m.2),
                mob_dir: self.mob_dir,
                mob_age_ms: self.mob_age_ms,
                me_age_ms: self.me_age_ms,
                since_seen_ms: self.since_seen_ms,
                invisible: b.map(|b| b.0),
                sneak: b.map(|b| b.1),
                deodorize: b.map(|b| b.2),
                hpp: self.hpp,
                resting: self.recorder_status == Some(RESTING),
                recorder_status: self.recorder_status,
                vana_hour: self.vana_hour,
                weather_id: self.weather_id,
            },
        )
    }
}

/// A pass still open: when it began and last held, and its closest moment, as (idx, ts, state).
struct Pass {
    start: i64,
    end: i64,
    d: f64,
    best: Option<(u64, i64, State)>,
}

/// An engage row still waiting for the mob's first action, an answer, or a claim.
struct Pending {
    row: RowId,
    mob: i64,
    ts_ms: i64,
    first: bool,
    answered: bool,
    claimed: bool,
}

/// The character, its party and alliance, or a trust or pet: an id of the zone's dynamic range.
fn friendly(uid: Option<i64>, world: &World) -> bool {
    // ponytail: any trust or pet counts, a stranger's too; the party list would tell them apart.
    uid.is_some_and(|u| Some(u) == world.character_id || world.party.contains(&u)) || combat::is_dynamic(uid)
}

/// Python's truthiness of an id.
fn some(id: Option<i64>) -> bool {
    id.is_some_and(|i| i != 0)
}

#[derive(Default)]
pub struct Engages {
    places: Places,
    resends: Resends,
    mobs: IndexMap<i64, Mob>,
    pending: Vec<Pending>,
    /// Mob -> its open pass.
    passes: IndexMap<i64, Pass>,
    buffs: Option<(bool, bool, bool)>,
    status: Option<i64>,
    scanned: i64,
    /// The scan's mobs, kept to reuse.
    idle: Vec<i64>,
}

impl Extractor for Engages {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let key = p.key();
        if key == (S2C, 0x00E) {
            let uid = UID.int(f);
            let places = &self.places;
            let before =
                (places.pos.get(&uid).copied(), places.at.get(&uid).copied(), places.dir.get(&uid).map(|&(d, _)| d));
            self.places.update(p, f);
            if combat::is_mob(uid) {
                self.mob(p, f, uid.unwrap(), before, world, out);
            }
            return;
        }
        if self.places.update(p, f) {
            if key == (S2C, 0x00A) {
                for (_, x) in self.passes.drain(..) {
                    close(x, out);
                }
                self.mobs.clear();
            } else if key == (C2S, 0x015) && p.ts_ms - self.scanned >= SCAN_MS {
                self.scanned = p.ts_ms;
                let mut idle = std::mem::take(&mut self.idle);
                idle.clear();
                idle.extend(
                    self.mobs
                        .iter()
                        .filter(|(u, m)| (m.status == Some(0) && m.unclaimed) || self.passes.contains_key(*u))
                        .map(|(&u, _)| u),
                );
                for &uid in &idle {
                    self.pass(p, uid, world, out);
                }
                self.idle = idle;
            }
        } else if key == (S2C, 0x037) {
            let (mut inv, mut sneak, mut deo) = (false, false, false);
            for b in &BUFS {
                match b.int(f) {
                    Some(INVISIBLE) => inv = true,
                    Some(SNEAK) => sneak = true,
                    Some(DEODORIZE) => deo = true,
                    _ => {}
                }
            }
            self.buffs = Some((inv, sneak, deo));
            self.status = ME_STATUS.int(f);
            if some(world.character_id)
                && let Some(hpp) = ME_HPP.int(f)
            {
                self.places.hpp.insert(world.character_id, hpp);
            }
        } else if key == (C2S, 0x01A) {
            let Some(uid) = TARGET.int(f) else { return };
            if let Some(m) = self.mobs.get_mut(&uid) {
                m.me_act = Some((p.ts_ms, ACTION_ID.int(f)));
                self.answered(p, uid, out);
            }
        } else if key == (S2C, 0x028) && !self.resends.is_resend(p) {
            self.action(p, f, world, out);
        }
    }

    fn finish(&mut self, _world: &World, out: &mut Out) {
        for (_, x) in self.passes.drain(..) {
            close(x, out);
        }
    }
}

fn close(x: Pass, out: &mut Out) {
    if let Some((idx, ts, state)) = x.best {
        let id = state.emit(out, "mob_passes", idx, ts);
        out.set(id, "duration_ms", x.end - x.start);
    }
}

impl Engages {
    /// The STATE columns, the mob at pos since at, facing heading.
    fn state(
        &self,
        ts: i64,
        uid: i64,
        world: &World,
        pos: Option<Xyz>,
        at: Option<i64>,
        heading: Option<i64>,
    ) -> State {
        let here = world.here();
        let (distance, dz, facing) = match (pos, here) {
            (Some(pos), Some(here)) => (Some(dist3(pos, here)), Some(here.2 - pos.2), bearing(pos, here, heading)),
            _ => (None, None, None),
        };
        State {
            zone_id: world.zone,
            mob_id: uid,
            distance,
            dz,
            facing,
            mob: pos,
            mob_dir: heading,
            mob_age_ms: pos.and(at).map(|at| ts - at),
            me_age_ms: here.map(|_| ts - world.pos_ms),
            since_seen_ms: self.mobs.get(&uid).map(|m| ts - m.seen),
            buffs: self.buffs,
            hpp: self.places.hpp.get(&world.character_id).copied(),
            recorder_status: self.status,
            vana_hour: vana(ts).1,
            weather_id: world.weather,
        }
    }

    fn mob(
        &mut self,
        p: &Packet,
        f: &Decoded,
        uid: i64,
        before: (Option<Xyz>, Option<i64>, Option<i64>),
        world: &World,
        out: &mut Out,
    ) {
        if DESPAWN.flag(f) {
            if let Some(x) = self.passes.shift_remove(&uid) {
                close(x, out);
            }
            self.mobs.shift_remove(&uid);
            return;
        }
        let m = self.mobs.entry(uid).or_insert_with(|| Mob::new(p.ts_ms));
        let (was, speed) = (m.status, m.speed);
        if GENERAL.flag(f) {
            let status = STATUS.int(f);
            if was == Some(3) && status == Some(0) {
                m.seen = p.ts_ms;
            }
            (m.status, m.monster) = (status, Some(MONSTER.flag(f)));
        }
        let placed = POSITION.flag(f);
        if placed {
            m.speed = SPEED.int(f);
        }
        let claimed = CLAIMED.flag(f);
        let bt = if claimed { BT.int(f) } else { m.bt };
        if claimed && !some(bt) && matches!(m.status, Some(0) | None) {
            m.unclaimed = true;
        }
        let status = m.status;
        let fire = m.unclaimed && status != Some(3) && ((claimed && some(bt)) || (was == Some(0) && status == Some(1)));
        if claimed {
            m.bt = bt;
        }
        if some(bt) {
            let party = friendly(bt, world);
            for r in self.pending.iter_mut().filter(|r| r.mob == uid && !r.claimed) {
                r.claimed = true;
                out.set(r.row, "claim_ms", p.ts_ms - r.ts_ms);
                out.set(r.row, "claimer_id", bt);
                out.set(r.row, "claimer_party", party);
            }
        }
        if !fire {
            self.pass(p, uid, world, out);
            return;
        }
        let m = &mut self.mobs[&uid];
        m.unclaimed = false;
        let (me_act, party_act, other_act, mob_act) = (m.me_act, m.party_act, m.other_act, m.mob_act);
        self.passes.shift_remove(&uid); // it engaged: no pass
        // Where it stood and faced before the update; seen first in it, where it stands now, heading unknown.
        let (pos, at, heading) = if before.0.is_some() {
            before
        } else {
            (self.places.pos.get(&Some(uid)).copied(), self.places.at.get(&Some(uid)).copied(), None)
        };
        let state = self.state(p.ts_ms, uid, world, pos, at, heading);
        let here = world.here();
        let ago = |t: Option<i64>| t.map(|t| p.ts_ms - t).filter(|&d| d <= BEFORE_MS);
        let (me_t, me_id) = me_act.map_or((None, None), |(t, i)| (Some(t), i));
        let (party_t, party_by, party_cat) = party_act.map_or((None, None, None), |(t, a, c)| (Some(t), a, c));
        let party = ago(party_t).is_some();
        let dir = DIR.int(f);
        let flip_facing = match (placed, here) {
            (true, Some(here)) => match (X.float(f), Y.float(f)) {
                (Some(x), Some(y)) => bearing((x, y, 0.0), here, dir),
                _ => None,
            },
            _ => None,
        };
        let link = self.link(p.ts_ms, uid, pos, world);
        let id = state.emit(out, "mob_engages", p.idx, p.ts_ms);
        let own = row! {
            status_before: was,
            status: status,
            mob_speed: speed,
            flip_dir: if placed { dir } else { None },
            flip_speed: if placed { SPEED.int(f) } else { None },
            flip_facing: flip_facing,
            me_action_id: if ago(me_t).is_some() { me_id } else { None },
            me_action_ms: ago(me_t),
            party_actor_id: if party { party_by } else { None },
            party_category: if party { party_cat } else { None },
            party_ms: ago(party_t),
            other_ms: ago(other_act),
            mob_acted_ms: ago(mob_act),
            link_mob_id: link.map(|l| l.1),
            link_distance: link.map(|l| l.0),
            link_ms: link.and_then(|l| l.2),
        };
        for (k, v) in own {
            out.set(id, k, v);
        }
        let claimed = some(bt);
        if claimed {
            out.set(id, "claim_ms", 0);
            out.set(id, "claimer_id", bt);
            out.set(id, "claimer_party", friendly(bt, world));
        }
        self.mobs[&uid].engaged = Some(p.ts_ms);
        self.pending.push(Pending { row: id, mob: uid, ts_ms: p.ts_ms, first: false, answered: false, claimed });
    }

    /// The nearest other mob engaged now, as (distance, id, ms since its engage): the party's, a stranger's
    /// close by, or itself just engaged unclaimed.
    fn link(&self, ts: i64, uid: i64, pos: Option<Xyz>, world: &World) -> Option<(f64, i64, Option<i64>)> {
        let pos = pos?;
        let mut best: Option<(f64, i64, Option<i64>)> = None;
        for (&other, o) in &self.mobs {
            if other == uid || o.status != Some(1) {
                continue;
            }
            let Some(&there) = self.places.pos.get(&Some(other)) else { continue };
            let recent = o.engaged.is_some_and(|e| ts - e <= LINKED_MS);
            let d = dist3(pos, there);
            let ours = friendly(o.bt, world) || (!some(o.bt) && recent);
            if (ours || (some(o.bt) && d < STRANGER_NEAR)) && best.is_none_or(|b| d < b.0) {
                best = Some((d, other, if recent { o.engaged.map(|e| ts - e) } else { None }));
            }
        }
        best
    }

    fn answered(&mut self, p: &Packet, uid: i64, out: &mut Out) {
        for r in self.pending.iter_mut().filter(|r| r.mob == uid && !r.answered) {
            r.answered = true;
            out.set(r.row, "answered_ms", p.ts_ms - r.ts_ms);
        }
    }

    fn action(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let a = f.action();
        let actor = a.actor_id;
        self.pending.retain(|r| p.ts_ms - r.ts_ms <= AFTER_MS);
        if combat::is_mob(actor) {
            let Some(t) = a.targets.iter().map(|t| t.id).find(|&t| t.is_some() && !combat::is_mob(t)) else {
                return;
            };
            if let Some(m) = self.mobs.get_mut(&actor.unwrap()) {
                m.mob_act = Some(p.ts_ms);
            }
            for r in self.pending.iter_mut().filter(|r| Some(r.mob) == actor && !r.first) {
                r.first = true;
                out.set(r.row, "first_ms", p.ts_ms - r.ts_ms);
                out.set(r.row, "first_category", a.cmd_no);
                out.set(r.row, "first_target_id", t);
                out.set(r.row, "first_target_recorder", t == world.character_id);
                out.set(r.row, "first_target_party", friendly(t, world));
            }
            return;
        }
        let mine = friendly(actor, world);
        for t in &a.targets {
            let Some(uid) = t.id else { continue };
            let Some(m) = self.mobs.get_mut(&uid) else { continue };
            if mine {
                m.party_act = Some((p.ts_ms, actor, a.cmd_no));
                self.answered(p, uid, out);
            } else if combat::is_player(actor) {
                m.other_act = Some(p.ts_ms);
            }
        }
    }

    /// Open, follow, or close the character's pass by an idle, unclaimed monster.
    fn pass(&mut self, p: &Packet, uid: i64, world: &World, out: &mut Out) {
        let idle = self
            .mobs
            .get(&uid)
            .is_some_and(|m| m.monster == Some(true) && m.status == Some(0) && m.unclaimed && !some(m.bt));
        let there = self.places.pos.get(&Some(uid)).copied();
        let (true, Some(there), Some(me)) = (idle, there, world.here()) else {
            if let Some(x) = self.passes.shift_remove(&uid) {
                close(x, out);
            }
            return;
        };
        let d = dist3(there, me);
        let open = self.passes.contains_key(&uid);
        if d > if open { FAR } else { NEAR } {
            if let Some(x) = self.passes.shift_remove(&uid) {
                close(x, out);
            }
            return;
        }
        let best = self.passes.get(&uid).map_or(f64::INFINITY, |x| x.d);
        let state = (d < best).then(|| {
            let heading = self.places.dir.get(&Some(uid)).map(|&(h, _)| h);
            self.state(p.ts_ms, uid, world, Some(there), Some(self.places.at[&Some(uid)]), heading)
        });
        let x = self.passes.entry(uid).or_insert(Pass { start: p.ts_ms, end: 0, d: f64::INFINITY, best: None });
        x.end = p.ts_ms;
        if let Some(state) = state {
            (x.d, x.best) = (d, Some((p.idx, p.ts_ms, state)));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, PLAYER, STRANGER, drive};

    /// Jugner Forest: outdoors.
    const ZONE: i64 = 104;
    const fn id(i: i64) -> i64 {
        0x01000000 | (ZONE << 12) | i
    }
    const MOB: i64 = id(0x020);
    const OTHER: i64 = id(0x021);

    /// A full update: idle or engaged, placed, facing d (0 faces +x), with its claim.
    fn mob(uid: i64, status: i64, x: f64, d: i64, speed: i64, claim: i64) -> (u16, MapFields) {
        let f = MapFields::new()
            .int("UniqueNo", uid)
            .int("ActIndex", uid & 0xFFF)
            .int("SendFlg.General", 1)
            .int("server_status", status)
            .int("Flags1.MonsterFlag", 1)
            .int("SendFlg.Position", 1)
            .float("x", x)
            .float("y", 0.0)
            .float("z", 0.0)
            .int("dir", d)
            .int("Speed", speed)
            .int("SendFlg.ClaimStatus", 1)
            .int("BtTargetID", claim);
        (0x00E, f)
    }

    fn idle() -> (u16, MapFields) {
        mob(MOB, 0, 0.0, 0, 40, 0)
    }

    fn me(x: f64) -> (u16, MapFields) {
        (0x015, MapFields::new().float("x", x).float("y", 0.0).float("z", 1.0))
    }

    fn hits(actor: i64, target: i64) -> (u16, MapFields) {
        let p = combat::P;
        let f = MapFields::new()
            .int(&format!("{p}actor_id"), actor)
            .int(&format!("{p}cmd_no"), 1)
            .int(&format!("{p}target_count"), 1)
            .int(&format!("{p}targets[0].target_id"), target)
            .int(&format!("{p}targets[0].result_count"), 1)
            .int(&format!("{p}targets[0][0].message"), 1);
        (0x028, f)
    }

    /// test_aggro.py's walk: a zone-in and a 0x037 at 0, then the steps a second apart.
    fn walk(steps: Vec<(u16, MapFields)>) -> Out {
        let zone_in = MapFields::new()
            .int("ZoneNo", ZONE)
            .int("WeatherNumber", 6)
            .float("PosHead.x", 50.0)
            .float("PosHead.y", 0.0)
            .float("PosHead.z", 1.0);
        let status = MapFields::new()
            .int("BufStatus[0]", 71)
            .int("BufStatus[1]", 255)
            .int("server_status", 0)
            .int("Flags0.hpp", 90);
        let n = steps.len() as i64;
        let all: Vec<(u16, MapFields)> = [(0x00A, zone_in), (0x037, status)].into_iter().chain(steps).collect();
        let times = [0, 0].into_iter().chain((0..n).map(|i| i * 1000 + 1)).collect();
        let directions = all.iter().map(|(op, _)| if matches!(op, 0x015 | 0x01A) { C2S } else { S2C }).collect();
        drive(
            &mut Engages::default(),
            all,
            Drive { times: Some(times), directions: Some(directions), ..Drive::default() },
        )
    }

    fn float(v: V) -> f64 {
        match v {
            V::Float(x) => x,
            v => panic!("{v:?}"),
        }
    }

    #[test]
    fn a_mob_that_turns_on_the_character_unprovoked() {
        // Idle and unclaimed, facing +x; the character 8 yalms ahead; it engages, turning to it, then hits it.
        let out = walk(vec![
            idle(),
            me(30.0),
            me(8.0),
            mob(MOB, 1, 0.0, 0, 100, 0),
            hits(MOB, PLAYER),
            mob(MOB, 1, 0.0, 0, 40, PLAYER),
        ]);
        let e = out.rows("mob_engages");
        assert_eq!(e.len(), 1);
        assert!((float(e.get(0, "distance")) - 8.0625).abs() < 1e-3, "8 across, 1 up");
        assert_eq!(float(e.get(0, "facing")).round(), 0.0);
        assert_eq!(
            [e.get(0, "dz"), e.get(0, "mob_speed"), e.get(0, "flip_speed")],
            [V::Float(1.0), V::Int(40), V::Int(100)]
        );
        assert_eq!(
            [e.get(0, "sneak"), e.get(0, "invisible"), e.get(0, "hpp"), e.get(0, "weather_id"), e.get(0, "zone_id")],
            [V::Bool(true), V::Bool(false), V::Int(90), V::Int(6), V::Int(ZONE)]
        );
        assert_eq!(
            [e.get(0, "first_ms"), e.get(0, "first_target_recorder"), e.get(0, "claim_ms"), e.get(0, "claimer_id")],
            [V::Int(1000), V::Bool(true), V::Int(2000), V::Int(PLAYER)]
        );
        assert_eq!((e.get(0, "me_action_id"), e.get(0, "party_ms")), (V::Null, V::Null));
        assert!(out.rows("mob_passes").is_empty(), "it engaged: the approach is no pass");
    }

    #[test]
    fn a_pull_is_the_characters_action_before_the_engage() {
        let act = (0x01A, MapFields::new().int("UniqueNo", MOB).int("ActionID", 2));
        let out = walk(vec![idle(), me(20.0), act, mob(MOB, 1, 0.0, 0, 40, 0)]);
        let e = out.rows("mob_engages");
        assert_eq!((e.len(), e.get(0, "me_action_id"), e.get(0, "me_action_ms")), (1, V::Int(2), V::Int(1000)));
    }

    #[test]
    fn a_strangers_fight_close_by_is_one_a_mob_may_have_linked_to() {
        // OTHER, 5 yalms off, engages a stranger and is claimed; MOB engages 1 s later.
        let out = walk(vec![
            mob(OTHER, 0, 5.0, 0, 40, 0),
            idle(),
            me(30.0),
            mob(OTHER, 1, 5.0, 0, 40, STRANGER),
            mob(MOB, 1, 0.0, 0, 40, 0),
        ]);
        let e = out.rows("mob_engages");
        assert_eq!(e.len(), 2);
        assert_eq!(
            [e.get(1, "link_mob_id"), e.get(1, "link_distance"), e.get(1, "link_ms")],
            [V::Int(OTHER), V::Float(5.0), V::Int(1000)]
        );
    }

    #[test]
    fn a_pass_by_a_mob_that_does_not_engage_is_one_row_at_the_closest() {
        // Behind it (it faces -x), from 30 yalms to 10 and back past 17, then near again.
        let out = walk(vec![mob(MOB, 0, 0.0, 128, 40, 0), me(30.0), me(16.0), me(10.0), me(16.5), me(20.0), me(12.0)]);
        let p = out.rows("mob_passes");
        assert_eq!(p.len(), 2);
        assert!((float(p.get(0, "distance")) - 10.05).abs() < 0.01);
        assert_eq!(float(p.get(0, "facing")).round().abs(), 180.0);
        assert_eq!((p.get(0, "duration_ms"), p.get(0, "sneak")), (V::Int(1000), V::Bool(true)));
        assert!((float(p.get(1, "distance")) - 12.04).abs() < 0.01);
    }
}
