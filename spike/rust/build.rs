fn main() {
    let x = "/xicap";
    let mut b = cc::Build::new();
    b.cpp(true).flag("-std=c++23").include(format!("{x}/include")).include(format!("{x}/src")).opt_level(3);
    for e in std::fs::read_dir(format!("{x}/src")).unwrap().flatten() {
        let p = e.path();
        if p.is_dir() {
            for f in std::fs::read_dir(&p).unwrap().flatten() {
                if f.path().extension().map_or(false, |s| s == "cpp") { b.file(f.path()); }
            }
        } else if p.extension().map_or(false, |s| s == "cpp") { b.file(p); }
    }
    b.file(format!("{x}/bindings/go/capi.cpp"));
    b.compile("xicap");
    println!("cargo:rustc-link-lib=zstd");
    println!("cargo:rustc-link-lib=stdc++");
}
