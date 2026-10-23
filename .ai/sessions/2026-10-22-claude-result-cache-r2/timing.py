"""Cold run vs cached reuse of each DLD port and Basic plots v1 plot, for the opt-in list."""
import json, os, statistics, subprocess, sys, tempfile, time
sys.path.insert(0, "tests")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from helab.analysis import result_codec, result_cache
from helab.analysis.runner_core import AnalysisQueue
from helab.analysis.results import AnalysisResult
from helab.scripts.dld import (basic_plots, correlations_plot, density_images, mean_position, release_time,
                               scatter_3d, shot_times, shot_trends, t_spectrum, transfer_fractions,
                               velocity_distributions)
from helab.scripts.standard import basic_plots as std_basic, scatter_3d as std_scatter, transfer_fractions as std_tf
from helab.utils.cache_store import CacheStore
import test_release_time_plot as tr, test_correlations_plot as tc

queue = AnalysisQueue()
cloud, _ = tr.cloud_view(shots=100, count=5000)
corr_small = tc.txy_view(tc.thermal_velocities(1, shots=100, events=400))
corr_big = tc.txy_view(tc.thermal_velocities(2, shots=100, events=1500))
folder = {"release_time": tc.T_R, "trap_x": tc.ORIGIN[0], "trap_y": tc.ORIGIN[1]}
fits = {"fit_t": True, "fit_x": True, "fit_y": True}
CASES = [
    ("DLD Counts per shot", basic_plots.CountsPerShot(), cloud, {}, None),
    ("DLD T/X/Y histograms", basic_plots.TxyHistograms(), cloud, {}, None),
    ("DLD T/X/Y histograms, 3 fits", basic_plots.TxyHistograms(), cloud, fits, None),
    ("DLD Density images", density_images.DensityImages(), cloud, {}, None),
    ("DLD Mean X, Y vs T", mean_position.MeanPositionVsT(), cloud, {}, None),
    ("DLD T spectrum", t_spectrum.TProfileSpectrum(), cloud, {}, None),
    ("DLD Shot times", shot_times.ShotTimesPlot(), cloud, {}, None),
    ("DLD Shot trends", shot_trends.ShotTrends(), cloud, {}, None),
    ("DLD Transfer fractions", transfer_fractions.TransferFractions(), cloud, {}, None),
    ("DLD Velocity distributions", velocity_distributions.VelocityDistributions(), cloud, {}, None),
    ("DLD 3D scatter", scatter_3d.Scatter3D(), cloud, {}, None),
    ("DLD Release time (bootstrap 1000)", release_time.ReleaseTimePlot(), cloud, {}, None),
    ("DLD Correlations radial, 400 ev/shot", correlations_plot.Correlations(), corr_small, tc.RADIAL, folder),
    ("DLD Correlations 1D, 400 ev/shot", correlations_plot.Correlations(), corr_small, {}, folder),
    ("DLD Correlations radial, 1500 ev/shot", correlations_plot.Correlations(), corr_big, tc.RADIAL, folder),
    ("Basic v1 T/X/Y histograms", std_basic.TxyHistograms(), cloud, {}, None),
    ("Basic v1 Transfer fractions", std_tf.TransferFractions(), cloud, {}, None),
    ("Basic v1 3D scatter", std_scatter.Scatter3D(), cloud, {}, None),
]
store_dir = tempfile.mkdtemp(prefix="timing-store-")
rows = []
for name, script, view, values, layer in CASES:
    context = queue.prepare(script, script.get_metadata(), "Plot", view, values,
                            {"folder": layer} if layer else {}, owner=f"timing-{name}")
    started = time.perf_counter()
    data = script.compute("Plot", context)
    cold = time.perf_counter() - started
    result = AnalysisResult.of(context, "completed", data, found=script.result_found("Plot", data))
    try:
        packed = result_codec.pack(*result_codec.encode(data, script.cache_types("Plot")))
        with CacheStore(store_dir) as store:
            key = result_cache.lookup_key(context)
            lookup = result_cache.digest(key)
            path = f"root://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/{len(rows)}"
            store.save_result(path, lookup, "f", {"key": key, "result": result_cache.record_of(result)},
                              store.write_result_file(packed), store.start_result_job(path), analysis_id="t",
                              action="Plot", computed_at=time.time())
            started = time.perf_counter()
            found = store.find_result(path, lookup).value
            assert found is not None
        tree, arrays = result_codec.unpack(found.data)
        script.cache_unpack("Plot", tree, arrays)
        result_cache.result_from(found.row["record"]["result"], None)
        reuse = time.perf_counter() - started
        size = len(packed)
    except result_codec.CodecError as error:
        reuse, size = float("nan"), f"not packable: {error}"
    rows.append((name, cold, reuse, size))
    print(f"{name:42s} cold {cold:7.3f} s   read+unpack {reuse * 1000:7.1f} ms   {size}", flush=True)
# A local-lane helper's start and exit (each lookup runs one).
starts = []
for _ in range(5):
    started = time.perf_counter()
    subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps({"operation": "nothing"}) + "\n",
                   capture_output=True, text=True)
    starts.append(time.perf_counter() - started)
print(f"helper start+exit: median {statistics.median(starts):.3f} s over 5")
