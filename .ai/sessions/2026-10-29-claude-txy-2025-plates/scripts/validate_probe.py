"""Check probe_match against MATLAB's TXY (d_txy_forc) on the 2026 samples: same hit count, and
T/X/Y equal to 6e-8 relative (the TXY are written with 8 significant digits)."""
import numpy as np
from common import SAMPLES, raw_files, read_raw, read_txy
from probe_match import match

bad = 0; n = 0
for setdir in sorted((SAMPLES / "txy-2026").iterdir()):
    if not setdir.is_dir():
        continue
    for f in raw_files(setdir)[::4]:
        c, t = read_raw(f)
        h = match(c, t)
        ref = read_txy(f.with_name(f.name.replace("d", "d_txy_forc", 1)))
        ref = ref[ref[:, 0] != 0] if len(ref) else ref
        ours = np.c_[h["T"], h["X"], h["Y"]]
        ok = len(ours) == len(ref) and np.allclose(ours, ref, rtol=6e-8, atol=1e-12)
        n += 1
        if not ok:
            bad += 1
            print("MISMATCH", f, len(ours), len(ref))
print(f"{n - bad} of {n} files equal")
