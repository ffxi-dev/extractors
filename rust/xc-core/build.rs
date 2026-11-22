// Compiles xicap's reader and its C API (bindings/go/capi.cpp) from the source XICAP_SRC names: a checkout of
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
    let Ok(x) = std::env::var("XICAP_SRC") else {
        // cargo check and clippy need no xicap; a build that links does.
        println!("cargo:warning=XICAP_SRC is unset: xicap is not compiled, so linking fails");
        return;
    };
    let x = Path::new(&x);
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
