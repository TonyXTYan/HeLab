"""Write profile-plates-2025.provisional.json: the measurements beside matlab-2019's values, and two
loadable candidate profiles (checked with DetectorProfile.from_dict). Numbers come from out/*.json."""
import json
import math
from common import SESSION, OUT, helab_env

helab_env()
from helab.convert.profile import DetectorProfile, builtin_profile  # noqa: E402

pp = json.loads((OUT / "plate_probes.json").read_text())
ps = json.loads((OUT / "pulse_spacing_fine.json").read_text())
gf = json.loads((OUT / "geometry_flatfield.json").read_text())
ih = json.loads((OUT / "images_hotspots.json").read_text())
mp = json.loads((OUT / "matching_params.json").read_text())
m19 = builtin_profile("matlab-2019")
jun = pp["2025 plates, Jun 2026 (weak trap)"]
jul = pp["2025 plates, Jul 2026 (tight trap)"]
ratio = 1.07
s = math.sqrt(ratio)

common_notes = ("PROVISIONAL, not calibrated (session 2026-10-29-claude-txy-2025-plates). Same matching as matlab-2019; "
                "v_perp_y/v_perp_x = 1.07 from the active-area edge (assumes a round MCP), geometric mean kept "
                "(absolute scale unknown). Uncalibrated: time sums (no MCP pulses), non-linearity, hot spots, efficiency.")
cand_june = m19.replace(name="plates-2025-provisional-jun2026", version=1, calibrated=False, tag="",
                        notes=common_notes + " Wiring as in June 2026 and all earlier data.",
                        v_perp_x=round(m19.v_perp_x / s, 1), v_perp_y=round(m19.v_perp_y * s, 1))
cand_swapped = cand_june.replace(name="plates-2025-provisional-swapped", channel_x1=1, channel_x2=0, channel_y1=3, channel_y2=2,
                                 notes=common_notes + " Corner channels as wired from ~July 2026 (x1<->x2, y1<->y2 found swapped): "
                                       "this map restores the June/historical orientation (X -> -X, Y -> -Y).")
for c in (cand_june, cand_swapped):
    assert DetectorProfile.from_dict(c.to_dict()) == c

