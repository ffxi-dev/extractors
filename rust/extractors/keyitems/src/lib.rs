//! progress/keyitems.py, line for line: key items gained or lost (0x055), where, and the event that gave or
//! took each, as log_changes links them. Its Python twin keeps the docs. key_items() is experience's too.

use std::collections::{HashMap, HashSet};

use xc_core::extract::{Extractor, Meta, Out, Table, Ty::*};
use xc_core::{C2S, Decoded, Fields, Packet, S2C, World, row};
use xc_link::{Link, Resent, kind};

/// The 16 words of a 0x055 list, a bit a key item.
pub type Words = [u32; 16];

const FLAGS: [&str; 16] = [
    "GetItemFlag[0]",
    "GetItemFlag[1]",
    "GetItemFlag[2]",
    "GetItemFlag[3]",
    "GetItemFlag[4]",
    "GetItemFlag[5]",
    "GetItemFlag[6]",
    "GetItemFlag[7]",
    "GetItemFlag[8]",
    "GetItemFlag[9]",
    "GetItemFlag[10]",
    "GetItemFlag[11]",
    "GetItemFlag[12]",
    "GetItemFlag[13]",
    "GetItemFlag[14]",
    "GetItemFlag[15]",
];

/// A 0x055 key item list: its table, 512 key items each, and the ones held in it, a bit each.
pub fn key_items(f: &dyn Fields) -> (i64, Words) {
    // Only a word's low 32 bits name key items.
    (f.int("TableIndex").unwrap_or(0), FLAGS.map(|p| f.int(p).unwrap_or(0) as u32))
}

/// The key item ids of a table's words, in order.
pub fn ids(table: i64, words: Words) -> impl Iterator<Item = i64> {
    (0..16).flat_map(move |i| {
        (0..32).filter(move |b| words[i] >> b & 1 != 0).map(move |b| table * 512 + (i * 32 + b) as i64)
    })
}

pub static META: Meta = Meta {
    name: "keyitems",
    version: 4,
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
        (S2C, 0x055),
        (S2C, 0x00A),
    ],
    tables: &[Table {
        name: "keyitems",
        columns: &[
            ("key_item_id", I32),
            ("change", Str),
            ("x", F32),
            ("y", F32),
            ("z", F32),
            ("zone_id", I32),
            ("event_idx", I64),
            ("event_id", I32),
        ],
    }],
    sparse: true,
};

#[derive(Default)]
pub struct KeyItems {
    /// Table index -> key items held.
    held: HashMap<i64, Words>,
    link: Link,
    /// Event start idx -> its 0x02A messages' first numbers.
    told: HashMap<i64, HashSet<Option<i64>>>,
    resent: Resent,
}

