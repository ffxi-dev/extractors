//! Turns packets' schemas into static field tables, walking each layout as ffxi_packets' `_Columns` does: every
//! field of a fixed layout sits at one bit offset, valid when the packet holds it and, inside a union, when the
//! discriminator holds the variant's value. Layouts whose offsets depend on the data are left out.

use serde_json::Value as J;
use std::fmt::Write;

const WIDE: u64 = 53;

struct Entry {
    path: String,
    seq: usize,
    pos: u64,
    bits: u64,
    kind: &'static str,
    cond: Option<usize>,
}

struct Cond {
    field: usize, // an entry's seq until the sort, then its index
    value: i64,
    parent: Option<usize>,
}

#[derive(Default)]
struct Walk {
    entries: Vec<Entry>,
    conds: Vec<Cond>,
}

fn s<'a>(f: &'a J, k: &str) -> Option<&'a J> {
    f.get(k).filter(|v| !v.is_null())
}
fn u(f: &J, k: &str) -> u64 {
    s(f, k).and_then(J::as_u64).unwrap_or(0)
}
fn list<'a>(f: &'a J, k: &str) -> Option<&'a Vec<J>> {
    s(f, k).and_then(J::as_array)
}
fn is_char(f: &J) -> bool {
    f["base_type"] == "char"
}
fn is_float(f: &J) -> bool {
    f["base_type"] == "float"
}
fn is_union(f: &J) -> bool {
    f["is_union"] == true && list(f, "union_variants").is_some()
}
fn path(prefix: &str, name: &str) -> String {
    if name.starts_with('[') || prefix.is_empty() { format!("{prefix}{name}") } else { format!("{prefix}.{name}") }
}

/// `_elem_bits`: None when it is not whole, which makes a layout not fixed.
fn elem_bits(f: &J) -> Option<u64> {
    let b = u(f, "bits");
    if b != 0 {
        return Some(b);
    }
    let (size, count) = (u(f, "size_bytes"), u(f, "array_size"));
    if size == 0 || count == 0 {
        Some(0)
    } else if size * 8 % count == 0 {
        Some(size * 8 / count)
    } else {
        None
    }
}

fn element_end(f: &J, bits: u64, pos: u64) -> u64 {
    if is_float(f) { ((pos + 7) & !7) + 32 } else { pos + bits }
}

/// `_fixed_end`.
fn fixed_end(fields: &[J], mut pos: u64, tail: bool) -> Option<u64> {
    for (k, f) in fields.iter().enumerate() {
        let last = tail && k == fields.len() - 1;
        if s(f, "array_size").is_some() {
            let n = u(f, "array_size");
            if is_char(f) {
                pos = ((pos + 7) & !7) + n * 8;
                continue;
            }
            for _ in 0..n {
                if let Some(nested) = list(f, "nested_fields") {
                    pos = fixed_end(nested, pos, false)?;
                } else {
                    pos = element_end(f, elem_bits(f)?, pos);
                }
            }
        } else if let Some(nested) = list(f, "nested_fields") {
            pos = fixed_end(nested, pos, last)?;
        } else if is_union(f) {
            let size = u(f, "size_bytes") * 8;
            let mut ends = Vec::new();
            for v in list(f, "union_variants").unwrap() {
                ends.push(fixed_end(v["fields"].as_array().unwrap(), pos, false)?);
            }
            let most = ends.iter().copied().max().unwrap_or(pos);
            if size == 0 || (!last && most - pos > size) {
                return None;
            }
            pos = most.max(pos + size);
        } else {
            let bits = if u(f, "bits") != 0 { u(f, "bits") } else { u(f, "size_bytes") * 8 };
            pos = element_end(f, bits, pos);
        }
    }
    Some(pos)
}

impl Walk {
    fn put(&mut self, path: String, pos: u64, bits: u64, kind: &'static str, cond: Option<usize>) -> usize {
        let seq = self.entries.len();
        self.entries.push(Entry { path, seq, pos, bits, kind, cond });
        seq
    }

