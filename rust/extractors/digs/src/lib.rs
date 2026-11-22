//! items/digs.py, line for line: each chocobo dig the character made, and what it found: the item an
//! 'Obtained' message (0x02A) named that also entered the inventory. Its Python twin keeps the docs.

use std::collections::HashSet;

use xc_core::extract::{Extractor, Meta, Out, RowId, Table, Ty::*};
use xc_core::{C2S, Decoded, Field, Packet, S2C, World, row};
use xc_gathering::{Held, WINDOW_MS, place, place_columns};

static TOLD: [Field; 2] = [Field::new(S2C, 0x02A, "UniqueNo"), Field::new(S2C, 0x02A, "num[0]")];

pub static META: Meta = Meta {
    name: "digs",
    version: 1,
    reads: &[(S2C, 0x01E), (S2C, 0x01F), (S2C, 0x020), (S2C, 0x00A), (C2S, 0x063), (S2C, 0x02A)],
    sparse: true,
    tables: &[Table { name: "digs", columns: place_columns![("item_id", I32)] }],
};

/// The last dig: its row, its window's end, items named and gained.
struct Dig {
    id: RowId,
    end: i64,
    named: Vec<Option<i64>>,
    gained: HashSet<i64>,
    found: bool,
}

impl Dig {
    /// The dig's item: the first one its messages named that the inventory gained.
    fn settle(&mut self, out: &mut Out) {
        if self.found {
            return;
        }
        if let Some(i) = self.named.iter().flatten().find(|i| self.gained.contains(i)) {
            out.set(self.id, "item_id", *i);
            self.found = true;
        }
    }
}

#[derive(Default)]
pub struct Digs {
    held: Held,
    open: Option<Dig>,
}

impl Extractor for Digs {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        match p.key() {
            (S2C, 0x00A) => self.open = None,
            (C2S, 0x063) => {
                let id = out.emit("digs", Some(p), row! {});
                place(p, world, out, id);
                self.open =
                    Some(Dig { id, end: p.ts_ms + WINDOW_MS, named: Vec::new(), gained: HashSet::new(), found: false });
            }
            (S2C, 0x02A) => {
                let me = world.character_id;
                if let Some(dig) = self.live(p)
                    && (me.is_none_or(|m| m == 0) || TOLD[0].int(f) == me)
                {
                    dig.named.push(TOLD[1].int(f));
                    dig.settle(out);
                }
            }
            _ => {
                if let Some(item) = self.held.gained(p, f)
                    && let Some(dig) = self.live(p)
                {
                    dig.gained.insert(item);
                    dig.settle(out);
                }
            }
        }
    }
}

impl Digs {
    /// The last dig, while p falls in its window.
    fn live(&mut self, p: &Packet) -> Option<&mut Dig> {
        self.open.as_mut().filter(|d| p.ts_ms <= d.end)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::extract::Rows;
    use xc_core::testing::{Drive, MapFields, PLAYER, drive};

    const GREENS: i64 = 4545;
    const PEBBLE: i64 = 17296;
    const HINT: i64 = 3;
    const ZONE: i64 = 117;

    type Step = (u16, MapFields);

    fn slot(op: u16, index: i64, item: i64, count: i64) -> Step {
        (op, MapFields::new().int("Category", 0).int("ItemIndex", index).int("ItemNo", item).int("ItemNum", count))
    }

    fn count(index: i64, n: i64) -> Step {
        (0x01E, MapFields::new().int("Category", 0).int("ItemIndex", index).int("ItemNum", n))
    }

    fn told(number: i64, message: i64) -> Step {
        (0x02A, MapFields::new().int("UniqueNo", PLAYER).int("MesNum", message).int("num[0]", number))
    }

    /// A zone-in in sunshine, greens and a pebble held, a position, then a dig and what follows it.
    fn dig(after: Vec<Step>) -> Rows {
        let n = after.len();
        let mut steps = vec![
            (
                0x00A,
                MapFields::new()
                    .int("ZoneNo", ZONE)
                    .int("WeatherNumber", 1)
                    .float("PosHead.x", 1.0)
                    .float("PosHead.y", 2.0)
                    .float("PosHead.z", 3.0),
            ),
            slot(0x020, 5, GREENS, 12),
            slot(0x020, 9, PEBBLE, 1),
            (0x015, MapFields::new().float("x", 10.0).float("y", 20.0).float("z", 30.0)),
            (0x063, MapFields::new()),
        ];
        steps.extend(after);
        let directions = steps.iter().map(|(op, _)| if matches!(op, 0x015 | 0x063) { C2S } else { S2C }).collect();
        // Inside 3 s.
        let times = (0..5).map(|i| i * 1000).chain((0..n as i64).map(|k| 4000 + 200 * (k + 1))).collect();
        let o = Drive { times: Some(times), directions: Some(directions), ..Drive::default() };
        drive(&mut Digs::default(), steps, o).tables.remove(0)
    }

    #[test]
    fn a_dig_finds_the_item_a_message_named_that_the_inventory_gained() {
        // A hint whose number is no item, the greens eaten, 'Obtained: Pebble', and the pebble's count rising.
        let r = dig(vec![told(HINT, 40109), count(5, 11), told(PEBBLE, 39344), count(9, 2)]);
        assert_eq!(r.len(), 1);
        let got: Vec<V> = ["item_id", "zone_id", "weather_id", "x", "y", "z"].iter().map(|c| r.get(0, c)).collect();
        assert_eq!(got, [V::Int(PEBBLE), V::Int(ZONE), V::Int(1), V::Float(10.0), V::Float(20.0), V::Float(30.0)]);
    }

    #[test]
    fn a_dig_that_finds_nothing() {
        // The greens go, a hint names a number, and an item the dig did not name enters the inventory.
        let r = dig(vec![count(5, 11), told(HINT, 40109), slot(0x020, 12, 515, 1)]);
        assert_eq!((r.len(), r.get(0, "item_id")), (1, V::Null));
    }
}
