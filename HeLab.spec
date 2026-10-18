# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from packaging.version import Version
from PyInstaller.config import CONF

ROOT = Path(SPECPATH).resolve()
sys.path.insert(0, str(ROOT))
from helab._version import __version__
from helab.build_info import BUILD_INFO_FILENAME, write_build_info

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
           (str(metadata_path), 'helab')],
    hiddenimports=["helab.io_helper"],
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