    /// One primitive, as `_Columns.element`.
    fn element(&mut self, f: &J, bits: u64, pos: u64, path: String, cond: Option<usize>) -> (usize, u64) {
        if is_float(f) {
            let pos = (pos + 7) & !7;
            return (self.put(path, pos, 32, "F", cond), pos + 32);
        }
        if bits == 0 {
            return (self.put(path, pos, 0, "Zero", cond), pos);
        }
        let signed = f["signed"] == true;
        let kind = match (bits > WIDE, signed) {
            (false, false) => "U",
            (false, true) => "I",
            (true, false) => "WideU",
            (true, true) => "WideI",
        };
        (self.put(path, pos, bits, kind, cond), pos + bits)
    }

    fn fields(&mut self, fields: &[J], mut pos: u64, prefix: &str, cond: Option<usize>) -> u64 {
        let mut context: Vec<(&str, usize)> = Vec::new();
        for f in fields {
            pos = self.field(f, pos, path(prefix, f["name"].as_str().unwrap()), cond, &mut context);
        }
        pos
    }

    fn field<'a>(
        &mut self,
        f: &'a J,
        mut pos: u64,
        path: String,
        cond: Option<usize>,
        context: &mut Vec<(&'a str, usize)>,
    ) -> u64 {
        if s(f, "array_size").is_some() {
            let n = u(f, "array_size");
            if is_char(f) {
                pos = (pos + 7) & !7;
                self.put(path, pos, n * 8, "Text", cond);
                return pos + n * 8;
            }
            let bits = elem_bits(f).unwrap();
            for i in 0..n {
                let p = format!("{path}[{i}]");
                if let Some(nested) = list(f, "nested_fields") {
                    pos = self.fields(nested, pos, &p, cond);
                } else {
                    pos = self.element(f, bits, pos, p, cond).1;
                }
            }
            return pos;
        }
        if let Some(nested) = list(f, "nested_fields") {
            return self.fields(nested, pos, &path, cond);
        }
        if is_union(f) {
            let disc = s(f, "discriminator_field").and_then(J::as_str);
            if let Some(&(_, field)) = disc.and_then(|d| context.iter().rev().find(|(n, _)| *n == d)) {
                for v in list(f, "union_variants").unwrap() {
                    let value = v["discriminator_value"].as_i64().expect("an integer discriminator value");
                    self.conds.push(Cond { field, value, parent: cond });
                    let c = Some(self.conds.len() - 1);
                    self.fields(v["fields"].as_array().unwrap(), pos, &path, c);
                }
            }
            return pos + u(f, "size_bytes") * 8;
        }
        let bits = if u(f, "bits") != 0 { u(f, "bits") } else { u(f, "size_bytes") * 8 };
        let (seq, end) = self.element(f, bits, pos, path, cond);
        context.push((f["name"].as_str().unwrap(), seq));
        end
    }
}

/// When each client version that starts or ends an older layout went live, UTC midnight of the update's day in
/// Unix ms: a capture whose header names no version picks its layouts by when it was recorded. Every `until`
/// and `from` in layouts.json needs one.
const LIVE: &[(&str, u64)] = &[
    // The 2021-11-10 update, Master Levels: LSB's CLIENT_VER went from 30211005_0 to it that day.
    ("30211103_1", 1_636_502_400_000),
];

fn opcode(p: &J) -> u16 {
    u16::from_str_radix(p["id"].as_str().unwrap().trim_start_matches("0x"), 16).unwrap()
}

