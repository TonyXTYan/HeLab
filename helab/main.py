# Frozen I/O helpers must bypass GUI, caches and Dash initialization.
import sys
if getattr(sys, "frozen", False):
    # A process the converter's helper spawned (``io_ops.convert``'s worker pool) runs here and exits.
    import multiprocessing
    multiprocessing.freeze_support()
if "--helab-io-helper" in sys.argv:
    # Windowed PyInstaller executables may have no standard streams. Exchange
    # requests/results through local files instead of relying on console handles.
    helper_arg = sys.argv.index("--helab-io-helper")
    sys.stdin = open(sys.argv[helper_arg + 1], encoding="utf-8")
    sys.stdout = open(sys.argv[helper_arg + 2], "w", encoding="utf-8")
    from helab.io_helper import main as io_helper_main
    io_helper_main()
    raise SystemExit(0)
# The try-import of a user script folder (Q49.3 (b), ``helab.scripts.probe``), in its own process: before
# any GUI, cache or Dash import (it makes its own offscreen QApplication).
if "--helab-script-probe" in sys.argv:
    probe_arg = sys.argv.index("--helab-script-probe")
    from helab.scripts.probe import main as probe_main
    raise SystemExit(probe_main(sys.argv[probe_arg + 1:probe_arg + 3]))


UPDATING = ("HeLab is being updated. It starts again by itself when the update has finished; start it then if it "
            "doesn't.")
UPDATING_COMMAND = "HeLab is being updated: run this again when the update has finished."


def _stop_during_update(command: bool) -> None:
    """While HeLab's updater changes this checkout's code and venv (it holds ``update.lock``), nothing of HeLab
    starts but the start the updater makes itself: checked here before the rest of HeLab is imported (the app,
    ``helab convert`` and ``helab cache``; not the helpers above, which belong to a HeLab already running, and
    which the updater waits for). The app and the converter check again once they hold their own lock, which
    is what makes it certain (``cache_locks.update_in_progress``); this one keeps a start from importing code
    that is being replaced. Read only: no file is made. An app folder that can't be read stops nothing."""
    from helab.utils.app_dirs import app_folder as _app_folder
    from helab.utils.cache_locks import update_in_progress
    try:
        if not update_in_progress(_app_folder()):
            return
    except OSError:
        return
    if command:
        if sys.stderr is not None:
            print(UPDATING_COMMAND, file=sys.stderr)
    else:
        _say_updating()
    raise SystemExit(1)


def _say_updating() -> None:
    """The app's start refused during an update: said in a window that closes itself, because a HeLab left
    waiting at a message would hold up the update it is told about (the updater waits for every process of
    this venv). Qt is the venv's, which may be half replaced: if it can't be shown, the line on the console
    is all."""
    if sys.stderr is not None:
        print(UPDATING, file=sys.stderr)
    try:
        from PyQt6.QtCore import QTimer as _QTimer
        from PyQt6.QtWidgets import QApplication as _QApplication, QMessageBox as _QMessageBox
        app = _QApplication.instance() or _QApplication(sys.argv[:1])
        box = _QMessageBox(_QMessageBox.Icon.Information, "HeLab is being updated", UPDATING)
        _QTimer.singleShot(UPDATING_SHOWN_MS, box.close)
        box.exec()
        del app
    except Exception:  # (Nothing to add: the update goes on, and starts HeLab when it is done.)
        pass


UPDATING_SHOWN_MS = 8000

# The headless converter (``helab convert --watch <folder>``, also ``HeLab convert …`` in the
# packaged app): before any Qt widgets, caches or Dash.
if len(sys.argv) > 1 and sys.argv[1] == "convert":
    _stop_during_update(command=True)
    from helab.convert_cli import main as convert_main
    raise SystemExit(convert_main(sys.argv[2:]))
# ``helab cache dump|export …`` (caching v2's .hlb files, read only): before any Qt widgets, caches or Dash too.
if len(sys.argv) > 1 and sys.argv[1] == "cache":
    _stop_during_update(command=True)
    from helab.cache_cli import main as cache_main
    raise SystemExit(cache_main(sys.argv[2:]))

