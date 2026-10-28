"""Simulate retrying the other x2 candidate over whole shots (for the x2 report; not a profile
option, Q6.10): what MATLAB's 4-corner match gives if, when no y pair fits the first x2, it tries
the next x2 candidate (``second``: the one MATLAB's search stops at; ``all``: every candidate in
the 36-row window), each recovered hit then taking its pulses from later x1 rows.

    python dev/txy/x2_retry.py [--positions all] [--json OUT]

A copy of ``helab.convert.backends.reference``'s loop with the retry added; ``retry="none"`` must
give the reference's output exactly, which this script checks on every shot before counting.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys

import numpy as np

from _common import guard, sample_arguments

guard()

from helab.convert.backends.reference import offsets, reconstruct_reference, sort_order, uniquetol_keep  # noqa: E402
from helab.convert.profile import DetectorProfile, builtin_profile  # noqa: E402
from helab.convert.raw import RawPulses, parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402

NAN = math.nan


def reconstruct_retry(pulses: RawPulses, profile: DetectorProfile, retry: str) -> np.ndarray:
    raw_channels, raw_times = pulses.channels.tolist(), pulses.times.tolist()
    n = len(raw_times)
    if n == 0 and profile.subtract_time_zero:
        raise NoRowsError("no rows")
    order = sort_order(raw_times)
    ch = [raw_channels[k] for k in order]
    t = [raw_times[k] for k in order]
    if profile.subtract_time_zero:
        t = [value - raw_times[0] for value in t]
    snapshot = list(ch)
    for channel, dead_time in ((profile.channel_x1, profile.dead_time_x1), (profile.channel_x2, profile.dead_time_x2),
                               (profile.channel_y1, profile.dead_time_y1), (profile.channel_y2, profile.dead_time_y2)):
        if dead_time > 0:
            rows = [k for k in range(n) if snapshot[k] == channel]
            for k, first_of_group in zip(rows, uniquetol_keep([t[k] for k in rows], dead_time / profile.bin_time)):
                if not first_of_group:
                    ch[k] = NAN
    search = offsets(profile.search_depth)
    window = profile.search_window
    x_limit = profile.match_time_sum_x + profile.match_tolerance_x
    y_limit = profile.match_time_sum_y + profile.match_tolerance_y
    centred = profile.position_formula == "centred"
    out = [[NAN] * 5 for _ in range(n // 4)]
    grown = 0.0 if profile.matlab_overflow_row else NAN

    def put(row: int, column: int, value: float) -> None:
        while len(out) < row:
            out.append([grown] * 5)
        out[row - 1][column - 1] = value

    which_row = 0
    for i in range(1 if profile.skip_first_sorted_row else 0, n):
        if ch[i] != profile.channel_x1:
            continue
        x1 = t[i]
        candidates: list[int] = []
        for dummy in search:
            j = i + dummy
            if j < 0 or j >= n or abs(t[j] - x1) > window or ch[j] != profile.channel_x2:
                continue
            if abs(x1 - t[j]) < x_limit:
                candidates.append(j)
                if retry != "all" and len(candidates) > 1:
                    break
        if not candidates:
            continue
        tries = candidates[:1] if retry == "none" else candidates
        which_row += 1
        matched = False
        for x2_index in tries:
            x2 = t[x2_index]
            tx = 0.5 * (x1 + x2 - profile.time_sum_t_x)
            put(which_row, 2, x1 - tx if centred else x1)
            put(which_row, 3, x2 - tx if centred else x2)
            how_many_y = 0
            for dummy2 in search:
                j2 = i + dummy2
                if j2 < 0 or j2 >= n or abs(t[j2] - x1) > window or ch[j2] != profile.channel_y1:
                    continue
                y1 = t[j2]
                for dummy3 in search:
                    j3 = i + dummy3
                    if j3 < 0 or j3 >= n or abs(t[j3] - x1) > window or ch[j3] != profile.channel_y2:
                        continue
                    y2 = t[j3]
                    if abs(y1 - y2) < y_limit and abs(x1 + x2 - y1 - y2) < profile.xy_sum_tolerance:
                        how_many_y += 1
                        if how_many_y > 1:
                            break
                        ty = 0.5 * (y1 + y2 - profile.time_sum_t_y)
                        put(which_row, 4, y1 - ty if centred else y1)
                        put(which_row, 5, y2 - ty if centred else y2)
                        put(which_row, 1, (tx + ty) / 2)
                        ch[i] = ch[x2_index] = ch[j2] = ch[j3] = NAN
            if how_many_y:
                matched = True
                break
        if not matched:
            which_row -= 1
    kept = [row for row in out if not math.isnan(row[0])]
    b, vx, vy = profile.bin_time, profile.v_perp_x, profile.v_perp_y
    hits = [[r[0] * b, (r[1] - r[2]) * vx * b, (r[3] - r[4]) * vy * b] for r in kept]
    return np.array([hits[k] for k in sort_order([h[0] for h in hits])], dtype=np.float64).reshape(-1, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for shot in select_shots(load_manifest(args.root), args.positions, args.sets):
        pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
        try:
            reference = reconstruct_reference(pulses, profile)
        except NoRowsError:
            continue
        none = reconstruct_retry(pulses, profile, "none")
        if not np.array_equal(none, reference):
            print(f"{shot.label}: the copy differs from the reference; fix x2_retry.py first")
            return 1
        base = {tuple(row) for row in reference.tolist()}
        row = counts[shot.set_name]
        row["hits"] += len(reference)
        for mode in ("second", "all"):
            hits = reconstruct_retry(pulses, profile, mode)
            mine = {tuple(r) for r in hits.tolist()}
            row[f"{mode}_net"] += len(hits) - len(reference)
            row[f"{mode}_new"] += len(mine - base)
            row[f"{mode}_lost"] += len(base - mine)
    total: dict[str, int] = defaultdict(int)
    for row in counts.values():
        for key, value in row.items():
            total[key] += value
    print("| Set | Hits | Retry the second x2: net (new, lost) | Retry every candidate: net |")
    print("|---|---|---|---|")
    for name, row in [*counts.items(), ("all", total)]:
        print(f"| {name} | {row['hits']:,} | {row['second_net']:+,} ({100 * row['second_net'] / row['hits']:.2f} %; "
              f"{row['second_new']:,} new, {row['second_lost']:,} lost) | {row['all_net']:+,} "
              f"({100 * row['all_net'] / row['hits']:.2f} %) |")
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({name: dict(row) for name, row in [*counts.items(), ("all", total)]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
