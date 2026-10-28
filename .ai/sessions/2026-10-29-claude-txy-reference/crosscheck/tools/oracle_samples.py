import hashlib, json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, sys.argv[1])
import oracle
ROOT = os.path.expanduser("~/HeLab-samples/txy-v1")
def one(job):
    s, pos, shot = job
    d = os.path.join(ROOT, s)
    raw = open(os.path.join(d, f"d{shot['shot']}.txt"), "rb").read()
    ref = open(os.path.join(d, f"d_txy_forc{shot['shot']}.txt"), "rb").read()
    ok_sha = hashlib.sha256(raw).hexdigest() == shot["raw_sha256"] and hashlib.sha256(ref).hexdigest() == shot["txy_sha256"]
    t = time.perf_counter()
    out = oracle.dlmwrite_bytes(oracle.reconstruct(oracle.read_raw(raw), "2019"))
    return s, pos, shot["shot"], ok_sha, out == ref, len(raw), time.perf_counter() - t
if __name__ == '__main__':
    m = json.load(open(os.path.join(ROOT, "manifest.json")))
    jobs = [(s, i, sh) for s, v in m["sets"].items() for i, sh in enumerate(v["shots"])]
    res = {}
    with ProcessPoolExecutor(6) as ex:
        for r in ex.map(one, jobs):
            res.setdefault(r[0], []).append(r)
    for s, rs in res.items():
        bad = [r[2] for r in rs if not r[4]]
        print(f"{s:32s} shots {len(rs):3d} sha_ok {sum(r[3] for r in rs):3d} identical {sum(r[4] for r in rs):3d} MB {sum(r[5] for r in rs)/1e6:7.1f} cpu_s {sum(r[6] for r in rs):6.1f} bad {bad}")
