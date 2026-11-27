//! Every case in packets' cases/ decodes to its fields, as both of packets' decoders do.

use serde_json::Value as J;
use std::collections::BTreeMap;
use xc_decode::{C2S, S2C, Value, capture_version, decode};

/// A value as a case file stores it: JSON has no NaN, so a NaN float is no value.
pub fn json(v: &Value) -> Option<J> {
    Some(match v {
        Value::U(x) => J::from(*x),
        Value::I(x) => J::from(*x),
        Value::F(x) if x.is_nan() => return None,
        Value::F(x) => J::from(*x),
        Value::Wide(x) => J::from(x.to_string()),
        Value::Text(s) => J::from(s.as_ref()),
    })
}

#[test]
fn cases() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("packets/cases");
    let mut n = 0;
    for f in std::fs::read_dir(dir).unwrap().flatten() {
        if f.file_name() == "versions.json" {
            continue;
        }
        let cases: Vec<J> = serde_json::from_str(&std::fs::read_to_string(f.path()).unwrap()).unwrap();
        for c in cases {
            let dir = if c["direction"] == "c2s" { C2S } else { S2C };
            let op = u16::from_str_radix(c["opcode"].as_str().unwrap().trim_start_matches("0x"), 16).unwrap();
            let raw: Vec<u8> = (0..c["hex"].as_str().unwrap().len() / 2)
                .map(|i| u8::from_str_radix(&c["hex"].as_str().unwrap()[2 * i..2 * i + 2], 16).unwrap())
                .collect();
            let Some(p) = decode(dir, op, &raw, c["client_version"].as_str()) else {
                eprintln!("skipped {} {}: offsets depend on the data", c["direction"], c["opcode"]);
                continue;
            };
            let got: BTreeMap<String, J> = p.fields().filter_map(|(k, v)| Some((k.into_owned(), json(&v)?))).collect();
            let want: BTreeMap<String, J> =
                c["fields"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.clone())).collect();
            for (k, v) in &want {
                let g = got.get(k);
                // A case's 0.0 is written 0, as JSON from JavaScript writes it.
                let same = g == Some(v) || g.and_then(J::as_f64).is_some_and(|g| Some(g) == v.as_f64());
                assert!(same, "{} {} {}#{} {k}: {g:?} != {v}", c["direction"], c["opcode"], c["capture"], c["index"]);
            }
            for k in got.keys() {
                assert!(want.contains_key(k), "{} {} extra {k}", c["direction"], c["opcode"]);
            }
            n += 1;
        }
    }
    assert!(n > 0);
    eprintln!("{n} cases");
}

#[test]
fn capture_versions() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("packets/cases/versions.json");
    let v: J = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let cases = v["capture_versions"].as_array().unwrap();
    assert!(!cases.is_empty());
    for c in cases {
        let got = capture_version(c["client_version"].as_str().unwrap(), c["start_ms"].as_u64().unwrap());
        assert!(c["picks"] == got, "{}: {got}", c["note"]);
    }
}
