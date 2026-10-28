"""PyInstaller hook for mlx (the TXY converter's mlx backend; HeLab.spec's hookspath).

mlx's extension finds libmlx and its Metal kernel library (mlx.metallib) in ``mlx/lib``, so both
keep that folder; the C++ headers and CMake files (``include``, ``share``, ``lib/cmake``) stay out.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hiddenimports = collect_submodules("mlx")
binaries = collect_dynamic_libs("mlx")
datas = collect_data_files("mlx", excludes=["include", "share", "lib/cmake"])
