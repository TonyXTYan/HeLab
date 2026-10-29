import os
import subprocess

# The checkout's root, where the type checkers run (their own subprocess's working folder, not this
# process's: these tests run first, and the tests after them run where pytest started).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cache(name: str) -> list[str]:
    """Each mypy run's own cache folder: these run at once, on separate xdist workers, and mypy runs
    sharing one SQLite cache crashed ("database is locked" setting its journal mode)."""
    return ['--cache-dir', os.path.join('.mypy_cache', 'test_typing', name)]


def test_mypy_helab_soft() -> None:
    result = subprocess.run(['mypy', 'helab', *cache('helab')], capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check failed"

def test_mypy_helab_strict() -> None:
    result = subprocess.run(['mypy', 'helab', '--strict', *cache('helab-strict')],
                            capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check on helab failed"

def test_mypy_helab_tests_soft() -> None:
    result = subprocess.run(['mypy', 'tests', *cache('tests')], capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check on tests failed"

def test_mypy_helab_tests_strict() -> None:
    result = subprocess.run(['mypy', 'tests', '--strict', *cache('tests-strict')],
                            capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check on tests failed"


def test_pyright_helab() -> None:
    result = subprocess.run(['pyright', 'helab'], capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "pyright type check on helab failed"


def test_pyright_tests() -> None:
    result = subprocess.run(['pyright', 'tests'], capture_output=True, text=True, cwd=ROOT)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "pyright type check on tests failed"


if __name__ == "__main__":
    test_mypy_helab_soft()
    test_mypy_helab_strict()
    test_mypy_helab_tests_soft()
    test_mypy_helab_tests_strict()

    test_pyright_helab()
    test_pyright_tests()
