# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

import importlib.util

from packaging.version import Version
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT))
from helab._version import __version__
from helab.build_info import BUILD_INFO_FILENAME, write_build_info
from helab.convert.reconstruct import _MODULES


def converter_backends():
    """The TXY converter's backends (Q9.2: every one ships for now; A9.1 drops the unused ones).
    Each is imported by name (``reconstruct._MODULES``) and imports its package through importlib,
    so the analysis sees none of them. A compiled extension or package missing from this Python
    leaves that backend out of the app, unavailable there with the reason (``python
    native/build.py`` builds cython's and rust's; ``native/check_build.py --frozen`` checks the
    app). Returns (hiddenimports, binaries, datas)."""
    hidden = list(_MODULES.values())  # the reference too: nothing else names helab.convert.backends
    binaries, datas = [], []
    optional = {
        "cython": ["helab.convert.backends.cython._kernel"],
        "rust": ["helab_convert_rs", "helab_convert_rs.helab_convert_rs"],
        # numba's own hook adds llvmlite and its LLVM library.
        "numba": ["helab.convert.backends.numba_kernels", "numba", "numba.core.caching"],
        "mlx": ["mlx", "mlx.core"],
    }
    for backend, modules in optional.items():
        try:
            found = importlib.util.find_spec(modules[0]) is not None
        except ImportError:
            found = False
        if not found:
            print(f"HeLab.spec: the {backend} backend ships without {modules[0]} (not in this Python)")
            continue
        hidden += modules
    if "mlx" in hidden:
        hidden += collect_submodules("mlx")
        binaries += collect_dynamic_libs("mlx")  # libmlx, beside its Metal library (mlx/lib)
        datas += collect_data_files("mlx", excludes=["include", "share", "lib/cmake"])  # not the C++ headers
    return hidden, binaries, datas


backend_imports, backend_binaries, backend_datas = converter_backends()

metadata_path = Path(CONF['workpath']) / BUILD_INFO_FILENAME
build_info = write_build_info(ROOT, metadata_path)
APP_VERSION = __version__
# Apple's machine-readable fields use numeric components; the full PEP 440
# version and Git commit remain in separate fields and the app's About dialog.
release = Version(APP_VERSION).release
BUNDLE_VERSION = '.'.join(str(value) for value in (release + (0, 0))[:3])


a = Analysis(
    [str(ROOT / 'helab/main.py')],
    pathex=[str(ROOT)],
    binaries=backend_binaries,
    datas=[(str(ROOT / 'helab/resources/menu-right.svg'), 'helab/resources'),
           # The window's icon, which HelabMainWindow looks for beside the package (R-12).
           (str(ROOT / 'helab/resources/ai-icon.icns'), 'helab/resources'),
           (str(metadata_path), 'helab')] + backend_datas,
    hiddenimports=["helab.io_helper"] + backend_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HeLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HeLab',
)
app = BUNDLE(
    coll,
    name='HeLab.app',
    icon=str(ROOT / 'helab/resources/ai-icon.icns'),
    bundle_identifier='au.edu.anu.he-bec-lab',
    info_plist={
        'CFBundleShortVersionString': BUNDLE_VERSION,
        'CFBundleVersion': BUNDLE_VERSION,
        'HeLabVersion': APP_VERSION,
        'HeLabCommit': build_info.commit,
        'HeLabBuildDate': build_info.built_at,
        'HeLabBuildRef': build_info.build_ref,
        'HeLabBranch': build_info.branch,
        'CFBundleName': 'HeLab',
        'CFBundleDisplayName': 'HeLab',
        'CFBundleExecutable': 'HeLab',
        'NSHumanReadableCopyright': 'Tony Xintong Yan © 2024',
    },
)
