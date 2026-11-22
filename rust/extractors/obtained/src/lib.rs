//! items/obtained.py, line for line: items the character received, whatever gave them, netted over a run of
//! container changes, with the event each follows. Its Python twin keeps the docs.

use std::collections::HashMap;

use indexmap::IndexMap;
use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{C2S, Decoded, Field, Fields, Packet, S2C, World, row};
use xc_link::{Link, kind};

const GIL: i64 = 0xFFFF;
/// A change this soon after the last is part of the same move, trade or synthesis.
const SETTLE_MS: i64 = 1000;
/// An item the character won from the pool lands this soon after.
const POOL_MS: i64 = 10_000;

pub static META: Meta = Meta {
    name: "obtained",
    version: 3,
    reads: &[
        (S2C, 0x032),
        (S2C, 0x033),
        (S2C, 0x034),
        (S2C, 0x05C),
        (S2C, 0x05D),
        (C2S, 0x05B),
        (C2S, 0x05C),
        (S2C, 0x052),
        (S2C, 0x036),
        (S2C, 0x027),
        (S2C, 0x02A),
        (S2C, 0x053),
        (S2C, 0x00A),
        (S2C, 0x01D),
        (S2C, 0x01E),
        (S2C, 0x01F),
        (S2C, 0x020),
        (S2C, 0x0D2),
        (S2C, 0x0D3),
    ],
    tables: &[Table {
        name: "obtained",
        columns: &[
            ("item_id", I32),
            ("quantity", I32),
            ("container", I32),
            ("source", Str),
            ("zone_id", I32),
            ("event_idx", I64),
        ],
    }],
    sparse: true,
};

/// A container change's fields, by opcode: 0x01E, 0x01F, 0x020.
macro_rules! slot {
    ($($op:literal)*) => { [$([
        Field::new(S2C, $op, "Category"),
        Field::new(S2C, $op, "ItemIndex"),
        Field::new(S2C, $op, "ItemNo"),
        Field::new(S2C, $op, "ItemNum"),
    ]),*] };
}
static SLOT: [[Field; 4]; 3] = slot!(0x01E 0x01F 0x020);

/// An item's net change over a run: Python's [count, first rise's packet, container, event, zone].
#[derive(Default)]
struct Net {
    n: i64,
    /// The first rise's packet: (idx, ts_ms).
    first: Option<(u64, i64)>,
    container: Option<i64>,
    event: Option<i64>,
    zone: Option<i64>,
}

#[derive(Default)]
pub struct Obtained {
    /// (container, index) -> (item, quantity).
    slots: HashMap<(Option<i64>, Option<i64>), (i64, i64)>,
    /// Containers sent whole since the last zone-in, a bit each.
    synced: Option<i64>,
    /// Item -> its net change, in the order first changed.
    net: IndexMap<i64, Net>,
    /// The last change's time.
    last: i64,
    /// Pool slot -> item.
    pool: HashMap<Option<i64>, Option<i64>>,
    /// Item -> when the character won it.
    won: HashMap<i64, i64>,
    link: Link,
}

impl Extractor for Obtained {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        if !self.net.is_empty() && p.ts_ms - self.last > SETTLE_MS {
            self.settle(out);
        }
        if kind(p.key()).is_some() {
            self.link.follow(p, f);
            return;
        }
        match p.opcode {
            // The server sends every container again, one by one.
            0x00A => {
                self.synced = Some(0);
                self.link.follow(p, f);
            }
            0x01D => {
                if let Some(s) = &mut self.synced {
                    *s |= f.int("Flags").unwrap_or(0);
                }
            }
            0x0D2 => {
                self.pool.insert(f.int("TrophyItemIndex"), f.int("TrophyItemNo"));
            }
            0x0D3 => {
                let mine = f.int("JudgeFlg") == Some(1) && f.int("LootUniqueNo") == world.character_id;
                if mine
                    && let Some(&Some(item)) = self.pool.get(&f.int("TrophyItemIndex"))
                    && item != 0
                {
                    self.won.insert(item, p.ts_ms);
                }
            }
            op => {
                let [category, index, item_no, item_num] = &SLOT[(op - 0x01E) as usize];
                let slot = (category.int(f), index.int(f));
                let old = self.slots.get(&slot).copied();
                let new = if op == 0x01E {
                    // The quantity alone.
                    let Some(old) = old else { return };
                    (old.0, item_num.int(f).unwrap_or(0))
                } else {
                    (item_no.int(f).unwrap_or(0), item_num.int(f).unwrap_or(0))
                };
                if Some(new) == old {
                    return;
                }
                if new.0 != 0 && new.1 != 0 {
                    self.slots.insert(slot, new);
                } else {
                    self.slots.remove(&slot);
                }
                // A slot first seen before its container was sent whole is what the character held.
                let c = slot.0.unwrap_or(0);
                let synced = (0..64).contains(&c) && self.synced.unwrap_or(0) >> c & 1 != 0;
                if old.is_none() && !synced {
                    return;
                }
                if let Some((item, n)) = old {
                    self.add(item, -n, p, slot.0, world.zone);
                }
                if new.0 != 0 && new.1 != 0 {
                    self.add(new.0, new.1, p, slot.0, world.zone);
                }
            }
        }
    }

    fn finish(&mut self, _world: &World, out: &mut Out) {
        self.settle(out);
    }
}

impl Obtained {
    fn add(&mut self, item: i64, n: i64, p: &Packet, container: Option<i64>, zone: Option<i64>) {
        if item == GIL || n == 0 {
            return;
        }
        self.last = p.ts_ms;
        let event = self.link.at(p.ts_ms).map(|s| s.idx);
        let e = self.net.entry(item).or_default();
        e.n += n;
        if n > 0 && e.first.is_none() {
            (e.first, e.container, e.event, e.zone) = (Some((p.idx, p.ts_ms)), container, event, zone);
        }
    }

    fn settle(&mut self, out: &mut Out) {
        for (item, e) in self.net.drain(..) {
            if e.n <= 0 {
                continue;
            }
            let (idx, ts_ms) = e.first.expect("a rise");
            let pool = self.won.remove(&item).is_some_and(|won| won >= ts_ms - POOL_MS);
            let p = Packet { idx, ts_ms, channel: 0, direction: S2C, opcode: 0, flags: 0, data: &[] };
            out.emit(
                "obtained",
                Some(&p),
                row! {
                    item_id: item,
                    quantity: e.n,
                    container: e.container,
                    source: pool.then_some("pool"),
                    zone_id: e.zone,
                    event_idx: e.event,
                },
            );
        }
    }
}

#[cfg(test)]
mod tests;
