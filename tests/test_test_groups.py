"""``--test-group N/M`` (``tests/conftest.py``): CI runs the suite in two groups per OS (Q16.2), and
every test must be in exactly one of them, or a test would run twice or never on CI."""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import ALL_TESTS, SLOW_FIRST_MODULES, group_numbers, group_option

ROOT = Path(__file__).resolve().parents[1]

PROBE = "\n".join(f"def test_{index}():\n    pass\n" for index in range(40))
SLOW = "\n".join(f"def test_slow_{index}():\n    pass\n" for index in range(5))


def is_slow(nodeid: str) -> bool:
    return nodeid.split("::")[0].rsplit("/", 1)[-1] in SLOW_FIRST_MODULES


def test_the_whole_collection_splits_into_two_groups_of_about_half(request: pytest.FixtureRequest) -> None:
    """This run's own collection (every test, before a group's selection): each test is in group 1
    or 2, the two are close in size, and each has its share of the slow-first tests."""
    everything = request.config.stash[ALL_TESTS]
    assert len(everything) == len(set(everything)) > 0
    numbers = group_numbers(everything, 2)
    assert set(numbers) <= {1, 2}
    if len(everything) >= 1000:  # (the full suite, not a file or two run alone)
        sizes = Counter(numbers)
        assert abs(sizes[1] - sizes[2]) < 0.05 * len(everything), sizes
    slow = Counter(number for nodeid, number in zip(everything, numbers) if is_slow(nodeid))
    assert abs(slow[1] - slow[2]) <= 1, slow
    group = group_option(request.config.getoption("test_group"))
    if group is not None and group[1] == 2:  # (CI's run of one group: it runs only that group's tests)
        mine = {nodeid for nodeid, number in zip(everything, numbers) if number == group[0]}
        assert {item.nodeid for item in request.session.items} <= mine


def test_a_tests_group_depends_on_its_node_id_only() -> None:
    nodeids = [f"tests/test_x.py::test_{index}" for index in range(200)]
    for groups in (1, 2, 3):
        numbers = group_numbers(nodeids, groups)
        assert set(numbers) == set(range(1, groups + 1))
        assert group_numbers(list(reversed(nodeids)), groups) == list(reversed(numbers))
        assert group_numbers(nodeids[50:], groups) == numbers[50:]


def test_the_slow_first_tests_are_dealt_out_in_turn() -> None:
    [module] = SLOW_FIRST_MODULES  # (the rule holds for any; the test reads one)
    nodeids = ["tests/test_a.py::test_one", *(f"tests/{module}::test_{index}" for index in range(5))]
    assert group_numbers(nodeids, 2)[1:] == [1, 2, 1, 2, 1]
    assert group_numbers(nodeids, 3)[1:] == [1, 2, 3, 1, 2]


@pytest.mark.parametrize("text", ["0/2", "3/2", "1", "a/b", "1/0", ""])
def test_a_bad_group_is_a_usage_error(text: str) -> None:
    with pytest.raises(pytest.UsageError, match="--test-group"):
        group_option(text)


def test_a_group_is_read_as_n_of_m() -> None:
    assert group_option(None) is None
    assert group_option("1/2") == (1, 2) and group_option(" 2 / 2 ") == (2, 2)


def nested_collect(tmp_path: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """A collection of the probe tests of its own, with this conftest as its plugin (as in
    test_convert_required_backends)."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("COV_CORE_", "PYTEST_XDIST_"))}  # (no coverage or xdist of the outer run)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "tests")])
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider",
                           "-p", "no:xdist", "-p", "no:randomly", "--collect-only", "-q", *options],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def collected(done: subprocess.CompletedProcess[str]) -> list[str]:
    assert done.returncode == 0, done.stdout + done.stderr
    return [line for line in done.stdout.splitlines() if "::" in line]


def test_the_groups_of_a_run_cover_its_tests_once_each(tmp_path: Path) -> None:
    [module] = SLOW_FIRST_MODULES
    (tmp_path / "test_probe.py").write_text(PROBE, encoding="utf-8")
    (tmp_path / module).write_text(SLOW, encoding="utf-8")
    everything = collected(nested_collect(tmp_path))
    one = collected(nested_collect(tmp_path, "--test-group", "1/2"))
    two = collected(nested_collect(tmp_path, "--test-group", "2/2"))
    assert len(everything) == 45 and sorted(one + two) == sorted(everything) and one and two
    assert not set(one) & set(two)
    # Each group runs its slow-first tests first (3 and 2 of the 5).
    assert [nodeid.startswith(module) for nodeid in one[:3]] == [True] * 3
    assert [nodeid.startswith(module) for nodeid in two[:2]] == [True] * 2


def test_a_bad_group_stops_the_run(tmp_path: Path) -> None:
    (tmp_path / "test_probe.py").write_text(PROBE, encoding="utf-8")
    done = nested_collect(tmp_path, "--test-group", "3/2")
    assert done.returncode == pytest.ExitCode.USAGE_ERROR, done.stdout + done.stderr
    assert "--test-group takes N/M" in done.stdout + done.stderr
