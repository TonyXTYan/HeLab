# tests/conftest.py
import os
import sys
import tempfile
import json
import uuid
from pathlib import Path
from typing import Iterator

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
# helab.io_helper's functions called here, refuse such source paths before touching them and note
# them in this folder, which fails the test (``no_real_data``). New tabs start in an empty folder
# of their own, never the first of constants.DEV_POTENTIAL_DATA_PATHS that exists.
os.environ["HELAB_TEST_SOURCE_GUARD"] = tempfile.mkdtemp(prefix=f"helab_test_refused_{_worker_id}_")
START_FOLDER = tempfile.mkdtemp(prefix=f"helab_test_start_{_worker_id}_")
# Tests write TXY files and load them at once; helpers would otherwise treat
# them as still being written. Settling has its own tests.
os.environ["HELAB_SETTLE_SECONDS"] = "0"


import pytest  # noqa: E402  (after the environment above is set)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "no_auto_data_root: test the RAM-only or explicit marker path")
    # The folders HeLab resolved must be this process's private ones, never the real app's.
    from helab.utils import constants
    expected = (os.environ["HELAB_DIR_CACHES_OVERRIDE"], os.environ["HELAB_DIR_TEMPS_OVERRIDE"],
                os.environ["HELAB_APP_DIR_OVERRIDE"])
    if (constants.cache_dir(), constants.DIR_TEMPS, constants.app_folder()) != expected:
        raise pytest.UsageError(f"Tests would use HeLab's real folders ({constants.cache_dir()}, "
                                f"{constants.DIR_TEMPS}, {constants.app_folder()}), not {expected}")


@pytest.fixture(autouse=True)
def no_real_data(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """New tabs start in an empty temp folder; a test whose helpers were refused a source path
    that could be real data (``io_helper._guard``) fails, naming it. A refusal noted after its
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
def temporary_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                        request: pytest.FixtureRequest) -> Iterator[None]:
    """Give existing cache tests a marker and stable fake volume ID in test dirs.

    Individual root tests opt out and construct their own marker state. The
    wrapper seeds each test store through its roots table before the production
    helper resolver opens it; no production fallback is introduced. The worker's
    shared store forgets the test's roots afterwards, so a later test's
    ``roots_verify`` checks only its own.
    """
    from helab import io_helper
    from helab.utils import cache_paths, data_roots
    from helab.utils.cache_store import CacheStore, store_root

    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "test-volume")
    monkeypatch.setattr(io_helper, "_volume_id_cache", {})
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

    main_store = store_root(os.environ["HELAB_DIR_CACHES_OVERRIDE"])
    seeded: set[str] = set()  # Root locations recorded in the shared store.

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
            if store_dir == main_store:
                seeded.add(location)
            if store.root_at(location) is None:
                store.record_root(location, identifier,
                                  "smb" if location.startswith("smb://") else "vol",
                                  Path(folder).name, decision="confirmed")
            for volume_mount, volume_id in volumes.volumes:
                store.record_volume(volume_mount.path, volume_mount.source, volume_id)

    ensure_marker(str(tmp_path))
    seed(main_store, str(tmp_path))
    original = io_helper._cache_store

    def open_seeded(root: str, source_paths: list[str] | None = None, *,
                    local_lane: bool = False, allow_unrooted: bool = False,
                    verified_volumes: list[list[str]] | None = None) -> CacheStore:
        for source in source_paths or ():
            seed(root, source)
        return original(root, source_paths, local_lane=local_lane, allow_unrooted=allow_unrooted,
                        verified_volumes=verified_volumes)

    monkeypatch.setattr(io_helper, "_cache_store", open_seeded)
    yield
    if not seeded:
        return
    monkeypatch.undo()  # Tests that forbid I/O patch it out; this cleanup reads the store.
    from helab.utils.cache_store import StoreError
    try:
        with CacheStore(main_store, root_mode=True) as store:
            for location, _, _ in store.root_locations():
                if any(location == root or location.startswith(root + "/") for root in seeded):
                    store.forget_root(location)
    except (StoreError, OSError):
        pass  # (A test that left the store unusable; the next one's roots are its own anyway.)


@pytest.fixture(autouse=True)
def default_budget_is_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each worker shares one store, which keeps the newest budget it was sent; a budget an
    earlier test lowered must not hold later tests' saves. Budget tests set their own again."""
    import time
    from helab.utils import folder_cache
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())


@pytest.fixture(autouse=True)
def no_selection_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests select folders back to back and expect their loads at once; the wait for the
    selection to settle (Finish, Cancel) has its own tests, which set ``SETTLE_MAX`` again."""
    from helab.views.FolderExplorer import FolderExplorer
    monkeypatch.setattr(FolderExplorer, "SETTLE_MAX", 0.0)
