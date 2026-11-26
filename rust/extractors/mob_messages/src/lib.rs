//! battle/mob_messages.py: draw-ins and blue magic learned, from 0x029. A draw-in's mob is the engaged
//! monster nearest the player's next position. Its Python twin keeps the docs.

use std::collections::{HashMap, HashSet};

use xc_core::combat::{Resends, is_mob};
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::py::dist3;
use xc_core::{C2S, Decoded, Field, Packet, S2C, World, row};

static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static DATA: Field = Field::new(S2C, 0x029, "Data");
static GENERAL: Field = Field::new(S2C, 0x00E, "SendFlg.General");
static STATUS: Field = Field::new(S2C, 0x00E, "server_status");
static MONSTER: Field = Field::new(S2C, 0x00E, "Flags1.MonsterFlag");
/// UniqueNo, SendFlg.Despawn, SendFlg.Position, x, y, z of 0x00E, 0x00D, and c2s 0x015.
macro_rules! place {
    ($dir:expr, $op:expr) => {
        [
            Field::new($dir, $op, "UniqueNo"),
            Field::new($dir, $op, "SendFlg.Despawn"),
            Field::new($dir, $op, "SendFlg.Position"),
            Field::new($dir, $op, "x"),
            Field::new($dir, $op, "y"),
            Field::new($dir, $op, "z"),
        ]
    };
}
static AT_00E: [Field; 6] = place!(S2C, 0x00E);
static AT_00D: [Field; 6] = place!(S2C, 0x00D);
static AT_015: [Field; 6] = place!(C2S, 0x015);
const UID: usize = 0;
const DESPAWN: usize = 1;
const POSITION: usize = 2;

/// "<target> is drawn in!": actor and target are both the player drawn in.
const DRAWN_IN: i64 = 232;
/// "<target> learns <spell>!"
const LEARNED: i64 = 419;
/// server_status of a monster in a fight (LSB ANIMATION_ATTACK).
const ENGAGED: i64 = 1;
/// Yalms: a draw-in leaves the player beside its mob, up to 12 from a large one's centre.
const NEAR: f64 = 12.0;
/// A drawn player's next position comes within this.
const WAIT_MS: i64 = 3000;

pub static META: Meta = Meta {
    name: "mob_messages",
    version: 3,
    reads: &[(S2C, 0x029), (S2C, 0x00E), (S2C, 0x00D), (C2S, 0x015), (S2C, 0x00A)],
    tables: &[Table {
        name: "mob_messages",
        columns: &[
            ("kind", Str),
            ("player_id", I64),
            ("mob_id", I64),
            ("distance", F32),
            ("spell_id", I32),
            ("zone_id", I32),
        ],
    }],
    sparse: true,
};

type Id = Option<i64>;
type Xyz = (Option<f64>, Option<f64>, Option<f64>);

#[derive(Default)]
pub struct MobMessages {
    resends: Resends,
    monsters: HashSet<Id>,
    /// Monsters whose last general update had them engaged.
    engaged: HashSet<i64>,
    /// Monster -> its last position.
    pos: HashMap<i64, (f64, f64, f64)>,
    /// Player -> its draw-in's (row, ts_ms), until the player's next position.
    drawn: HashMap<Id, (RowId, i64)>,
}

fn xyz(k: &[Field; 6], f: &Decoded) -> Xyz {
    (k[3].float(f), k[4].float(f), k[5].float(f))
}

impl MobMessages {
    fn landed(&mut self, uid: Id, at: Xyz, p: &Packet, out: &mut Out) {
        let Some((row, ts)) = self.drawn.remove(&uid) else { return };
        let (Some(x), Some(y), Some(z)) = at else { return };
        if p.ts_ms - ts > WAIT_MS {
            return;
        }
        // Python's min over (distance, id): a tie goes to the lower id.
        let mut near: Option<(f64, i64)> = None;
        for (&m, &there) in self.pos.iter().filter(|(m, _)| self.engaged.contains(m)) {
            let d = dist3((x, y, z), there);
            if near.is_none_or(|(bd, bm)| if d == bd { m < bm } else { d < bd }) {
                near = Some((d, m));
            }
        }
        if let Some((d, m)) = near.filter(|&(d, _)| d <= NEAR) {
            out.set(row, "distance", d);
            out.set(row, "mob_id", m);
        }
    }
}

