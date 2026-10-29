# tests/conftest.py
import os
import sys
import tempfile
import json
import re
import traceback
import uuid
import zlib
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generator, Iterator

# Run Qt headless (offscreen) by default so tests don't pop up windows.
# Set HELAB_SHOW_GUI=1 to force a real, visible display (e.g. when a test
# genuinely needs to be watched/debugged interactively).
if not os.environ.get("HELAB_SHOW_GUI") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# helab.utils.constants normally resolves DIR_TEMPS/DIR_CACHES from a
# QSettings value that's shared (and persisted) across every process on the
# machine, including other pytest-xdist workers running concurrently. That
# makes every process's disk cache the *same* on-disk store, so one worker's
# test clearing a cache races another worker's test reading/writing it. Give this process
# its own private cache/temp dirs before helab.utils.constants (imported
# transitively below) ever computes DIR_TEMPS/DIR_CACHES.
#
# This must be an unconditional assignment, not setdefault(): the xdist
# *controller* process also imports this conftest (to collect tests) before
# it spawns worker subprocesses, and those workers inherit its environment.
# setdefault() would let the controller's one HELAB_DIR_*_OVERRIDE value leak
# into every worker unchanged, defeating the whole point of per-worker
# isolation. Each worker re-executes this module at its own startup, so an
# unconditional assignment here always lets it stomp the inherited value with
# a directory unique to itself.
#
# helab.utils.constants reads these overrides once, when it is first imported. A run that
# imported helab before this file (a script calling pytest.main() after its own helab imports)
# would already have the real cache folder and settings, and tests would write there.
if "helab.utils.constants" in sys.modules:
    raise RuntimeError("helab was imported before tests/conftest.py, so tests would use the real cache "
                       "folder: import helab only after pytest has loaded conftest (e.g. patch it from a "
                       "fixture or the test itself).")
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
os.environ["HELAB_DIR_TEMPS_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_temps_{_worker_id}_")
os.environ["HELAB_DIR_CACHES_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_caches_{_worker_id}_")
os.environ["HELAB_APP_DIR_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_app_{_worker_id}_")
os.environ["HELAB_TEST_VOLUME_ID"] = "test-volume"
os.environ["HELAB_TEST_LOCAL_MOUNT"] = Path(tempfile.gettempdir()).anchor
# Tests never touch real data (a mounted share, a developer's data folder): helpers, and
# helab.io_ops' functions called here, refuse such source paths before touching them and note
# them in this folder, which fails the test (``no_real_data``). New tabs start in an empty folder
# of their own, never the first of constants.DEV_POTENTIAL_DATA_PATHS that exists.
os.environ["HELAB_TEST_SOURCE_GUARD"] = tempfile.mkdtemp(prefix=f"helab_test_refused_{_worker_id}_")
START_FOLDER = tempfile.mkdtemp(prefix=f"helab_test_start_{_worker_id}_")
# Tests write TXY files and load them at once; helpers would otherwise treat
# them as still being written. Settling has its own tests.
os.environ["HELAB_SETTLE_SECONDS"] = "0"


import pytest  # noqa: E402  (after the environment above is set)

if TYPE_CHECKING:
    from helab.utils.io_service import IOService


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "no_auto_data_root: test the RAM-only or explicit marker path")
    group_option(config.getoption("test_group"))  # (a bad --test-group stops the run before collecting)
    # The folders HeLab resolved must be this process's private ones, never the real app's.
    from helab.utils import constants
    expected = (os.environ["HELAB_DIR_CACHES_OVERRIDE"], os.environ["HELAB_DIR_TEMPS_OVERRIDE"],
                os.environ["HELAB_APP_DIR_OVERRIDE"])
    if (constants.cache_dir(), constants.DIR_TEMPS, constants.app_folder()) != expected:
        raise pytest.UsageError(f"Tests would use HeLab's real folders ({constants.cache_dir()}, "
                                f"{constants.DIR_TEMPS}, {constants.app_folder()}), not {expected}")
    if REQUIRED_BACKENDS:
        problems = required_backend_problems(REQUIRED_BACKENDS)
        if problems:
            raise pytest.UsageError("HELAB_REQUIRE_BACKENDS names converter backends that can't run here:\n  "
                                    + "\n  ".join(problems))
        # A skip turned into a failure (below) isn't flaky: pytest-rerunfailures' --rerun-except
        # makes it final instead of running it again (its wrapper sees the failure: ours is inner).
        if hasattr(config.option, "rerun_except"):
            names = "|".join(re.escape(name) for name in REQUIRED_BACKENDS)
            config.option.rerun_except = [*(config.option.rerun_except or []), rf"(?i)^Skipped: .*\b({names})\b"]