/// `static {id}: Layout`, or false for a layout whose offsets depend on the data.
fn emit(out: &mut String, id: &str, p: &J, direction: u8, older: bool) -> bool {
    let opcode = opcode(p);
    let fields = p["fields"].as_array().unwrap();
    let custom = (direction, opcode) == (0, 0x028);
    if !custom && fixed_end(fields, 0, true).is_none() {
        return false;
    }
    let mut w = Walk::default();
    w.fields(fields, 0, "", None);
    // Sorted by path for lookup; a path written twice keeps its walk order, the last write winning.
    w.entries.sort_by(|a, b| a.path.cmp(&b.path).then(a.seq.cmp(&b.seq)));
    let mut at = vec![0; w.entries.len()];
    for (i, e) in w.entries.iter().enumerate() {
        at[e.seq] = i;
    }
    write!(
        out,
        "static {id}: Layout = Layout {{ name: {:?}, direction: {direction}, opcode: {opcode:#05x}, older: {older}, custom: {custom}, entries: &[",
        p["name"].as_str().unwrap()
    )
    .unwrap();
    let mut names = String::new();
    let mut runs = String::new();
    for (i, e) in w.entries.iter().enumerate() {
        if i == 0 || w.entries[i - 1].path != e.path {
            write!(names, "{:?},", e.path).unwrap();
            write!(runs, "{i},").unwrap();
        }
        let cond = e.cond.map_or(u16::MAX, |c| c as u16);
        write!(out, "E({},{},K::{},{cond}),", e.pos, e.bits, e.kind).unwrap();
    }
    write!(runs, "{}", w.entries.len()).unwrap();
    write!(out, "], names: &[{names}], runs: &[{runs}]").unwrap();
    out.push_str(", conds: &[");
    for c in &w.conds {
        let parent = c.parent.map_or(u16::MAX, |c| c as u16);
        write!(out, "C({},{},{parent}),", at[c.field], c.value).unwrap();
    }
    out.push_str("] };\n");
    true
}

/// A client version as `(30211103, 1)`, as packets' `_version_key` reads it.
fn version(v: &str) -> String {
    let (a, b) = v.split_once('_').unwrap();
    format!("({}, {})", a.parse::<u64>().unwrap(), b.parse::<u64>().unwrap())
}

fn main() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("packets");
    let read = |name: &str| -> J {
        let p = dir.join(name);
        println!("cargo:rerun-if-changed={}", p.display());
        serde_json::from_str(&std::fs::read_to_string(&p).unwrap()).unwrap()
    };

    let mut out = String::new();
    let mut table = vec!["None".to_string(); 2 * 0x200]; // opcodes are 9 bits
    for (direction, name) in [(0u8, "s2c"), (1u8, "c2s")] {
        for p in read(&format!("{name}.json")).as_array().unwrap() {
            let id = format!("{}_{:03X}", name.to_uppercase(), opcode(p));
            if emit(&mut out, &id, p, direction, false) {
                table[direction as usize * 0x200 + opcode(p) as usize] = format!("Some(&{id})");
            }
        }
    }
    writeln!(out, "static LAYOUTS: [Option<&Layout>; {}] = [{}];", table.len(), table.join(",")).unwrap();

    out.push_str("static OLDER: &[Older] = &[");
    let mut older = String::new();
    for (i, p) in read("layouts.json").as_array().unwrap().iter().enumerate() {
        let direction = if p["direction"] == "c2s" { 1u8 } else { 0 };
        let id = format!("OLDER_{i}");
        let layout = if emit(&mut older, &id, p, direction, true) { format!("Some(&{id})") } else { "None".into() };
        let bound = |k: &str| {
            p[k].as_str().map_or("None".into(), |v| {
                assert!(LIVE.iter().any(|(l, _)| *l == v), "build.rs's LIVE needs the day {v} went live");
                format!("Some({})", version(v))
            })
        };
        write!(
            out,
            "Older {{ direction: {direction}, opcode: {:#05x}, until: {}, from: {}, layout: {layout} }},",
            opcode(p),
            bound("until"),
            bound("from")
        )
        .unwrap();
    }
    out.push_str("];\n");
    out.push_str(&older);
    out.push_str("static LIVE: &[(&str, u64)] = &[");
    for (v, ms) in LIVE {
        write!(out, "({v:?}, {ms}),").unwrap();
    }
    out.push_str("];\n");
    std::fs::write(std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).join("layouts.rs"), out).unwrap();
}
