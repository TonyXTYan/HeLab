"""Every bundled analysis has a stable ``analysis_id`` and a ``version`` (``scripts/base.py``),
and no two share an id: results and their records are keyed by it, so a copied script that
kept its original's id would mix the two plots' results."""
from __future__ import annotations

from collections import Counter

from helab.scripts import dld, standard
from helab.scripts.scripts_manager import ScriptsManager


def test_bundled_analyses_have_unique_ids_and_versions() -> None:
    manager = ScriptsManager()
    for module in (*standard.MODULES, *dld.MODULES):
        manager.load_module(module)
    metadata = [meta for group in manager.get_groups() for meta in manager.get_scripts_in_group(group)]
    assert len(metadata) >= len(standard.MODULES) + len(dld.MODULES)
    missing = [meta.name for meta in metadata if not (meta.analysis_id and meta.version)]
    assert missing == [], f"Without analysis_id or version: {missing}"
    ids = Counter(meta.analysis_id for meta in metadata)
    assert [analysis_id for analysis_id, count in ids.items() if count > 1] == []