# The converter backends this run must have (CI, after native/build.py: e.g.
# HELAB_REQUIRE_BACKENDS=cython,rust,numba). Each must load, or the run stops before collecting,
# and a test that skips naming one of them fails instead: a broken build can't pass as skips.
REQUIRED_BACKENDS = tuple(name.strip() for name in os.environ.get("HELAB_REQUIRE_BACKENDS", "").split(",")
                          if name.strip())


def required_backend_problems(names: tuple[str, ...]) -> list[str]:
    """Why each of these backends can't run here (none: all can)."""
    from helab.convert.reconstruct import _MODULES, get_backend
    problems = []
    for name in names:
        if name not in _MODULES:
            problems.append(f"{name}: no such backend (the backends: {', '.join(_MODULES)})")
        elif (why := get_backend(name).unavailable(None)) is not None:
            problems.append(f"{name}: {why}")
    return problems


def required_backend_named(reason: str, names: tuple[str, ...]) -> str | None:
    """The first of these backends a skip's reason names, as a word (the backend tests' skips say
    which backend is missing)."""
    for name in names:
        if re.search(rf"\b{re.escape(name)}\b", reason, re.IGNORECASE):
            return name
    return None


@pytest.hookimpl(wrapper=True, trylast=True)  # inside pytest-rerunfailures' wrapper
def pytest_runtest_makereport(item: pytest.Item,
                               call: pytest.CallInfo[None]) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if REQUIRED_BACKENDS and report.skipped and not hasattr(report, "wasxfail") and isinstance(report.longrepr, tuple):
        reason = str(report.longrepr[2])
        name = required_backend_named(reason, REQUIRED_BACKENDS)
        if name is not None:
            report.outcome = "failed"
            report.longrepr = f"{item.nodeid} skipped, but HELAB_REQUIRE_BACKENDS requires {name}: {reason}"
    return report


_reruns: list[tuple[str, str]] = []  # (test, why it reran), in this process (the controller under xdist)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.outcome == "rerun":  # type: ignore[comparison-overlap]  # (pytest-rerunfailures' outcome)
        text = report.longreprtext.splitlines()
        lines = [line for line in text if line.startswith("E ")][:6]
        lines += [line for line in text if re.match(r"\S+\.py:\d+: \w", line)][-1:]  # Where it failed.
        _reruns.append((report.nodeid, "\n".join(lines) or report.longreprtext[-600:]))


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Why each rerun test failed: ``-rR`` names them only, so a flaky test's cause on CI was lost."""
    if _reruns:
        terminalreporter.section("rerun reasons")
        for test, why in _reruns:
            terminalreporter.write_line(f"{test}\n{why}")


# The slowest tests: test_typing.py runs mypy and pyright, 10 s to 1 min each by machine. Collected
# last, they ran one after another on the xdist worker that got them, minutes after the others had
# finished (CI's Windows test job reached its 30-min limit in that tail). They run first instead,
# each on its own worker where there are enough, beside the rest of the suite.
SLOW_FIRST_MODULES = frozenset({"test_typing.py"})


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-group", metavar="N/M", default=None,
                     help="run only group N of M (each test is in exactly one; CI runs two per OS)")


# CI runs the suite in two groups per OS, each a job of its own (Q16.2), so neither job nears its
# time limit. A test's group is a hash of its node ID: the same on every OS, xdist worker and run,
# with nothing to record or keep up to date, and each module's tests split about evenly, so the
# groups' times stay close as the suite grows. The slow-first tests are dealt out in turn instead,
# so each group gets its share of them (and still runs them first, below).
ALL_TESTS = pytest.StashKey[list[str]]()  # every test collected, before the group's selection


