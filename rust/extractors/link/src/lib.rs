//! link.py: the event a change follows. What an event's packets are, and the one under way, for events,
//! obtained, and keyitems.

use xc_core::{C2S, Fields, Packet, S2C};

/// What an event packet is: KINDS's values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Start,
    Update,
    Reply,
    Release,
    Message,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Start => "start",
            Kind::Update => "update",
            Kind::Reply => "reply",
            Kind::Release => "release",
            Kind::Message => "message",
        }
    }
}

/// KINDS's keys, for an extractor's reads.
pub const KINDS: [(u8, u16); 12] = [
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
];

/// KINDS: (direction, opcode) -> kind.
pub fn kind(key: (u8, u16)) -> Option<Kind> {
    Some(match key {
        (S2C, 0x032..=0x034) => Kind::Start,
        (S2C, 0x05C | 0x05D) => Kind::Update,
        (C2S, 0x05B | 0x05C) => Kind::Reply,
        (S2C, 0x052) => Kind::Release,
        (S2C, 0x036 | 0x027 | 0x02A | 0x053) => Kind::Message,
        _ => return None,
    })
}

/// A log change this soon after an event's last packet follows from it.
pub const LINK_MS: i64 = 30_000;

/// An event's start: its packet and event id, what Python's start row holds of it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Start {
    pub idx: i64,
    pub event_id: Option<i64>,
}

/// The event a change follows: the one under way, or one whose last packet came at most LINK_MS before.
#[derive(Default, Debug)]
pub struct Link {
    /// The start of the event under way.
    pub open: Option<Start>,
    /// (start, ts of its last packet).
    last: Option<(Start, i64)>,
}

impl Link {
    /// An event packet at ts, which begins start if given; returns the event it belongs to.
    pub fn see(&mut self, ts: i64, start: Option<Start>) -> Option<Start> {
        if start.is_some() {
            self.open = start;
        }
        if let Some(s) = self.open {
            self.last = Some((s, ts));
        }
        self.open
    }

    /// The event under way is over: a release or a zone-in. It still links changes for LINK_MS.
    pub fn end(&mut self) {
        self.open = None;
    }

    pub fn at(&self, ts: i64) -> Option<Start> {
        if self.open.is_some() {
            return self.open;
        }
        match self.last {
            Some((s, t)) if ts - t <= LINK_MS => Some(s),
            _ => None,
        }
    }

    /// Follow an event packet or a zone-in, for a unit that links its rows to the event's start packet: a
    /// zone-in ends the event under way, and starts one when it plays a cutscene.
    pub fn follow(&mut self, p: &Packet, f: &dyn Fields) {
        let start = || Some(Start { idx: p.idx as i64, event_id: f.int("EventPara") });
        if p.key() == (S2C, 0x00A) {
            self.end();
            if f.flag("EventNum") {
                self.see(p.ts_ms, start());
            }
            return;
        }
        let k = kind(p.key());
        self.see(p.ts_ms, if k == Some(Kind::Start) { start() } else { None });
        if k == Some(Kind::Release) {
            self.end();
        }
    }
}

/// Event packets as bytes, for events' and keyitems' tests: tests/progress/test_events.py's builders.
pub mod packets {
    use xc_core::{C2S, S2C};

    pub const PLAYER: i64 = 0x0001_0001;
    /// An NPC of Lower Jeuno, index 100.
    pub const NPC: u32 = 0x0100_0000 | (0x0F5 << 12) | 0x064;

    /// (direction, opcode, bytes), its header's size set, the body at offset 4.
    pub type Raw = (u8, u16, Vec<u8>);

    fn pkt(dir: u8, op: u16, size: usize, body: &[u8]) -> Raw {
        let mut data = vec![0u8; size];
        data[0] = op as u8;
        data[1] = (op >> 8) as u8 | ((size / 4) << 1) as u8;
        data[4..4 + body.len()].copy_from_slice(body);
        (dir, op, data)
    }

