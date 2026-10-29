"""Are the corner bursts that come with ch7 also there without ch7? In each 2026-06-25 shot, find
'bursts': >= 15 corner pulses within 1 us, all four corners present, outside the atoms' arrival
windows (so dense clouds don't count). Then: how many bursts have a ch7 pulse within 1 us; the burst
profile (pulses per channel vs time from the burst's first pulse, or from ch7). Repeated for the
July tight-trap raw sample. Writes out/ch7_bursts.json and figures/ch7_burst_profile.png."""
import json
import numpy as np
from common import OUT, SAMPLES, BIN, figure, save, raw_files, read_raw

NS = 1e-9 / BIN


def windows_busy(T_all):
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(T_all, edges)
    busy = h > 2 * np.median(h[h > 0])
    return edges, np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0


res = {}
profiles = {}
for name, folder in (("2026-06-25 (Jun wiring)", SAMPLES / "calib-2026/20260625_Ramsey_weak_trap"),
                     ("2026-07 tight trap (swapped wiring)", SAMPLES / "calib-2026/20260722-tight-trap-freq-meas")):
    files = raw_files(folder)
    data = []
    allT = []
    for f in files:
        c, t = read_raw(f)
        t0 = t[0]
        o = np.argsort(t, kind="stable")
        data.append((c[o], t[o] - t0))
        allT.append((t[o][c[o] <= 3] - t0) * BIN)
    edges, busy = windows_busy(np.concatenate(allT))
    bursts = with7 = 0
    ch7_in_burst = ch7_total = 0
    prof = np.zeros((5, 120))  # channels 0-3 and 7, 10 ns bins from -200 to +1000 ns relative to burst start
    nprof = 0
    for c, t in data:
        sec = t * BIN
        quiet = ~busy[np.clip(np.searchsorted(edges, sec, side="right") - 1, 0, len(busy) - 1)]
        corner = (c <= 3) & quiet
        tc = t[corner]
        cc = c[corner]
        t7 = t[c == 7]
        ch7_total += len(t7)
        j = 0
        used_until = -1
        n = len(tc)
        for i in range(n):
            if tc[i] <= used_until:
                continue
            k = np.searchsorted(tc, tc[i] + 1000 * NS)
            if k - i >= 15 and len(set(cc[i:k].tolist())) == 4:
                bursts += 1
                used_until = tc[k - 1]
                has7 = np.any(np.abs(t7 - tc[i]) < 1000 * NS)
                with7 += int(has7)
                rel = (t[(t > tc[i] - 200 * NS) & (t < tc[i] + 1000 * NS)] - tc[i]) / NS
                ch = c[(t > tc[i] - 200 * NS) & (t < tc[i] + 1000 * NS)]
                for chan, row in ((0, 0), (1, 1), (2, 2), (3, 3), (7, 4)):
                    h, _ = np.histogram(rel[ch == chan], bins=np.arange(-200, 1000.1, 10))
                    prof[row] += h
                nprof += 1
        for x in t7:
            k0 = np.searchsorted(tc, x - 1000 * NS); k1 = np.searchsorted(tc, x + 1000 * NS)
            ch7_in_burst += int(k1 - k0 >= 15)
    quiet_time = len(data) * 4.03 * (1 - busy.mean())
    res[name] = {"shots": len(data), "quiet_time_s": round(quiet_time, 1), "bursts_in_quiet_windows": bursts,
                 "burst_rate_hz": round(bursts / quiet_time, 4), "bursts_with_ch7": with7,
                 "share_with_ch7": round(with7 / max(bursts, 1), 3), "ch7_total": int(ch7_total),
                 "ch7_with_>=15_corner_pulses_within_1us": int(ch7_in_burst)}
    profiles[name] = (prof / max(nprof, 1), nprof)
    print(name, res[name])
(OUT / "ch7_bursts.json").write_text(json.dumps(res, indent=1))
fig = figure(13, 4.5)
axs = fig.subplots(1, 2)
x = np.arange(-200, 1000, 10) + 5
for ax, (name, (prof, n)) in zip(axs, profiles.items()):
    for row, lab, col in ((0, "ch0 (x1)", "#4269d0"), (1, "ch1 (x2)", "#ef4444"), (2, "ch2 (y1)", "#16a34a"),
                          (3, "ch3 (y2)", "#a855f7"), (4, "ch7", "k")):
        ax.step(x, prof[row], where="mid", color=col, label=lab, lw=1)
    ax.set_xlabel("time from the burst's first corner pulse [ns]"); ax.set_ylabel("pulses per burst per 10 ns")
    ax.set_title(f"{name}: {n} bursts (≥15 corner pulses in 1 µs, quiet windows)", fontsize=9); ax.legend(fontsize=7)
save(fig, "ch7_burst_profile.png")