# ``helab --help`` (A56.7): a short usage, before Qt, settings, caches, Dash or the one-app lock.
USAGE = """\
usage: helab [--geometry WxH+X+Y]   start HeLab (the app)
       helab --version              print HeLab's version and build, and exit
       helab --help                 print this help, and exit
       helab convert --watch FOLDER [options]
                                    the headless TXY converter (helab convert --help)
       helab cache dump|export ...  look into the disk cache's .hlb files, read only
                                    (helab cache --help)

  --geometry WxH+X+Y  this run's main window: W x H points, its top-left at X,Y
                      (a sign each; "-" for a screen left of or above the main one)
"""
if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
    if sys.stdout is not None:  # (A windowed frozen app may have none.)
        print(USAGE, end="")
    raise SystemExit(0)

# Query provenance before importing Qt, opening settings/caches or starting Dash.
if "--version" in sys.argv:
    from helab.build_info import get_build_info
    if sys.stdout is not None:
        print(get_build_info().description())
    raise SystemExit(0)

# The app itself: not while it is being updated (before Qt and the rest of HeLab are imported).
_stop_during_update(command=False)

# This Python file uses the following encoding: utf-8
import atexit
import logging
import tempfile

import coloredlogs

coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )


import platform
from typing import Any
import sys

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QMessageBox

from helab.resources.icons import IconsInitUtil
from helab.utils import app_log, console_tee, crash_file
from helab.utils.constants import (
    APP_BUILD_INFO, APP_COMMIT_HASH, APP_VERSION, app_folder, read_log_keep, record_cache_folder, start_cache_dir)
from helab.utils.settings_store import app_settings
from helab.views import quit_watch
from helab.views.HelabMainWindow import HelabMainWindow


def _raise_fd_limit(target: int = 10240) -> None:
    # macOS's default launchd/Finder-launch environment caps RLIMIT_NOFILE at 256
    # (vs. a typical interactive shell's much higher ulimit), which HeLab's
    # directory-scanning worker pools can exhaust, aborting Qt's event dispatcher.
    if sys.platform == "win32":
        return
    import resource
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logging.info(f"Raised file-descriptor limit (RLIMIT_NOFILE): {soft} -> {new_soft} (hard={hard})")
    except (ValueError, OSError) as e:
        logging.warning(f"Could not raise RLIMIT_NOFILE: {e}")


def _start_cache() -> str:
    """Resolve a leftover cache move and register this instance; what was repaired ("" if nothing)."""
    import time
    from helab.utils.cache_locks import startup
    settings = app_settings()
    waiting: list[QMessageBox] = []
    quitting: list[bool] = []

    def wait() -> None:
        if quitting:
            raise SystemExit(0)  # (Quit: nothing is held between these waits; the move goes on in the other HeLab.)
        if not waiting:
            box = startup_box("Another HeLab is moving the cache…",
                              "Quit ends this HeLab; start it again once the move has finished.", quitting)
            box.show()
            waiting.append(box)
        QApplication.processEvents()
        time.sleep(0.2)
    def recover(token: str) -> str:
        message, usable = _recover_in_helper(settings, token)
        # Still holding cache.lock: the setting may have changed, so use the folder it names now
        # (or, if the move couldn't be resolved, no disk cache this session).
        settings.sync()
        reason = ("The disk cache is off for this session: an interrupted cache move couldn't be finished. "
                  "HeLab tries again at the next start.")
        start_cache_dir(settings, usable=usable, reason=reason)
        record_cache_folder()  # (A44.2: for ``helab cache``; logged and ignored if it can't be written.)
        return message
    message, instance = startup(app_folder(), recover, wait)
    for box in waiting:
        box.blockSignals(True)  # (Closed because the move ended: not a Quit.)
        box.close()
    app = QApplication.instance()
    assert app is not None  # (main() makes it before starting the cache.)
    app.aboutToQuit.connect(instance.unlock)
    _INSTANCE_LOCK.append(instance)
    return message


