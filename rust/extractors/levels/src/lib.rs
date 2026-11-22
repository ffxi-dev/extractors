//! world/levels.py: mob levels as widescan lists (0x0F4) and /check replies (0x029) report them, a row per
//! change of level in a mob's life. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::combat;
use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{Decoded, Field, Packet, S2C, World, row};

pub static META: Meta = Meta {
    name: "levels",
    version: 2,
    reads: &[(S2C, 0x0F4), (S2C, 0x029), (S2C, 0x00E), (S2C, 0x00A)],
    sparse: true,
    tables: &[Table {
        name: "levels",
        columns: &[
            ("entity_id", I64),
            ("level", I32),
            ("source", Str),
            ("name", Str),
            ("zone_id", I32),
            ("end_idx", I64),
        ],
    }],
};

/// Widescan's entry type for a mob.
const ENEMY: i64 = 2;
/// /check replies that carry the level (LSB msg_basic around CheckDefault 174).
const CHECK: std::ops::RangeInclusive<i64> = 170..=178;

static DESPAWN: Field = Field::new(S2C, 0x00E, "SendFlg.Despawn");
static UID: Field = Field::new(S2C, 0x00E, "UniqueNo");
static LEVEL: Field = Field::new(S2C, 0x0F4, "TrackingListTbl.Level");
static INDEX: Field = Field::new(S2C, 0x0F4, "TrackingListTbl.ActIndex");
static TYPE: Field = Field::new(S2C, 0x0F4, "TrackingListTbl.Type");
static NAME: Field = Field::new(S2C, 0x0F4, "TrackingListTbl.sName");
static MESSAGE: Field = Field::new(S2C, 0x029, "MessageNum");
static TARGET: Field = Field::new(S2C, 0x029, "UniqueNoTar");
static DATA: Field = Field::new(S2C, 0x029, "Data");

#[derive(Default)]
pub struct Levels {
    /// (mob, source) -> its last level reported in this life.
    last: HashMap<(Option<i64>, &'static str), i64>,
    /// Mob -> its rows in this life.
    life: HashMap<Option<i64>, Vec<(RowId, &'static str)>>,
}

impl Levels {
    fn end(&mut self, uid: Option<i64>, p: &Packet, out: &mut Out) {
        for (row, source) in self.life.remove(&uid).unwrap_or_default() {
            out.set(row, "end_idx", p.idx as i64);
            self.last.remove(&(uid, source));
        }
    }
}

impl Extractor for Levels {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let (uid, level, source) = match p.opcode {
            0x00A => {
                for (_, rows) in self.life.drain() {
                    for (row, _) in rows {
                        out.set(row, "end_idx", p.idx as i64);
                    }
                }
                self.last.clear();
                return;
            }
            0x00E => {
                if DESPAWN.flag(f) {
                    self.end(UID.int(f), p, out);
                }
                return;
            }
            0x0F4 => {
                let (level, index) = (LEVEL.int(f), INDEX.int(f));
                let (Some(level), Some(index), Some(zone)) = (level, index, world.zone) else { return };
                if TYPE.int(f) != Some(ENEMY) || level < 0 {
                    return;
                }
                (Some(0x1000000 + (zone << 12) + index), level, "widescan")
            }
            _ => {
                let msg = MESSAGE.int(f);
                if combat::is_defeat(msg) {
                    self.end(TARGET.int(f), p, out);
                    return;
                }
                // A mob /check cannot gauge (level ???) answers 0xFFFFFFFF: no level, and no row.
                match (msg, DATA.int(f)) {
                    (Some(m), Some(level)) if CHECK.contains(&m) && 0 < level && level < 256 => {
                        (TARGET.int(f), level, "check")
                    }
                    _ => return,
                }
            }
        };
        if self.last.get(&(uid, source)) != Some(&level) {
            self.last.insert((uid, source), level);
            let name = if source == "widescan" { NAME.text(f) } else { None };
            let row = out.emit(
                "levels",
                Some(p),
                row! { entity_id: uid, level: level, source: source, name: name, zone_id: world.zone },
            );
            self.life.entry(uid).or_default().push((row, source));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MOB, MapFields, drive};

    fn zone_in() -> (u16, MapFields) {
        (0x00A, MapFields::new().int("ZoneNo", 0x0A3))
    }

    fn scan(index: i64, level: i64, kind: i64) -> (u16, MapFields) {
        let f = MapFields::new().int("TrackingListTbl.ActIndex", index).int("TrackingListTbl.Level", level);
        (0x0F4, f.int("TrackingListTbl.Type", kind).text("TrackingListTbl.sName", "Goblin"))
    }

    fn reply(uid: i64, msg: i64, data: i64) -> (u16, MapFields) {
        (0x029, MapFields::new().int("UniqueNoTar", uid).int("MessageNum", msg).int("Data", data))
    }

    fn rows<const N: usize>(steps: Vec<(u16, MapFields)>, cols: [&str; N]) -> Vec<[V; N]> {
        let out = drive(&mut Levels::default(), steps, Drive::default());
        let r = out.rows("levels");
        (0..r.len()).map(|i| cols.map(|c| r.get(i, c))).collect()
    }

    #[test]
    fn a_widescan_list_and_a_check() {
        let steps = vec![
            zone_in(),
            scan(0x010, 30, 2),
            scan(0x010, 30, 2),
            scan(0x010, 32, 2),
            scan(0x011, 1, 1),
            reply(MOB, 173, 31),
            // A mob whose level /check cannot gauge answers 0xFFFFFFFF.
            reply(MOB + 1, 174, 0xFFFFFFFF),
        ];
        let (n, s) = (V::Int, |t: &str| V::Str(t.into()));
        assert_eq!(
            rows(steps, ["entity_id", "level", "source", "name"]),
            [
                [n(MOB), n(30), s("widescan"), s("Goblin")],
                [n(MOB), n(32), s("widescan"), s("Goblin")],
                [n(MOB), n(31), s("check"), V::Null],
            ]
        );
    }

    #[test]
    fn levels_by_life() {
        let defeat = || reply(MOB, 6, 0);
        let gone = (0x00E, MapFields::new().int("UniqueNo", MOB).int("ActIndex", 0x010).int("SendFlg.Despawn", 1));
        // 5 (twice), defeated; 6, defeated; 5, out of view; 5 again, then a zone change and a /check.
        let steps = vec![
            zone_in(),
            scan(0x010, 5, 2),
            scan(0x010, 5, 2),
            defeat(),
            scan(0x010, 6, 2),
            defeat(),
            scan(0x010, 5, 2),
            gone,
            scan(0x010, 5, 2),
            zone_in(),
            reply(MOB, 173, 5),
        ];
        let (n, s) = (V::Int, |t: &str| V::Str(t.into()));
        assert_eq!(
            rows(steps, ["level", "source", "idx", "end_idx"]),
            [
                [n(5), s("widescan"), n(1), n(3)],
                [n(6), s("widescan"), n(4), n(5)],
                [n(5), s("widescan"), n(6), n(7)],
                [n(5), s("widescan"), n(8), n(9)],
                [n(5), s("check"), n(10), V::Null],
            ]
        );
    }
}
