# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

import importlib.util

from packaging.version import Version
from PyInstaller.config import CONF

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
    app). Returns the hiddenimports."""
    hidden = list(_MODULES.values())  # the reference too: nothing else names helab.convert.backends
    optional = {
        "cython": ["helab.convert.backends.cython._kernel"],
        "rust": ["helab_convert_rs", "helab_convert_rs.helab_convert_rs"],
        # numba's own hook adds llvmlite and its LLVM library.
        "numba": ["numba", "numba.core.caching", "helab.convert.backends.numba_kernels"],
        "mlx": ["mlx", "mlx.core"],
    }
    for backend, modules in optional.items():  # modules[0]: the one that may be missing
        try:
            found = importlib.util.find_spec(modules[0]) is not None
        except ImportError:
            found = False
        if not found:
            print(f"HeLab.spec: the {backend} backend ships without {modules[0]} (not in this Python)")
            continue
        hidden += modules
    return hidden  # mlx's libraries and Metal kernels: native/pyinstaller-hooks/hook-mlx.py


backend_imports = converter_backends()

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
    binaries=[],
    datas=[(str(ROOT / 'helab/resources/menu-right.svg'), 'helab/resources'),
           # The window's icon, which HelabMainWindow looks for beside the package (R-12).
           (str(ROOT / 'helab/resources/ai-icon.icns'), 'helab/resources'),
           # The built-in detector profiles as JSON (A10.3; read by ``profile.builtin_files``).
           (str(ROOT / 'helab/convert/builtin_profiles/*.json'), 'helab/convert/builtin_profiles'),
           (str(metadata_path), 'helab')],
    hiddenimports=["helab.io_helper"] + backend_imports,
    hookspath=[str(ROOT / 'native/pyinstaller-hooks')],
    hooksconfig={},
    runtime_hooks=[],
    # Cython builds the cython backend's kernel (native/build.py); only optional imports in
    # pyarrow's conftest, scipy's test utilities and pydantic.v1 would collect it (5.6 MB).
    excludes=["Cython", "cython", "pyximport"],
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
