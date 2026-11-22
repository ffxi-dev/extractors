//! A packet as the reader gives it, and its decoded fields by path, as ffxi_packets names them.
//!
//! Extractors and the World read a packet's fields by path through [`Fields`], as Python's
//! `f("SendFlg.Despawn")` does: a field the packet does not hold, or that has no value, is None. xc-decode's
//! packets are Fields; so is testing's MapFields, which drive() feeds.

use std::cell::OnceCell;

use crate::combat::{self, ActResult, Action, Extra, Target};

pub const S2C: u8 = 0;
pub const C2S: u8 = 1;

#[derive(Clone, Copy, Debug)]
pub struct Packet<'a> {
    /// Position in the capture, counting from 0 across every channel, as Lens's #packet= links do.
    pub idx: u64,
    pub ts_ms: i64,
    /// 0 game, 1 search.
    pub channel: u8,
    /// 0 to the client (s2c), 1 from it (c2s).
    pub direction: u8,
    pub opcode: u16,
    /// xicap's packet flags: injected, excluded (stubbed), redacted, ...
    pub flags: u16,
    /// The whole packet, its 4-byte header included.
    pub data: &'a [u8],
}

impl Packet<'_> {
    pub fn key(&self) -> (u8, u16) {
        (self.direction, self.opcode)
    }
}

pub use xc_decode::Value;

/// One packet's fields by path: `UniqueNo`, `SendFlg.Position`, `GroupTbl[3].UniqueNo`, `Data.name`.
pub trait Fields {
    fn get(&self, path: &str) -> Option<Value<'_>>;

    /// An integer field; None for a float, text, or a field wider than 53 bits (Python's decimal text).
    fn int(&self, path: &str) -> Option<i64> {
        self.get(path)?.int()
    }

    /// A number as a float: an integer field reads as one too, as Python's arithmetic would take it.
    fn float(&self, path: &str) -> Option<f64> {
        match self.get(path)? {
            Value::U(v) => Some(v as f64),
            Value::I(v) => Some(v as f64),
            Value::F(v) => Some(v),
            Value::Wide(_) | Value::Text(_) => None,
        }
    }

    /// Text, or a field wider than 53 bits as its decimal text, as Python gives both.
    fn text(&self, path: &str) -> Option<String> {
        match self.get(path)? {
            Value::Text(s) => Some(s.into_owned()),
            Value::Wide(v) => Some(v.to_string()),
            _ => None,
        }
    }

    /// Python's truthiness of the field: present and not 0. Empty text has no value.
    fn flag(&self, path: &str) -> bool {
        match self.get(path) {
            Some(Value::U(v)) => v != 0,
            Some(Value::I(v)) => v != 0,
            Some(Value::F(v)) => v != 0.0,
            Some(Value::Wide(v)) => v != 0,
            Some(Value::Text(s)) => !s.is_empty(),
            None => false,
        }
    }

    /// The action packet (0x028), as combat.action reads it.
    fn action(&self) -> Action {
        combat::action_by_path(self)
    }
}

/// A packet with no fields: one whose opcode has no layout.
pub struct NoFields;

impl Fields for NoFields {
    fn get(&self, _: &str) -> Option<Value<'_>> {
        None
    }
}

impl Fields for xc_decode::Packet<'_> {
    fn get(&self, path: &str) -> Option<Value<'_>> {
        xc_decode::Packet::get(self, path)
    }

    /// The bitstream read straight: the same as by path, without a lookup a field.
    fn action(&self) -> Action {
        let Some(a) = xc_decode::Packet::action(self) else { return Action::default() };
        let n = |v: u32| Some(v as i64);
        let extra = |e: Option<xc_decode::Extra>| {
            e.map(|e| Extra { kind: n(e.kind), info: n(e.info), value: n(e.value), message: n(e.message) })
        };
        Action {
            actor_id: n(a.actor_id),
            cmd_no: n(a.cmd_no),
            cmd_arg: n(a.cmd_arg),
            info: n(a.info),
            targets: a
                .targets()
                .map(|t| Target {
                    id: n(t.target_id),
                    results: t
                        .results()
                        .map(|r| ActResult {
                            miss: n(r.miss),
                            kind: n(r.kind),
                            sub_kind: n(r.sub_kind),
                            info: n(r.info),
                            scale: n(r.scale),
                            value: n(r.value),
                            message: n(r.message),
                            bit: n(r.bit),
                            proc: extra(r.proc),
                            react: extra(r.react),
                        })
                        .collect(),
                })
                .collect(),
        }
    }
}

/// What an extractor gets for a packet: its fields, and its action decoded once however many extractors ask.
pub struct Decoded<'a> {
    fields: &'a dyn Fields,
    action: OnceCell<Action>,
}

impl<'a> Decoded<'a> {
    pub fn new(fields: &'a dyn Fields) -> Self {
        Decoded { fields, action: OnceCell::new() }
    }

    /// The 0x028 action this packet carries; empty for any other packet.
    pub fn action(&self) -> &Action {
        self.action.get_or_init(|| self.fields.action())
    }
}

impl<'a> std::ops::Deref for Decoded<'a> {
    type Target = dyn Fields + 'a;

    fn deref(&self) -> &Self::Target {
        self.fields
    }
}

impl Fields for Decoded<'_> {
    fn get(&self, path: &str) -> Option<Value<'_>> {
        self.fields.get(path)
    }

    fn action(&self) -> Action {
        Decoded::action(self).clone()
    }
}
