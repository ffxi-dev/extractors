//! Decodes FFXI packets as ffxi_packets does, field for field, straight from the packet's bytes.
//!
//! build.rs turns packets' schemas (`packets/`, tag v2.3.0) into a table per layout: every field's path,
//! bit offset, width, and the union variant it sits in. A field is read only when asked for. A field has
//! no value when the packet ends before it, when it is empty text, or when its union holds another
//! variant: what Python's `Fields(path)` gives as None. Layouts whose offsets depend on the data are not
//! decoded; the action packet (s2c 0x028) has its own bitstream decoder, `Action`.

use std::borrow::Cow;

mod action;
pub use action::{Action, ActionResult, Extra, Results, Target, Targets};

/// Server to client, as Python's `DIR_IN`.
pub const S2C: u8 = 0;
/// Client to server, as Python's `DIR_OUT`.
pub const C2S: u8 = 1;

/// A field's value, as Python's decoder gives it.
#[derive(Debug, Clone, PartialEq)]
pub enum Value<'a> {
    U(u64),
    I(i64),
    /// A float32, widened.
    F(f64),
    /// Wider than 53 bits: Python gives its decimal text. Only its low 64 bits, as numpy keeps them.
    Wide(i128),
    Text(Cow<'a, str>),
}

impl Value<'_> {
    /// An integer field's value; None for float, wide, and text.
    pub fn int(&self) -> Option<i64> {
        match *self {
            Value::U(v) => Some(v as i64),
            Value::I(v) => Some(v),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[allow(dead_code)] // what build.rs may write; today's schemas hold no zero-bit or signed wide field
enum K {
    U,
    I,
    F,
    WideU,
    WideI,
    Zero,
    Text,
}

/// One place a path is written: bit offset, width, kind, and the union condition (u16::MAX for none).
#[derive(Debug)]
struct E(u32, u32, K, u16);

/// A union variant: holds when entry .0 has value .1 and the parent condition .2 holds.
#[derive(Debug)]
struct C(u16, i64, u16);

const NONE: u16 = u16::MAX;

/// A packet layout: its paths, sorted, and where each is written: entries[runs[i]..runs[i + 1]] for names[i].
#[derive(Debug)]
pub struct Layout {
    pub name: &'static str,
    pub direction: u8,
    pub opcode: u16,
    /// An older layout from layouts.json: a FieldId found in today's is not its own.
    pub older: bool,
    custom: bool,
    entries: &'static [E],
    names: &'static [&'static str],
    runs: &'static [u16],
    conds: &'static [C],
}

/// An older layout from layouts.json: `until` is the first client version that no longer uses it, `from` the
/// first that does. None for a layout whose offsets depend on the data.
struct Older {
    direction: u8,
    opcode: u16,
    until: Option<(u64, u64)>,
    from: Option<(u64, u64)>,
    layout: Option<&'static Layout>,
}

include!(concat!(env!("OUT_DIR"), "/layouts.rs"));

/// A field of one layout, found once by path and read from many packets.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FieldId(u16);

/// `30211103_1` as `(30211103, 1)`, as packets' `_version_key`; None for anything else, such as a captain build.
fn version_key(v: &str) -> Option<(u64, u64)> {
    let (a, b) = v.split_once('_')?;
    let n = |s: &str| s.bytes().all(|c| c.is_ascii_digit()).then(|| s.parse().ok()).flatten();
    Some((n(a)?, n(b)?))
}

/// The layout a client version uses for this opcode, as packets picks it: the first older layout that applies,
/// else today's. A version that does not read as `30211103_1` gets today's.
pub fn layout(direction: u8, opcode: u16, client_version: Option<&str>) -> Option<&'static Layout> {
    if let Some(v) = client_version.and_then(version_key)
        && let Some(o) = OLDER.iter().find(|o| {
            o.direction == direction
                && o.opcode == opcode
                && (o.until.is_some_and(|u| v < u) || o.from.is_some_and(|f| v >= f))
        })
    {
        return o.layout;
    }
    *LAYOUTS.get(direction as usize * 0x200 + opcode as usize)?
}

