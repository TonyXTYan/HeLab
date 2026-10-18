# tests/conftest.py
import os
import tempfile
import json
import uuid
from pathlib import Path

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
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
os.environ["HELAB_DIR_TEMPS_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_temps_{_worker_id}_")
os.environ["HELAB_DIR_CACHES_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_caches_{_worker_id}_")
os.environ["HELAB_APP_DIR_OVERRIDE"] = tempfile.mkdtemp(prefix=f"helab_test_app_{_worker_id}_")
os.environ["HELAB_TEST_VOLUME_ID"] = "test-volume"
os.environ["HELAB_TEST_LOCAL_MOUNT"] = Path(tempfile.gettempdir()).anchor
# Tests write TXY files and load them at once; helpers would otherwise treat
# them as still being written. Settling has its own tests.
os.environ["HELAB_SETTLE_SECONDS"] = "0"


import pytest  # noqa: E402  (after the environment above is set)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "no_auto_data_root: test the RAM-only or explicit marker path")


@pytest.fixture(autouse=True)
def temporary_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                        request: pytest.FixtureRequest) -> None:
    """Give existing cache tests a marker and stable fake volume ID in test dirs.

    Individual root tests opt out and construct their own marker state. The
    wrapper seeds each test store through its roots table before the production
    helper resolver opens it; no production fallback is introduced.
    """
    from helab import io_helper
    from helab.utils import cache_paths, data_roots
    from helab.utils.cache_store import CacheStore, store_root

    monkeypatch.setattr(data_roots, "_volume_id", lambda _: "test-volume")
    if os.name == "nt":
        mount_root = Path(tempfile.gettempdir()).anchor
        monkeypatch.setattr(cache_paths, "_windows_mounts",
                            lambda: [cache_paths.Mount(mount_root, mount_root, "local")])
    if request.node.get_closest_marker("no_auto_data_root"):
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

    main_store = store_root(os.environ["HELAB_DIR_CACHES_OVERRIDE"])
    ensure_marker(str(tmp_path))
    seed(main_store, str(tmp_path))
    original = io_helper._cache_store

    def open_seeded(root: str, source_paths: list[str] | None = None, *,
                    local_lane: bool = False, allow_unrooted: bool = False) -> CacheStore:
        for source in source_paths or ():
            seed(root, source)
        return original(root, source_paths, local_lane=local_lane, allow_unrooted=allow_unrooted)

    monkeypatch.setattr(io_helper, "_cache_store", open_seeded)


@pytest.fixture(autouse=True)
def no_selection_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests select folders back to back and expect their loads at once; the wait for the
    selection to settle (Finish, Cancel) has its own tests, which set ``SETTLE_MAX`` again."""
    from helab.views.FolderExplorer import FolderExplorer
    monkeypatch.setattr(FolderExplorer, "SETTLE_MAX", 0.0)
