"""The plots ported from the lab's DLD front panel, imported normally (not scanned from a folder)
so that packaged builds include them; the Scripts panel registers ``MODULES`` after
``helab.scripts.standard.MODULES``. They share the group ``group.NAME`` ("DLD Front Panel Port").

Counts per shot, the T, X, Y histograms, the 3D scatter and Transfer fractions are the port's own
versions of the "Basic plots v1" plots of the same names (``helab.dld.*`` analysis ids): ms and mm,
fits and BEC properties, masks, wrapped titles and lab/folder constants. They draw with PyQtGraph
only (the scatter with Plotly); the "Basic plots v1" ones offer every library."""
from helab.scripts.dld import (basic_plots, correlations_plot, density_images, mean_position, release_time,
                               scatter_3d, shot_times, shot_trends, t_spectrum, transfer_fractions,
                               velocity_distributions)

MODULES = (scatter_3d, basic_plots, mean_position, t_spectrum, density_images, shot_times, shot_trends,
           transfer_fractions, release_time, velocity_distributions, correlations_plot)
