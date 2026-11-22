//! battle/positions.py: where each entity is, as the packets last placed it, and which way it faces.

use indexmap::IndexMap;
use rustc_hash::{FxBuildHasher, FxHashMap as HashMap};

use crate::packet::{C2S, Field, Fields, Packet, S2C};
use crate::py;

pub type Xyz = (f64, f64, f64);

static HP_0DD: [Field; 2] = [Field::new(S2C, 0x0DD, "UniqueNo"), Field::new(S2C, 0x0DD, "Hpp")];
static HP_0DF: [Field; 2] = [Field::new(S2C, 0x0DF, "UniqueNo"), Field::new(S2C, 0x0DF, "Hpp")];
const UID: usize = 0;
const DESPAWN: usize = 1;
const POSITION: usize = 2;
const X: usize = 3;
const Y: usize = 4;
const Z: usize = 5;
const DIR: usize = 6;
const GENERAL: usize = 7;
const HPP: usize = 8;
const SIZE: usize = 9;
macro_rules! entity {
    ($op:expr) => {
        [
            Field::new(S2C, $op, "UniqueNo"),
            Field::new(S2C, $op, "SendFlg.Despawn"),
            Field::new(S2C, $op, "SendFlg.Position"),
            Field::new(S2C, $op, "x"),
            Field::new(S2C, $op, "y"),
            Field::new(S2C, $op, "z"),
            Field::new(S2C, $op, "dir"),
            Field::new(S2C, $op, "SendFlg.General"),
            Field::new(S2C, $op, "Hpp"),
            Field::new(S2C, $op, "Flags2.g"),
        ]
    };
}
static ENTITY_00D: [Field; 10] = entity!(0x00D);
static ENTITY_00E: [Field; 10] = entity!(0x00E);

/// The last position, heading, size, and HP% the packets sent of each entity: NPCs, mobs, and trusts (0x00E),
/// other players (0x00D), HP% from those and the party's (0x0DD, 0x0DF). A zone-in forgets them all. Keys are
/// Option as in Python, where a packet without UniqueNo still files under None.
#[derive(Default)]
pub struct Places {
    /// Entity id -> last x, y, z, in the order Python's dict keeps: a key set again keeps its place.
    pub pos: IndexMap<Option<i64>, Xyz, FxBuildHasher>,
    pub at: HashMap<Option<i64>, i64>,
    /// Entity id -> (heading, when).
    pub dir: HashMap<Option<i64>, (i64, i64)>,
    /// Entity id -> yalms.
    pub size: HashMap<Option<i64>, f64>,
    pub hpp: HashMap<Option<i64>, i64>,
}

impl Places {
    pub const READS: [(u8, u16); 6] =
        [(S2C, 0x00A), (S2C, 0x00E), (S2C, 0x00D), (S2C, 0x0DD), (S2C, 0x0DF), (C2S, 0x015)];

    /// Keep what p says; true when p is one of READS.
    pub fn update(&mut self, p: &Packet, f: &dyn Fields) -> bool {
        match p.key() {
            (S2C, 0x00A) => {
                self.pos.clear();
                self.at.clear();
                self.dir.clear();
                self.size.clear();
                self.hpp.clear();
            }
            (C2S, 0x015) => {}
            (S2C, op @ (0x0DD | 0x0DF)) => {
                let ids = if op == 0x0DD { &HP_0DD } else { &HP_0DF };
                if let (Some(uid), Some(hpp)) = (ids[0].int(f), ids[1].int(f)) {
                    self.hpp.insert(Some(uid), hpp);
                }
            }
            (S2C, op @ (0x00D | 0x00E)) => {
                let k = if op == 0x00E { &ENTITY_00E } else { &ENTITY_00D };
                let uid = k[UID].int(f);
                if k[DESPAWN].flag(f) {
                    self.pos.shift_remove(&uid);
                    return true;
                }
                if k[POSITION].flag(f) {
                    if let (Some(_), Some(x), Some(y), Some(z)) = (uid, k[X].float(f), k[Y].float(f), k[Z].float(f)) {
                        self.pos.insert(uid, (x, y, z));
                        self.at.insert(uid, p.ts_ms);
                    }
                    if op == 0x00E
                        && let Some(d) = k[DIR].int(f)
                    {
                        self.dir.insert(uid, (d, p.ts_ms));
                    }
                }
                if k[GENERAL].flag(f) {
                    if let Some(hpp) = k[HPP].int(f) {
                        self.hpp.insert(uid, hpp);
                    }
                    if op == 0x00E && k[SIZE].flag(f) {
                        self.size.insert(uid, k[SIZE].float(f).unwrap() / 10.0);
                    }
                }
            }
            _ => return false,
        }
        true
    }
}

/// Degrees from the heading to there, -180 to 180. A heading counts 256ths of a turn as LSB's worldAngle
/// does: -atan2(dy, dx) on the ground plane, which XiPackets names x and y.
pub fn bearing(here: Xyz, there: Xyz, heading: Option<i64>) -> Option<f64> {
    let (dx, dy) = (there.0 - here.0, there.1 - here.1);
    let heading = heading?;
    if py::hypot(&[dx, dy]) < 0.1 {
        return None;
    }
    Some(py::fmod(-dy.atan2(dx).to_degrees() - (heading * 360) as f64 / 256.0 + 180.0, 360.0) - 180.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bearings() {
        let o = (0.0, 0.0, 0.0);
        assert_eq!(bearing(o, (1.0, 0.0, 0.0), Some(0)), Some(0.0));
        assert_eq!(bearing(o, (0.0, -1.0, 0.0), Some(0)), Some(90.0));
        assert_eq!(bearing(o, (0.0, -1.0, 0.0), Some(64)), Some(0.0));
        assert_eq!(bearing(o, (-1.0, 0.0, 0.0), Some(0)), Some(-180.0));
        assert_eq!(bearing(o, (0.05, 0.0, 0.0), Some(0)), None);
        assert_eq!(bearing(o, (1.0, 0.0, 0.0), None), None);
    }
}
