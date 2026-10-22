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
        assert (ROOT / source).is_file(), source
