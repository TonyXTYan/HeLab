"""Compare oracle.py with MATLAB's recorded outcome for every case: python3 -I compare_oracle.py <cases>."""
import json, os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
cases = sys.argv[1]
bad = 0
for name in sorted(os.listdir(cases)):
    d = os.path.join(cases, name)
    if not os.path.isfile(os.path.join(d, "d1.txt")):
        continue
    for v in ("2019", "2023"):
        res = json.load(open(os.path.join(d, f"matlab-{v}.json")))
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "o.txt")
            r = subprocess.run([sys.executable, "-I", os.path.join(here, "oracle.py"), os.path.join(d, "d1.txt"), v, out], capture_output=True, text=True).stdout.strip()
            st = res["status"]
            if st == "file":
                ok = os.path.exists(out) and open(out, "rb").read() == open(os.path.join(d, f"expected-{v}.txt"), "rb").read()
            elif st == "nofile":
                ok = r == "NOFILE"
            else:
                ok = r.startswith("ERROR")
            if not ok:
                bad += 1
                print(f"{v} {name}: MATLAB {st} ({res['hits']}), oracle {r}")
print("mismatches:", bad)
