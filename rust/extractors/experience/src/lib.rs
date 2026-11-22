//! progress/experience.py, line for line: points the character gained and level changes, from the battle
//! message 0x02D, with what changes the points: its status effects (0x063's status list), key items (0x055),
//! and party (the world's). Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat::{Resends, is_mob};
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};
use xc_keyitems::key_items;

/// 0x02D messages that give points (LSB msg_basic): (kind, whether Data2 holds the chain number).
fn gain(msg: i64) -> Option<(&'static str, bool)> {
    Some(match msg {
        8 => ("exp", false),
        253 => ("exp", true),
        371 => ("limit", false),
        372 => ("limit", true),
        718 => ("capacity", false),
        735 => ("capacity", true),
        809 => ("exemplar", false),
        810 => ("exemplar", true),
        _ => return None,
    })
}

/// LSB msg_basic LevelUp, LevelDown.
fn level(msg: i64) -> Option<&'static str> {
    Some(match msg {
        9 => "up",
        11 => "down",
        _ => return None,
    })
}

/// 0x063's type for the character's status list.
const STATUS_ICONS: i64 = 9;
/// Python's EFFECTS and SIGNET, in order: the status effects that change the points a kill gives.
const EFFECTS: [i64; 8] = [143, 249, SIGNET, 256, 269, 326, 512, 579];
/// A bonus in a party of 2 to 5 only.
const SIGNET: i64 = 253;
/// Key items that raise the points, in order.
const KEY_ITEMS: [i64; 19] =
    [542, 562, 563, 2716, 2745, 2746, 2754, 2762, 2765, 2771, 2775, 2787, 2788, 2884, 2885, 2886, 2887, 2888, 2889];

pub static META: Meta = Meta {
    name: "experience",
    version: 1,
    reads: &[(S2C, 0x02D), (S2C, 0x063), (S2C, 0x055)],
    tables: &[
        Table {
            name: "exp_gains",
            columns: &[
                ("recipient_id", I64),
                ("own", Bool),
                ("kind", Str),
                ("points", I64),
                ("chain", I32),
                ("message", I32),
                ("mob_id", I64),
                ("party_size", I32),
                ("effects", ListI32),
                ("key_items", ListI32),
                ("zone_id", I32),
            ],
        },
        Table {
            name: "level_changes",
            columns: &[
                ("member_id", I64),
                ("own", Bool),
                ("change", Str),
                ("level", I32),
                ("mob_id", I64),
                ("zone_id", I32),
            ],
        },
    ],
    sparse: true,
};

static TYPE: Field = Field::new(S2C, 0x063, "type");
static MSG: Field = Field::new(S2C, 0x02D, "MessageNum");
static CASTER: Field = Field::new(S2C, 0x02D, "UniqueNoCas");
static TARGET: Field = Field::new(S2C, 0x02D, "UniqueNoTar");
static DATA: Field = Field::new(S2C, 0x02D, "Data");
static DATA2: Field = Field::new(S2C, 0x02D, "Data2");

macro_rules! icons {
    ($($i:literal)*) => { [$(Field::new(S2C, 0x063, concat!("data.icon[", $i, "]"))),*] };
}
static ICONS: [Field; 32] =
    icons!(0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31);

/// The ids of xs whose bit is set in mask.
fn chosen(xs: &[i64], mask: u32) -> Vec<Option<i64>> {
    xs.iter().enumerate().filter(|&(i, _)| mask >> i & 1 != 0).map(|(_, &x)| Some(x)).collect()
}

#[derive(Default)]
pub struct Experience {
    /// The character's statuses among EFFECTS, a bit each.
    statuses: u32,
    /// Key item table -> the KEY_ITEMS it holds, a bit each.
    held: HashMap<i64, u32>,
    resends: Resends,
}