doc = {
    "provisional": True,
    "calibrated": False,
    "plate": "plates-2025 (MCP plates fitted 2025-06-18)",
    "made": "2026-10-29, Claude, session .ai/sessions/2026-10-29-claude-txy-2025-plates/ (investigation.md)",
    "approval": "None. Tony approves calibrations; nothing here is applied to HeLab's built-in profiles.",
    "data": {
        "raw": ["~/HeLab-samples/txy-2026 (172 shots, 4 runs 2026-06-19..27)",
                "~/HeLab-samples/calib-2026/20260625_Ramsey_weak_trap (all 519 raw)",
                "~/HeLab-samples/calib-2026/20260722-tight-trap-freq-meas (24 raw + TXY)"],
        "txy_only": ["calib-2026/20261010-411trapcollisions44 (866)", "calib-2026/20260727-RingBEC (100 of 1007)",
                     "calib-2026/20260812_Quantum_efficiency (45 of 498)"],
        "comparison": ["~/HeLab-samples/txy-v1 (2017 and 2022 plates)", "~/HeLab-samples/calib-v1 (2017- and 2022-plate halos)"],
    },
    "measurements": {
        "channel_map": {
            "matlab_2019": {"x1": 0, "x2": 1, "y1": 2, "y2": 3, "mcp": 4, "trigger": 5},
            "measured": "June 2026: as matlab-2019. From ~2026-07-21 (tight-trap raw) to at least 2026-10-09 (collisions TXY): "
                        "x1<->x2 and y1<->y2 swapped relative to June (image rotated 180 degrees).",
            "evidence": {"reflection_peak_ns_jun_x1_x2_y1_y2": [ps["2025 plates Jun 2026 (0625 Ramsey)"][c]["reflection_peak_ns"] for c in ("x1", "x2", "y1", "y2")],
                         "reflection_peak_ns_jul_x1_x2_y1_y2": [ps["2025 plates Jul 2026 (tight trap)"][c]["reflection_peak_ns"] for c in ("x1", "x2", "y1", "y2")],
                         "reflection_peak_ns_2022_plates_2023_03": [ps["2022 plates 2023-03"][c]["reflection_peak_ns"] for c in ("x1", "x2", "y1", "y2")],
                         "background_image_corr_with_june": gf["rotation_test"]},
            "confidence": "high",
            "channel_7": "new since the 2025 swap (none in any 2017-2025-01 sample); ignored by the converter (output byte-identical without it).",
            "channel_4_mcp": "no pulses in any post-swap raw file",
        },
        "xy_time_sum_difference_bins": {
            "matlab_2019_assumes": 0, "tolerance_matlab_2019": m19.xy_sum_tolerance,
            "jun_2026_median": jun["D_median"], "jun_2026_median_sd": round(jun["D_median_boot_sd"], 2), "jun_2026_iqr": jun["D_iqr"],
            "jun_2026_plane_fit": jun["D_fit_bins"], "jun_2026_map_p5_p95": jun["D_map_range_p5_p95"],
            "jul_2026_median": jul["D_median"], "jul_2026_iqr": jul["D_iqr"], "jul_2026_plane_fit": jul["D_fit_bins"],
            "plates_2022_median": pp["2022 plates (2023-02..2025-01)"]["D_median"],
            "plates_2017_median": pp["2017 plates (2020, 2022-07)"]["D_median"],
            "method": "median of (x1+x2)-(y1+y2) over matched hits; plane fit in kbins of x1-x2 and y1-y2; bootstrap over shots",
            "confidence": "high for the value, medium for the map (cloud positions differ per run)",
        },
        "absolute_time_sums_bins": {"matlab_2019": [m19.time_sum_t_x, m19.time_sum_t_y], "plates_2025": "not measurable (no MCP pulses)",
                                    "plates_2022_from_mcp_2022_11": [pp["mcp_2022_11"]["sum_x_median"], pp["mcp_2022_11"]["sum_y_median"]],
                                    "plates_2022_position_fit": [pp["mcp_2022_11"]["sum_x_fit"], pp["mcp_2022_11"]["sum_y_fit"]]},
        "match_window_bins": {"matlab_2019": m19.search_window, "proposed": m19.search_window,
                              "wide_4000_adds_pct_jun": round(jun["wide_added_pct"], 3),
                              "share_of_wide_extras_with_consistent_sum": 0.25, "normal_hits_consistent": 0.74, "random_expectation": 0.15,
                              "reading": "~80 % of the extra hits are random pulse combinations in dense clouds; real clipped atoms <~0.1 %: keep 3200",
                              "confidence": "medium-high"},
        "pulse_spacing": {"shortest_interval_ns_p0.1": {c: ps["2025 plates Jun 2026 (0625 Ramsey)"][c]["shortest_ns_p0.1"] for c in ("x1", "x2", "y1", "y2")},
                          "reflection_excess_per_pulse": {c: ps["2025 plates Jun 2026 (0625 Ramsey)"][c]["reflection_excess_per_pulse"] for c in ("x1", "x2", "y1", "y2")},
                          "pulses_per_hit_jun": json.loads((OUT / "pulse_spacing.json").read_text())["p25-0625-ramsey"]["pulses_per_hit"],
                          "dead_time_proposed_s": 0.0,
                          "reading": "electronics dead time ~100-125 ns per channel (as on the 2022 plates); delay-line reflections 170-196 ns after a pulse; "
                                     "a converter dead time would drop real atoms (0.25 us on all corners: -17.6 % hits, nearly all atoms)"},
        "geometry": {"edge_ellipse_jun_2026": ih["2025 plates, Jun 2026 (Rabi/Ramsey)"]["edge"],
                     "edge_ellipse_2026_10_10_collisions_in_its_frame": ih["2025 plates, 2026-10-10 collisions"]["edge"],
                     "edge_halves_collisions": [gf["edge"]["2026-10-10 collisions"]["even"], gf["edge"]["2026-10-10 collisions"]["odd"]],
                     "axis_ratio_estimate": "1.07 +- 0.02 (X wider; long axis within ~10-14 deg of X)",
                     "mean_edge_radius_mm_at_matlab_2019_scale": "40.0 +- 0.5 (half-density of dark counts)",
                     "centre_mm_june_frame": "(+0.6, -1.3) June; (+1.0, -0.5) from collisions rotated: ~(0.8, -0.9) +- 0.8",
                     "rotation_rad": "not measurable from these data (halo is not round; BB correlation is blind to rotation); "
                                     "front panel uses 0.61 rad and the halo's long axis lies at ~35 deg, consistent",
                     "v_perp_matlab_2019": [m19.v_perp_x, m19.v_perp_y],
                     "v_perp_provisional": [cand_june.v_perp_x, cand_june.v_perp_y],
                     "confidence": "medium (assumes the visible active area is round; 2017 plates show the same 1.09 ratio, so it may be the anode)"},
        "hot_spots_june_frame_mm": [
            {"x": 15.9, "y": 1.4, "r": 2.5, "rate_hz_jun": 3.3, "rate_hz_oct": 4.4, "seen": "Jun, Jul tight trap, RingBEC, Oct (all rotated)"},
            {"x": 32.3, "y": 1.2, "r": 1.4, "rate_hz_jun": 1.8, "rate_hz_oct": 0.44, "seen": "Jun, RingBEC, Oct"},
            {"x": 8.8, "y": -1.0, "r": 1.5, "rate_hz_jun": 0.10, "rate_hz_oct": 0.13, "seen": "Jun, Oct"},
            {"x": 1.2, "y": -0.2, "r": 1.1, "rate_hz_jun": 0.08, "seen": "Jun only"},
            {"x": -27.6, "y": -7.7, "r": 3.8, "rate_hz_oct": 0.14, "seen": "Oct only"},
            {"x": 7.1, "y": -3.1, "r": 1.6, "rate_hz_oct": 0.06, "seen": "Oct only"},
            {"x": -29.0, "y": -18.3, "r": 1.6, "rate_hz_jun": 0.04, "seen": "Jun only (weak)"},
            {"x": -21.6, "y": -19.4, "r": 1.0, "rate_hz_jun": 0.04, "seen": "Jun only (weak)"}],
        "hot_spot_method": "helab.analysis.hotspots.find_hot_spots (alpha 0.01, 0.5 mm bins, 1 mm background) on background-window hits; "
                           "rates = excess / background time (Jun 2194 s, Oct 3389 s)",
        "flat_field_proxy": gf["flat_without_hot_bins"],
        "matching_parameter_effects_jun_2026": {k: {kk: v[kk] for kk in ("hits", "change_pct", "change_in_windows", "change_outside")}
                                                 for k, v in mp["Jun 2026 (4 runs, 172 shots)"].items() if not k.startswith("_")},
    },
    "candidate_profiles": {"wired_as_june_2026": cand_june.to_dict(), "wired_as_from_july_2026": cand_swapped.to_dict()},
    "not_changed_and_why": {
        "time_sum_t_x/y": "absolute sums need MCP pulses (record channel 4 in a calibration run); T shift is ~1.5 ns, negligible",
        "xy_sum_tolerance": "keep 400: the check is centred on 0 while the 2025 sum difference is +121 (map 7..186); a tighter "
                            "check needs an offset field (not in schema 1): 200 would drop 9.7 % of hits",
        "search_window/match sums": "keep 3200 (see match_window_bins)",
        "dead times": "keep 0 (see pulse_spacing)",
        "x2_handling": "keep matlab: a retry adds 0.007 %",
    },
}
out = SESSION / "profile-plates-2025.provisional.json"
out.write_text(json.dumps(doc, indent=1, default=float) + "\n")
print(out, cand_june.v_perp_x, cand_june.v_perp_y)
