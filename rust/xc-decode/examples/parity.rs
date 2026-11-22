//! Compares the crate with Python on parity/dump.py's lines, opcode by opcode, then times reading every
//! field of each opcode's packets (for 0x028, walking its targets and results).
//!
//!     cargo run --release --example parity -- <dump.txt>...

use std::collections::BTreeMap;
use std::fmt::Write;
use std::hint::black_box;
use std::time::Instant;
use xc_decode::{Packet, Value, decode};

/// zlib's CRC-32.
fn crc32(b: &[u8]) -> u32 {
    !b.iter().fold(!0u32, |mut c, &x| {
        c ^= x as u32;
        for _ in 0..8 {
            c = if c & 1 != 0 { (c >> 1) ^ 0xEDB88320 } else { c >> 1 };
        }
        c
    })
}

fn canon(p: &Packet) -> String {
    let mut fields: Vec<_> = p.fields().collect();
    fields.sort_by(|a, b| a.0.cmp(&b.0));
    let mut out = String::new();
    for (k, v) in fields {
        match v {
            Value::U(x) => writeln!(out, "{k}={x}"),
            Value::I(x) => writeln!(out, "{k}={x}"),
            Value::F(x) if x.is_nan() => writeln!(out, "{k}=fnan"),
            Value::F(x) => writeln!(out, "{k}=f{:016x}", x.to_bits()),
            Value::Wide(x) => writeln!(out, "{k}=s{x}"),
            Value::Text(s) => writeln!(out, "{k}=s{s}"),
        }
        .unwrap();
    }
    out
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len() / 2).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect()
}

/// An opcode's packets, and how many decode as Python's.
type Packets = (Vec<Vec<u8>>, usize);

fn main() {
    let mut by: BTreeMap<(u8, u16), Packets> = BTreeMap::new();
    let mut shown = 0;
    for path in std::env::args().skip(1) {
        for line in std::fs::read_to_string(&path).unwrap().lines() {
            let mut w = line.split(' ');
            let (d, op): (u8, u16) = (w.next().unwrap().parse().unwrap(), w.next().unwrap().parse().unwrap());
            let (raw, want) = (hex(w.next().unwrap()), u32::from_str_radix(w.next().unwrap(), 16).unwrap());
            let got = decode(d, op, &raw, None).map(|p| canon(&p)).unwrap_or_default();
            let e = by.entry((d, op)).or_default();
            if crc32(got.as_bytes()) == want {
                e.1 += 1;
            } else if shown < 5 {
                shown += 1;
                println!("mismatch {d} {op:#05x} {}\n{got}", w.clone().count());
                println!("  hex {}", raw.iter().map(|b| format!("{b:02x}")).collect::<String>());
            }
            e.0.push(raw);
        }
    }
    println!("| Opcode | Packets | Same as Python | Paths | ns a packet, every field | ns a field |");
    println!("|---|---|---|---|---|---|");
    for ((d, op), (raws, same)) in &by {
        let dir = if *d == 0 { "s2c" } else { "c2s" };
        let reps = (2_000_000 / raws.len()).max(1);
        let t = Instant::now();
        for _ in 0..reps {
            for r in raws {
                let p = decode(*d, *op, r, None).unwrap();
                if let Some(a) = p.action() {
                    for t in a.targets() {
                        for r in t.results() {
                            black_box(r);
                        }
                    }
                } else {
                    for f in p.layout.paths() {
                        black_box(p.at(f.1));
                    }
                }
            }
        }
        let all = t.elapsed().as_nanos() as f64 / (reps * raws.len()) as f64;
        let n = decode(*d, *op, &raws[0], None).unwrap().layout.paths().count();
        println!("| {dir} {op:#05x} | {} | {same} | {n} | {all:.0} | {:.1} |", raws.len(), all / n as f64);
    }
    let (n, same) = by.values().fold((0, 0), |a, v| (a.0 + v.0.len(), a.1 + v.1));
    println!("\n{same} of {n} packets the same");
    std::process::exit(if same == n { 0 } else { 1 });
}
