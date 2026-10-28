"""The packaged app bundles the files HeLab looks up beside its package (R-12): HeLab.spec's
``datas``, read without running PyInstaller."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def spec_datas() -> set[tuple[str, str]]:
    """``Analysis(datas=[(str(ROOT / '<source>'), '<folder in the bundle>'), …])``, the plain entries."""
    tree = ast.parse((ROOT / "HeLab.spec").read_text(encoding="utf-8"))
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "Analysis")
    datas = next(keyword.value for keyword in call.keywords if keyword.arg == "datas")
    assert isinstance(datas, ast.List)
    found = set()
    for entry in datas.elts:
        assert isinstance(entry, ast.Tuple)
        source, target = entry.elts
        if (isinstance(source, ast.Call) and isinstance(source.args[0], ast.BinOp)
                and isinstance(source.args[0].right, ast.Constant) and isinstance(target, ast.Constant)):
            found.add((str(source.args[0].right.value), str(target.value)))
    return found


def test_the_window_icon_is_bundled_where_the_window_looks_for_it() -> None:
    # HelabMainWindow looks in helab/resources beside the package (R-12): the bundle's helab/resources.
    assert ("helab/resources/ai-icon.icns", "helab/resources") in spec_datas()
    assert (ROOT / "helab" / "resources" / "ai-icon.icns").is_file()


def test_every_bundled_file_exists() -> None:
    for source, _ in spec_datas():
        if any(mark in source for mark in "*?["):
            # A glob (PyInstaller takes one): it must match files.
            matches = sorted(ROOT.glob(source))
            assert matches and all(path.is_file() for path in matches), source
        else:
            assert (ROOT / source).is_file(), source


def test_the_builtin_profiles_are_bundled_and_packaged() -> None:
    """``profile.builtin_files`` reads them from the package (A10.3): the frozen app's and a wheel's."""
    from fnmatch import fnmatch
    assert ("helab/convert/builtin_profiles/*.json", "helab/convert/builtin_profiles") in spec_datas()
    files = sorted((ROOT / "helab" / "convert" / "builtin_profiles").glob("*.json"))
    assert len(files) == 5
    patterns = setup_package_data()["helab.convert"]
    assert all(any(fnmatch(f"builtin_profiles/{path.name}", pattern) for pattern in patterns) for path in files)


def setup_package_data() -> dict[str, list[str]]:
    """setup.py's ``setup(package_data={...})``, read without running it."""
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "setup")
    data = next(keyword.value for keyword in call.keywords if keyword.arg == "package_data")
    assert isinstance(data, ast.Dict)
    found: dict[str, list[str]] = {}
    for key, value in zip(data.keys, data.values):
        if isinstance(key, ast.Constant) and isinstance(value, ast.List):
            found[str(key.value)] = [str(item.value) for item in value.elts if isinstance(item, ast.Constant)]
    return found


def test_a_wheel_carries_the_window_icon_too() -> None:
    """``pip install`` (a wheel) as well as the packaged app: the icon is package data of helab.resources."""
    from fnmatch import fnmatch
    patterns = setup_package_data()["helab.resources"]
    assert any(fnmatch("ai-icon.icns", pattern) for pattern in patterns)
    assert not any(fnmatch("Beatunes.icns", pattern) for pattern in patterns)  # (Unused: not shipped.)