def startup_box(text: str, informative: str, quitting: list[bool]) -> QMessageBox:
    """A box shown while startup waits (no event loop yet), with Quit (Q~3, Tony 2026-11-10: it had no button and
    no limit): Quit, or closing the box, appends to ``quitting``, which the waiting code checks."""
    from helab.utils.accessible import identify_buttons
    box = QMessageBox(QMessageBox.Icon.Information, "HeLab", text, QMessageBox.StandardButton.NoButton)
    box.setInformativeText(informative)
    box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    identify_buttons(box, "startup_wait")
    box.finished.connect(lambda _result: quitting.append(True))
    return box


def _recover_in_helper(settings: QSettings, token: str) -> tuple[str, bool]:
    """Recover an interrupted cache move in a helper process: it reads the store and may delete
    a folder, neither of which the GUI process does. Nothing to do without a move record."""
    import math
    from PyQt6.QtCore import QEventLoop
    from helab.utils.cache_move import read_record
    from helab.utils.cache_setting import settings_spec
    from helab.utils.io_service import get_io_service
    app_dir = app_folder()
    if read_record(app_dir) is None:
        return "", True
    service = get_io_service()
    result: list[Any] = ["", False]
    loop = QEventLoop()

    def event(request: object, event: dict[str, object]) -> None:
        if getattr(request, "owner", "") != "startup-recovery":
            return
        if event["kind"] == "move_recovered":
            result[0], result[1] = str(event["message"]), bool(event.get("usable"))
        elif event["kind"] in ("error", "cancelled"):
            result[0] = (f"An interrupted cache move couldn't be finished ({event.get('message', 'stopped')}). "
                         "HeLab tries again at the next start.")
        if event["kind"] in ("done", "error", "cancelled"):
            loop.quit()
    service.resultReady.connect(event)
    move = {"action": "recover", "app_dir": app_dir, "settings": settings_spec(settings), "token": token}
    quitting: list[bool] = []
    if service.submit("startup-recovery", 0, app_dir, "cache_move", {"move": move}, timeout=math.inf):
        box = startup_box("Finishing an interrupted cache move…",
                          "Quit ends HeLab now; the move is finished at the next start.", quitting)
        box.finished.connect(loop.quit)
        box.show()
        loop.exec()
        if not quitting:
            box.blockSignals(True)  # (Closed because the helper answered: not a Quit.)
            box.close()
    service.resultReady.disconnect(event)
    if quitting:
        # The record stays: the next start recovers the move again (each step is safe to redo after a stop).
        service.cancel("startup-recovery")
        logging.warning("Quit while an interrupted cache move was being finished; the next start finishes it")
        raise SystemExit(0)
    return str(result[0]), bool(result[1])  # Not usable unless the helper said so.


# This instance's lock, held for the app's life.
_INSTANCE_LOCK: list[object] = []
# The one-running-HeLab lock, held until the process ends (not at quit: it may still be saving).
_RUNNING_LOCK: list[object] = []


def _another_running() -> bool:
    """Whether another HeLab app runs on this computer (its app folder's ``running.lock``; an override's
    folder has its own), or HeLab is being updated (``update.lock``), which a message box then says; else
    this one holds the lock from now on. A lock that can't be checked (the app folder unwritable) doesn't
    stop HeLab: it is logged."""
    from helab.utils import cache_locks
    try:
        lock, pid = cache_locks.take_running(app_folder())
        # Its own lock first, the updater's second (``cache_locks.update_in_progress``): an updater that came
        # first holds ``update.lock`` by now, and one that comes later waits for ``running.lock``. (A lock that
        # wasn't free may have been the updater looking at it.)
        updating = cache_locks.update_in_progress(app_folder())
    except OSError as exc:
        logging.warning(f"Couldn't check for another running HeLab: {exc}")
        return False
    if updating:
        if lock is not None:
            lock.unlock()
        logging.warning(UPDATING)
        _say_updating()
        return True
    if lock is not None:
        _RUNNING_LOCK.append(lock)
        return False
    text = (f"HeLab is already running on this computer{f' (process {pid})' if pid.isdigit() else ''}. Use its "
            "window, or quit it before starting HeLab again.")
    logging.warning(text)
    QMessageBox.information(None, "HeLab is running", text)
    return True


