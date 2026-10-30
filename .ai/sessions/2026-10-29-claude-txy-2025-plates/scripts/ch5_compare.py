"""Channel 5's rows besides the trigger, per era, for comparison with channel 7: when they occur
(relative to the trigger), group sizes and spacing, and corner pulses around them.
Writes out/ch5_compare.json."""
import json
import numpy as np
from common import OUT, SAMPLES, BIN, raw_files, read_raw

sets = {"2026-06-25 (2025 plates)": SAMPLES / "calib-2026/20260625_Ramsey_weak_trap",
        "2026-07 tight trap (2025 plates)": SAMPLES / "calib-2026/20260722-tight-trap-freq-meas",
        "2025-01 (2022 plates)": SAMPLES / "calib-2026/20250104_off_axis_check_mirror",
        "2024-11 (2022 plates)": SAMPLES / "txy-v1/2024-11-rt-low-occupancy",
        "2023-03 (2022 plates)": SAMPLES / "txy-v1/2023-03-momentum-bells",
        "2022-11 MCP (2022 plates)": SAMPLES / "txy-v1/2022-11-ghost-counts-mcp",
        "2022-07 (2017 plates)": SAMPLES / "txy-v1/2022-07-old-plates-large-he3",
        "2019 (2017 plates)": SAMPLES / "txy-v1/2019-halos-old-plates"}
res = {}
for nm, d in sets.items():
    groups = {"+54..56 us": 0, "3.9..4.2 s (end of window)": 0, "before the trigger": 0, "other": 0}
    sizes, spacing, near = [], [], []
    files = raw_files(d)[:60]
    for f in files:
        c, t = read_raw(f)
        t0 = t[0]
        e = np.sort(t[np.flatnonzero(c == 5)[1:]])
        if not len(e):
            continue
        rel = (e - t0) * BIN
        for r in rel:
            k = ("+54..56 us" if 50e-6 < r < 60e-6 else "3.9..4.2 s (end of window)" if 3.9 < r < 4.2
                 else "before the trigger" if r < 0 else "other")
            groups[k] += 1
        # groups: rows within 1 us of each other
        cut = np.flatnonzero(np.diff(e) > 40000)
        for g in np.split(e, cut + 1):
            sizes.append(len(g))
            spacing += (np.diff(g) * BIN * 1e9).tolist()
            near.append(int(((np.abs(t - g[0]) < 40000) & (c <= 3)).sum()))
    res[nm] = {"files": len(files), "extra_rows": groups, "group_size_median": float(np.median(sizes)),
               "spacing_ns_median": float(np.median(spacing)) if spacing else None,
               "corner_pulses_within_1us_median": float(np.median(near)), "corner_pulses_within_1us_mean": float(np.mean(near))}
    print(nm, res[nm])
(OUT / "ch5_compare.json").write_text(json.dumps(res, indent=1))
