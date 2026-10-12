# Frozen I/O helpers must bypass GUI, caches and Dash initialization.
import sys
if "--helab-io-helper" in sys.argv:
    # Windowed PyInstaller executables may have no standard streams. Exchange
    # requests/results through local files instead of relying on console handles.
    helper_arg = sys.argv.index("--helab-io-helper")
    sys.stdin = open(sys.argv[helper_arg + 1], encoding="utf-8")
    sys.stdout = open(sys.argv[helper_arg + 2], "w", encoding="utf-8")
    from helab.io_helper import main as io_helper_main
    io_helper_main()
    raise SystemExit(0)

# Query provenance before importing Qt, opening settings/caches or starting Dash.
if "--version" in sys.argv:
    from helab.build_info import get_build_info
    if sys.stdout is not None:
        print(get_build_info().description())
    raise SystemExit(0)

# This Python file uses the following encoding: utf-8
import logging
import tempfile

import coloredlogs

# from helab.utils.loggingSetup import setup_logging
# setup_logging()
coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )


import platform
from typing import Any
import re
import subprocess
import sys
import os

from PyQt6.QtCore import QSettings, Qt, QThreadPool, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QMessageBox

from helab.resources.icons import StatusIcons, ToolIcons, IconsInitUtil
from helab.utils.constants import *
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
    settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
    waiting: list[QMessageBox] = []

    def wait() -> None:
        if not waiting:
            box = QMessageBox(QMessageBox.Icon.Information, "HeLab", "Another HeLab is moving the cache…",
                              QMessageBox.StandardButton.NoButton)
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
        return message
    message, instance = startup(app_folder(), recover, wait)
    for box in waiting:
        box.close()
    QApplication.instance().aboutToQuit.connect(instance.unlock)  # type: ignore[union-attr]
    _INSTANCE_LOCK.append(instance)
    return message


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
    if service.submit("startup-recovery", 0, app_dir, "cache_move", {"move": move}, timeout=math.inf):
        box = QMessageBox(QMessageBox.Icon.Information, "HeLab", "Finishing an interrupted cache move…",
                          QMessageBox.StandardButton.NoButton)
        box.show()
        loop.exec()
        box.close()
    service.resultReady.disconnect(event)
    return str(result[0]), bool(result[1])  # Not usable unless the helper said so.


# This instance's lock, held for the app's life.
_INSTANCE_LOCK: list[object] = []


def main() -> None:
    # setup_logging()
    _raise_fd_limit()
    logging.debug("this is a debugging message")
    logging.info("this is an informational message")
    logging.warning("this is a warning message")
    logging.error("this is an error message")
    logging.critical("this is a critical message")
    logging.fatal("this is a fatal message")

    logging.info(f"Platform: {sys.platform}, {platform.system()}, {platform.release()}, {platform.version()}, {platform.machine()}, {platform.processor()}")
    logging.info(f"{tempfile.gettempdir() = }")

    logging.info(f"Starting HeLab v{APP_VERSION} ({APP_COMMIT_HASH})")
    logging.info(APP_BUILD_INFO.description())

    # font_db = QFontDatabase()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # app.setStyleSheet("QWidget { background-color: #fafafa; }")
    if "SF Mono" in QFontDatabase.families():
        helab_mono_font = QFont("SF Mono", 12)
        logging.debug("Using SF Mono helab_mono_font.")
    else:
        helab_mono_font = QFont("Monospace", 12)
        logging.warning("SF Mono helab_mono_font not found. Using Monospace helab_mono_font instead.")
    app.setFont(helab_mono_font)

    IconsInitUtil.initialise_icons()

    # Before any cache is opened: wait out a cache move in another HeLab, finish or undo a move
    # a crash interrupted, and register this instance (roadmap S9).
    moved = _start_cache()

    main_window = HelabMainWindow()
    main_window.show()
    if moved:
        QTimer.singleShot(0, lambda: QMessageBox.information(main_window, "Disk cache", moved))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