def main() -> None:
    # The packaged app has no console: errors leave their trace in the app folder's log file, and
    # an unhandled exception is logged there and HeLab carries on (PyQt6 would end it).
    app_log.start_log_file(app_folder())
    # After a crash (LR-15): every thread's stack in logs/crash-<pid>.txt, the console's output in
    # console-<pid>.txt (C-level writes too), Qt's messages and Python's warnings in the log, and the last
    # run's crash named.
    app_log.start_crash_file(app_folder())
    console = console_tee.start(app_log.log_folder(app_folder()))
    if console is not None:
        atexit.register(console.stop)
    app_log.install_qt_messages()
    logging.captureWarnings(True)
    app_log.note_previous_crash(app_folder())
    app_log.catch_unhandled()
    _raise_fd_limit()
    logging.info(f"Platform: {sys.platform}, {platform.system()}, {platform.release()}, {platform.version()}, {platform.machine()}, {platform.processor()}")
    logging.info(f"{tempfile.gettempdir() = }")

    logging.info(f"Starting HeLab v{APP_VERSION} ({APP_COMMIT_HASH})")
    logging.info(APP_BUILD_INFO.description())

    # font_db = QFontDatabase()

    # --geometry WxH+X+Y: this run's window size and place (a test runner's fixed coordinates).
    geometry, argv = HelabMainWindow.take_geometry(sys.argv)
    app = QApplication(argv)
    # One HeLab per computer (Q39.1): a second start stops here, having opened no store, started no
    # helper and written no setting.
    if _another_running():
        sys.exit(1)
    app.setStyle("Fusion")
    # app.setStyleSheet("QWidget { background-color: #fafafa; }")
    if "SF Mono" in QFontDatabase.families():
        helab_mono_font = QFont("SF Mono", 12)
        logging.debug("Using SF Mono helab_mono_font.")
    else:
        helab_mono_font = QFont("Monospace", 12)
        logging.warning("SF Mono helab_mono_font not found. Using Monospace helab_mono_font instead.")
    app.setFont(helab_mono_font)
    from helab.views import tooltips
    tooltips.install(app)  # Long plain-text tooltips wrapped (LR-3).

    IconsInitUtil.initialise_icons()

    # Before any cache is opened: wait out a cache move in another HeLab, finish or undo a move
    # a crash interrupted, and register this instance (roadmap S9).
    moved = _start_cache()

    main_window = HelabMainWindow()
    if geometry is not None:
        main_window.apply_geometry(geometry)
    app_log.catch_unhandled(main_window.show_status_notice)
    main_window.show()
    # At most once a day, 30 s from now (Settings › General); only the app schedules it, never a test's window.
    main_window.update_check.schedule_startup()
    # Once the event loop turns: when the updater started this HeLab, tell it this version runs; then the last
    # update's outcome, once (the updater records it only after that mark, so the window polls for it).
    QTimer.singleShot(0, main_window.after_start)
    # Registered as a running instance by now, so other HeLabs keep its log file.
    main_window.old_logs.start(read_log_keep(app_settings()))
    if moved:
        QTimer.singleShot(0, lambda: QMessageBox.information(main_window, "Disk cache", moved))

    code = app.exec()
    quit_watch.exit_soon(code)  # Never left running without windows (helab/views/quit_watch.py).
    # And where its thread can't run (a teardown stuck in Python's last collection): ended from C (GT-2).
    crash_file.exit_after(quit_watch.GRACE + quit_watch.NOTE_SECONDS + 2.0)
    sys.exit(code)


if __name__ == "__main__":
    main()