def group_option(text: str | None) -> tuple[int, int] | None:
    """``--test-group N/M`` as ``(N, M)``, or None without it."""
    if text is None:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", text)
    if match is None or not 1 <= int(match.group(1)) <= int(match.group(2)):
        raise pytest.UsageError(f"--test-group takes N/M with 1 <= N <= M (e.g. 1/2), not {text!r}")
    return int(match.group(1)), int(match.group(2))


def group_numbers(nodeids: list[str], groups: int) -> list[int]:
    """Each test's group, 1 to ``groups``."""
    numbers = []
    dealt = 0
    for nodeid in nodeids:
        if nodeid.split("::")[0].rsplit("/", 1)[-1] in SLOW_FIRST_MODULES:
            numbers.append(dealt % groups + 1)
            dealt += 1
        else:
            numbers.append(zlib.crc32(nodeid.encode("utf-8")) % groups + 1)
    return numbers


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    config.stash[ALL_TESTS] = [item.nodeid for item in items]
    group = group_option(config.getoption("test_group"))
    if group is not None:
        number, groups = group
        numbers = group_numbers(config.stash[ALL_TESTS], groups)
        others = [item for item, of in zip(items, numbers) if of != number]
        items[:] = [item for item, of in zip(items, numbers) if of == number]
        if others:
            config.hook.pytest_deselected(items=others)
    slow = [item for item in items if item.path.name in SLOW_FIRST_MODULES]
    if not slow:
        return
    # A worker collects; it reads the command line's --dist, "no" with -n alone (which the
    # controller runs as "load").
    workers = int(getattr(config, "workerinput", {}).get("workercount", 1))
    spread = config.getoption("dist", "no") in ("no", "load")
    positions = slow_first_positions(len(items), len(slow), workers if spread else 1,
                                     config.getoption("maxschedchunk", None))
    rest = iter(item for item in items if item.path.name not in SLOW_FIRST_MODULES)
    at = dict(zip(positions, slow))
    items[:] = [at[i] if i in at else next(rest) for i in range(len(items))]