impl Extractor for Experience {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if p.opcode == 0x063 {
            if TYPE.int(f) == Some(STATUS_ICONS) {
                self.statuses = 0;
                for icon in &ICONS {
                    if let Some(i) = icon.int(f).and_then(|s| EFFECTS.iter().position(|&e| e == s)) {
                        self.statuses |= 1 << i;
                    }
                }
            }
            return;
        }
        if p.opcode == 0x055 {
            let (table, words) = key_items(f);
            let mut mask = 0;
            for (i, &ki) in KEY_ITEMS.iter().enumerate() {
                let (t, k) = (ki / 512, ki % 512);
                if t == table && words[(k / 32) as usize] >> (k % 32) & 1 != 0 {
                    mask |= 1 << i;
                }
            }
            self.held.insert(table, mask);
            return;
        }
        let Some(msg) = MSG.int(f).filter(|&m| gain(m).is_some() || level(m).is_some()) else { return };
        if self.resends.is_resend(p) {
            return;
        }
        let (who, target) = (CASTER.int(f), TARGET.int(f));
        let mob = target.filter(|_| is_mob(target));
        let own = who == world.character_id;
        if let Some(change) = level(msg) {
            out.emit(
                "level_changes",
                Some(p),
                row! { member_id: who, own: own, change: change, level: DATA.int(f), mob_id: mob, zone_id: world.zone },
            );
            return;
        }
        let (kind, chained) = gain(msg).unwrap();
        let me = world.character_id.is_some_and(|c| world.party.contains(&c));
        let size = world.party.len() - me as usize + 1;
        let signet = 1 << EFFECTS.iter().position(|&e| e == SIGNET).unwrap();
        let effects = if (2..=5).contains(&size) { self.statuses } else { self.statuses & !signet };
        let held = if own { self.held.values().fold(0, |a, &m| a | m) } else { 0 };
        out.emit(
            "exp_gains",
            Some(p),
            row! {
                recipient_id: who,
                own: own,
                kind: kind,
                points: DATA.int(f),
                chain: if chained { DATA2.int(f).unwrap_or(0) } else { 0 },
                message: msg,
                mob_id: mob,
                party_size: size,
                effects: chosen(&EFFECTS, if own { effects } else { 0 }),
                key_items: chosen(&KEY_ITEMS, held),
                zone_id: world.zone,
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MEMBER, MOB, MapFields, PLAYER, drive};

    const DEDICATION: i64 = 249;
    const WHITE: i64 = 2884;

    fn message(msg: i64, data: i64, data2: i64, who: i64, target: i64) -> (u16, MapFields) {
        let f = MapFields::new()
            .int("UniqueNoCas", who)
            .int("UniqueNoTar", target)
            .int("Data", data)
            .int("Data2", data2)
            .int("MessageNum", msg);
        (0x02D, f)
    }

    fn statuses(ids: &[i64]) -> (u16, MapFields) {
        let mut f = MapFields::new().int("type", 9).int("data.icon[5]", 255);
        for (i, &s) in ids.iter().enumerate() {
            f = f.int(&format!("data.icon[{i}]"), s);
        }
        (0x063, f)
    }

    /// Table 5 holds 2560 to 3071.
    fn key_items(ids: &[i64]) -> (u16, MapFields) {
        let mut words: HashMap<i64, i64> = HashMap::new();
        for k in ids {
            *words.entry((k - 2560) / 32).or_default() |= 1 << ((k - 2560) % 32);
        }
        let mut f = MapFields::new().int("TableIndex", 5);
        for (i, w) in words {
            f = f.int(&format!("GetItemFlag[{i}]"), w);
        }
        (0x055, f)
    }

    fn ints(xs: &[i64]) -> V {
        V::Ints(xs.iter().map(|&x| Some(x)).collect())
    }

    #[test]
    fn gains_name_their_chain_mob_and_bonuses() {
        // drive's party holds a member, so Signet counts.
        let steps = vec![
            statuses(&[DEDICATION, SIGNET, 40]),
            key_items(&[WHITE, 2890]),
            message(8, 493, 0, PLAYER, MOB),
            message(253, 1200, 1, PLAYER, MOB),
            message(253, 1250, 2, PLAYER, MOB),
            message(372, 4888, 52, PLAYER, MOB),
            message(8, 300, 0, PLAYER, PLAYER),
        ];
        let out = drive(&mut Experience::default(), steps, Drive::default());
        let r = out.rows("exp_gains");
        let cols = ["kind", "points", "chain", "mob_id", "effects", "key_items", "party_size"];
        let got: Vec<_> = (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect();
        let row = |kind: &str, points, chain, mob: Option<i64>| {
            [
                V::Str(kind.into()),
                V::Int(points),
                V::Int(chain),
                mob.into(),
                ints(&[DEDICATION, SIGNET]),
                ints(&[WHITE]),
                V::Int(2),
            ]
        };
        assert_eq!(
            got,
            [
                row("exp", 493, 0, Some(MOB)),
                row("exp", 1200, 1, Some(MOB)),
                row("exp", 1250, 2, Some(MOB)),
                row("limit", 4888, 52, Some(MOB)),
                row("exp", 300, 0, None),
            ]
        );
    }

    #[test]
    fn level_ups_and_downs_of_anyone() {
        let steps =
            vec![message(9, 12, 0, PLAYER, MOB), message(9, 12, 0, MEMBER, MOB), message(11, 74, 0, PLAYER, PLAYER)];
        let out = drive(&mut Experience::default(), steps, Drive::default());
        let r = out.rows("level_changes");
        let cols = ["member_id", "own", "change", "level", "mob_id"];
        let got: Vec<_> = (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect();
        let row = |who: i64, own, change: &str, level, mob: Option<i64>| {
            [V::Int(who), V::Bool(own), V::Str(change.into()), V::Int(level), mob.into()]
        };
        assert_eq!(
            got,
            [
                row(PLAYER, true, "up", 12, Some(MOB)),
                row(MEMBER, false, "up", 12, Some(MOB)),
                row(PLAYER, true, "down", 74, None)
            ]
        );
    }

    #[test]
    fn signet_counts_only_in_a_party_of_two_to_five() {
        let out = drive(
            &mut Experience::default(),
            vec![statuses(&[SIGNET, DEDICATION]), message(8, 10, 0, PLAYER, MOB), message(8, 10, 0, MEMBER, MOB)],
            Drive { me: MEMBER, ..Drive::default() },
        );
        let r = out.rows("exp_gains");
        assert_eq!((r.get(0, "party_size"), r.get(0, "effects")), (V::Int(1), ints(&[])), "not the character's");
        assert_eq!((r.get(1, "party_size"), r.get(1, "effects")), (V::Int(1), ints(&[DEDICATION])), "alone");
    }
}
