"""The same burst finder (ch7_burst_detail.py) on the older local samples, to see whether the bursts
are new with the 2025 plates. Writes out/ch7_burst_eras.json."""
import json
import numpy as np
from common import OUT, SAMPLES, BIN, raw_files
from ch7_burst_detail_lib import busy_windows, bursts_in, load

sets = {"2019 (2017 plates)": "txy-v1/2019-halos-old-plates", "2020 (2017 plates)": "txy-v1/2020-halos-weak-trap",
        "2022-07 (2017 plates)": "txy-v1/2022-07-old-plates-large-he3", "2022-11 MCP (2022 plates)": "txy-v1/2022-11-ghost-counts-mcp",
        "2023-02 (2022 plates)": "txy-v1/2023-02-new-plates-he3he4", "2023-03 (2022 plates)": "txy-v1/2023-03-momentum-bells",
        "2024-11 (2022 plates)": "txy-v1/2024-11-rt-low-occupancy", "2025-01 (2022 plates)": "calib-2026/20250104_off_axis_check_mirror",
        "2026-06-25 (2025 plates)": "calib-2026/20260625_Ramsey_weak_trap"}
res = {}
for nm, rel in sets.items():
    data = [load(f) for f in raw_files(SAMPLES / rel)[:120]]
    e, b = busy_windows([(t[c <= 3]) * BIN for c, t, _ in data])
    nb = 0; qt = 0.0; first = np.zeros(4); n7 = 0; sizes = []
    for c, t, _ in data:
        bs = bursts_in(c, t, e, b)
        nb += len(bs); n7 += sum(x[5] for x in bs)
        for x in bs:
            first[x[4]] += 1; sizes.append(x[3])
        qt += float(t.max() * BIN) * (1 - b.mean())
    res[nm] = {"files": len(data), "quiet_s": round(qt, 1), "bursts": nb, "rate_hz": round(nb / max(qt, 1e-9), 2),
               "first_channel_share": (first / max(nb, 1)).round(3).tolist(), "size_3us_median": float(np.median(sizes)) if sizes else None,
               "with_ch7": int(n7)}
    print(nm, res[nm], flush=True)
(OUT / "ch7_burst_eras.json").write_text(json.dumps(res, indent=1))
