// Compiles xicap's reader and its C API (bindings/go/capi.cpp): from the checkout XICAP_SRC names, else from a
// clone of XICAP_TAG, the tag pyproject.toml pins (tests/test_build.py checks they agree). C++23, so gcc 14 or
// newer; links zstd.
use std::path::{Path, PathBuf};
use std::process::Command;

const XICAP_TAG: &str = "v7.2.0";

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
    let x = match std::env::var("XICAP_SRC") {
        Ok(x) => PathBuf::from(x),
        Err(_) => clone(),
    };
    let x = x.as_path();
    assert!(x.join("bindings/go/capi.cpp").is_file(), "{} holds no xicap checkout", x.display());
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

/// xicap at XICAP_TAG, cloned once into the build's own folder.
fn clone() -> PathBuf {
    let x = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join(format!("xicap-{XICAP_TAG}"));
    if !x.join("bindings/go/capi.cpp").is_file() {
        let _ = std::fs::remove_dir_all(&x);
        let ok = Command::new("git")
            .args(["clone", "-q", "--depth", "1", "--branch", XICAP_TAG, "https://github.com/ffxi-dev/xicap"])
            .arg(&x)
            .status()
            .is_ok_and(|s| s.success());
        assert!(ok, "cloning xicap {XICAP_TAG} failed: install git, or set XICAP_SRC to a checkout of it");
    }
    x
}
