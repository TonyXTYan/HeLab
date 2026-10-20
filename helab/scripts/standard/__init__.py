"""HeLab's bundled analyses, imported normally (not scanned from a folder) so that
packaged builds include them; the Scripts panel registers ``MODULES``. They share the
group ``group.NAME`` ("Basic plots v1"), whose version marks this first set of plots."""
from helab.scripts.standard import basic_plots, density_images, scatter_3d, shot_times, transfer_fractions

MODULES = (scatter_3d, basic_plots, density_images, shot_times, transfer_fractions)
