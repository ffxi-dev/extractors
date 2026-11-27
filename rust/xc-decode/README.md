# xc-decode

FFXI packets decoded as `ffxi_packets` decodes them, field for field, straight from the packet's bytes.

`build.rs` turns `packets/` (ffxi-dev/packets at tag v2.3.0: `schemas/*.json` and `cases/`) into a table per
fixed layout: each field's path, bit offset, width, and union variant. A field is read only when asked for,
with no allocation except text that is not valid UTF-8. The action packet (s2c 0x028) has its own bitstream
decoder, `Action`, matching Python's `_action`.

```rust
use xc_decode::{decode, layout, S2C};

let p = decode(S2C, 0x00E, &bytes, Some("30261006_0")).unwrap();
p.get("UniqueNo");                        // Option<Value>, None where Python's Fields gives None
let l = layout(S2C, 0x00E, None).unwrap();
let id = l.field("SendFlg.Position").unwrap(); // find once
p.at(id);                                 // read from each packet
for t in decode(S2C, 0x028, &action, None).unwrap().action().unwrap().targets() {
    for r in t.results() { /* r.message, r.proc, ... */ }
}
```

Bump packets: copy the tag's `schemas/*.json` and `cases/*.json` into `packets/`, set the tag in
`decode.PACKETS` and in pyproject.toml's `ffxi-packets` source, `uv lock`, then `cargo test` and
`pytest tests/test_rust.py`, which fails when a copied schema is not the tag's.
Older layouts (`layouts.json`) are picked by client version as packets picks them. A capture whose header
names no version, such as a PacketViewer import, picks by when it was recorded: `version_at` gives the version
live then, from build.rs's `LIVE`, which fails the build when a layout's `until` or `from` has no day there.

`parity/` compares the crate with Python on real captures: every packet the same. Its README has the numbers.
