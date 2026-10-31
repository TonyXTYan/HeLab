"""Moving the disk cache folder while HeLab stays open (roadmap S9, Settings → General → Change…).

1. A helper checks the target (writable, empty or new, not inside the cache, not a network or
   synced folder, enough free space) and measures the cache; the user confirms.
2. ``cache.lock`` is taken (refused while another HeLab runs); every helper that opens the cache
   is held and stopped, and the move starts once their exits are confirmed.
3. A helper renames the folder (same disk) or checkpoints, copies and verifies it, recording
   each step in ``cache-move.json`` (:mod:`helab.utils.cache_move`). Cancel works until the
   copy is verified; a rename has no cancel point.
4. The cutover: the setting is written and synced, then recorded. HeLab switches to the new
   folder in place (``set_cache_dir``) and resumes; a copy's old folder is deleted last, and
   the lock is held until then, so no other move can start meanwhile.

Failure or Cancel before the cutover keeps the source; after it, never roll back. Whatever a
crash interrupts is recovered at the next start. One mover per app (:func:`cache_mover`): it
outlives the Settings dialog that started it.
"""
from __future__ import annotations

import logging
import math
import os
import sys
from typing import Any, Callable
from uuid import uuid4

from PyQt6.QtCore import QObject, QSettings, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QAbstractButton, QMessageBox, QProgressDialog, QPushButton, QWidget

from helab.utils import cache_move
from helab.utils.accessible import identify, identify_buttons
from helab.utils.cache_locks import FileLock, lock_for_move
from helab.utils.cache_setting import write_cache_setting
from helab.utils.cache_store import live_layout
from helab.utils.constants import app_folder, cache_dir, set_cache_dir
from helab.utils.settings_defaults import DIR_CACHES_SETTING
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest
from helab.utils.number_format import byte_size

SHOW = "Show in Explorer" if sys.platform == "win32" else "Show in Finder"
FAILED = "Couldn't move the disk cache"


def cache_mover(cache: FolderCache, settings: QSettings) -> CacheMover:
    """The app's mover, kept with the cache so a move outlives the dialog that started it."""
    mover = cache.cache_mover
    if not isinstance(mover, CacheMover):
        mover = CacheMover(cache, settings)
        cache.cache_mover = mover
    mover.settings = settings
    return mover


