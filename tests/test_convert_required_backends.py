"""The converter backends a run must have: ``HELAB_REQUIRE_BACKENDS`` (``tests/conftest.py``) and
``native/check_build.py``, which CI runs after building the compiled backends (``native/build.py``).

CI requires cython, rust and numba on every OS (and mlx where Metal exists), so a backend whose
build broke fails the run instead of passing as skipped tests."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from conftest import REQUIRED_BACKENDS, required_backend_named, required_backend_problems
from helab.convert.reconstruct import _MODULES, get_backend

ROOT = Path(__file__).resolve().parents[1]

SKIPS = '''
import pytest

def test_names_a_required_backend():
    pytest.skip("the reference backend can't run here (a probe)")

@pytest.mark.skipif(True, reason="rust extension not built (a probe)")
def test_marked_for_another_backend():
    pass

def test_skips_for_something_else():
    pytest.skip("POSIX file modes")
'''


def check_build() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_build", ROOT / "native" / "check_build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def nested_pytest(tmp_path: Path, required: str, test: str = SKIPS) -> subprocess.CompletedProcess[str]:
    """A run of its own with this conftest as its plugin (outside tests/, as in test_left_widgets)."""
    (tmp_path / "test_probe.py").write_text(test, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("COV_CORE_", "PYTEST_XDIST_"))}  # (no coverage or xdist of the outer run)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "tests")])
    env["HELAB_REQUIRE_BACKENDS"] = required
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider",
                           "-p", "no:xdist", "-p", "no:rerunfailures", "-q", "-rA", "test_probe.py"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_the_names_are_read_as_a_comma_separated_list() -> None:
    assert all(name and name == name.strip() for name in REQUIRED_BACKENDS)


def test_a_skip_counts_when_its_reason_names_a_required_backend_as_a_word() -> None:
    names = ("cython", "rust")
    assert required_backend_named("cython extension not built (stage 4 packaging): …", names) == "cython"
    assert required_backend_named("Rust extension not built", names) == "rust"
    assert required_backend_named("trusted folders only", names) is None
    assert required_backend_named("the numba backend can't run here", names) is None


def test_problems_name_an_unknown_backend_and_none_for_one_that_runs() -> None:
    assert required_backend_problems(("reference", "numpy")) == []
    [problem] = required_backend_problems(("fortran",))
    assert problem.startswith("fortran: no such backend") and "reference" in problem


def test_an_unavailable_required_backend_stops_the_run_before_it_starts(tmp_path: Path) -> None:
    done = nested_pytest(tmp_path, "reference, fortran")
    out = done.stdout + done.stderr
    assert done.returncode == pytest.ExitCode.USAGE_ERROR, out
    assert "HELAB_REQUIRE_BACKENDS names converter backends that can't run here" in out, out
    assert "fortran: no such backend" in out, out


def test_a_skip_naming_a_required_backend_fails_and_other_skips_stay_skips(tmp_path: Path) -> None:
    done = nested_pytest(tmp_path, "reference,rust" if get_backend("rust").unavailable(None) is None
                         else "reference")
    out = done.stdout + done.stderr
    assert "FAILED test_probe.py::test_names_a_required_backend" in out, out
    assert "HELAB_REQUIRE_BACKENDS requires reference" in out, out
    assert "SKIPPED [1] test_probe.py" in out and ": POSIX file modes" in out, out
    if get_backend("rust").unavailable(None) is None:
        assert "test_marked_for_another_backend" in out and "requires rust" in out, out


def test_without_the_variable_every_skip_is_a_skip(tmp_path: Path) -> None:
    done = nested_pytest(tmp_path, "")
    out = done.stdout + done.stderr
    assert done.returncode == pytest.ExitCode.OK, out
    assert "3 skipped" in out, out


def test_every_backend_that_runs_here_gives_the_references_bytes() -> None:
    """``check_build`` in this Python, as CI runs it after building (every case, both profiles)."""
    module = check_build()
    results = module.check_here(module.cases())
    assert set(results) == set(_MODULES) - {"reference"}
    for backend, problem in results.items():
        assert problem is None or problem.startswith("unavailable: "), (backend, problem)
        assert (problem is None) == (get_backend(backend).unavailable(None) is None), (backend, problem)


def test_the_check_reports_a_difference(monkeypatch: pytest.MonkeyPatch) -> None:
    module = check_build()
    real = module.outcome

    def numpy_off_by_one_byte(data: bytes, profile: str, backend: str) -> bytes | str:
        result = real(data, profile, backend)
        return result + b"0" if backend == "numpy" and isinstance(result, bytes) else result

    monkeypatch.setattr(module, "outcome", numpy_off_by_one_byte)
    results = module.check_here(module.cases()[:3])
    assert str(results["numpy"]).startswith("differs on ")
