"""HeLab's bundled analyses, imported normally (not scanned from a folder) so that
packaged builds include them; the Scripts panel registers ``MODULES``."""
from helab.scripts.standard import basic_plots, scatter_3d

MODULES = (scatter_3d, basic_plots)
