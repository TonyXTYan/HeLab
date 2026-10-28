"""Load Scripts… for a user's folder (``ScriptsManager.load_directory``): what is loaded and
grouped, what loading the folder again replaces, and what a broken file does to the rest.

tests/test_script_system.py covers one working script in the Scripts panel; these cover the
manager itself with scripts written into ``tmp_path``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from helab.scripts import scripts_manager
from helab.scripts.base import DatasetAnalysis
from helab.scripts.scripts_manager import ScriptLoadError, ScriptsManager

HEADER = '''
from typing import Any, List, Optional
from PyQt6.QtWidgets import QLabel, QWidget
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.scripts.base import DatasetAnalysis, HelabAnalysisScript, ScriptMetadata
'''


def analysis(cls: str = "Counts", name: str = "Counts", group: str = "Lab", file_path: str = "__file__",
             base: str = "DatasetAnalysis", body: str = "") -> str:
    """A DatasetAnalysis class's source (no imports): ``file_path`` is a Python expression."""
    return f'''
class {cls}({base}):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata({name!r}, "test", {group!r}, {file_path}, "lab.{cls.lower()}", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return context.view.event_count

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(str(result.data), parent)
{body}'''


def write(folder: Path, name: str, *classes: str, header: str = HEADER) -> Path:
    path = folder / name
    path.write_text(header + "".join(classes))
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def names(manager: ScriptsManager, group: str) -> list[str]:
    return sorted(metadata.name for metadata in manager.get_scripts_in_group(group))


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    made = tmp_path / "lab_scripts"
    made.mkdir()
    return made


def test_a_dataset_analysis_is_loaded_and_grouped(folder: Path) -> None:
    path = write(folder, "counts.py", analysis())
    (folder / "notes.txt").write_text("not a script")
    (folder / "__pycache__").mkdir()
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    assert manager.get_groups() == ["Lab"]
    (metadata,) = manager.get_scripts_in_group("Lab")
    script_id = f"{path}::Counts"
    assert metadata.script_id == script_id and metadata.file_path == str(path)
    assert (metadata.name, metadata.group, metadata.analysis_id, metadata.version) == ("Counts", "Lab", "lab.counts", "1")
    assert metadata.file_hash == sha256(path)
    assert manager.get_script_metadata(script_id) is metadata
    script_class = manager.get_script(script_id)
    assert script_class is not None and issubclass(script_class, DatasetAnalysis)
    assert script_class().get_actions() == ["Plot"]
    # Loaded from its file, not imported: no module is left in sys.modules.
    assert script_class.__module__ == "helab.scripts.dynamic.counts.py"
    assert script_class.__module__ not in sys.modules
    # Unknown ids and groups.
    assert manager.get_script("nope") is None and manager.get_script_metadata("nope") is None
    assert manager.get_scripts_in_group("Nope") == []


def test_classes_and_files_of_one_group_merge(folder: Path) -> None:
    write(folder, "two.py", analysis("First", "First"), analysis("Second", "Second"))
    write(folder, "third.py", analysis("Third", "Third"))
    write(folder, "other.py", analysis("Fourth", "Fourth", group="Other"))
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    assert sorted(manager.get_groups()) == ["Lab", "Other"]
    assert names(manager, "Lab") == ["First", "Second", "Third"]
    assert names(manager, "Other") == ["Fourth"]
    # The two classes of one file share its path and hash, each with its own id.
    first, second = sorted((m for m in manager.get_scripts_in_group("Lab") if m.name != "Third"),
                           key=lambda m: m.name)
    assert first.file_path == second.file_path == str(folder / "two.py")
    assert first.file_hash == second.file_hash == sha256(folder / "two.py")
    assert first.script_id != second.script_id


def test_loading_the_folder_again_replaces_its_scripts(folder: Path) -> None:
    kept = write(folder, "kept.py", analysis("Kept", "Kept"))
    write(folder, "gone.py", analysis("Gone", "Gone", group="Old"))
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    old_class = manager.get_script(f"{kept}::Kept")
    old_hash = sha256(kept)
    # The file is edited (new name and group), one is deleted and another added.
    write(folder, "kept.py", analysis("Kept", "Kept, edited", group="New"))
    (folder / "gone.py").unlink()
    write(folder, "added.py", analysis("Added", "Added"))
    # The same folder, spelled another way.
    manager.load_directory(str(folder) + os.sep + "." + os.sep)
    assert sorted(manager.get_groups()) == ["Lab", "New"]  # "Old" emptied and went.
    assert names(manager, "New") == ["Kept, edited"] and names(manager, "Lab") == ["Added"]
    assert manager.get_script(f"{folder / 'gone.py'}::Gone") is None
    metadata = manager.get_script_metadata(f"{kept}::Kept")
    assert metadata is not None and metadata.file_hash == sha256(kept) != old_hash
    new_class = manager.get_script(f"{kept}::Kept")
    assert new_class is not None and new_class is not old_class  # The edited code runs.
    # Loading it a third time, unchanged: still one of each.
    manager.load_directory(str(folder))
    assert len(manager.get_scripts_in_group("New")) == len(manager.get_scripts_in_group("Lab")) == 1