    fn le(words: &[u32]) -> Vec<u8> {
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    fn le16(xs: &[u16]) -> Vec<u8> {
        xs.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    /// s2c 0x034.
    pub fn event_num(event: u16, params: [u32; 8]) -> Raw {
        let body = [le(&[NPC]), le(&params), le16(&[100, 0, event, 8, 0, 0])].concat();
        pkt(S2C, 0x034, 52, &body)
    }

    /// s2c 0x05C.
    pub fn update(params: [u32; 8]) -> Raw {
        pkt(S2C, 0x05C, 36, &le(&params))
    }

    /// c2s 0x05B.
    pub fn reply(event: u16, option: u32, mode: u16) -> Raw {
        pkt(C2S, 0x05B, 20, &[le(&[NPC, option]), le16(&[100, mode, 0, event])].concat())
    }

    /// s2c 0x05D.
    pub fn update_strings(params: [i32; 9], strings: [&str; 4]) -> Raw {
        let mut body: Vec<u8> = params.iter().flat_map(|w| w.to_le_bytes()).collect();
        for s in strings {
            let mut b = [0u8; 16];
            b[..s.len()].copy_from_slice(s.as_bytes());
            body.extend(b);
        }
        pkt(S2C, 0x05D, 104, &body)
    }

    /// s2c 0x052.
    pub fn release() -> Raw {
        pkt(S2C, 0x052, 8, &[1])
    }

    /// s2c 0x056.
    pub fn log(port: u16, words: [u32; 8]) -> Raw {
        pkt(S2C, 0x056, 40, &[le(&words), le16(&[port])].concat())
    }

    /// s2c 0x055.
    pub fn keyitems(table: u8, words: [u32; 16]) -> Raw {
        pkt(S2C, 0x055, 136, &[le(&words), le(&[0; 16]), vec![table]].concat())
    }

    /// s2c 0x02A, as an NPC's "Obtained key item" sends it.
    pub fn message(num: u32) -> Raw {
        pkt(S2C, 0x02A, 32, &[le(&[NPC, num, 0, 0, 0]), le16(&[100, 6396])].concat())
    }

    /// s2c 0x00A that plays no event.
    pub fn zone_in() -> Raw {
        pkt(S2C, 0x00A, 260, &le(&[PLAYER as u32]))
    }

    /// c2s 0x015, XiPackets' order x, z, y.
    pub fn position(x: f32, y: f32, z: f32) -> Raw {
        pkt(C2S, 0x015, 32, &[x, z, y].iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>())
    }

    /// (ts_ms, packet) as testing::raw takes them.
    pub fn timed(packets: Vec<(i64, Raw)>) -> Vec<(i64, u8, u16, Vec<u8>)> {
        packets.into_iter().map(|(ts, (d, op, data))| (ts, d, op, data)).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xc_core::testing::MapFields;

    const START: (u8, u16) = (S2C, 0x032);
    const RELEASE: (u8, u16) = (S2C, 0x052);
    const ZONE_IN: (u8, u16) = (S2C, 0x00A);

    fn at(idx: u64, ms: i64, key: (u8, u16)) -> Packet<'static> {
        Packet { idx, ts_ms: ms, channel: 0, direction: key.0, opcode: key.1, flags: 0, data: &[] }
    }

    #[test]
    fn a_start_links_until_a_release_and_for_a_while_after() {
        let mut link = Link::default();
        link.follow(&at(1, 0, START), &MapFields::new().int("EventPara", 7));
        let s = Some(Start { idx: 1, event_id: Some(7) });
        assert_eq!(link.at(500), s);
        link.follow(&at(2, 1000, RELEASE), &MapFields::new());
        assert_eq!(link.at(1000 + LINK_MS), s);
        assert_eq!(link.at(1001 + LINK_MS), None);
    }

    #[test]
    fn a_zone_in_ends_the_event_and_starts_one_when_it_plays_a_cutscene() {
        let mut link = Link::default();
        link.follow(&at(1, 0, START), &MapFields::new().int("EventPara", 7));
        link.follow(&at(2, 100, ZONE_IN), &MapFields::new());
        assert_eq!(link.open, None);
        link.follow(&at(3, 200, ZONE_IN), &MapFields::new().int("EventNum", 1).int("EventPara", 9));
        assert_eq!(link.at(200), Some(Start { idx: 3, event_id: Some(9) }));
    }
}
