"""The helper's event contract (``helab/io_ops/events.py``) matches the code on both sides.

Every kind the helper sends is declared, every declared kind is sent, and every kind the app
matches on is one the helper sends or one the app makes itself (``GUI_KINDS``): a typo on
either side fails here. Strict type checking then checks each event's fields at its ``send``.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, get_args, get_type_hints

from helab.io_ops import events

ROOT = Path(__file__).resolve().parent.parent
HELPER = [*sorted((ROOT / "helab" / "io_ops").glob("*.py")), ROOT / "helab" / "io_helper.py"]
# Not about helper events: a scan outcome's ``kind`` (its saved history).
NOT_GUI = {"scan_history.py"}
GUI = [path for path in [ROOT / "helab" / "main.py", *sorted((ROOT / "helab" / "utils").glob("*.py")),
                         *sorted((ROOT / "helab" / "views").glob("*.py")),
                         *sorted((ROOT / "helab" / "models").glob("*.py"))]
       if path.name not in NOT_GUI]

# Dicts with a "kind" key in helper code that aren't events: (file, the kind's source text).
NOT_EVENTS = {
    ("scanning.py", "'success'"),  # A basic scan's outcome for its saved history (``write_outcome``).
    ("loading.py", "file_kinds.TXY.name"),  # A cached dataset's ``info``: its file kind.
}

# Kinds the app makes itself (``IOService``; ``FolderCache`` also makes ``queued`` and ``cancelled``), never sent by a helper.
GUI_KINDS = {
    "queued",  # A request waiting for a slot, or requeued for a retry.
    "started",  # Its helper started.
    "cancelled",  # Cancelled before or while it ran.
    "exit",  # Its helper exited (the reader thread's last event).
}


def kind_values(node: ast.expr) -> Iterator[str] | None:
    """The kind names an expression can be: a string, or a conditional between strings."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return iter([node.value])
    if isinstance(node, ast.IfExp):
        body, orelse = kind_values(node.body), kind_values(node.orelse)
        if body is not None and orelse is not None:
            return iter([*body, *orelse])
    return None


def produced(files: list[Path]) -> dict[str, set[str]]:
    """Every kind put in a dict literal (``{"kind": …}``), in ``dict(kind=…)`` or by
    ``event["kind"] = …``, by file; an unrecognised kind expression is listed by its source."""
    found: dict[str, set[str]] = {}
    for path in files:
        kinds = found.setdefault(path.name, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            values: list[ast.expr] = []
            if isinstance(node, ast.Dict):
                values = [value for key, value in zip(node.keys, node.values)
                          if isinstance(key, ast.Constant) and key.value == "kind"]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
                values = [keyword.value for keyword in node.keywords if keyword.arg == "kind"]
            elif isinstance(node, ast.Assign):
                values = [node.value for target in node.targets if isinstance(target, ast.Subscript)
                          and isinstance(target.slice, ast.Constant) and target.slice.value == "kind"]
            for value in values:
                if (path.name, ast.unparse(value)) in NOT_EVENTS:
                    continue
                names = kind_values(value)
                kinds.update(names if names is not None else [f"<{ast.unparse(value)}>"])
    return found


def is_kind_lookup(node: ast.expr) -> bool:
    """``x["kind"]`` or ``x.get("kind")``."""
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "kind"
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == "kind")


def matched(files: list[Path]) -> dict[str, set[str]]:
    """Every kind the app compares an event's kind with (``==``, ``!=``, ``in``, ``not in``), by
    file: on ``x["kind"]``, ``x.get("kind")`` or a name a function assigned one of those to."""
    found: dict[str, set[str]] = {}
    for path in files:
        kinds = found.setdefault(path.name, set())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.Lambda))]:
            names: set[str] = set()
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        pairs = (zip(target.elts, node.value.elts) if isinstance(target, ast.Tuple)
                                 and isinstance(node.value, ast.Tuple) else [(target, node.value)])
                        names.update(name.id for name, value in pairs
                                     if isinstance(name, ast.Name) and is_kind_lookup(value))
            for node in ast.walk(function):
                if not isinstance(node, ast.Compare):
                    continue
                for left, op, right in zip([node.left, *node.comparators], node.ops, node.comparators):
                    if not isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                        continue
                    for side, other in ((left, right), (right, left)):
                        if is_kind_lookup(side) or isinstance(side, ast.Name) and side.id in names:
                            options = other.elts if isinstance(other, (ast.Tuple, ast.List, ast.Set)) else [other]
                            kinds.update(str(option.value) for option in options
                                         if isinstance(option, ast.Constant) and isinstance(option.value, str))
    return found


def test_kinds_are_the_unions_kinds() -> None:
    declared: set[str] = set()
    for shape in get_args(events.HelperEvent):
        declared.update(get_args(get_type_hints(shape)["kind"]))
    assert declared == events.KINDS


def test_every_kind_the_helper_sends_is_declared_and_every_declared_kind_is_sent() -> None:
    sent = set().union(*produced(HELPER).values())
    assert sent - events.KINDS == set(), "Sent but not in helab/io_ops/events.py"
    assert events.KINDS - sent == set(), "Declared but never sent"


def test_every_kind_the_app_matches_on_is_sent_or_its_own() -> None:
    unknown = {name: sorted(kinds - events.KINDS - GUI_KINDS) for name, kinds in matched(GUI).items()}
    assert {name: kinds for name, kinds in unknown.items() if kinds} == {}
    # (The scan finds the app's matching at all.)
    assert {"loaded", "entries", "status", "done", "error", "cancelled"} <= matched(GUI)["folder_cache.py"]


def test_the_apps_own_kinds_are_made_by_the_app_and_never_by_a_helper() -> None:
    made = set().union(*produced(GUI).values())
    assert GUI_KINDS <= made
    assert GUI_KINDS & events.KINDS == set()