impl Extractor for MobMessages {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let op = p.opcode;
        if op == 0x00A {
            self.monsters.clear();
            self.engaged.clear();
            self.pos.clear();
            self.drawn.clear();
        } else if p.direction == C2S {
            self.landed(world.character_id, xyz(&AT_015, f), p, out);
        } else if op == 0x00D {
            if AT_00D[POSITION].flag(f) {
                self.landed(AT_00D[UID].int(f), xyz(&AT_00D, f), p, out);
            }
        } else if op == 0x00E {
            let k = &AT_00E;
            let uid = k[UID].int(f);
            if k[DESPAWN].flag(f) {
                if let Some(u) = uid {
                    self.pos.remove(&u);
                    self.engaged.remove(&u);
                }
                return;
            }
            if GENERAL.flag(f) {
                if MONSTER.flag(f) {
                    self.monsters.insert(uid);
                } else {
                    self.monsters.remove(&uid);
                }
                if let Some(u) = uid {
                    if STATUS.int(f) == Some(ENGAGED) {
                        self.engaged.insert(u);
                    } else {
                        self.engaged.remove(&u);
                    }
                }
            }
            let at = xyz(k, f);
            if k[POSITION].flag(f)
                && let (Some(x), Some(y), Some(z)) = at
            {
                if self.monsters.contains(&uid)
                    && let Some(u) = uid.filter(|_| is_mob(uid))
                {
                    self.pos.insert(u, (x, y, z));
                }
                self.landed(uid, at, p, out);
            }
        } else {
            let msg = MESSAGE.int(f);
            if !matches!(msg, Some(DRAWN_IN | LEARNED)) || self.resends.is_resend(p) {
                return;
            }
            let who = TARGET.int(f);
            if msg == Some(LEARNED) {
                let row = row! { kind: "learned", player_id: who, spell_id: DATA.int(f), zone_id: world.zone };
                out.emit("mob_messages", Some(p), row);
            } else {
                let row =
                    out.emit("mob_messages", Some(p), row! { kind: "drawn_in", player_id: who, zone_id: world.zone });
                self.drawn.insert(who, (row, p.ts_ms));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MEMBER, MapFields, PLAYER, drive};

    const ZONE: i64 = 0x0A3;
    const MOB: i64 = 0x01000000 | (ZONE << 12) | 0x010;
    const OTHER: i64 = MOB + 1;

    fn mob(uid: i64, x: f64, monster: i64) -> (u16, MapFields) {
        mob_in(uid, x, monster, 1)
    }

    fn mob_in(uid: i64, x: f64, monster: i64, status: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("UniqueNo", uid).int("SendFlg.General", 1).int("SendFlg.Position", 1);
        let f = f.int("Flags1.MonsterFlag", monster).int("server_status", status);
        (0x00E, f.float("x", x).float("y", 0.0).float("z", 0.0))
    }

    fn message(number: i64, who: i64, data: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("UniqueNoCas", who).int("UniqueNoTar", who);
        (0x029, f.int("MessageNum", number).int("Data", data))
    }

    fn at(op: u16, uid: Option<i64>, x: f64, y: f64) -> (u16, MapFields) {
        let f = MapFields::new().float("x", x).float("y", y).float("z", 0.0);
        match uid {
            Some(u) => (op, f.int("UniqueNo", u).int("SendFlg.Position", 1)),
            None => (op, f),
        }
    }

    fn got(out: &Out) -> Vec<[V; 5]> {
        let r = out.rows("mob_messages");
        let cols = ["kind", "player_id", "mob_id", "distance", "spell_id"];
        (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect()
    }

    /// test_mob_events.py's test_a_draw_in_names_the_monster_nearest_where_the_player_landed.
    #[test]
    fn a_draw_in_names_the_monster_nearest_where_the_player_landed() {
        let steps = vec![
            (0x00A, MapFields::new().int("ZoneNo", ZONE)),
            mob(MOB, 0.0, 1),
            mob(OTHER, 20.0, 1),
            mob(OTHER + 1, 1.0, 0), // an NPC beside the player is no monster
            message(232, PLAYER, 0),
            at(0x015, None, 19.0, 1.0), // the character lands beside OTHER
            message(232, MEMBER, 0),
            at(0x00D, Some(MEMBER), 0.5, 0.0),
            message(232, MEMBER, 0), // drawn in again, but its next position comes too late
            at(0x00D, Some(MEMBER), 0.5, 0.0),
            message(419, PLAYER, 584),
        ];
        let directions = steps.iter().map(|(op, _)| (*op == 0x015) as u8).collect();
        let times = vec![0, 0, 0, 0, 1000, 1100, 2000, 2200, 3000, 7000, 8000];
        let out = drive(
            &mut MobMessages::default(),
            steps,
            Drive { times: Some(times), directions: Some(directions), ..Drive::default() },
        );
        let s = |k: &str| V::Str(k.into());
        assert_eq!(
            got(&out),
            [
                [s("drawn_in"), V::Int(PLAYER), V::Int(OTHER), V::Float(2f64.sqrt() as f32 as f64), V::Null],
                [s("drawn_in"), V::Int(MEMBER), V::Int(MOB), V::Float(0.5), V::Null],
                [s("drawn_in"), V::Int(MEMBER), V::Null, V::Null, V::Null],
                [s("learned"), V::Int(PLAYER), V::Null, V::Null, V::Int(584)],
            ]
        );
    }

    /// test_mob_events.py's test_a_trust_drawn_in_lands_by_its_own_update_and_no_trust_draws_in.
    #[test]
    fn a_trust_drawn_in_lands_by_its_own_update_and_no_trust_draws_in() {
        let (trust, other) = (0x01000000 | (ZONE << 12) | 0x700, 0x01000000 | (ZONE << 12) | 0x701);
        let steps = vec![
            (0x00A, MapFields::new().int("ZoneNo", ZONE)),
            mob(MOB, 0.0, 1),
            mob(other, 9.0, 1), // another trust, flagged a monster, beside where the trust lands
            message(232, trust, 0),
            mob(trust, 9.5, 1),
        ];
        let out = drive(&mut MobMessages::default(), steps, Drive::default());
        let g = got(&out);
        assert_eq!((g.len(), &g[0][1..4]), (1, &[V::Int(trust), V::Int(MOB), V::Float(9.5)][..]));
    }

    /// test_mob_events.py's test_an_idle_monster_nearer_where_the_player_landed_drew_no_one_in.
    #[test]
    fn an_idle_monster_nearer_where_the_player_landed_drew_no_one_in() {
        let steps = vec![
            mob(MOB, 0.0, 1),
            mob_in(OTHER, 15.4, 1, 0),
            mob_in(OTHER, 15.4, 1, 1),
            mob_in(OTHER, 15.4, 1, 0),
            message(232, PLAYER, 0),
            (0x015, MapFields::new().float("x", 8.6).float("y", 0.0).float("z", 0.0)),
        ];
        let out = drive(
            &mut MobMessages::default(),
            steps,
            Drive { directions: Some(vec![0, 0, 0, 0, 0, 1]), ..Drive::default() },
        );
        assert_eq!(got(&out)[0][2], V::Int(MOB));
    }

    #[test]
    fn a_tie_goes_to_the_lower_id() {
        let steps = vec![
            mob(OTHER, 1.0, 1),
            mob(MOB, -1.0, 1),
            message(232, PLAYER, 0),
            (0x015, MapFields::new().float("x", 0.0).float("y", 0.0).float("z", 0.0)),
        ];
        let out =
            drive(&mut MobMessages::default(), steps, Drive { directions: Some(vec![0, 0, 0, 1]), ..Drive::default() });
        assert_eq!(got(&out)[0][2], V::Int(MOB));
    }
}
