"""What the build ships of the TXY converter's backends (A9.1, Q11.2): numpy (the default), cython
and the reference. Numba, mlx and rust leave the requirements, the lock, ``HeLab.spec`` and CI's
required set, while their code stays (Q11.3), read here without installing or building anything."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import re
from types import ModuleType

from helab.convert.reconstruct import _MODULES

ROOT = Path(__file__).resolve().parents[1]
UNSHIPPED = ("numba", "llvmlite", "mlx", "mlx-metal", "maturin")


def requirement_names(path: Path) -> set[str]:
    """The package names a requirements file or lock lists (lower case, ``_`` as ``-``)."""
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def spec_list(name: str) -> list[str]:
    """A list of string literals ``HeLab.spec`` assigns to ``name`` at the top, or passes to
    ``Analysis`` as that keyword (a ``*NAME`` in it is that top-level list)."""
    tree = ast.parse((ROOT / "HeLab.spec").read_text(encoding="utf-8"))
    lists = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
             for target in node.targets if isinstance(target, ast.Name) and isinstance(node.value, ast.List)}
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "Analysis")
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    value = keywords.get(name, lists.get(name))
    assert isinstance(value, ast.List), name
    found: list[str] = []
    for element in value.elts:
        if isinstance(element, ast.Starred) and isinstance(element.value, ast.Name):
            found += spec_list(element.value.id)
        else:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), ast.dump(element)
            found.append(element.value)
    return found


def build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("native_build", ROOT / "native" / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_requirements_and_the_lock_have_cython_and_none_of_the_unshipped_backends() -> None:
    for file in ("requirements.txt", "requirements.lock"):
        names = requirement_names(ROOT / file)
        assert "cython" in names and "numpy" in names, file
        assert not names & set(UNSHIPPED), (file, sorted(names & set(UNSHIPPED)))


def test_the_spec_leaves_the_unshipped_backends_packages_out_even_when_installed() -> None:
    """pandas and scipy import numba optionally: in a Python that has it, only ``excludes`` keeps
    its 127 MB out of the app."""
    excludes = spec_list("excludes")
    assert {"numba", "llvmlite", "mlx", "helab_convert_rs"} <= set(excludes)
    assert {"Cython", "cython", "pyximport"} <= set(excludes)  # (the build tool, never the kernel)
    assert spec_list("hookspath") == []  # (mlx's hook went with mlx)


def test_ci_builds_and_requires_cython_only_and_rust_is_opt_in() -> None:
    build = build_script()
    assert build.CI_REQUIRED == ("cython",)
    assert build.DEFAULT_TARGETS == ("cython",)
    assert "rust" in build.TARGETS  # (python native/build.py --only rust, for a developer)
    workflows = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / ".github" / "workflows").glob("*.yml"))
    # (The tests job's guard still names every backend package: it fails if one is installed.)
    assert "--only rust" not in workflows and "--prebuilt" not in workflows


def test_the_unshipped_backends_code_stays() -> None:
    """Q11.3: a developer who installs numba, mlx or maturin can still use that backend."""
    assert {"reference", "numpy", "cython", "numba", "mlx", "rust"} <= set(_MODULES)
    for module in _MODULES.values():
        assert importlib.util.find_spec(module) is not None, module
    assert (ROOT / "native" / "rust" / "Cargo.toml").is_file()
