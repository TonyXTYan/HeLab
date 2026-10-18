from dataclasses import asdict
import json
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

import pytest

from helab._version import __version__
from helab import build_info
from helab.build_info import BuildInfo, checkout_build_info, get_build_info, read_build_info, write_build_info
from helab.release import decide_release

ROOT = Path(__file__).resolve().parent.parent


def test_source_provenance_ignores_launch_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected_commit = "a" * 40
    def git(command: list[str], **options: object) -> str:
        assert command[:3] == ["git", "-C", str(ROOT)]
        assert options["timeout"] == 2
        return {"--show-toplevel": str(ROOT), "HEAD": expected_commit,
                "--abbrev-ref HEAD": "dev/v0.0.5", "--porcelain --untracked-files=normal": "M changed.py"}[
            " ".join(command[4:])]
    monkeypatch.setattr(subprocess, "check_output", git)
    (tmp_path / "setup.py").write_text('version="99.0.0"', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    info = get_build_info()
    assert info.version == __version__
    assert info.commit == expected_commit
    assert info.built_at is None
    assert info.dirty is not None


def test_installed_package_without_metadata_never_uses_enclosing_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    # This directory is inside the actual checkout, but is not its root.
    monkeypatch.setattr(build_info, "PACKAGE_DIR", ROOT / "tests" / "installed_package")
    assert get_build_info() == BuildInfo()


def test_version_query_does_not_initialize_gui_services(tmp_path: Path) -> None:
    code = (
        "import runpy, sys; sys.path.insert(0, sys.argv[1]); sys.argv=['helab', '--version']; "
        "\ntry: runpy.run_module('helab', run_name='__main__')"
        "\nexcept SystemExit as exc: assert exc.code == 0"
        "\nassert 'PyQt6' not in sys.modules"
        "\nassert 'helab.utils.constants' not in sys.modules"
        "\nassert 'helab.utils.dash_server' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code, str(ROOT)], cwd=tmp_path,
                            capture_output=True, text=True, check=True)
    assert f"HeLab {__version__}" in result.stdout


def test_checkout_git_failure_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    def fail(*args: object, **kwargs: object) -> str:
        raise subprocess.TimeoutExpired("git", 2)
    monkeypatch.setattr(subprocess, "check_output", fail)
    assert checkout_build_info(tmp_path) == BuildInfo()


def test_frozen_metadata_survives_no_git_and_unrelated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package"
    metadata = package / build_info.BUILD_INFO_FILENAME
    expected = write_build_info(ROOT, metadata)
    assert expected.commit != "unknown" and expected.built_at is not None
    monkeypatch.setattr(build_info, "PACKAGE_DIR", package)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.chdir(tmp_path)
    with patch.object(subprocess, "check_output", side_effect=AssertionError("Packaged app must not run git")):
        assert get_build_info() == expected
    assert not (ROOT / "helab" / build_info.BUILD_INFO_FILENAME).exists()


@pytest.mark.parametrize("payload", [None, "broken", [], {},
    {"version": "99.0.0"},
    {**asdict(BuildInfo()), "built_at": "not a timestamp"},
    {**asdict(BuildInfo()), "built_at": "2026-10-12T12:00:00+00:00", "dirty": 1},
    {**asdict(BuildInfo()), "built_at": "2026-10-12T12:00:00+00:00", "commit": "bad"},
])
def test_missing_or_malformed_frozen_metadata_is_unknown(
    payload: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_info, "PACKAGE_DIR", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    metadata = tmp_path / build_info.BUILD_INFO_FILENAME
    if payload is not None:
        metadata.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    with patch.object(subprocess, "check_output", side_effect=AssertionError("No git fallback")):
        assert read_build_info(metadata) is None
        assert get_build_info() == BuildInfo()


@pytest.mark.parametrize("ref,version,tags,releases,prerelease", [
    ("refs/heads/dev/v0.0.5", "0.0.5a1", [], False, True),
    ("refs/pull/5/merge", "0.0.5", [], False, False),
    ("refs/tags/v0.0.5", "0.0.5", [], False, False),
    ("refs/heads/main", "0.0.5a1", ["v0.0.4a", "v.0.0.1i", "CI-CD-everything-passed"], True, True),
    ("refs/heads/main", "0.0.5", ["v0.0.5a1"], True, False),
    ("refs/heads/main", "0.0.5", ["v0.0.5"], True, False),
    ("refs/heads/main", "0.0.4a0", ["v0.0.4a"], False, True),
])
def test_release_only_for_new_main_version(
    ref: str, version: str, tags: list[str], releases: bool, prerelease: bool,
) -> None:
    decision = decide_release(version, tags, ref)
    assert decision.tag == f"v{version}"
    assert decision.should_release is releases
    assert decision.prerelease is prerelease


@pytest.mark.parametrize("version,tags", [
    ("0.0.4", ["v0.0.5a1"]), ("v0.0.5", []), ("0.0.5a", []),
    ("0.0.5+local", []), ("0.0.5z1", []), ("1!0.0.5", []),
])
def test_invalid_or_decreasing_release_versions_fail(version: str, tags: list[str]) -> None:
    with pytest.raises(ValueError):
        decide_release(version, tags, "refs/heads/main")


def test_spec_uses_same_metadata_and_numeric_bundle_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyInstaller.config import CONF
    captured: list[dict[str, object]] = []
    class Target:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured.append(kwargs)
            self.pure: list[object] = []
            self.scripts: list[object] = []
            self.binaries: list[object] = []
            self.datas: list[object] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(CONF, "workpath", str(tmp_path))
    runpy.run_path(str(ROOT / "HeLab.spec"), init_globals={
        "SPECPATH": str(ROOT),
        **dict.fromkeys(["Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE"], Target),
    })
    info = read_build_info(tmp_path / build_info.BUILD_INFO_FILENAME)
    assert info is not None and info.version == __version__
    datas = captured[0]["datas"]
    assert isinstance(datas, list)
    assert (str(tmp_path / build_info.BUILD_INFO_FILENAME), "helab") in datas
    plist = captured[-1]["info_plist"]
    assert isinstance(plist, dict)
    assert plist["HeLabVersion"] == __version__
    assert plist["HeLabCommit"] == info.commit
    for name in ("CFBundleVersion", "CFBundleShortVersionString"):
        assert len(plist[name].split(".")) == 3
        assert all(part.isdigit() for part in plist[name].split("."))
