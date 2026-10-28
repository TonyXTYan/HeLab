"""HeLab's modules import names explicitly (R-15): a star import hides where a name comes from and
takes along whatever the other module imported. The legacy Plotly figures (outside the type
checks) are left as the lab wrote them."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "helab" / "scripts" / "legacy_plotly"


def test_no_module_imports_with_a_star() -> None:
    starred = []
    for file in sorted((ROOT / "helab").rglob("*.py")):
        if LEGACY in file.parents:
            continue
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                starred.append(f"{file.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not starred