/// The client version to pick layouts by for a capture recorded at `ms` (Unix ms) whose header names none: the
/// newest that starts or ends an older layout and was live by then, or `0_0`, older than all of them.
pub fn version_at(ms: u64) -> &'static str {
    LIVE.iter().filter(|(_, live)| *live <= ms).max_by_key(|(v, _)| version_key(v)).map_or("0_0", |(v, _)| v)
}

/// The client version a capture's layouts are picked by: its header's when it reads as one, else, for a captain
/// build or an import that names none, `version_at` its first packet. A capture with neither gets today's.
pub fn capture_version(header: &str, start_ms: u64) -> &str {
    if version_key(header).is_some() || start_ms == 0 { header } else { version_at(start_ms) }
}

/// A packet of a known layout, decoded on demand.
pub fn decode<'a>(direction: u8, opcode: u16, raw: &'a [u8], client_version: Option<&str>) -> Option<Packet<'a>> {
    Some(Packet { layout: layout(direction, opcode, client_version)?, raw })
}

impl Layout {
    /// The field at this path, or None when the layout has no such path.
    pub fn field(&self, path: &str) -> Option<FieldId> {
        self.names.binary_search(&path).ok().map(|i| FieldId(i as u16))
    }

    /// Every path of the layout, in order (the action bitstream's are not among them).
    pub fn paths(&self) -> impl Iterator<Item = (&'static str, FieldId)> + '_ {
        self.names.iter().enumerate().map(|(i, &p)| (p, FieldId(i as u16)))
    }

    /// A field's value in `raw`: the last place it is written whose variant the packet holds.
    #[inline]
    pub fn read<'a>(&self, raw: &'a [u8], id: FieldId) -> Option<Value<'a>> {
        let i = id.0 as usize;
        let run = &self.entries[self.runs[i] as usize..self.runs[i + 1] as usize];
        if let [e] = run
            && e.3 == NONE
        {
            return value(raw, e);
        }
        let e = run.iter().rev().find(|e| self.holds(raw, e.3))?;
        value(raw, e)
    }

    fn holds(&self, raw: &[u8], mut c: u16) -> bool {
        while c != NONE {
            let cond = &self.conds[c as usize];
            match value(raw, &self.entries[cond.0 as usize]).and_then(|v| v.int()) {
                Some(v) if v == cond.1 => c = cond.2,
                _ => return false,
            }
        }
        true
    }
}

/// `bits` (at most 64) at bit `pos`; the caller has checked the packet holds them.
#[inline]
fn bits_at(raw: &[u8], pos: u32, bits: u32) -> u64 {
    let (start, shift) = ((pos >> 3) as usize, pos & 7);
    let mask = if bits >= 64 { u64::MAX } else { (1 << bits) - 1 };
    if shift + bits <= 64
        && let Some(b) = raw.get(start..start + 8)
    {
        return (u64::from_le_bytes(b.try_into().unwrap()) >> shift) & mask;
    }
    let mut acc = 0u128;
    for (i, &b) in raw[start..start + ((shift + bits + 7) >> 3) as usize].iter().enumerate() {
        acc |= (b as u128) << (8 * i);
    }
    (acc >> shift) as u64 & mask
}

fn value<'a>(raw: &'a [u8], e: &E) -> Option<Value<'a>> {
    let (pos, bits) = (e.0, e.1);
    match e.2 {
        K::Zero => return Some(Value::U(0)),
        // Text keeps what is inside the packet.
        K::Text => {
            let b = raw.get((pos >> 3) as usize..).unwrap_or_default();
            return text(&b[..b.len().min((bits >> 3) as usize)]).map(Value::Text);
        }
        _ => {}
    }
    if (raw.len() as u64) * 8 < pos as u64 + bits as u64 {
        return None;
    }
    Some(match e.2 {
        K::U => Value::U(bits_at(raw, pos, bits)),
        K::I => {
            let v = bits_at(raw, pos, bits) as i64;
            Value::I(if bits < 64 && v >= 1 << (bits - 1) { v - (1 << bits) } else { v })
        }
        K::F => Value::F(f32::from_le_bytes(raw[(pos >> 3) as usize..][..4].try_into().unwrap()) as f64),
        K::WideU => Value::Wide(bits_at(raw, pos, bits.min(64)) as i128),
        K::WideI => {
            let v = bits_at(raw, pos, bits.min(64)) as i128;
            Value::Wide(if bits <= 64 && v >= 1 << (bits - 1) { v - (1 << bits) } else { v })
        }
        K::Zero | K::Text => unreachable!(),
    })
}

