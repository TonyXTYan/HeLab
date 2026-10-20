"""HeLab's bundled analyses, imported normally (not scanned from a folder) so that
packaged builds include them; the Scripts panel registers ``MODULES``. They share the
group ``group.NAME`` ("Basic plots v1"), whose version marks this first set of plots."""
from helab.scripts.standard import (basic_plots, density_images, mean_position, release_time, scatter_3d, shot_times,
                                    shot_trends, t_spectrum, transfer_fractions, velocity_distributions)

MODULES = (scatter_3d, basic_plots, mean_position, t_spectrum, density_images, shot_times, shot_trends,
           transfer_fractions, release_time, velocity_distributions)
