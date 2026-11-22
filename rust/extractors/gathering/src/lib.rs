//! items/gathering.py: what digs and fishing share, the place they happened and what the character held.

use std::collections::HashMap;

use xc_core::extract::{Out, RowId};
use xc_core::vana::vana;
use xc_core::{Field, Fields, Packet, S2C, World};

/// A dig's result: the messages and inventory updates under this long after it.
pub const WINDOW_MS: i64 = 3000;

/// A table's columns: PLACE's, then these. `place_columns![("item_id", I32)]`, with xc_core's Ty in scope.
#[macro_export]
macro_rules! place_columns {
    ($($c:expr),* $(,)?) => {
        &[
            ("zone_id", I32),
            ("x", F32),
            ("y", F32),
            ("z", F32),
            ("weather_id", I32),
            ("vana_weekday", I32),
            ("vana_hour", I32),
            ("moon_phase", I32),
            $($c),*
        ]
    };
}

/// place(): fill in a row's zone, the character's position, the weather, and Vana'diel time.
pub fn place(p: &Packet, world: &World, out: &mut Out, id: RowId) {
    let (day, hour, moon) = vana(p.ts_ms);
    let (x, y, z) = world.pos;
    out.set(id, "zone_id", world.zone);
    out.set(id, "x", x);
    out.set(id, "y", y);
    out.set(id, "z", z);
    out.set(id, "weather_id", world.weather);
    out.set(id, "vana_weekday", day);
    out.set(id, "vana_hour", hour);
    out.set(id, "moon_phase", moon);
}

/// An inventory packet's (0x01E, 0x01F, 0x020) Category, ItemIndex, ItemNum, ItemNo.
pub struct Slot {
    pub category: Field,
    pub index: Field,
    pub count: Field,
    pub item: Field,
}

macro_rules! slot {
    ($op:expr) => {
        Slot {
            category: Field::new(S2C, $op, "Category"),
            index: Field::new(S2C, $op, "ItemIndex"),
            count: Field::new(S2C, $op, "ItemNum"),
            item: Field::new(S2C, $op, "ItemNo"),
        }
    };
}
static SLOTS: [Slot; 3] = [slot!(0x01E), slot!(0x01F), slot!(0x020)];

/// The slot fields of an inventory packet: op is 0x01E, 0x01F or 0x020.
pub fn slot(op: u16) -> &'static Slot {
    &SLOTS[(op - 0x01E) as usize]
}

/// Held: each inventory slot's item and count, from 0x01E (a count without its item), 0x01F and 0x020.
#[derive(Default)]
pub struct Held {
    /// (container, slot) -> (item, count)
    slots: HashMap<(i64, i64), (i64, i64)>,
}

impl Held {
    pub const READS: [(u8, u16); 3] = [(S2C, 0x01E), (S2C, 0x01F), (S2C, 0x020)];

    pub fn reads(key: (u8, u16)) -> bool {
        Self::READS.contains(&key)
    }

    /// Read p; the item whose count it raised in the main inventory, if any. Slot 0 is gil.
    pub fn gained(&mut self, p: &Packet, f: &dyn Fields) -> Option<i64> {
        let k = self::slot(p.opcode);
        let slot = (k.category.int(f).unwrap_or(0), k.index.int(f).unwrap_or(0));
        let count = k.count.int(f).unwrap_or(0);
        let (was_item, was) = self.slots.get(&slot).map_or((None, 0), |&(i, c)| (Some(i), c));
        let item = if p.opcode == 0x01E { was_item } else { k.item.int(f) };
        let Some(item) = item.filter(|_| count != 0) else {
            self.slots.remove(&slot);
            return None;
        };
        self.slots.insert(slot, (item, count));
        (slot.0 == 0 && slot.1 != 0 && (Some(item) != was_item || count > was)).then_some(item)
    }
}