/// `_text`: up to the first NUL, less a leading byte order mark, invalid UTF-8 replaced; empty is None.
fn text(b: &[u8]) -> Option<Cow<'_, str>> {
    let b = &b[..b.iter().position(|&c| c == 0).unwrap_or(b.len())];
    let b = b.strip_prefix(b"\xef\xbb\xbf").unwrap_or(b);
    (!b.is_empty()).then(|| String::from_utf8_lossy(b))
}

/// A packet's bytes and its layout.
#[derive(Clone, Copy, Debug)]
pub struct Packet<'a> {
    pub layout: &'static Layout,
    pub raw: &'a [u8],
}

impl<'a> Packet<'a> {
    /// A field by path, as Python's `Fields`: `p.get("UniqueNo")`, `p.get("SendFlg.Position")`. The action
    /// bitstream's paths work too, decoding the bitstream each time: read `action()` instead.
    pub fn get(&self, path: &str) -> Option<Value<'a>> {
        if let Some(id) = self.layout.field(path) {
            return self.layout.read(self.raw, id);
        }
        if self.layout.custom && path.starts_with(action::PREFIX) {
            return self.action()?.fields().find(|(p, _)| p == path).map(|(_, v)| v);
        }
        None
    }

    /// A field found once with `Layout::field`.
    #[inline]
    pub fn at(&self, id: FieldId) -> Option<Value<'a>> {
        self.layout.read(self.raw, id)
    }

    /// The action bitstream, for s2c 0x028.
    pub fn action(&self) -> Option<Action<'a>> {
        if self.layout.custom { Action::decode(self.raw) } else { None }
    }

    /// Every field with a value, as Python's decoder gives them, the action bitstream's included.
    pub fn fields(&self) -> impl Iterator<Item = (Cow<'static, str>, Value<'a>)> + '_ {
        let own = self.layout.paths().filter_map(|(p, id)| Some((Cow::Borrowed(p), self.at(id)?)));
        own.chain(self.action().into_iter().flat_map(|a| a.fields().map(|(p, v)| (Cow::Owned(p), v))))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MASTER_LEVELS: u64 = 1_636_502_400_000; // 2021-11-10, when 30211103_1 went live

    fn name_at(version: Option<&str>) -> usize {
        let l = layout(S2C, 0x0DD, version).unwrap();
        let i = l.field("Name").unwrap().0 as usize;
        l.entries[l.runs[i] as usize].0 as usize / 8
    }

    #[test]
    fn a_version_before_until_gets_the_older_layout() {
        assert_eq!(name_at(Some("30211005_0")), 0x26);
        assert_eq!(name_at(Some("30211103_1")), 0x28);
        assert_eq!(name_at(Some("30261102_1")), 0x28);
        // Not a client version: today's, as packets does.
        assert_eq!(name_at(Some("Version 18:08:44 Nov 12 2025")), 0x28);
        assert_eq!(name_at(Some("")), 0x28);
        assert_eq!(name_at(None), 0x28);
    }

    #[test]
    fn a_capture_with_no_version_picks_by_when_it_was_recorded() {
        assert_eq!(capture_version("30211005_0", MASTER_LEVELS), "30211005_0");
        assert_eq!(capture_version("", MASTER_LEVELS - 1), "0_0");
        assert_eq!(capture_version("", MASTER_LEVELS), "30211103_1");
        assert_eq!(capture_version("Version 18:08:44 Nov 12 2025", 1_763_362_549_317), "30211103_1");
        assert_eq!(capture_version("", 0), "");
        assert_eq!(name_at(Some(capture_version("", 1_580_740_282_000))), 0x26);
    }

    #[test]
    fn only_digits_read_as_a_version() {
        assert_eq!(version_key("30211103_1"), Some((30211103, 1)));
        for v in ["", "_", "30211103", "+3021_1", "3021_1x", "Version 1_2"] {
            assert_eq!(version_key(v), None, "{v}");
        }
    }
}
