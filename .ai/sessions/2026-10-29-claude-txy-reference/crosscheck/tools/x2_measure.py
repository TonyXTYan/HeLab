import json, os, sys
from concurrent.futures import ProcessPoolExecutor
TOOLS = sys.argv[1]
sys.path.insert(0, TOOLS)
import oracle
ROOT = os.path.expanduser("~/HeLab-samples/txy-v1")
def one(job):
    s, n = job
    raw = oracle.read_raw(open(f"{ROOT}/{s}/d{n}.txt", "rb").read())
    res = {}
    for mode in ("matlab", "retry2", "retry_all"):
        st = {}
        hits = oracle.reconstruct(raw, "2019", mode, st)
        res[mode] = (len(hits), st)
    return s, res
if __name__ == "__main__":
    m = json.load(open(f"{ROOT}/manifest.json"))
    jobs = [(s, sh["shot"]) for s, v in m["sets"].items() for sh in v["shots"]]
    agg = {}
    with ProcessPoolExecutor(8) as ex:
        for s, res in ex.map(one, jobs):
            a = agg.setdefault(s, {})
            for mode, (h, st) in res.items():
                b = a.setdefault(mode, {"hits": 0})
                b["hits"] += h
                for k, v in st.items(): b[k] = b.get(k, 0) + v
    json.dump(agg, open(".ai/temp/crosscheck/x2_measure.json", "w"), indent=1)
    tot = {}
    print(f"{'set':30} {'hits':>9} {'x1 w/ x2':>9} {'x2 multi':>15} {'no y|multi':>10} {'y multi':>8} {'retry2 net':>16} {'retry_all net':>16}")
    for s, a in list(agg.items()) + [("all", None)]:
        if a is None: a = tot
        else:
            for mode, b in a.items():
                t = tot.setdefault(mode, {})
                for k, v in b.items(): t[k] = t.get(k, 0) + v
        mm = a["matlab"]; withx2 = mm["x1_rows"] - mm.get("x2_none", 0)
        d2 = a["retry2"]["hits"] - mm["hits"]; da = a["retry_all"]["hits"] - mm["hits"]
        print(f"{s:30} {mm['hits']:9,} {withx2:9,} {mm.get('x2_multi',0):7,} ({100*mm.get('x2_multi',0)/max(withx2,1):4.2f} %) {mm.get('y_fail_multi',0):10,} {mm.get('y_multi',0):8,} {d2:+8,} ({100*d2/mm['hits']:4.2f} %) {da:+8,} ({100*da/mm['hits']:4.2f} %)")
