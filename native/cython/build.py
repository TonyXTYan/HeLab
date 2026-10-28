"""Build the ``cython`` converter backend's kernel into the source tree.

    python native/cython/build.py [--force]

Cythonizes ``native/cython/_kernel.pyx`` and compiles it in place as
``helab/convert/backends/cython/_kernel<EXT_SUFFIX>`` (gitignored), with the intermediate C and
objects under ``native/cython/build/`` (gitignored). Needs ``Cython`` and ``setuptools`` in the
running Python and a C compiler (Xcode's clang on macOS, GCC or clang on Linux, MSVC Build Tools
on Windows); the built module needs neither Cython nor a compiler, only NumPy.

Floating-point contraction (FMA) and fast-math stay off on every compiler, so the kernel's doubles
are the reference's bit for bit: ``-ffp-contract=off`` matters on arm64 and on GCC (whose GNU-mode
default is ``fast``); MSVC's ``/fp:precise`` doesn't contract.

Not wired into ``pyproject.toml``, ``setup.py`` or ``HeLab.spec`` (stage 4's packaging floor does
that).
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "_kernel.pyx"
BUILD = HERE / "build"
MODULE = "helab.convert.backends.cython._kernel"

UNIX_FLAGS = ["-O3", "-ffp-contract=off", "-fno-fast-math"]
MSVC_FLAGS = ["/O2", "/fp:precise"]
DIRECTIVES = {"language_level": "3", "boundscheck": False, "wraparound": False, "cdivision": True,
              "initializedcheck": False}


def source_sha256() -> str:
    return hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="rebuild even when up to date")
    args = parser.parse_args()

    from Cython.Build import cythonize
    from setuptools import Distribution, Extension

    BUILD.mkdir(exist_ok=True)
    # The source's hash, compiled in (SOURCE_SHA256) so the backend can tell a stale binary.
    header = BUILD / "_kernel_build.h"
    text = f'#define KERNEL_SOURCE_SHA256 "{source_sha256()}"\n'
    if not header.exists() or header.read_text() != text:
        header.write_text(text)
    flags = MSVC_FLAGS if sys.platform == "win32" else UNIX_FLAGS
    extension = Extension(MODULE, [str(SOURCE.relative_to(ROOT))], include_dirs=[str(BUILD)],
                          extra_compile_args=flags)
    modules = cythonize([extension], build_dir=str(BUILD.relative_to(ROOT)), compiler_directives=DIRECTIVES,
                        force=args.force, quiet=True)
    distribution = Distribution({"name": "helab-convert-cython", "ext_modules": modules,
                                 "options": {"build": {"build_base": str(BUILD)}}})  # not ./build
    command = distribution.get_command_obj("build_ext")
    command.inplace = True
    command.force = args.force
    command.ensure_finalized()
    command.run()
    print(f"built {Path(command.get_ext_fullpath(MODULE)).resolve().relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)  # build_ext --inplace places the module by its dotted name, from here
    sys.exit(main())
