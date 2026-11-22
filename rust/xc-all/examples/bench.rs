//! Times the Rust walk with each extractor alone, without Python:
//! `cargo run --release --example bench -p xc-all <capture> world actions looks`.
use std::time::Instant;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    for name in &a[2..] {
        let mut xs: Vec<Box<dyn xc_core::Extractor>> =
            if name == "world" { vec![] } else { vec![xc_all::by_name(name).expect("no such extractor")] };
        let t = Instant::now();
        let (_, _, outs) = xc_core::run::walk(a[1].as_ref(), &mut xs, None).unwrap();
        let n: usize = outs.iter().flat_map(|o| o.tables.iter().map(|t| t.len())).sum();
        println!("{name} {:?} rows {n}", t.elapsed());
    }
}
