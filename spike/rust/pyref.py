import glob, sys, time
from ffxi_packets import Decoder
from ffxi_extractors import combat
from ffxi_extractors.capture import read
from ffxi_extractors.decode import Decoded
from ffxi_extractors.world import WORLD, World

path, mode = sys.argv[1], sys.argv[2]  # mode: rows | count | read
t0 = time.perf_counter()
cap = read(path, "x", True)
world, dec, out, n, rows = World(cap), Decoder(), sys.stdout, 0, 0
keys = WORLD | {(0, 0x028)}
N = "N\tN\tN\tN"
for batch in cap.batches():
    n += len(batch)
    if mode == "read":
        continue
    d = Decoded(dec, cap.client_version, batch, keys)
    for i, p in enumerate(batch):
        key = (p.direction, p.opcode)
        if key not in keys or p.channel != 0:
            continue
        f = d.fields(i, p)
        if key in WORLD:
            world.update(p, f)
        if key == (0, 0x028):
            a = combat.action(f)
            for t, (tid, results) in enumerate(a["targets"]):
                for ri, r in enumerate(results):
                    rows += 1
                    if mode == "rows":
                        ex = lambda g: N if g is None else "\t".join(str(g[k]) for k in combat.EXTRA)
                        out.write(f"{p.idx}\t{a['actor_id']}\t{a['cmd_no']}\t{a['cmd_arg']}\t{a['info']}\t{tid}\t{t}\t{ri}\t"
                                  + "\t".join(str(r[k]) for k in combat.RESULT) + f"\t{ex(r['proc'])}\t{ex(r['react'])}\n")
print(f"python {mode}: packets {n} result_rows {rows} zone {world.zone} {time.perf_counter() - t0:.2f}s", file=sys.stderr)