def slow_first_positions(total: int, count: int, workers: int, max_chunk: int | None) -> list[int]:
    """Where ``count`` slow tests go among ``total`` so that xdist's ``load`` scheduling starts them
    on different workers at once. It sends each worker a batch of consecutive tests first (a quarter
    of its share, at least 2, at most ``--maxschedchunk``; one each, in turn, under 2 per worker:
    ``LoadScheduling.schedule``), so slow test ``j`` goes at the start of worker ``j % workers``'s
    batch. Simply first when that layout doesn't fit (one worker, more slow tests than batch room)."""
    if workers <= 1 or total < 2 * workers:
        return list(range(count))
    batch = max(min(total // workers // 4, max_chunk or total), 2)
    if count > workers * batch:
        return list(range(count))
    return [(j % workers) * batch + j // workers for j in range(count)]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item) -> Iterator[None]:
    try:
        result = yield
    except BaseException:  # A fixture's or pytest-qt's teardown failed: clean up, keep its failure.
        delete_left_widgets(item.nodeid, fail=False)
        raise
    delete_left_widgets(item.nodeid)
    return result


def delete_left_widgets(test: str, *, fail: bool = True) -> None:
    """Widgets a test leaves go with it. pytest-qt and fixtures only ``deleteLater()`` them, so a
    later test's event loop, or the interpreter's exit, deleted them; a QWebEngineView outliving
    its test that way crashed Qt (segfaults in ``test_live_plots.py`` on CI). Deferred deletes are
    sent at each test's teardown, and a web view still alive after that fails the test: nothing
    would delete it (``fail=False``: deleted only, when the teardown already failed)."""
    if "PyQt6.QtWebEngineWidgets" not in sys.modules:
        return
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    alive = [view for view in QApplication.allWidgets() if isinstance(view, QWebEngineView)]
    if alive:
        for view in alive:  # (So the next test doesn't fail for this one too.)
            view.close()
            view.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        if fail:
            pytest.fail(f"{test} left {len(alive)} web view(s) alive: close or delete its plots",
                        pytrace=False)


def store_free(*services: "IOService") -> bool:
    """Whether no helper of these IOServices, nor of the app-wide one, has the disk cache open (every
    exit confirmed): only then may a test delete the store, which Windows refuses while a helper has
    it open (WinError 32). A plot's Presets row reads presets through the app-wide FolderCache,
    whatever cache the test gave the plot, and its timers keep starting helpers in later tests, on
    the store of the test running then."""
    from helab.utils import io_service
    app = io_service._service
    return not any(service.cache_busy() for service in (*services, app) if service is not None)


@pytest.fixture(autouse=True)
def private_settings(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test's app settings are an ini file of its own (``settings_store.app_settings``), never
    the machine's native store. In a folder apart from ``tmp_path``, which tests list."""
    folder = tmp_path_factory.mktemp("settings")
    monkeypatch.setenv("HELAB_TEST_SETTINGS_FILE", str(folder / "helab-settings.ini"))


@pytest.fixture(autouse=True)
def no_real_data(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """New tabs start in an empty temp folder; a test whose helpers were refused a source path
    that could be real data (``io_ops.infra._guard``) fails, naming it. A refusal noted after its
    test ended (a helper still running) fails the next test of this worker."""
    monkeypatch.setattr("helab.views.FolderTabWidget.DEFAULT_DATA_PATH", START_FOLDER)
    monkeypatch.setattr("helab.views.FolderTabWidget.DEV_POTENTIAL_DATA_PATHS", [START_FOLDER])
    yield
    notes = Path(os.environ["HELAB_TEST_SOURCE_GUARD"])
    refused: list[str] = []
    for note in sorted(notes.glob("*.txt")):
        refused += note.read_text(encoding="utf-8").splitlines()
        note.unlink()
    if refused:
        pytest.fail(f"Tests never touch real data, but this test's I/O asked for: {sorted(set(refused))}",
                    pytrace=False)


@pytest.fixture(autouse=True)
def private_store(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Each test's disk cache is a store of its own (``constants.cache_dir()``, which helpers are
    sent). A worker's tests shared one, so what a test left there (a pending save, a budget, roots)
    changed a later test's results. In a folder apart from ``tmp_path``, which tests list."""
    from helab.utils import constants
    folder = str(tmp_path_factory.mktemp("caches"))
    before = (constants.cache_dir(), constants.cache_dir_refused(), constants.cache_dir_enabled())
    monkeypatch.setenv("HELAB_DIR_CACHES_OVERRIDE", folder)
    monkeypatch.setattr(constants, "_dir_caches_override", folder)
    constants.set_cache_dir(folder)
    yield folder
    constants.set_cache_dir(*before)


@pytest.fixture(autouse=True)
def temporary_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                        request: pytest.FixtureRequest, private_store: str) -> Iterator[None]:
    """Give existing cache tests a marker and stable fake volume ID in test dirs.

    Individual root tests opt out and construct their own marker state. The
    wrapper seeds each test store through its roots table before the production
    helper resolver opens it; no production fallback is introduced. The store
    is the test's own (``private_store``), so a later test's ``roots_verify``
    checks only its own roots.
    """
    from helab.io_ops import infra, stores
    from helab.utils import cache_paths, data_roots
    from helab.utils.cache_store import CacheStore, store_root

    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "test-volume")
    monkeypatch.setattr(infra, "_volume_id_cache", {})
    # (On Windows, HELAB_TEST_LOCAL_MOUNT above stands in for the drive list.)
    if request.node.get_closest_marker("no_auto_data_root"):
        yield
        return
    identifiers: dict[str, str] = {}

    def ensure_marker(folder: str) -> str:
        target = Path(folder)
        if not target.is_relative_to(tmp_path):
            return ""
        file = target / data_roots.MARKER_NAME
        if file.exists():
            return data_roots.read_marker(folder).uuid
        identifier = identifiers.setdefault(folder, str(uuid.uuid4()))
        file.write_text(json.dumps({"helab": "root", "version": 1, "uuid": identifier,
                                    "label": target.name, "created_at": "2026-10-18T00:00:00Z"}),
                        encoding="utf-8")
        return identifier

    main_store = store_root(private_store)

    def seed(store_dir: str, source: str) -> None:
        mounts = cache_paths.current_mounts()
        matches = [mount for mount in mounts if cache_paths._inside(
            cache_paths._normal(source), cache_paths._normal(mount.path))]
        mount = max(matches, key=lambda item: len(item.path)) if matches else None
        folder = (mount.path if mount is not None and
                  (mount.remote or cache_paths._smb_source(mount.source, mount.fstype) is not None) and
                  Path(mount.path).is_relative_to(tmp_path) else str(tmp_path))
        identifier = ensure_marker(folder)
        if not identifier:
            return
        paths = cache_paths.CachePaths(mounts)
        volumes = data_roots.current_local_volumes(mounts, paths=[folder])
        resolver = data_roots.DataRoots(paths, [], local_location=volumes.location)
        try:
            location = resolver.location(folder)
        except data_roots.NoDataRoot:
            return
        with CacheStore(store_dir, root_mode=True) as store:
            if store.read_only:
                return
            if store.root_at(location) is None:
                store.record_root(location, identifier,
                                  "smb" if location.startswith("smb://") else "vol",
                                  Path(folder).name, decision="confirmed")
            for volume_mount, volume_id in volumes.volumes:
                store.record_volume(volume_mount.path, volume_mount.source, volume_id)

    ensure_marker(str(tmp_path))
    seed(main_store, str(tmp_path))
    original = stores._cache_store

    def open_seeded(root: str, source_paths: list[str] | None = None, *,
                    local_lane: bool = False, allow_unrooted: bool = False,
                    verified_volumes: list[list[str]] | None = None, offline: bool = False) -> CacheStore:
        for source in source_paths or ():
            seed(root, source)
        return original(root, source_paths, local_lane=local_lane, allow_unrooted=allow_unrooted,
                        verified_volumes=verified_volumes, offline=offline)

    monkeypatch.setattr(stores, "_cache_store", open_seeded)
    yield


@pytest.fixture(autouse=True)
def default_constants() -> None:
    """Plots that use constants start from the table's defaults: the app-wide FolderCache keeps
    lab and folder values for the worker's whole run, and a test building a real
    ``HelabMainWindow`` fills the lab's from its settings' saved Lab parameters. Only an existing
    app-wide cache is reset (none is created here)."""
    from helab.utils import io_service
    service = io_service._service
    cache = service.folder_cache if service is not None else None
    if cache is not None:
        cache.lab_constants = {}
        cache.folder_constant_records.clear()
        cache.constants_unsaved.clear()


@pytest.fixture(autouse=True)
def no_quitting_cache() -> Iterator[None]:
    """A main window closed while saves were pending waits in its quit window, with the app-wide
    FolderCache ``quitting``; deleted with its test, it never quits, and the worker's next test got
    that cache, which refuses presets, flags and constants (a presets test then hung on the warning
    it showed). It is shut down at teardown, so the next test gets a new one."""
    yield
    from helab.utils import io_service
    service = io_service._service
    cache = service.folder_cache if service is not None else None
    if service is not None and cache is not None and cache.quitting:
        service.shutdown()  # (Once closed, nothing.)


@pytest.fixture(autouse=True)
def where_qt_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception Qt reports from C, before any Python frame (a callable that is None when Qt
    calls it), has no traceback, so pytest-qt's "Exceptions caught in Qt event loop" names no line
    (``test_live_plots.py``'s scatter test on Ubuntu CI: "TypeError: 'NoneType' object is not
    callable" at teardown). It gets a note: the test's or HeLab's code that was running Qt's event loop.
    (Wraps pytest-qt's hook, which it installs before the test's fixtures.)"""
    hook = sys.excepthook

    def noted(kind: type[BaseException], value: BaseException, tback: TracebackType | None) -> None:
        if tback is None:
            ours = [frame for frame in traceback.extract_stack()[:-1] if "site-packages" not in frame.filename]
            stack = "".join(traceback.format_list(ours[-4:]))  # (Short: the rerun reason keeps 600 characters.)
            value.add_note(f"(No traceback: raised by Qt outside Python code, while this ran its event loop:)\n{stack}")
        hook(kind, value, tback)

    monkeypatch.setattr(sys, "excepthook", noted)


@pytest.fixture(autouse=True)
def no_selection_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests select folders back to back and expect their loads at once; the wait for the
    selection to settle (Finish, Cancel) has its own tests, which set ``SETTLE_MAX`` again."""
    from helab.views.FolderExplorer import FolderExplorer
    monkeypatch.setattr(FolderExplorer, "SETTLE_MAX", 0.0)
