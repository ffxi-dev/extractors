//! battle/actions.py, line for line: every action packet (0x028), by anyone, in every category; each result
//! on each target; and for a mob TP move, who stood near the mob. The reference port: its Python twin keeps
//! the docs, and this keeps its name, version, reads, and columns.

use std::collections::{HashMap, HashSet};

use xc_core::combat::{self, Resends};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::positions::{Places, Xyz, bearing};
use xc_core::py::dist3;
use xc_core::{C2S, Decoded, Packet, S2C, World, row};

/// A mob's heading older than this at its TP move is unknown.
const FRESH_MS: i64 = 2000;
/// Yalms: bystanders farther from the mob than this are not kept; targets always are.
const NEAR: f64 = 30.0;
/// A start's cmd_arg low half when it stops what began (LSB's interrupt).
const INTERRUPT: i64 = 28787;
/// A start older than this is not the finish's.
const STALE_MS: i64 = 30000;

/// A finish's category -> its start's.
fn start_of(finish: Option<i64>) -> Option<i64> {
    match finish? {
        11 => Some(7),
        4 => Some(8),
        2 => Some(12),
        _ => None,
    }
}

pub static META: Meta = Meta {
    name: "actions",
    version: 5,
    reads: &[(S2C, 0x028), (S2C, 0x00A), (S2C, 0x00E), (S2C, 0x00D), (S2C, 0x0DD), (S2C, 0x0DF), (C2S, 0x015)],
    tables: &[
        Table {
            name: "actions",
            columns: &[
                ("actor_id", I64),
                ("actor_is_mob", Bool),
                ("category", I32),
                ("action_id", I64),
                ("cmd_arg", I64),
                ("targets", I32),
                ("message", I32),
                ("animation", I32),
                ("ready_ms", I64),
                ("max_range", F32),
                ("max_spread", F32),
                ("actor_dir", I32),
                ("actor_size", F32),
                ("zone_id", I32),
                ("resend", Bool),
            ],
        },
        Table {
            name: "action_results",
            columns: &[
                ("actor_id", I64),
                ("category", I32),
                ("action_id", I64),
                ("target_id", I64),
                ("target_index", I32),
                ("result_index", I32),
                ("miss", I32),
                ("kind", I32),
                ("sub_kind", I32),
                ("info", I32),
                ("scale", I32),
                ("value", I64),
                ("message", I32),
                ("bit", I64),
                ("proc_kind", I32),
                ("proc_info", I32),
                ("proc_value", I64),
                ("proc_message", I32),
                ("react_kind", I32),
                ("react_info", I32),
                ("react_value", I64),
                ("react_message", I32),
            ],
        },
        Table {
            name: "tp_nearby",
            columns: &[
                ("actor_id", I64),
                ("action_id", I64),
                ("entity_id", I64),
                ("hit", Bool),
                ("party", Bool),
                ("distance", F32),
                ("bearing", F32),
                ("from_target", F32),
                ("age_ms", I64),
            ],
        },
    ],
};

#[derive(Default)]
pub struct Actions {
    /// Actor -> (category, action id, ts) of its last start.
    starts: HashMap<Option<i64>, (Option<i64>, Option<i64>, i64)>,
    resends: Resends,
    places: Places,
}

