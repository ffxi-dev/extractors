//! world.py: what a capture's packets say about the world so far: the zone and its weather, the recording
//! character and where it stands, its party, its inventory, and the entities around it. Field for field as
//! Python's World, None where Python keeps None.

use std::collections::{HashMap, HashSet};

use crate::packet::{C2S, Fields, Packet, S2C};

/// The packets update() reads. Every run decodes them, beside its extractors' own.
pub const WORLD: [(u8, u16); 11] = [
    (S2C, 0x00A),
    (S2C, 0x00E),
    (S2C, 0x037),
    (S2C, 0x0DD),
    (S2C, 0x0E2),
    (S2C, 0x0C8),
    (S2C, 0x01E),
    (S2C, 0x01F),
    (S2C, 0x020),
    (S2C, 0x057),
    (C2S, 0x015),
];
/// world.py's WORLD_VERSION: what update() keeps.
pub const WORLD_VERSION: u32 = 2;

/// An NPC or mob id holds its zone in bits 12 to 23, as LSB reads it; a player's id does not.
pub fn zone_of(id: Option<i64>) -> Option<i64> {
    id.filter(|&i| i >= 0x1000000).map(|i| (i >> 12) & 0xFFF)
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Entity {
    pub id: Option<i64>,
    pub name: Option<String>,
}

pub type Pos = (Option<f64>, Option<f64>, Option<f64>);

#[derive(Clone, Debug, Default)]
pub struct World {
    pub zone: Option<i64>,
    pub character_id: Option<i64>,
    pub character: Option<String>,
    /// Party and alliance member ids.
    pub party: HashSet<i64>,
    /// Act index -> its entity.
    pub entities: HashMap<Option<i64>, Entity>,
    /// (container, index) -> item id.
    pub items: HashMap<(Option<i64>, Option<i64>), Option<i64>>,
    /// The character's last position: c2s 0x015, the zone-in.
    pub pos: Pos,
    /// When it came.
    pub pos_ms: i64,
    /// The zone's weather: the zone-in, 0x057.
    pub weather: Option<i64>,
}

fn or<T>(v: Option<T>, falsy: impl Fn(&T) -> bool, old: Option<T>) -> Option<T> {
    match v {
        Some(x) if !falsy(&x) => Some(x),
        _ => old,
    }
}

impl World {
    /// The world at a capture's start: the character as its header names it.
    pub fn new(character_id: i64, character: &str) -> World {
        World { character_id: Some(character_id), character: Some(character.to_string()), ..World::default() }
    }

    pub fn is_world(key: (u8, u16)) -> bool {
        WORLD.contains(&key)
    }

    /// A mob's or NPC's name, when the entity at its index is still it.
    pub fn name(&self, uid: Option<i64>) -> Option<&str> {
        let uid = uid.filter(|&u| u >= 0x1000000)?;
        let e = self.entities.get(&Some(uid & 0xFFF))?;
        if e.id == Some(uid) { e.name.as_deref() } else { None }
    }

    /// The character's position, when the packets gave all three coordinates.
    pub fn here(&self) -> Option<(f64, f64, f64)> {
        Some((self.pos.0?, self.pos.1?, self.pos.2?))
    }

    pub fn claimed_by_party(&self, claim_id: Option<i64>) -> bool {
        claim_id.is_some_and(|c| Some(c) == self.character_id || self.party.contains(&c))
    }

    pub fn update(&mut self, p: &Packet, f: &dyn Fields) {
        if p.channel != 0 {
            return;
        }
        let op = p.opcode;
        if p.direction == C2S {
            if op == 0x015 {
                self.pos = (f.float("x"), f.float("y"), f.float("z"));
                self.pos_ms = p.ts_ms;
            }
            return;
        }
        match op {
            0x00A => {
                self.zone = f.int("ZoneNo");
                self.entities.clear();
                self.character_id = or(f.int("PosHead.UniqueNo"), |&v| v == 0, self.character_id);
                self.character = or(f.text("name"), |s| s.is_empty(), self.character.take());
                self.pos = (f.float("PosHead.x"), f.float("PosHead.y"), f.float("PosHead.z"));
                self.pos_ms = p.ts_ms;
                self.weather = f.int("WeatherNumber");
            }
            0x057 => self.weather = f.int("WeatherNumber"),
            0x037 => self.character_id = or(f.int("UniqueNo"), |&v| v == 0, self.character_id),
            0x00E => {
                let uid = f.int("UniqueNo");
                if self.zone.is_none() {
                    self.zone = zone_of(uid);
                }
                let Some(index) = f.int("ActIndex") else { return };
                let e = self.entities.entry(Some(index)).or_default();
                if e.id != uid {
                    *e = Entity { id: uid, name: None };
                }
                if let Some(name) = f.text("Data.name").filter(|s| !s.is_empty()) {
                    e.name = Some(name);
                }
                if f.flag("SendFlg.Despawn") {
                    self.entities.remove(&Some(index));
                }
            }
            0x0DD | 0x0E2 => {
                if let Some(uid) = f.int("UniqueNo") {
                    self.party.insert(uid);
                }
            }
            0x0C8 => {
                let members: Vec<Option<i64>> = (0..20).map(|i| f.int(&format!("GroupTbl[{i}].UniqueNo"))).collect();
                if members.iter().any(Option::is_some) {
                    self.party = members.into_iter().flatten().filter(|&m| m != 0).collect();
                }
            }
            0x01E..=0x020 => {
                let key = (f.int("Category"), f.int("ItemIndex"));
                if !f.flag("ItemNum") {
                    self.items.remove(&key);
                } else if op != 0x01E {
                    self.items.insert(key, f.int("ItemNo"));
                }
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::MapFields;

    fn at(op: u16, dir: u8) -> Packet<'static> {
        Packet { idx: 0, ts_ms: 5, channel: 0, direction: dir, opcode: op, flags: 0, data: &[] }
    }

    #[test]
    fn zone_in_entities_and_party() {
        let mut w = World::new(7, "Me");
        let mob = 0x01000000 | (0x0A3 << 12) | 0x010;
        w.update(
            &at(0x00E, S2C),
            &MapFields::new().int("UniqueNo", mob).int("ActIndex", 0x010).text("Data.name", "Bee"),
        );
        assert_eq!(w.zone, Some(0x0A3), "the first mob names the zone before a zone-in");
        assert_eq!(w.name(Some(mob)), Some("Bee"));
        assert_eq!(w.name(Some(mob + 0x1000)), None, "another mob at the same index");
        w.update(
            &at(0x00A, S2C),
            &MapFields::new().int("ZoneNo", 230).int("PosHead.UniqueNo", 0).float("PosHead.x", 1.5),
        );
        assert_eq!((w.zone, w.character_id, w.name(Some(mob))), (Some(230), Some(7), None));
        assert_eq!((w.pos.0, w.here()), (Some(1.5), None));
        w.update(&at(0x0DD, S2C), &MapFields::new().int("UniqueNo", 9));
        assert!(w.claimed_by_party(Some(9)) && w.claimed_by_party(Some(7)) && !w.claimed_by_party(None));
        w.update(&at(0x0C8, S2C), &MapFields::new().int("GroupTbl[0].UniqueNo", 7).int("GroupTbl[1].UniqueNo", 0));
        assert_eq!(w.party, HashSet::from([7]));
        w.update(&at(0x015, C2S), &MapFields::new().float("x", 1.0).float("y", 2.0).float("z", 3.0));
        assert_eq!(w.here(), Some((1.0, 2.0, 3.0)));
    }

    #[test]
    fn items() {
        let mut w = World::new(0, "");
        let slot = |n| MapFields::new().int("Category", 0).int("ItemIndex", 3).int("ItemNum", n).int("ItemNo", 4096);
        w.update(&at(0x020, S2C), &slot(1));
        w.update(&at(0x01E, S2C), &slot(5));
        assert_eq!(w.items.get(&(Some(0), Some(3))), Some(&Some(4096)));
        w.update(&at(0x01E, S2C), &slot(0));
        assert!(w.items.is_empty());
    }
}
