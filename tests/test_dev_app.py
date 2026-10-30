"""The dev app stub (``dev/dev_app.py``): a macOS ``.app`` with its own bundle ID whose executable
runs a checkout's ``venv/bin/python -m helab``. Built into the test's own folder for a fake
checkout; its launcher is run with ``sh`` where there is one (not on Windows)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_app", ROOT / "dev" / "dev_app.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev_app = load_tool()


def checkout(tmp_path: Path, *, python: bool = True, name: str = "check out") -> Path:
    """A fake checkout whose ``venv/bin/python`` prints where it runs, its arguments and ``DEV_APP_TEST``."""
    folder = tmp_path / name
    (folder / "helab").mkdir(parents=True)
    (folder / "helab" / "_version.py").write_text('__version__ = "1.2.3a4"\n', encoding="utf-8")
    if python:
        (folder / "venv" / "bin").mkdir(parents=True)
        fake = folder / "venv" / "bin" / "python"
        fake.write_text('#!/bin/sh\necho "cwd=$(pwd)"\nfor arg do echo "arg=$arg"; done\necho "env=$DEV_APP_TEST"\n',
                        encoding="utf-8", newline="\n")
        fake.chmod(0o755)
    return folder


def info(app: Path) -> dict[str, Any]:
    with open(app / "Contents" / "Info.plist", "rb") as file:
        found: dict[str, Any] = plistlib.load(file)
    return found


def test_the_stub_has_its_own_bundle_id_and_names_its_checkout(tmp_path: Path) -> None:
    source = checkout(tmp_path)
    app = dev_app.build(tmp_path / "out" / "HeLab-dev.app", source)
    plist = info(app)
    assert plist["CFBundleIdentifier"] == "au.edu.anu.he-bec-lab.dev" != dev_app.RELEASE_ID
    assert plist["CFBundleName"] == plist["CFBundleDisplayName"] == "HeLab-dev"
    assert plist["CFBundleExecutable"] == "HeLab-dev" and plist["CFBundlePackageType"] == "APPL"
    assert plist["HeLabCheckout"] == str(source) and str(source) in plist["CFBundleGetInfoString"]
    assert plist["CFBundleShortVersionString"] == "1.2.3a4"
    script = app / "Contents" / "MacOS" / "HeLab-dev"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n") and "\r" not in text and 'exec "$PYTHON" -m helab "$@"' in text
    if os.name != "nt":
        assert os.access(script, os.X_OK)
    assert (app / "Contents" / "Resources" / "ai-icon.icns").is_file()
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == ["HeLab-dev.app"]  # (No staging left.)


def test_a_tag_gives_a_second_checkout_its_own_id_and_name() -> None:
    assert dev_app.identity("") == ("au.edu.anu.he-bec-lab.dev", "HeLab-dev")
    assert dev_app.identity("floor-2") == ("au.edu.anu.he-bec-lab.dev.floor-2", "HeLab-dev-floor-2")
    with pytest.raises(ValueError, match="letters, digits"):
        dev_app.identity("a b")


def test_the_release_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="release"):
        dev_app.info_plist(tmp_path, dev_app.RELEASE_ID, "HeLab", "")


def test_only_a_stub_of_its_own_is_replaced(tmp_path: Path) -> None:
    source = checkout(tmp_path)
    other = tmp_path / "HeLab-dev.app"
    (other / "Contents").mkdir(parents=True)
    (other / "Contents" / "keep.txt").write_text("someone else's", encoding="utf-8")
    with pytest.raises(ValueError, match="isn't a stub"):
        dev_app.build(other, source)
    assert (other / "Contents" / "keep.txt").is_file()
    shutil.rmtree(other)
    dev_app.build(other, source)
    (other / "Contents" / "Resources" / "stale.txt").write_text("old", encoding="utf-8")
    dev_app.build(other, source, tag="again")
    assert info(other)["CFBundleIdentifier"] == "au.edu.anu.he-bec-lab.dev.again"
    assert not (other / "Contents" / "Resources" / "stale.txt").exists()


def test_a_malformed_info_plist_is_no_stub_of_its_own(tmp_path: Path) -> None:
    app = tmp_path / "HeLab-dev.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text('<?xml version="1.0"?><plist><dict><key>HeLab', encoding="utf-8")
    assert not dev_app.is_stub(app)
    with pytest.raises(ValueError, match="isn't a stub"):
        dev_app.build(app, checkout(tmp_path))


@pytest.mark.parametrize("bad", ['quo"te', pytest.param("back\\slash", marks=pytest.mark.skipif(
    os.name == "nt", reason="Windows' separator, not in a name")), "new\nline", "line\u2028break"])
def test_a_path_the_launcher_cant_quote_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="quote, backslash or control"):
        dev_app.build(tmp_path / "HeLab-dev.app", tmp_path / bad)
    env_file = tmp_path / f"env-{bad}.sh"
    try:
        env_file.write_text("", encoding="utf-8")
    except OSError:  # (Not a name this file system takes: nothing to refuse.)
        return
    with pytest.raises(ValueError, match="quote, backslash or control"):
        dev_app.build(tmp_path / "HeLab-dev.app", checkout(tmp_path), env_file=str(env_file))


def test_a_missing_env_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such file"):
        dev_app.build(tmp_path / "HeLab-dev.app", checkout(tmp_path), env_file=str(tmp_path / "none.sh"))


needs_sh = pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="runs the launcher with sh")


def launch(app: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "DEV_APP_TEST"}
    env["HELAB_DEV_APP_QUIET"] = "1"
    return subprocess.run(["sh", str(app / "Contents" / "MacOS" / "HeLab-dev"), *args], capture_output=True,
                          text=True, env=env, cwd=str(app.parent), timeout=30)


@needs_sh
def test_the_launcher_runs_the_checkout_with_its_arguments_and_env_file(tmp_path: Path) -> None:
    source = checkout(tmp_path)
    env_file = tmp_path / "floor env.sh"
    env_file.write_text("export DEV_APP_TEST='from the env file'\n", encoding="utf-8", newline="\n")
    app = dev_app.build(tmp_path / "HeLab-dev.app", source, env_file=str(env_file))
    assert info(app)["HeLabEnvFile"] == str(env_file.resolve())
    done = launch(app, "--geometry", "1600x928+0+39", "two words", "-psn_0_12345")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert Path(lines[0].removeprefix("cwd=")).resolve() == source.resolve()
    assert lines[1:] == ["arg=-m", "arg=helab", "arg=--geometry", "arg=1600x928+0+39", "arg=two words",
                         "env=from the env file"]


@needs_sh
def test_the_env_file_is_sourced_in_the_checkout_and_a_missing_one_is_said(tmp_path: Path) -> None:
    """Sourced after the ``cd``, so a relative path in it is the checkout's; gone at launch, the stub
    says so and HeLab doesn't start. A checkout path with ``$`` and a backtick stays as it is."""
    source = checkout(tmp_path, name="check $HOME `out`")
    env_file = tmp_path / "floor-env.sh"
    env_file.write_text('export DEV_APP_TEST="$(pwd)/folders"\n', encoding="utf-8", newline="\n")
    app = dev_app.build(tmp_path / "HeLab-dev.app", source, env_file=str(env_file))
    done = launch(app)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert Path(lines[0].removeprefix("cwd=")).resolve() == source.resolve()
    assert Path(lines[-1].removeprefix("env=")).resolve() == (source / "folders").resolve()
    env_file.unlink()
    done = launch(app)
    assert done.returncode == 1 and done.stdout == ""
    assert f"the env file {env_file.resolve()} is missing" in done.stderr


@needs_sh
def test_the_launcher_without_a_venv_says_so_and_fails(tmp_path: Path) -> None:
    app = dev_app.build(tmp_path / "HeLab-dev.app", checkout(tmp_path, python=False))
    done = launch(app)
    assert done.returncode == 1 and "venv/bin/python not found" in done.stderr and done.stdout == ""


def test_the_tool_is_macos_only(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert dev_app.main([]) == 2 and "macOS only" in capsys.readouterr().err