impl Extractor for Actions {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if self.places.update(p, f) {
            if p.opcode == 0x00A {
                self.starts.clear();
            }
            return;
        }
        let a = f.action();
        let (cat, actor) = (a.cmd_no, a.actor_id);
        let first = a.first();
        let mut action_id = match first {
            Some(r) if matches!(cat, Some(7..=9)) => r.value,
            _ => a.cmd_arg,
        };
        let resend = self.resends.is_resend(p);
        let mut ready = None;
        let starting = matches!(cat, Some(7 | 8 | 12));
        if !resend && starting && a.cmd_arg.unwrap_or(0) & 0xFFFF == INTERRUPT {
            if let Some((c, i, t)) = self.starts.remove(&actor)
                && c == cat
                && p.ts_ms - t <= STALE_MS
            {
                (action_id, ready) = (i, Some(p.ts_ms - t));
            }
        } else if !resend && starting {
            self.starts.insert(actor, (cat, action_id, p.ts_ms));
        } else if !resend && start_of(cat).is_some() && self.starts.contains_key(&actor) {
            let (c, i, t) = self.starts.remove(&actor).unwrap();
            // A ranged start carries no id of its finish's.
            if c == start_of(cat) && (cat == Some(2) || i == action_id) && p.ts_ms - t <= STALE_MS {
                ready = Some(p.ts_ms - t);
            }
        }
        let (mut reach, mut spread, mut heading, mut size) = (None, None, None, None);
        if cat == Some(11) && !resend {
            let me = world.character_id;
            if let (Some(m), Some(here)) = (me.filter(|&m| m != 0), world.here()) {
                self.places.pos.insert(Some(m), here);
                self.places.at.insert(Some(m), world.pos_ms);
            }
            let targets: Vec<Option<i64>> = a.targets.iter().map(|t| t.id).filter(|&t| t != actor).collect();
            (reach, spread) = self.measure(actor, &targets);
            heading = match self.places.dir.get(&actor) {
                Some(&(d, at)) if p.ts_ms - at <= FRESH_MS => Some(d),
                _ => None,
            };
            size = self.places.size.get(&actor).copied();
            let all: Vec<Option<i64>> = a.targets.iter().map(|t| t.id).collect();
            self.nearby(p, actor, action_id, &all, heading, world, out);
        }
        out.emit(
            "actions",
            Some(p),
            row! {
                actor_id: actor,
                actor_is_mob: combat::is_mob(actor),
                category: cat,
                action_id: action_id,
                cmd_arg: a.cmd_arg,
                targets: a.targets.len(),
                message: first.and_then(|r| r.message),
                animation: first.and_then(|r| r.sub_kind),
                ready_ms: ready,
                max_range: reach,
                max_spread: spread,
                actor_dir: heading,
                actor_size: size,
                zone_id: world.zone,
                resend: resend,
            },
        );
        for (t, target) in a.targets.iter().enumerate() {
            for (i, r) in target.results.iter().enumerate() {
                let (proc, react) = (r.proc.clone().unwrap_or_default(), r.react.clone().unwrap_or_default());
                out.emit(
                    "action_results",
                    Some(p),
                    row! {
                        actor_id: actor,
                        category: cat,
                        action_id: action_id,
                        target_id: target.id,
                        target_index: t,
                        result_index: i,
                        miss: r.miss,
                        kind: r.kind,
                        sub_kind: r.sub_kind,
                        info: r.info,
                        scale: r.scale,
                        value: r.value,
                        message: r.message,
                        bit: r.bit,
                        proc_kind: proc.kind,
                        proc_info: proc.info,
                        proc_value: proc.value,
                        proc_message: proc.message,
                        react_kind: react.kind,
                        react_info: react.info,
                        react_value: react.value,
                        react_message: react.message,
                    },
                );
            }
        }
    }
}

impl Actions {
    /// A tp_nearby row for each target placed and each other placed entity within NEAR of the mob.
    #[allow(clippy::too_many_arguments)]
    fn nearby(
        &self,
        p: &Packet,
        actor: Option<i64>,
        action_id: Option<i64>,
        targets: &[Option<i64>],
        heading: Option<i64>,
        world: &World,
        out: &mut Out,
    ) {
        let places = &self.places;
        let Some(&here) = places.pos.get(&actor) else { return };
        let hit: HashSet<Option<i64>> = targets.iter().copied().collect();
        let in_party = |uid: Option<i64>| uid == world.character_id || uid.is_some_and(|u| world.party.contains(&u));
        let first = targets.first().and_then(|t| places.pos.get(t)).copied();
        for (&uid, &there) in &places.pos {
            if uid == actor {
                continue;
            }
            let far = dist3(here, there);
            if !hit.contains(&uid) && (far > NEAR || places.hpp.get(&uid) == Some(&0)) {
                continue;
            }
            out.emit(
                "tp_nearby",
                Some(p),
                row! {
                    actor_id: actor,
                    action_id: action_id,
                    entity_id: uid,
                    hit: hit.contains(&uid),
                    party: in_party(uid),
                    distance: far,
                    bearing: bearing(here, there, heading),
                    from_target: first.map(|f| dist3(f, there)),
                    age_ms: p.ts_ms - places.at[&uid],
                },
            );
        }
    }

