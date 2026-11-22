//! tests/conftest.py's drivers, for extractors' own tests: drive() feeds decoded fields, raw() feeds bytes
//! through the decoder as a capture would.

pub mod packets;

use std::collections::HashMap;

use crate::extract::{Extractor, Out};
use crate::packet::{Decoded, Fields, Packet, Value};
use crate::run::{Error, Source, walk_packets};
use crate::world::World;

pub const PLAYER: i64 = 0x0001_0001;
pub const MEMBER: i64 = 0x0001_0002;
pub const STRANGER: i64 = 0x0001_0003;
pub const MOB: i64 = 0x01000000 | (0x0A3 << 12) | 0x010;

/// A packet's fields as a test gives them: Python's dict, read by d.get.
#[derive(Clone, Debug, Default)]
pub struct MapFields(pub HashMap<String, Value<'static>>);

impl MapFields {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn int(mut self, path: &str, v: i64) -> Self {
        self.0.insert(path.into(), Value::I(v));
        self
    }

    pub fn float(mut self, path: &str, v: f64) -> Self {
        self.0.insert(path.into(), Value::F(v));
        self
    }

    pub fn text(mut self, path: &str, v: &str) -> Self {
        self.0.insert(path.into(), Value::Text(v.to_string().into()));
        self
    }
}

impl Fields for MapFields {
    fn get(&self, path: &str) -> Option<Value<'_>> {
        self.0.get(path).cloned()
    }
}

/// drive()'s keywords: times instead of t0 + i seconds, directions instead of all s2c, and me.
pub struct Drive {
    pub t0: i64,
    pub times: Option<Vec<i64>>,
    pub directions: Option<Vec<u8>>,
    pub me: i64,
}

impl Default for Drive {
    fn default() -> Self {
        Drive { t0: 0, times: None, directions: None, me: PLAYER }
    }
}

/// Steps of (opcode, fields) as one capture's packets, through the world and, for its reads, the extractor;
/// the world starts with MEMBER in the party. Each packet's bytes differ, so none reads as a resend.
pub fn drive(x: &mut dyn Extractor, steps: Vec<(u16, MapFields)>, o: Drive) -> Out {
    let mut w = World::new(o.me, "Me");
    w.party.insert(MEMBER);
    let mut out = Out::new(x.meta());
    for (i, (op, d)) in steps.into_iter().enumerate() {
        let data = [i as u8; 8];
        let p = Packet {
            idx: i as u64,
            ts_ms: o.times.as_ref().map_or(o.t0 + i as i64 * 1000, |t| t[i]),
            channel: 0,
            direction: o.directions.as_ref().map_or(0, |d| d[i]),
            opcode: op,
            flags: 0,
            data: &data,
        };
        w.update(&p, &d);
        if x.meta().reads.contains(&p.key()) {
            x.packet(&p, &Decoded::new(&d), &w, &mut out);
        }
    }
    x.finish(&w, &mut out);
    out
}

/// A test's packets, owned: (ts_ms, direction, opcode, bytes).
pub struct Owned {
    packets: Vec<(i64, u8, u16, Vec<u8>)>,
    next: usize,
}

impl Source for Owned {
    fn next_packet(&mut self) -> Result<Option<Packet<'_>>, Error> {
        let Some((ts, dir, op, data)) = self.packets.get(self.next) else { return Ok(None) };
        let idx = self.next as u64;
        self.next += 1;
        Ok(Some(Packet { idx, ts_ms: *ts, channel: 0, direction: *dir, opcode: *op, flags: *dir as u16, data }))
    }
}

/// raw(): packets as (ts_ms, direction, opcode, bytes) decoded and walked as a capture's, the character me.
pub fn raw(x: Box<dyn Extractor>, packets: Vec<(i64, u8, u16, Vec<u8>)>, me: i64) -> Out {
    raw_with(x, packets, me, "")
}

/// raw() for a capture of this client version.
pub fn raw_with(x: Box<dyn Extractor>, packets: Vec<(i64, u8, u16, Vec<u8>)>, me: i64, client_version: &str) -> Out {
    let mut w = World::new(me, "Tester");
    let mut xs = [x];
    walk_packets(&mut Owned { packets, next: 0 }, client_version, &mut w, &mut xs, None).unwrap().pop().unwrap()
}
