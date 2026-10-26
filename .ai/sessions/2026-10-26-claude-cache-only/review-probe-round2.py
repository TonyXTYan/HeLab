import os
import tempfile
from pathlib import Path
from unittest.mock import patch

scratch = Path(tempfile.mkdtemp(prefix="helab-review-probe-"))
for variable, suffix in (("HELAB_APP_DIR_OVERRIDE", "app"), ("HELAB_DIR_CACHES_OVERRIDE", "cache"), ("HELAB_DIR_TEMPS_OVERRIDE", "temp")):
    os.environ[variable] = str(scratch / suffix)
os.environ["HELAB_TEST_SETTINGS_FILE"] = str(scratch / "settings.ini")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
from helab.utils.io_service import IOService, IORequest
from helab.utils.folder_cache import get_folder_cache
from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel

app = QApplication([])
def frozen():
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None
    return service, get_folder_cache(service)

# Switching online with an offline listing in flight.
service, cache = frozen()
cache.set_offline(True)
with patch("helab.models.SnapshotFileSystemModel.get_io_service", return_value=service):
    model = SnapshotFileSystemModel()
path = str(scratch / "data")
model.setRootPath(path)
before = next(r for r in service.pending if r.operation == "saved_list")
cache.set_offline(False)
model.refresh()
print("ONLINE_REFRESH", [(r.operation, r.path) for r in service.pending if r.path == path])
service.resultReady.emit(before, {"kind": "entries", "entries": [{"path": path + "/stale", "name": "stale"}]})
service.resultReady.emit(before, {"kind": "status", "offline": True, "listed": True, "listed_at": 1000., "details": False, "empty": False, "has_dirs": True})
service.resultReady.emit(before, {"kind": "done"})
if before in service.pending: service.pending.remove(before)
for _ in range(8):
    app.processEvents()
print("ONLINE_RESULT", cache.offline, model.root.offline_listed_at, [n.path for n in model.root.children], [(r.operation, r.path) for r in service.pending if r.path == path])
details = next(r for r in service.pending if r.operation == "list" and r.path == path)
service.resultReady.emit(details, {"kind": "entries", "entries": [{"path": path + "/fresh", "name": "fresh"}]})
service.resultReady.emit(details, {"kind": "status", "details": True, "status": "nothing", "count": -1, "raw": [], "txy": [], "empty": False, "has_dirs": True, "signature": "new"})
service.resultReady.emit(details, {"kind": "done"})
service.pending.remove(details)
for _ in range(8):
    app.processEvents()
print("AFTER_ONLINE_DETAILS", [n.path for n in model.root.children])
model.close_cleanup()
service.shutdown()

# A requested save waiting behind another load.
service, cache = frozen()
cache.submit("ordinary-load", 0, path, "load", {})
cache.save("live-stop-save", path, {})
print("SAVE_BEFORE", list(cache._deferred_saves))
events = []
cache.resultReady.connect(lambda request, event: events.append(event["kind"]) if request.owner == "live-stop-save" else None)
cache.set_offline(True)
for _ in range(8):
    app.processEvents()
print("SAVE_AFTER", list(cache._deferred_saves), events, [(r.operation, r.payload.get("save")) for r in service.pending if r.path == path], cache.quit_saves())
service.shutdown()

# A retired cached read may still touch source if misrouted; a completed load is retained.
service, cache = frozen()
request = IORequest("finished-source-load", 0, path, "load", {}, 60.)
request.completed = True
service.active.append(request)
cache.set_offline(True)
print("COMPLETED_SOURCE_LOAD", request in service.active, request.cancelled.is_set(), IOService.finishes_offline(request))
if request in service.active: service.active.remove(request)
service.shutdown()

# A stale nested mount hint under a currently mounted different share.
from helab.io_ops.stores import _offline_mounts
from helab.utils.cache_paths import Mount
from helab.utils.data_roots import LocalVolumes
class Hints:
    def mount_hints(self):
        return {"/Volumes/lab/subdir": "smb://old-server/old-share"}
paths, volumes = _offline_mounts(Hints(), [Mount("//new-server/new-share", "/Volumes/lab", "smbfs", True)], LocalVolumes([]))
print("NESTED_HINT", paths.key("/Volumes/lab/subdir/run"))

# The listing freshness comparison is outside the write transaction.
from contextlib import contextmanager
from helab.io_ops.listings import listing_guard, save_listing, read_listing
from helab.utils.cache_store import CacheStore
key = "root://11111111-1111-1111-1111-111111111111/run"
root = str(scratch / "listing-race")
with CacheStore(root) as older, CacheStore(root) as newer:
    old_guard, new_guard = listing_guard(older, key), listing_guard(newer, key)
    def status(at):
        return {"scanned_at": at, "status": "nothing", "count": -1, "raw": [], "txy": [], "empty": False, "has_dirs": True}
    wait = older.waiting
    @contextmanager
    def interleaved(seconds):
        print("NEWER_LISTING_WRITE", save_listing(newer, new_guard, key, ["new"], status(2000.)))
        with wait(seconds):
            yield
    older.waiting = interleaved
    print("OLDER_LISTING_WRITE", save_listing(older, old_guard, key, ["old"], status(1000.)))
    print("LISTING_RACE_RESULT", read_listing(older, key).value)

