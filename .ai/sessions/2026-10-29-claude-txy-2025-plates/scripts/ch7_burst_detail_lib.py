"""The burst finder from ch7_burst_detail.py, importable without running it."""
from __future__ import annotations

import json
import os
import re
import numpy as np
from common import OUT, SAMPLES, SCRATCH, BIN, M_PER_BIN, figure, save, raw_files, read_raw, shot_number
from probe_match import match

NS = 1e-9 / BIN
X = "/Volumes/192.168.137.1-4/dld_output_cheerypicked"


def quiet_mask(sec, edges, busy):
    return ~busy[np.clip(np.searchsorted(edges, sec, side="right") - 1, 0, len(busy) - 1)]


def busy_windows(Ts):
    edges = np.arange(0, 4.21, 0.01)
    h, _ = np.histogram(np.concatenate(Ts), edges)
    busy = h > 2 * np.median(h[h > 0])
    return edges, np.convolve(busy.astype(int), np.ones(5, int), mode="same") > 0


def bursts_in(c, t, edges, busy):
    """t: bins from t_zero, sorted. Returns list of (start, end, size1us, size3us, first_channel, has7)."""
    sec = t * BIN
    q = quiet_mask(sec, edges, busy)
    corner = (c <= 3) & q
    tc, cc = t[corner], c[corner]
    t7 = t[c == 7]
    out, used = [], -1
    for i in range(len(tc)):
        if tc[i] <= used:
            continue
        k = np.searchsorted(tc, tc[i] + 1000 * NS)
        if k - i >= 15 and len(set(cc[i:k].tolist())) == 4:
            k3 = np.searchsorted(tc, tc[i] + 3000 * NS)
            used = tc[k3 - 1]
            out.append((tc[i], tc[k3 - 1], k - i, k3 - i, int(cc[i]), bool(np.any(np.abs(t7 - tc[i]) < 1000 * NS))))
    return out


def load(path):
    c, t = read_raw(path)
    t0 = t[0]
    o = np.argsort(t, kind="stable")
    return c[o], t[o] - t0, (c, t)
