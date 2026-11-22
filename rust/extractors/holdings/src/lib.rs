//! items/holdings.py, line for line: a row each time one of the character's bag slots changes; a zone-in's
//! list of a slot as it was gives none. Its Python twin keeps the docs.

use std::collections::HashMap;

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{Decoded, Packet, S2C, World, row};
use xc_gathering::slot;

pub static META: Meta = Meta {
    name: "holdings",
    version: 1,
    reads: &[(S2C, 0x01E), (S2C, 0x01F), (S2C, 0x020)],
    // It reads only the world's packets.
    sparse: false,
    tables: &[Table { name: "holdings", columns: &[("container", I32), ("item_index", I32), ("item_id", I32)] }],
};

#[derive(Default)]
pub struct Holdings {
    /// (bag, slot) -> the item last written
    slots: HashMap<(i64, i64), Option<i64>>,
}

impl Extractor for Holdings {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, _world: &World, out: &mut Out) {
        let k = slot(p.opcode);
        let (Some(bag), Some(index)) = (k.category.int(f), k.index.int(f)) else { return };
        let item = if !k.count.flag(f) {
            None
        } else if p.opcode == 0x01E {
            // A quantity alone: the slot keeps its item.
            return;
        } else {
            k.item.int(f)
        };
        if self.slots.insert((bag, index), item) == Some(item) {
            return;
        }
        out.emit("holdings", Some(p), row! { container: bag, item_index: index, item_id: item });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::{Drive, MapFields, drive};

    fn item(op: u16, bag: i64, slot: i64, id: i64, n: i64) -> (u16, MapFields) {
        (op, MapFields::new().int("Category", bag).int("ItemIndex", slot).int("ItemNo", id).int("ItemNum", n))
    }

    #[test]
    fn a_slot_gives_a_row_when_it_changes_and_none_when_listed_again() {
        let steps = vec![
            item(0x020, 0, 1, 21173, 1), // a zone-in's list: Malignance Pole in the inventory
            item(0x020, 1, 4, 4096, 12), // and Fire Crystals in the Mog Safe
            item(0x020, 0, 1, 21173, 1), // the next zone-in lists it again
            item(0x01E, 1, 4, 0, 11),    // a crystal used: a quantity alone
            item(0x01F, 0, 1, 0, 0),     // the pole leaves the slot
            item(0x020, 0, 1, 21173, 1), // and comes back
        ];
        let out = drive(&mut Holdings::default(), steps, Drive::default());
        let r = out.rows("holdings");
        let got: Vec<[V; 3]> =
            (0..r.len()).map(|i| [r.get(i, "container"), r.get(i, "item_index"), r.get(i, "item_id")]).collect();
        let row = |c: i64, s: i64, i: Option<i64>| [V::Int(c), V::Int(s), i.map_or(V::Null, V::Int)];
        assert_eq!(got, [row(0, 1, Some(21173)), row(1, 4, Some(4096)), row(0, 1, None), row(0, 1, Some(21173))]);
    }
}