def test_another_folders_scripts_stay(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    write(first, "plot.py", analysis("Plot", "Plot"))
    write(second, "plot.py", analysis("Plot", "Plot"))  # Same file and class names.
    manager = ScriptsManager()
    manager.load_directory(str(first))
    manager.load_directory(str(second))
    ids = sorted(metadata.script_id for metadata in manager.get_scripts_in_group("Lab"))
    assert ids == [f"{first / 'plot.py'}::Plot", f"{second / 'plot.py'}::Plot"]
    (first / "plot.py").unlink()
    manager.load_directory(str(first))
    (metadata,) = manager.get_scripts_in_group("Lab")
    assert metadata.script_id == f"{second / 'plot.py'}::Plot"


def test_a_file_is_hashed_as_it_was_before_it_ran(folder: Path) -> None:
    """The hash identifies the code that made a result: a script that changes its own file when
    it runs keeps the hash of what ran."""
    path = write(folder, "rewrites.py", analysis(), "\nwith open(__file__, 'a') as handle:\n"
                 "    handle.write('# changed when it ran\\n')\n")
    before = sha256(path)
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    (metadata,) = manager.get_scripts_in_group("Lab")
    assert metadata.file_hash == before != sha256(path)


BROKEN: dict[str, tuple[str, str]] = {
    "syntax error": ("def broken(:\n", "Failed to load script: "),
    "import error": ("import helab_no_such_module\n", "No module named 'helab_no_such_module'"),
    "error at import": ("raise ValueError('lab script failed')\n", "lab script failed"),
    "no script class": ("def helper() -> int:\n    return 1\n", "No HelabAnalysisScript subclass found"),
    # A bundled analysis imported into the file is not the file's own script.
    "only an imported script": ("from helab.scripts.dld.shot_trends import ShotTrends\n",
                                "No HelabAnalysisScript subclass found"),
    "no name": (analysis(name=""), "Script metadata missing name or group"),
    "no group": (analysis(group=""), "Script metadata missing name or group"),
    "metadata raises": (analysis(body="\n    def get_metadata(self) -> ScriptMetadata:\n"
                                      "        raise KeyError('metadata broke')\n"), "metadata broke"),
    "constructor needs arguments": (analysis(body="\n    def __init__(self, size: int) -> None:\n"
                                                  "        self.size = size\n"), "missing 1 required positional"),
    "not a file": ("", "Failed to load script: "),
    # A script that forgot a method is abstract: the error names it and what it lacks.
    "a method missing": (analysis().replace("    def render", "    def draw_it"),
                         "No complete script: abstract Counts (missing render)"),
}


@pytest.mark.parametrize("kind", sorted(BROKEN))
def test_a_broken_file_is_skipped_and_the_rest_load(folder: Path, kind: str,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    source, reason = BROKEN[kind]
    write(folder, "good.py", analysis("Good", "Good"))
    if kind == "not a file":
        broken = folder / "broken.py"
        broken.mkdir()  # A folder whose name ends in .py.
    else:
        broken = write(folder, "broken.py", source)
    manager = ScriptsManager()
    with caplog.at_level(logging.WARNING):
        manager.load_directory(str(folder))
    assert manager.get_groups() == ["Lab"] and names(manager, "Lab") == ["Good"]
    (warning,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    message = warning.getMessage()
    assert message.startswith(f"Failed to load script {broken}: Failed to load script: ") and reason in message


def test_a_file_with_a_bad_class_keeps_the_good_ones_found_before_it(folder: Path) -> None:
    """Current behaviour, for the record: classes are taken in name order and the first bad one
    ends the file, so a good class named before it stays loaded (though the file is reported as
    failed) and one named after it doesn't."""
    write(folder, "mixed.py", analysis("Alpha", "Alpha"), analysis("Beta", "Beta", group=""),
          analysis("Gamma", "Gamma"))
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    assert names(manager, "Lab") == ["Alpha"]


def test_an_unexpected_error_from_one_file_is_logged_and_the_rest_load(
        folder: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    write(folder, "good.py", analysis("Good", "Good"))
    odd = write(folder, "odd.py", analysis("Odd", "Odd"))
    manager = ScriptsManager()
    load = manager._load_script_file

    def flaky(file_path: str) -> None:
        if file_path == str(odd):
            raise RuntimeError("disk went away")
        load(file_path)

    monkeypatch.setattr(manager, "_load_script_file", flaky)
    with caplog.at_level(logging.ERROR):
        manager.load_directory(str(folder))
    assert names(manager, "Lab") == ["Good"]
    assert any(record.levelno == logging.ERROR and record.getMessage() ==
               f"Unexpected error loading {odd}: disk went away" for record in caplog.records)


def test_a_file_without_a_module_spec_is_skipped(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(folder, "counts.py", analysis())
    no_spec = SimpleNamespace(util=SimpleNamespace(spec_from_file_location=lambda *args, **kwargs: None))
    monkeypatch.setattr(scripts_manager, "importlib", no_spec)
    manager = ScriptsManager()
    with pytest.raises(ScriptLoadError, match="Could not create module spec"):
        manager._load_script_file(str(path))
    manager.load_directory(str(folder))  # Logged and skipped.
    assert manager.get_groups() == []


def test_only_a_folder_can_be_loaded(tmp_path: Path) -> None:
    script = write(tmp_path, "counts.py", analysis())
    manager = ScriptsManager()
    for path in (script, tmp_path / "missing"):
        with pytest.raises(ValueError, match="Not a directory"):
            manager.load_directory(str(path))
    assert manager.get_groups() == []


def module_of(name: str, file_path: str, source: str) -> ModuleType:
    """A module made from ``source``, as an import would make it."""
    module = ModuleType(name)
    module.__file__ = file_path
    exec(compile(source, file_path, "exec"), module.__dict__)
    return module


def test_load_module_registers_an_imported_modules_scripts(tmp_path: Path) -> None:
    path = write(tmp_path, "lab_module.py", analysis())
    module = module_of("lab_module", str(path), path.read_text())
    manager = ScriptsManager()
    manager.load_module(module)
    (metadata,) = manager.get_scripts_in_group("Lab")
    assert metadata.script_id == f"{path}::Counts" and metadata.file_hash == sha256(path)
    # A module without scripts is an error the caller sees.
    empty = module_of("lab_empty", str(tmp_path / "lab_empty.py"), "VALUE = 1\n")
    with pytest.raises(ScriptLoadError, match="No HelabAnalysisScript subclass found"):
        manager.load_module(empty)
    # A module without a file: its name stands for the path and its hash is unknown.
    fileless = module_of("lab_fileless", "<lab>", HEADER + analysis("Fileless", "Fileless"))
    fileless.__file__ = None
    manager.load_module(fileless)
    metadata = next(m for m in manager.get_scripts_in_group("Lab") if m.name == "Fileless")
    assert metadata.script_id == f"{os.path.abspath('lab_fileless')}::Fileless" and metadata.file_hash == ""


def test_removing_an_unknown_script_does_nothing() -> None:
    manager = ScriptsManager()
    manager._remove_script("nope")
    assert manager.get_groups() == []


# Findings of this file's first version, fixed in scripts_manager.py.

def test_a_script_naming_another_file_is_replaced_too(folder: Path) -> None:
    path = write(folder, "named.py", analysis(file_path="'named.py'"))
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    manager.load_directory(str(folder))
    assert [metadata.script_id for metadata in manager.get_scripts_in_group("Lab")] == [f"{path}::Counts"]
    path.unlink()
    manager.load_directory(str(folder))
    assert manager.get_groups() == []


def test_an_abstract_base_class_in_a_file_is_not_a_script(folder: Path) -> None:
    base = '''
class LabBase(DatasetAnalysis):
    """Shared code for the lab's plots: abstract, no metadata."""

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(str(result.data), parent)
'''
    concrete = '''
class Counts(LabBase):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Counts", "test", "Lab", __file__, "lab.counts", "1")

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return context.view.event_count


class Widths(LabBase):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Widths", "test", "Lab", __file__, "lab.widths", "1")

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return context.view.event_count
'''
    write(folder, "shared.py", base, concrete)
    manager = ScriptsManager()
    manager.load_directory(str(folder))
    # The abstract LabBase is skipped, so the scripts named after it load too.
    assert names(manager, "Lab") == ["Counts", "Widths"]


def test_a_script_that_exits_at_import_is_skipped(folder: Path) -> None:
    write(folder, "good.py", analysis("Good", "Good"))
    write(folder, "exits.py", "import sys\nsys.exit(2)\n")
    manager = ScriptsManager()
    try:
        manager.load_directory(str(folder))
    except SystemExit:
        pytest.fail("SystemExit escaped load_directory")
    assert names(manager, "Lab") == ["Good"]

