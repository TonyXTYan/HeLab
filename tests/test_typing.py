import os
import subprocess

def test_mypy_helab_soft() -> None:
    # Change the current working directory to the script's directory
    # os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Change the current working directory to one directory up from the script's directory
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    result = subprocess.run(['mypy', 'helab'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check failed"



def test_mypy_helab_strict() -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(['mypy', 'helab', '--strict'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check failed"

def test_mypy_helab_tests_soft() -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(['mypy', 'tests'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check failed"

def test_mypy_helab_tests_strict() -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(['mypy', 'tests', '--strict'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "mypy type check failed"


def test_pyright_helab() -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(['pyright', 'helab'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "pyright type check failed"


def test_pyright_tests() -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(['pyright', 'tests'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "pyright type check failed"


if __name__ == "__main__":
    test_mypy_helab_soft()
    test_mypy_helab_strict()
    test_mypy_helab_tests_soft()
    test_mypy_helab_tests_strict()

    test_pyright_helab()
    test_pyright_tests()