impl Extractor for KeyItems {
    fn meta(&self) -> &'static Meta {
        &META
    }

    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out) {
        let key = p.key();
        if key == (S2C, 0x00A) {
            self.told.clear();
            self.resent.zone_in(p.idx as i64);
            self.link.follow(p, f);
            return;
        }
        if kind(key).is_some() {
            self.link.follow(p, f);
            if key == (S2C, 0x02A)
                && let Some(event) = self.link.at(p.ts_ms)
            {
                self.told.entry(event.idx).or_default().insert(f.int("num[0]"));
            }
            return;
        }
        let (table, now) = key_items(f);
        let before = self.held.insert(table, now);
        let event = self.resent.event(table, self.link.at(p.ts_ms));
        let (x, y, z) = world.pos;
        let mut emit = |change: &str, ki: i64| {
            out.emit(
                "keyitems",
                Some(p),
                row! {
                    key_item_id: ki,
                    change: change,
                    x: x,
                    y: y,
                    z: z,
                    zone_id: world.zone,
                    event_idx: event.map(|e| e.idx),
                    event_id: event.and_then(|e| e.event_id),
                },
            );
        };
        match before {
            // The server sends a lone list when a key item changes, and an event's "Obtained key item" message
            // names it first. ponytail: any message number that is a held key item counts; reading the zone's
            // dialog text would tell an "obtained" message from one that only names a key item.
            None => {
                let Some(told) = event.and_then(|e| self.told.get(&e.idx)) else { return };
                for ki in ids(table, now).filter(|ki| told.contains(&Some(*ki))) {
                    emit("gained", ki);
                }
            }
            Some(before) => {
                for ki in ids(table, std::array::from_fn(|i| now[i] & !before[i])) {
                    emit("gained", ki);
                }
                for ki in ids(table, std::array::from_fn(|i| before[i] & !now[i])) {
                    emit("lost", ki);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::V;
    use xc_core::testing::raw;
    use xc_link::packets::*;

    fn run(packets: Vec<(i64, Raw)>) -> Vec<(V, V, V, V)> {
        let out = raw(Box::new(KeyItems::default()), timed(packets), PLAYER);
        let r = out.rows("keyitems");
        (0..r.len())
            .map(|i| (r.get(i, "key_item_id"), r.get(i, "change"), r.get(i, "event_idx"), r.get(i, "event_id")))
            .collect()
    }

    fn w(first: u32, second: u32) -> Words {
        let mut words = [0; 16];
        (words[0], words[1]) = (first, second);
        words
    }

    fn got(ki: i64, change: &str, idx: Option<i64>, event: Option<i64>) -> (V, V, V, V) {
        (V::Int(ki), V::Str(change.into()), idx.into(), event.into())
    }

    #[test]
    fn a_key_item_gained() {
        let packets = vec![
            (0, keyitems(0, w(0b1, 0))),
            (1000, position(1.5, -20.0, 0.25)),
            (2000, keyitems(0, w(0b100, 0))),
            (3000, keyitems(1, w(0, 0))),
            (4000, keyitems(1, w(0, 1))),
        ];
        let out = raw(Box::new(KeyItems::default()), timed(packets.clone()), PLAYER);
        let r = out.rows("keyitems");
        assert_eq!(["x", "y", "z"].map(|c| r.get(0, c)), [V::Float(1.5), V::Float(-20.0), V::Float(0.25)]);
        assert_eq!(
            run(packets),
            [got(2, "gained", None, None), got(0, "lost", None, None), got(544, "gained", None, None)]
        );
    }

    #[test]
    fn a_key_item_from_an_npc() {
        let rows = run(vec![
            (0, keyitems(0, w(0, 0))),
            (1000, event_num(8700, [0; 8])),
            (2000, keyitems(0, w(0b1, 0))),
            (3000, release()),
            (20_000, keyitems(0, w(0b11, 0))),
            (60_000, keyitems(0, w(0b111, 0))),
        ]);
        assert_eq!(
            rows,
            [
                got(0, "gained", Some(1), Some(8700)),
                got(1, "gained", Some(1), Some(8700)),
                got(2, "gained", None, None)
            ]
        );
    }

    #[test]
    fn a_key_item_in_the_first_list() {
        let rows = run(vec![
            (1000, event_num(18, [0; 8])),
            (2000, message(544)),
            (3000, release()),
            (3100, keyitems(1, w(1, 1))),
            (4000, zone_in()),
            (5000, keyitems(1, w(1, 1))),
            (6000, event_num(19, [0; 8])),
            (7000, message(0)),
            (8000, zone_in()),
            (9000, keyitems(0, w(1, 0))),
        ]);
        assert_eq!(rows, [got(544, "gained", Some(0), Some(18))]);
    }

    #[test]
    fn a_reward_after_a_warp_follows_its_event() {
        let after = |n: u32| keyitems(0, w((1 << n) - 1, 0));
        let rows = run(vec![
            (0, keyitems(0, w(0, 0))),
            (1000, event_num(8700, [0; 8])),
            (2000, release()),
            (3000, zone_in()),
            (5000, after(1)),
            (6000, event_num(8800, [0; 8])),
            (7000, after(2)),
        ]);
        assert_eq!(rows.iter().map(|r| r.3.clone()).collect::<Vec<_>>(), [V::Int(8700), V::Int(8800)]);
    }

    #[test]
    fn a_key_item_after_the_zone_in_lists_follows_no_event_before_it() {
        let rows = run(vec![
            (0, keyitems(0, w(0, 0))),
            (1000, event_num(8500, [0; 8])),
            (2000, zone_in()),
            (3000, keyitems(0, w(0, 0))),
            (16_000, release()),
            (17_000, keyitems(0, w(0b1, 0))),
        ]);
        assert_eq!(rows, [got(0, "gained", None, None)]);
    }
}
