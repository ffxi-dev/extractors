# Parity with Python

`dump.py` decodes every packet of the opcodes the world and the extractors read, as `Decoded` gives them
the fields, and prints each packet with a CRC of its fields. `examples/parity.rs` decodes the same bytes
with the crate, compares, and times reading every field of each opcode's packets.

```bash
# on lsb, in a checkout: Python from Scholar's image, this checkout's ffxi_extractors
docker run --rm --user $(id -u):$(id -g) -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/w -v $PWD:/w -w /w \
  -v /home/sruon/scholar-data/mirror:/m:ro --entrypoint python scholar:latest \
  rust/xc-decode/parity/dump.py /m/<capture>.xicap > <capture>.txt
cargo run --release --example parity -- <capture>.txt...
python dump.py --hex <direction> <opcode> <hex>   # one packet's fields, to read a mismatch
```

## Result

Every packet decodes the same, for all 60 opcodes the world and the extractors read, against
ffxi-packets 2.2.0, the version `pyproject.toml` pins. Every case in packets' `cases/` does too
(`tests/cases.rs`, 53 cases).

- KDRkBynUt6A_, DZ6Cp6Zs3kEK, 1YZ8avSluJB9: 6,591,135 of 6,591,135 packets, 48 opcodes.
- 12 opcodes those captures lack, from the smallest captures that hold them (eG81evD6VpXS, 3kGqv6jKgrLQ,
  bMqSzX5owWQl, o9pUIWfPXQzp, P7KChFI6VAFq, FavAmKXvF-UU, A-ip_ijvEQHK, KG6OOkGCNTZf): 428,711 of 428,711
  packets of every opcode, these 12 among them.

Times are on lsb (Ryzen 7 7800X3D, one core): reading every field of a packet, then that over its paths.
An extractor reads a few fields, a few ns each. s2c 0x028's time walks every target and result of the
bitstream; its 3 paths are the head (id, size, sync).

| Opcode | Packets | Same as Python | Paths | ns a packet, every field | ns a field |
|---|---|---|---|---|---|
| s2c 0x00a | 1178 | 1178 | 112 | 743 | 6.6 |
| s2c 0x00b | 1195 | 1195 | 21 | 141 | 6.7 |
| s2c 0x00d | 336070 | 336070 | 121 | 864 | 7.1 |
| s2c 0x00e | 2829495 | 2829495 | 106 | 773 | 7.3 |
| s2c 0x01d | 531263 | 531263 | 8 | 73 | 9.1 |
| s2c 0x01e | 8617 | 8617 | 8 | 59 | 7.4 |
| s2c 0x01f | 100492 | 100492 | 8 | 64 | 8.0 |
| s2c 0x020 | 494887 | 494887 | 36 | 249 | 6.9 |
| s2c 0x027 | 11 | 11 | 23 | 144 | 6.3 |
| s2c 0x028 | 174084 | 174084 | 3 | 204 | |
| s2c 0x029 | 21443 | 21443 | 12 | 87 | 7.3 |
| s2c 0x02a | 2619 | 2619 | 44 | 185 | 4.2 |
| s2c 0x02d | 35810 | 35810 | 12 | 84 | 7.0 |
| s2c 0x032 | 24 | 24 | 10 | 70 | 7.0 |
| s2c 0x034 | 1592 | 1592 | 18 | 125 | 6.9 |
| s2c 0x036 | 311 | 311 | 9 | 64 | 7.1 |
| s2c 0x037 | 82793 | 82793 | 118 | 798 | 6.8 |
| s2c 0x038 | 10643 | 10643 | 8 | 61 | 7.6 |
| s2c 0x03c | 48 | 48 | 120 | 725 | 6.0 |
| s2c 0x03e | 30 | 30 | 5 | 39 | 7.8 |
| s2c 0x03f | 22 | 22 | 7 | 50 | 7.2 |
| s2c 0x050 | 115551 | 115551 | 7 | 58 | 8.3 |
| s2c 0x052 | 2030 | 2030 | 4 | 32 | 8.0 |
| s2c 0x053 | 7 | 7 | 7 | 49 | 7.0 |
| s2c 0x055 | 9662 | 9662 | 37 | 247 | 6.7 |
| s2c 0x056 | 32984 | 32984 | 13 | 88 | 6.8 |
| s2c 0x057 | 96 | 96 | 6 | 43 | 7.2 |
| s2c 0x05c | 1744 | 1744 | 11 | 77 | 7.0 |
| s2c 0x05e | 1181 | 1181 | 188 | 1216 | 6.5 |
| s2c 0x061 | 17215 | 17215 | 55 | 368 | 6.7 |
| s2c 0x062 | 16894 | 16894 | 98 | 642 | 6.5 |
| s2c 0x063 | 183707 | 183707 | 621 | 4804 | 7.7 |
| s2c 0x070 | 7 | 7 | 21 | 146 | 6.9 |
| s2c 0x071 | 3543 | 3543 | 247 | 2008 | 8.1 |
| s2c 0x075 | 470 | 470 | 145 | 938 | 6.5 |
| s2c 0x0c8 | 1058 | 1058 | 247 | 1587 | 6.4 |
| s2c 0x0d2 | 15653 | 15653 | 30 | 200 | 6.7 |
| s2c 0x0d3 | 1808 | 1808 | 20 | 141 | 7.0 |
| s2c 0x0dd | 1028 | 1028 | 30 | 202 | 6.7 |
| s2c 0x0df | 541343 | 541343 | 22 | 186 | 8.4 |
| s2c 0x0e2 | 1987 | 1987 | 30 | 201 | 6.7 |
| s2c 0x0f4 | 279805 | 279805 | 10 | 75 | 7.5 |
| c2s 0x015 | 682366 | 682366 | 16 | 142 | 8.8 |
| c2s 0x01a | 44960 | 44960 | 10 | 72 | 7.2 |
| c2s 0x036 | 6 | 6 | 29 | 193 | 6.7 |
| c2s 0x05b | 3373 | 3373 | 9 | 64 | 7.1 |
| c2s 0x05c | 10 | 10 | 13 | 88 | 6.8 |
| c2s 0x083 | 20 | 20 | 10 | 71 | 7.1 |

The 12 opcodes from the other captures:

| Opcode | Packets | Same as Python | Paths | ns a packet, every field | ns a field |
|---|---|---|---|---|---|
| s2c 0x033 | 1 | 1 | 20 | 161 | 8.0 |
| s2c 0x05d | 1 | 1 | 16 | 95 | 5.9 |
| s2c 0x06f | 1 | 1 | 34 | 226 | 6.6 |
| s2c 0x082 | 37 | 37 | 6 | 45 | 7.5 |
| s2c 0x083 | 13 | 13 | 125 | 838 | 6.7 |
| s2c 0x085 | 15 | 15 | 125 | 856 | 6.9 |
| s2c 0x086 | 5 | 5 | 8 | 58 | 7.2 |
| s2c 0x0bf | 1 | 1 | 7 | 47 | 6.7 |
| s2c 0x115 | 1 | 1 | 13 | 90 | 6.9 |
| c2s 0x063 | 25 | 25 | 8 | 56 | 7.0 |
| c2s 0x0aa | 37 | 37 | 6 | 45 | 7.6 |
| c2s 0x110 | 3 | 3 | 9 | 64 | 7.2 |
