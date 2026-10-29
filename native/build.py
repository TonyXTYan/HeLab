"""Build the TXY converter's compiled backends for the running Python.

    python native/build.py [--force]          # cython's kernel, the compiled backend that ships
    python native/build.py --only rust        # rust's module, for a developer trying it
    python native/build.py --ci

- ``cython``: ``native/cython/build.py`` compiles ``_kernel.pyx`` in place as
  ``helab/convert/backends/cython/_kernel<EXT_SUFFIX>`` (needs Cython, setuptools and a C
  compiler: Xcode's clang, GCC or clang, MSVC from VS 2022 17.0 or later).
- ``rust``: maturin builds ``native/rust/`` as an abi3 wheel (``helab-convert-rs``, one per OS and
  architecture for CPython 3.11 and later) and pip installs it into this Python (needs maturin,
  which isn't in the requirements, and a Rust toolchain; MSVC's on Windows). Opt-in only: rust
  doesn't ship (A9.1, Q11.2), CI doesn't build it, and ``HeLab.spec`` leaves its module out.

Cython's kernel is part of HeLab's build, not of ``pip install -e .``: HeLab and its tests work
without it, so a lab PC with no compiler can still install it. CI runs ``--ci`` in the converter
backends job and before PyInstaller (``.github/workflows/``): the kernel built,
``HELAB_REQUIRE_BACKENDS=cython`` set for the later steps, and ``native/check_build.py`` checking
every backend against the reference. Nothing it builds is committed. The flags that keep the
doubles exact (no FMA contraction, no fast-math, no ``target-cpu=native``) are in the two builds'
own files.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUST = HERE / "rust" / "Cargo.toml"
TARGETS = ("cython", "rust")
DEFAULT_TARGETS = ("cython",)  # what ships (Q11.2)
CI_REQUIRED = ("cython",)


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def build_cython(force: bool) -> None:
    run([sys.executable, str(HERE / "cython" / "build.py"), *(["--force"] if force else [])])


def rust_wheel(out: Path) -> Path:
    """maturin's abi3 wheel of ``native/rust/``, built into ``out``."""
    if "target-cpu" in os.environ.get("RUSTFLAGS", ""):
        # The lab's Windows PC is a Sandy Bridge (no AVX2): a wheel for this CPU only won't load there.
        raise SystemExit("RUSTFLAGS sets target-cpu; build for the default target instead")
    if importlib.util.find_spec("maturin") is None:
        raise SystemExit("maturin isn't installed (rust doesn't ship, so it isn't in the requirements): "
                         "install it into this Python, with a Rust toolchain, to build the rust backend")
    # maturin's own entry point is a binary beside this Python's scripts; the module form finds it
    # from any shell, activated or not.
    run([sys.executable, "-m", "maturin", "build", "--release", "--locked", "-m", str(RUST), "--out", str(out),
         "--interpreter", sys.executable])
    wheels = sorted(out.glob("helab_convert_rs-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one helab_convert_rs wheel in {out}, found {[wheel.name for wheel in wheels]}")
    return wheels[0]


def install_wheel(wheel: Path) -> None:
    install = [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)]
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode != 0:
        uv = shutil.which("uv")  # a venv made by uv without --seed has no pip
        if uv is None:
            raise SystemExit("neither pip nor uv can install the rust wheel into this Python")
        install = [uv, "pip", "install", "--python", sys.executable, "--no-deps", "--reinstall", str(wheel)]
    run(install)


def build_rust() -> None:
    with tempfile.TemporaryDirectory(prefix="helab-rust-wheel-") as out:
        install_wheel(rust_wheel(Path(out)))


def ci() -> None:
    """CI: build cython's kernel, require it (``HELAB_REQUIRE_BACKENDS`` for the later steps, as the
    tests read it) and check every backend against the reference (the unshipped ones are
    unavailable there, which passes)."""
    build_cython(force=True)
    required = ",".join(CI_REQUIRED)
    print(f"Required converter backends: {required}", flush=True)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as file:
            file.write(f"HELAB_REQUIRE_BACKENDS={required}\n")
    run([sys.executable, str(HERE / "check_build.py"), "--require", required])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=TARGETS, action="append",
                        help="build this one (repeatable; default: cython, the one that ships)")
    parser.add_argument("--force", action="store_true", help="rebuild the cython kernel even when up to date")
    parser.add_argument("--ci", action="store_true",
                        help="CI: build cython, set HELAB_REQUIRE_BACKENDS in $GITHUB_ENV, run check_build.py")
    args = parser.parse_args()
    if args.ci:
        ci()
        return 0
    targets = args.only or list(DEFAULT_TARGETS)
    if "cython" in targets:
        build_cython(args.force)
    if "rust" in targets:
        build_rust()  # cargo rebuilds only what changed
    return 0


if __name__ == "__main__":
    sys.exit(main())
