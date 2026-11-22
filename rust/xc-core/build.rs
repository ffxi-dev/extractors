// Compiles xicap's reader and its C API (bindings/go/capi.cpp) from the source XICAP_SRC names, and fails without it:
// ffxi-dev/xicap at the tag pyproject.toml pins. C++23, so gcc 14 or newer; links zstd.
use std::path::{Path, PathBuf};

fn cpp(dir: &Path, out: &mut Vec<PathBuf>) {
    for e in std::fs::read_dir(dir).unwrap().flatten() {
        let p = e.path();
        if p.is_dir() {
            cpp(&p, out);
        } else if p.extension().is_some_and(|s| s == "cpp") {
            out.push(p);
        }
    }
}

fn main() {
    println!("cargo:rerun-if-env-changed=XICAP_SRC");
    let x = std::env::var("XICAP_SRC").expect(
        "XICAP_SRC names no xicap checkout: clone ffxi-dev/xicap at the tag pyproject.toml pins and set XICAP_SRC to it",
    );
    let x = Path::new(&x);
    assert!(x.join("bindings/go/capi.cpp").is_file(), "XICAP_SRC={} holds no xicap checkout", x.display());
    let mut files = Vec::new();
    cpp(&x.join("src"), &mut files);
    files.sort();
    cc::Build::new()
        .cpp(true)
        .std("c++23")
        .include(x.join("include"))
        .include(x.join("src"))
        .files(&files)
        .file(x.join("bindings/go/capi.cpp"))
        .warnings(false)
        .compile("xicap");
    println!("cargo:rustc-link-lib=zstd");
    println!("cargo:rerun-if-changed={}", x.display());
}