class CacheMover(QObject):
    """One move at a time. ``switched`` when HeLab uses the new folder; ``finished(moved)`` when
    the move has ended either way (after a copy, once its old folder is deleted)."""
    switched = pyqtSignal()
    finished = pyqtSignal(bool)
    WAIT_MS = 100

    def __init__(self, cache: FolderCache, settings: QSettings, app_dir: str | None = None) -> None:
        super().__init__(cache)
        self.cache = cache
        self.service = cache.service
        self.window: QWidget | None = None
        self.settings = settings
        self.app_dir = app_dir or app_folder()
        self.owner = f"cache-move-{uuid4().hex}"
        self._generation = self._move_generation = 0
        self.move_id = ""
        self.source = self.target = ""
        self.method = ""
        self.bytes = 0
        self.lock: FileLock | None = None
        self.progress: QProgressDialog | None = None
        self.running = False
        # Started moving (checked and confirmed), and switched to the new folder.
        self.moving = self.switched_folder = False
        self._verified = self._cancelled = False
        self._abort_reason = ""
        # Replaceable in tests.
        self.confirm: Callable[[str], bool] = self._confirm
        self.report: Callable[[str, str, list[str]], None] = self._report
        self._wait = QTimer(self)
        self._wait.setInterval(self.WAIT_MS)
        self._wait.timeout.connect(self._start_when_stopped)
        self.service.resultReady.connect(self._event)

    def detach(self) -> None:
        self.service.resultReady.disconnect(self._event)

    @property
    def busy(self) -> bool:
        """Moving and not yet switched: the dialog that started it stays open meanwhile."""
        return self.moving and not self.switched_folder

    # The flow

    def change(self, target: str, window: QWidget | None = None) -> bool:
        """Start moving the cache to ``target``: check it first. False if a move is running."""
        if self.running:
            return False
        self.running, self.moving, self.switched_folder = True, False, False
        self._verified = self._cancelled = False
        self.window = window
        self.move_id = uuid4().hex
        self.source, self.target = cache_dir(), os.path.abspath(target)
        return self._submit("check")

    def _submit(self, action: str, *, after_move: bool = False, **extra: Any) -> bool:
        """Each step is its own request (a new generation: the previous one may not have exited
        yet). ``after_move``: the move's own key, so it starts only once the stopped move
        helper's exit is confirmed (a retry never runs beside the attempt it replaces)."""
        # (``layout``: the live store's, so the move keys on it even beside another layout's: C2-6.)
        move = {"action": action, "from": self.source, "to": self.target, "app_dir": self.app_dir,
                "method": self.method, "id": self.move_id, "token": self.move_id, "layout": live_layout(), **extra}
        if not after_move:
            self._generation += 1
        if action == "move":
            self._move_generation = self._generation
        generation = self._move_generation if after_move else self._generation
        if self.service.submit(self.owner, generation, self.source, "cache_move", {"move": move}, priority=True,
                               timeout=math.inf):
            return True
        if action == "cleanup":
            # After the cutover: the next start finishes deleting the old folder.
            logging.warning("Cache move cleanup not queued; it finishes at the next start")
            self._end(True)
            return False
        if action == "abort":
            self._undo_unknown("HeLab's work queue is full.")
            return False
        self._finish(False, FAILED, "HeLab's work queue is full. Try again in a moment.")
        return False

    def _undo_unknown(self, why: str) -> None:
        """Undoing the move didn't report where the store is (its helper failed or couldn't be
        queued): don't guess. The disk cache is off for this session, so no helper opens or
        creates a store in the wrong folder; the next start recovers the move from its record."""
        reason = (f"The disk cache is off for this session: a cache move couldn't be undone ({why}). "
                  "HeLab finishes it at the next start.")
        set_cache_dir(cache_dir(), reason, False)
        self._finish(False, FAILED, reason)

    def _event(self, request: IORequest, event: dict[str, Any]) -> None:
        if request.owner != self.owner:
            return
        try:
            self._handle(request, event)
        except Exception as exc:
            # Never leave the cache held or the move half-handled: the record (if any) stays for
            # the next start, and HeLab uses whichever folder it last switched to.
            logging.exception("Cache move")
            self._finish(self.switched_folder, FAILED,
                         f"Something went wrong ({exc}). HeLab uses {cache_dir()} and finishes the move at the next "
                         "start if needed.")

    def _handle(self, request: IORequest, event: dict[str, Any]) -> None:
        kind = event["kind"]
        action = request.payload["move"]["action"]
        if kind == "move_check":
            self._checked(event)
        elif kind == "move_progress":
            if self.progress is not None and event["total"]:
                self.progress.setValue(int(1000 * event["done"] / event["total"]))
        elif kind == "move_done":
            self._verified = True
            self._cutover(event["record"])
        elif kind == "move_failed":
            if not self._stuck_at_target(event, str(event["message"])):
                self._finish(False, FAILED, f"{event['message']} The cache stays in {self.source}.",
                             event.get("left") or [])
        elif kind == "move_aborted":
            left = event.get("left") or []
            if self._stuck_at_target(event, self._abort_reason.removesuffix(f" The cache stays in {self.source}.")):
                pass
            elif self._cancelled:
                self._finish(False, "Move cancelled", f"The cache stays in {self.source}.", left, quiet=not left)
            else:
                self._finish(False, FAILED, self._abort_reason, left)
        elif kind == "move_cleaned":
            left = event.get("left") or []
            if left:
                self.report("Old cache folder not fully deleted",
                            f"The cache now lives in {self.target}. The old folder {self.source} couldn't be fully "
                            "deleted; it is safe to delete. HeLab tries again at the next start.", left)
        elif kind in ("error", "cancelled") and not (self._cancelled and action == "move"):
            message = str(event.get("message") or "The move helper stopped.")
            if action == "check":
                self._finish(False, FAILED, message)
            elif action == "move":
                # The record says how far it got; abort undoes whatever came before the cutover.
                self._abort(f"{message} The cache stays in {self.source}.")
            elif action == "abort":
                self._undo_unknown(message)
            elif action == "cleanup":
                logging.warning("Cache move cleanup: %s", message)
        if kind in ("done", "error", "cancelled") and action == "cleanup":
            self._end(True)  # The old folder is gone (or left for the next start): other moves may start.

    def _stuck_at_target(self, event: dict[str, Any], message: str) -> bool:
        """Undoing the rename failed: the store is only at the target. Use it now (before I/O
        resumes); the record stays and the next start saves the setting."""
        if event.get("store_at") != self.target:
            return False
        self.settings.setValue(DIR_CACHES_SETTING, self.target)
        self._switch()
        self._finish(False, "Couldn't finish moving the disk cache",
                     f"{message} The cache is now in {self.target}; HeLab uses it and fixes the setting at the "
                     "next start.".strip(), [self.target])
        return True

    def _checked(self, event: dict[str, Any]) -> None:
        if event["problem"]:
            self._finish(False, "Can't move the disk cache here", event["problem"], [self.target])
            return
        self.method, self.bytes = str(event["method"]), int(event["bytes"])
        if not self.confirm(f"HeLab pauses loading and folder checks while it moves the cache "
                            f"({byte_size(self.bytes, 'disk')}) to {self.target}."):
            self._finish(False, "", "", quiet=True)
            return
        if cache_move.read_record(self.app_dir) is not None:
            self._finish(False, "Can't move the disk cache now",
                         "An earlier cache move hasn't finished (e.g. its old folder couldn't be deleted). "
                         "Restart HeLab to finish it, then try again.")
            return
        self.lock, reason = lock_for_move(self.app_dir, self.move_id)
        if self.lock is None:
            self._finish(False, "Can't move the disk cache now", reason)
            return
        # Pause: no helper opens the cache until the move has ended.
        self.moving = True
        self.service.hold_cache()
        self._show_progress()
        self._wait.start()
        self._start_when_stopped()

    def _start_when_stopped(self) -> None:
        if self.service.cache_busy():
            return  # Waiting for every stopped helper's exit to be confirmed.
        self._wait.stop()
        if self._cancelled:
            self._finish(False, "Move cancelled", "", quiet=True)
            return
        if self.progress is not None:
            self.progress.setLabelText(f"Moving the disk cache to {self.target}…")
            if self.method == cache_move.RENAME:
                self.progress.setCancelButton(None)  # A rename has no cancel point; it's instant.
        self._submit("move")

    def _show_progress(self) -> None:
        progress = QProgressDialog("Waiting for loads and folder checks to stop…", "Cancel", 0, 1000, self.window)
        progress.setWindowTitle("Moving the disk cache")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self.cancel)
        for button in progress.findChildren(QPushButton):
            identify(button, "cache_move_cancel")
        progress.show()
        self.progress = progress

    def cancel(self) -> None:
        """Until the copy is verified: stop, discard the copy and keep the source."""
        if not self.moving or self._verified or self._cancelled:
            return
        if self.method == cache_move.RENAME and not self._wait.isActive():
            return  # The rename has started: it can't be cancelled.
        self._cancelled = True
        if self._wait.isActive():
            return  # Not started yet: ends once the other helpers have stopped.
        self.service.cancel(self.owner)
        # Runs once the stopped helper's exit is confirmed (same request key).
        self._submit("abort", after_move=True, before_cutover=True)

    def _abort(self, reason: str) -> None:
        self._abort_reason = reason
        self._submit("abort", before_cutover=True)

    def _cutover(self, record: dict[str, Any]) -> None:
        if self.progress is not None:
            self.progress.setLabelText("Switching to the new folder…")
            self.progress.setCancelButton(None)  # From here the switch finishes, or the next start does.
        written: list[bool] = []

        def write(path: str) -> bool:
            written.append(write_cache_setting(self.settings, path))
            return written[-1]
        try:
            updated = cache_move.cutover(self.app_dir, record, write)
        except OSError as exc:
            if not (written and written[-1]):
                raise
            # The setting names the new folder (the cutover happened); only recording it failed.
            # The record stays at its last step, which the next start finishes from.
            logging.warning("Cache move: the cutover couldn't be recorded: %s", exc)
            self._switch()
            self._finish(True, "Couldn't finish moving the disk cache",
                         f"HeLab now uses {self.target} but couldn't record it; it finishes the move (deleting "
                         f"{self.source} if it was copied) at the next start. ({exc.strerror or exc})")
            return
        if updated is None:
            self._setting_failed(record)
            return
        self._switch()
        if record["method"] == cache_move.COPY:
            self._resume()
            self._submit("cleanup")  # Not held: it opens no cache. The lock is kept until it ends.
            return
        try:
            cache_move.cleanup(self.app_dir, updated)  # A rename leaves nothing to delete but the record.
        except OSError as exc:
            logging.warning("Cache move record not deleted; the next start does: %s", exc)
        self._finish(True, "", "", quiet=True)

    def _setting_failed(self, record: dict[str, Any]) -> None:
        reason = "HeLab couldn't save the new cache folder setting."
        # A failed write can leave the attempted value in memory, to be saved later: put it back.
        self.settings.setValue(DIR_CACHES_SETTING, self.source)
        if record["method"] == cache_move.COPY:
            self._abort(f"{reason} The cache stays in {self.source}.")
            return
        if cache_move.undo_rename(self.app_dir, record):
            self._finish(False, FAILED, f"{reason} The cache stays in {self.source}.")
            return
        # The renamed folder is the only store: use it now; the next start fixes the setting.
        self.settings.setValue(DIR_CACHES_SETTING, self.target)
        self._switch()
        self._finish(False, "Couldn't finish moving the disk cache",
                     f"{reason} HeLab uses {self.target} for now and fixes the setting at the next start.",
                     [self.target])

    def _switch(self) -> None:
        set_cache_dir(self.target)
        self.switched_folder = True
        self.switched.emit()

    def _resume(self) -> None:
        """Close the progress window and let helpers open the cache again."""
        self._wait.stop()
        if self.progress is not None:
            self.progress.canceled.disconnect(self.cancel)
            self.progress.close()
            self.progress.deleteLater()
            self.progress = None
        if self.service.cache_hold:
            self.service.release_cache()

    def _end(self, moved: bool) -> None:
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None
        was_running, self.running, self.moving = self.running, False, False
        if was_running:
            self.finished.emit(moved)

    def _finish(self, moved: bool, title: str, text: str, folders: list[str] | None = None,
                *, quiet: bool = False) -> None:
        self._resume()
        self._end(moved)
        if not quiet and title:
            self.report(title, text, folders or [])

    # Dialogs

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self.window, "Move the disk cache?", text,
                                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                                    ) == QMessageBox.StandardButton.Ok

    def _report(self, title: str, text: str, folders: list[str]) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=self.window)
        buttons: list[tuple[QAbstractButton | None, str]] = []
        for folder in folders:
            label = SHOW if len(folders) == 1 else f"{SHOW}: {os.path.basename(folder.rstrip(os.sep)) or folder}"
            buttons.append((box.addButton(label, QMessageBox.ButtonRole.ActionRole), folder))
        box.addButton(QMessageBox.StandardButton.Ok)
        identify_buttons(box, "cache_move_done")
        box.exec()
        clicked = box.clickedButton()
        chosen = next((folder for button, folder in buttons if clicked is not None and button is clicked), "")
        if chosen:
            QDesktopServices.openUrl(QUrl.fromLocalFile(_existing(chosen)))


def _existing(path: str) -> str:
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path
