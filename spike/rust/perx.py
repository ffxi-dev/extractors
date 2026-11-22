import sys, time
from ffxi_extractors.capture import read
from ffxi_extractors.extractors import ALL
from ffxi_extractors.index import walk
path = sys.argv[1]; which = sys.argv[2:]
def t(xs):
    cap = read(path, "x", True); t0 = time.perf_counter(); walk(cap, xs); return time.perf_counter() - t0
base = t([])
out = [f"world-only {base:.2f}"]
if "all" in which:
    out.append(f"all {t([x() for x in ALL]):.2f}")
if "each" in which:
    each = sorted(((t([x()]) - base, x.name) for x in ALL), reverse=True)
    out += [f"{n} {s:+.2f}" for s, n in each]
print("\n".join(out))
