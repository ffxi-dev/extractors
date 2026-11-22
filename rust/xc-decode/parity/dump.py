"""Every packet of the opcodes the world and the extractors read, as Python decodes it for them: one line
per packet, `direction opcode hex crc`. crc is zlib's CRC-32 of the packet's fields with a value, sorted by
path, `path=value\n` each: an int in decimal, a float as `f` and its double's bits in hex (`fnan` for NaN),
text as `s` and the text. examples/parity.rs hashes its own decoding the same way.

    python dump.py <capture.xicap> > packets.txt   # where ffxi_extractors and ffxi_packets import
    python dump.py --hex <direction> <opcode> <hex> # one packet's fields, to see a mismatch
"""

import math
import struct
import sys
import zlib

from ffxi_packets import Decoder

from ffxi_extractors.capture import read
from ffxi_extractors.decode import Decoded
from ffxi_extractors.extractors import ALL
from ffxi_extractors.world import WORLD


def enc(v) -> str:
    if isinstance(v, float):
        return "fnan" if math.isnan(v) else "f" + struct.pack(">d", v).hex()
    return "s" + v if isinstance(v, str) else str(v)


def canon(f, paths) -> bytes:
    return "".join(f"{k}={enc(v)}\n" for k in sorted(paths) if (v := f(k)) is not None).encode()


def main() -> None:
    keys = set(WORLD).union(*(x.reads for x in ALL))
    if sys.argv[1] == "--hex":
        from ffxi_extractors.capture import Packet

        d, op, raw = int(sys.argv[2]), int(sys.argv[3], 0), bytes.fromhex(sys.argv[4])
        p = Packet(0, 0, 0, d, op, 0, raw)
        dec = Decoded(Decoder(), "", [p], {(d, op)})
        sys.stdout.write(canon(dec.fields(0, p), dec.cols.get((d, op), {})).decode())
        return
    cap, decoder, out = read(sys.argv[1], "x", True), Decoder(), sys.stdout
    for batch in cap.batches():
        dec = Decoded(decoder, cap.client_version, batch, keys)
        for i, p in enumerate(batch):
            key = (p.direction, p.opcode)
            if p.channel == 0 and key in keys:
                h = zlib.crc32(canon(dec.fields(i, p), dec.cols.get(key, {})))
                out.write(f"{p.direction} {p.opcode} {bytes(p.data).hex()} {h:08x}\n")


main()
