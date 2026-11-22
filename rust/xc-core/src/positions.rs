//! battle/positions.py: where each entity is, as the packets last placed it, and which way it faces.

use std::collections::HashMap;

use indexmap::IndexMap;

use crate::packet::{C2S, Fields, Packet, S2C};
use crate::py;

pub type Xyz = (f64, f64, f64);

/// The last position, heading, size, and HP% the packets sent of each entity: NPCs, mobs, and trusts (0x00E),
/// other players (0x00D), HP% from those and the party's (0x0DD, 0x0DF). A zone-in forgets them all. Keys are
/// Option as in Python, where a packet without UniqueNo still files under None.
#[derive(Default)]
pub struct Places {
    /// Entity id -> last x, y, z, in the order Python's dict keeps: a key set again keeps its place.
    pub pos: IndexMap<Option<i64>, Xyz>,
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
            (S2C, 0x0DD | 0x0DF) => {
                if let (Some(uid), Some(hpp)) = (f.int("UniqueNo"), f.int("Hpp")) {
                    self.hpp.insert(Some(uid), hpp);
                }
            }
            (S2C, 0x00D | 0x00E) => {
                let uid = f.int("UniqueNo");
                if f.flag("SendFlg.Despawn") {
                    self.pos.shift_remove(&uid);
                    return true;
                }
                if f.flag("SendFlg.Position") {
                    if let (Some(_), Some(x), Some(y), Some(z)) = (uid, f.float("x"), f.float("y"), f.float("z")) {
                        self.pos.insert(uid, (x, y, z));
                        self.at.insert(uid, p.ts_ms);
                    }
                    if p.opcode == 0x00E
                        && let Some(d) = f.int("dir")
                    {
                        self.dir.insert(uid, (d, p.ts_ms));
                    }
                }
                if f.flag("SendFlg.General") {
                    if let Some(hpp) = f.int("Hpp") {
                        self.hpp.insert(uid, hpp);
                    }
                    if p.opcode == 0x00E && f.flag("Flags2.g") {
                        self.size.insert(uid, f.float("Flags2.g").unwrap() / 10.0);
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
