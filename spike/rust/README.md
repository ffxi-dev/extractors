# Spike: the hot path in Rust

Not for merging. A Rust binary reads a capture through xicap's C API (`bindings/go/capi.h`), decodes every
s2c 0x028 bitstream as `ffxi_packets` does (`_action`), keeps a stand-in world (zone, entity ids by index), and
prints one row per target result. `pyref.py` prints the same rows from the library's `World`, `Decoded`, and
`combat.action`. `perx.py` times a walk with the world alone, every extractor, and each extractor alone.

Build on lsb (xicap's source at /xicap): `docker run --rm -v $PWD:/w -v <xicap>:/xicap:ro -w /w rust:1-trixie sh -c
"apt-get install -y libzstd-dev && cargo build --release"`. C++23 needs gcc 14 (trixie).

## Identical rows

| Capture | Packets | 0x028 | Result rows | md5, Python = Rust |
|---|---|---|---|---|
| KDRkBynUt6A_ | 1,151,775 | 324 | 338 | yes |
| DZ6Cp6Zs3kEK | 6,584,619 | 173,516 | 233,812 | yes |
| 1YZ8avSluJB9 | 48,461 | 244 | 244 | yes |

## Time (lsb, one core each, best of 3 for Rust)

| Capture | Python: read only | Python: read, world, 0x028 | Rust: the same | Python: world only walk | Python: every extractor |
|---|---|---|---|---|---|
| KDRkBynUt6A_ | 1.76 s | 3.56 s | 0.083 s (43x) | 4.40 s | 18.39 s |
| DZ6Cp6Zs3kEK | 10.18 s | 32.54 s | 0.571 s (57x) | 34.33 s | 118.80 s |
| 1YZ8avSluJB9 | 0.09 s | 0.25 s | 0.010 s (25x) | | |

Python costs ~1.5 us a packet just to hand it to Python, ~3.8 us with the world, ~16-18 us with every extractor.
Rust read, decoded, and kept the world for ~0.08 us a packet.

Each extractor alone, over the world-only walk, KDRkBynUt6A_ (its own logic plus decoding its opcodes):
engages +6.67, looks +2.51, actions +1.76, entity_changes +1.54, levels +1.46, trades +1.40, obtained +1.21,
party +1.17, fights +1.16, defeats +1.12, kills +1.10, events +1.06, the rest under 1 s each.
