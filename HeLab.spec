# -*- mode: python ; coding: utf-8 -*-

import re
import os
import subprocess

# Function to extract version from setup.py
def get_version():
    with open('setup.py', 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'version\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return match.group(1)
    return '0.0.0'  # Default version if not found

def get_git_commit_hash_old():
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.STDOUT
        ).decode('utf-8').strip()
        return commit_hash
    except subprocess.CalledProcessError as e:
        print(f"Git command failed with error: {e.output.decode('utf-8')}")
        return 'unknown'
    except Exception as e:
        print(f"Error obtaining git commit hash: {e}")
        return 'unknown'

def get_git_commit_hash():
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.STDOUT
        ).decode('utf-8').strip()
        return commit_hash[:8]  # Return only the first 8 characters
    except Exception:
        return 'unknown'

APP_VERSION = get_version()
APP_COMMIT_HASH = get_git_commit_hash()


a = Analysis(
    ['helab/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='HeLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='HeLab.app',
    icon='helab/resources/ai-icon.icns',
    bundle_identifier='au.edu.anu.he-bec-lab',
    info_plist={
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleVersion': APP_COMMIT_HASH,
        'NSHumanReadableCopyright': 'Tony Xintong Yan © 2024',
    },
)