    /// The farthest target from the actor and the farthest two targets apart. Any unknown position leaves its
    /// measure unknown rather than short.
    fn measure(&self, actor: Option<i64>, targets: &[Option<i64>]) -> (Option<f64>, Option<f64>) {
        let here = self.places.pos.get(&actor).copied();
        let there: Option<Vec<Xyz>> = targets.iter().map(|t| self.places.pos.get(t).copied()).collect();
        let Some(there) = there.filter(|t| !t.is_empty()) else { return (None, None) };
        let reach = here.map(|h| there.iter().map(|&t| dist3(h, t)).fold(f64::NEG_INFINITY, f64::max));
        let mut spread: Option<f64> = None;
        for (i, &a) in there.iter().enumerate() {
            for &b in &there[i + 1..] {
                let d = dist3(a, b);
                spread = Some(spread.map_or(d, |s| if d > s { d } else { s }));
            }
        }
        (reach, spread)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MOB, MapFields, PLAYER, drive};

    const P: &str = "action (decoded bitstream).";

    fn action(actor: i64, cat: i64, arg: i64, targets: &[(i64, i64)]) -> MapFields {
        let mut f = MapFields::new()
            .int(&format!("{P}actor_id"), actor)
            .int(&format!("{P}cmd_no"), cat)
            .int(&format!("{P}cmd_arg"), arg)
            .int(&format!("{P}info"), 0)
            .int(&format!("{P}target_count"), targets.len() as i64);
        for (t, &(id, value)) in targets.iter().enumerate() {
            let tp = format!("{P}targets[{t}]");
            f = f.int(&format!("{tp}.target_id"), id).int(&format!("{tp}.result_count"), 1);
            for k in ["miss", "kind", "sub_kind", "info", "scale", "message", "bit"] {
                f = f.int(&format!("{tp}[0].{k}"), 0);
            }
            f = f.int(&format!("{tp}[0].value"), value);
        }
        f
    }

    fn place(uid: i64, x: f64) -> MapFields {
        MapFields::new()
            .int("UniqueNo", uid)
            .int("SendFlg.Position", 1)
            .float("x", x)
            .float("y", 0.0)
            .float("z", 0.0)
            .int("dir", 0)
    }

    #[test]
    fn a_tp_move_is_timed_measured_and_its_bystanders_placed() {
        let out = drive(
            &mut Actions::default(),
            vec![
                (0x00E, place(MOB, 0.0)),
                (0x00D, place(PLAYER, 3.0)),
                (0x00D, place(PLAYER + 9, 40.0)),
                (0x028, action(MOB, 7, 24931, &[(PLAYER, 300)])),
                (0x028, action(MOB, 11, 300, &[(PLAYER, 55)])),
            ],
            Drive { me: 0, ..Drive::default() },
        );
        let a = out.rows("actions");
        assert_eq!((a.len(), a.get(0, "action_id"), a.get(0, "ready_ms")), (2, V::Int(300), V::Null));
        assert_eq!(a.get(1, "ready_ms"), V::Int(1000));
        assert_eq!(a.get(1, "max_range"), V::Float(3.0));
        assert_eq!(a.get(1, "actor_dir"), V::Null, "the heading is 4 s old");
        assert_eq!(out.rows("action_results").len(), 2);
        let near = out.rows("tp_nearby");
        assert_eq!(near.len(), 1, "the player 40 yalms off is no bystander");
        assert_eq!((near.get(0, "entity_id"), near.get(0, "hit")), (V::Int(PLAYER), V::Bool(true)));
    }

    #[test]
    fn an_interrupt_carries_what_it_stopped() {
        let out = drive(
            &mut Actions::default(),
            vec![(0x028, action(MOB, 8, 24931, &[(PLAYER, 144)])), (0x028, action(MOB, 8, INTERRUPT, &[(PLAYER, 0)]))],
            Drive::default(),
        );
        let a = out.rows("actions");
        assert_eq!((a.get(1, "action_id"), a.get(1, "ready_ms")), (V::Int(144), V::Int(1000)));
    }
}
