//! decode.py's CaptureStats: what the decode unit keeps of every packet (sizes by opcode, packets per second,
//! zone visits) and its tables, as Python writes them with no Mogsafe record and no release.

use std::collections::BTreeMap;

use indexmap::IndexMap;

use crate::capture::Info;
use crate::extract::Col;
use crate::packet::Packet;
use crate::py::floordiv;
use crate::run::See;
use crate::world::World;

/// capture.py's BATCH: Python moves a capture's end to the last packet of each batch it reads.
const BATCH: u64 = 50_000;

/// A table's columns by name, in its Python Table's order.
pub type Columns = Vec<(&'static str, Col)>;

#[derive(Default)]
pub struct CaptureStats {
    sizes: IndexMap<(u8, u16, usize), i64>,
    seconds: BTreeMap<i64, i64>,
    /// (idx, start_ms, end_idx, end_ms, zone_id, zoned_in)
    visits: Vec<(i64, i64, i64, i64, i64, bool)>,
    zone: Option<i64>,
    packets: u64,
    last: Option<(u64, i64)>,
    ends: Vec<i64>,
}

impl See for CaptureStats {
    fn see(&mut self, p: &Packet, world: &World) {
        let zone = world.zone;
        let zoned_in = p.channel == 0 && p.direction == 0 && p.opcode == 0x00A;
        if p.channel == 0 {
            *self.sizes.entry((p.direction, p.opcode, p.data.len())).or_default() += 1;
        }
        *self.seconds.entry(floordiv(p.ts_ms, 1000)).or_default() += 1;
        let (idx, ts) = (p.idx as i64, p.ts_ms);
        match zone {
            Some(z) if Some(z) != self.zone || zoned_in => self.visits.push((idx, ts, idx, ts, z, zoned_in)),
            Some(_) => {
                let v = self.visits.last_mut().unwrap();
                (v.2, v.3) = (idx, ts);
            }
            None => {}
        }
        self.zone = zone;
        self.packets += 1;
        if (p.idx + 1).is_multiple_of(BATCH) {
            self.ends.push(ts);
        }
        self.last = Some((p.idx, ts));
    }
}

fn strs(v: Vec<Option<String>>) -> Col {
    Col::Str(v)
}

impl CaptureStats {
    /// The decode unit's tables: captures, sessions, sizes, zone_visits, activity. character_id is the header's,
    /// else the world's.
    pub fn tables(&self, capture_id: &str, info: &Info, character_id: Option<i64>) -> Vec<(&'static str, Columns)> {
        let cid = || Some(capture_id.to_string());
        let cv = || Some(info.client_version.clone());
        let start = info.start_ms as i64;
        // Capture.batches: the end moves to each batch's last packet when later.
        let mut end = info.end_ms as i64;
        let batch_ends =
            self.ends.iter().copied().chain(self.last.filter(|l| !(l.0 + 1).is_multiple_of(BATCH)).map(|l| l.1));
        for t in batch_ends {
            end = end.max(t);
        }
        let bucket = 1000.max(floordiv(floordiv(end - start, 400), 1000) * 1000);
        let mut activity: BTreeMap<i64, i64> = BTreeMap::new();
        for (&second, &n) in &self.seconds {
            *activity.entry(floordiv(second * 1000, bucket) * bucket).or_default() += n;
        }
        let none = || Col::Str(vec![None]);
        let n = self.sizes.len();
        let v = &self.visits;
        let a = activity.len();
        vec![
            (
                "captures",
                vec![
                    ("capture_id", strs(vec![cid()])),
                    ("client_version", strs(vec![cv()])),
                    ("release", none()),
                    ("character", strs(vec![Some(info.character.clone())])),
                    ("character_id", Col::I64(vec![character_id])),
                    ("retail", Col::Bool(vec![Some(true)])),
                    ("start_ms", Col::I64(vec![Some(start)])),
                    ("end_ms", Col::I64(vec![Some(end)])),
                    ("packets", Col::I64(vec![Some(self.packets as i64)])),
                    ("world", none()),
                    ("uploader", none()),
                    ("format", none()),
                    ("source", none()),
                ],
            ),
            (
                "sessions",
                vec![
                    ("capture_id", strs(vec![])),
                    ("name", strs(vec![])),
                    ("start_idx", Col::I64(vec![])),
                    ("end_idx", Col::I64(vec![])),
                    ("start_ms", Col::I64(vec![])),
                    ("end_ms", Col::I64(vec![])),
                    ("cut_short", Col::Bool(vec![])),
                ],
            ),
            (
                "sizes",
                vec![
                    ("capture_id", strs(vec![cid(); n])),
                    ("client_version", strs(vec![cv(); n])),
                    (
                        "direction",
                        strs(self.sizes.keys().map(|k| Some(if k.0 == 0 { "s2c" } else { "c2s" }.into())).collect()),
                    ),
                    ("opcode", Col::I32(self.sizes.keys().map(|k| Some(k.1 as i32)).collect())),
                    ("size", Col::I32(self.sizes.keys().map(|k| Some(k.2 as i32)).collect())),
                    ("packets", Col::I64(self.sizes.values().map(|&n| Some(n)).collect())),
                ],
            ),
            (
                "zone_visits",
                vec![
                    ("capture_id", strs(vec![cid(); v.len()])),
                    ("idx", Col::I64(v.iter().map(|x| Some(x.0)).collect())),
                    ("start_ms", Col::I64(v.iter().map(|x| Some(x.1)).collect())),
                    ("end_idx", Col::I64(v.iter().map(|x| Some(x.2)).collect())),
                    ("end_ms", Col::I64(v.iter().map(|x| Some(x.3)).collect())),
                    ("zone_id", Col::I32(v.iter().map(|x| Some(x.4 as i32)).collect())),
                    ("zoned_in", Col::Bool(v.iter().map(|x| Some(x.5)).collect())),
                ],
            ),
            (
                "activity",
                vec![
                    ("capture_id", strs(vec![cid(); a])),
                    ("t", Col::I64(activity.keys().map(|&t| Some(t)).collect())),
                    ("n", Col::I64(activity.values().map(|&n| Some(n)).collect())),
                ],
            ),
        ]
    }
}
