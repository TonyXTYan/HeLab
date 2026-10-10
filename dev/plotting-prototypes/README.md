# Plotting-library prototypes

Early experiments with Matplotlib, Plotly (in Qt and through Dash), PyQtGraph, PyVista, VisPy
and Manim, moved here from `helab/scripts/dev/` in 2026-10 (roadmap session S3 of
[the cache rebuild](../../roadmaps/cache-storage-and-settings.md)).

Unmaintained reference only. The app never loads them, and they no longer run as they are:
they import the old browser's `LoadFolderToRamWorker` (deleted) and read the old diskcache
store directly (`caching_setup.data_ram_cache`, deleted in S5). Analysis code belongs in
`helab/scripts/` as a `HelabAnalysisScript`.
