"""The disk cache's questions to the user, one at a time: a save that doesn't fit (Make room),
an update to a cached folder over 80% of the budget (Save update), and the 80% warning that
pauses automatic loads of new folders. See roadmaps/cache-storage-and-settings.md."""
from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QWidget

from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.number_format import byte_size


def _name(path: str) -> str:
    return os.path.basename(path.rstrip(os.sep)) or path


def room_text(room: dict[str, Any] | None) -> str:
    """What Make room removes, from the helper's room plan."""
    if not room:
        return "Make room removes the least recently used cached data of other folders until this fits."
    count = len(room.get("paths") or ())
    if not count:
        return "There is room now: Make room saves it without removing anything."
    since = room.get("newest_last_used")
    when = ""
    if isinstance(since, (int, float)):
        day = datetime.fromtimestamp(since)
        when = f" not used since {day.day} {day:%b}"
    return (f"Make room removes cached data for {count} folder{'' if count == 1 else 's'} "
            f"({byte_size(int(room.get('bytes', 0)))}){when}, least recently used first.")


class CacheDialogs(QObject):
    """Asks the disk cache's questions over ``parent``, never more than one at a time.

    Pending saves come first (each answer applies to exactly the ``pending_id`` it shows),
    then the 80% warning. A question whose pending save is gone (answered elsewhere,
    superseded or expired) is closed without an answer.
    """
    RETRY_MS = 1000

    def __init__(self, cache: FolderCache, parent: QWidget, open_purge_settings: Callable[[], None],
                 notify: Callable[[str], None] = logging.warning) -> None:
        super().__init__(parent)
        self.cache = cache
        self.parent_widget = parent
        self.open_purge_settings = open_purge_settings
        self.notify = notify
        self.dialog: QMessageBox | None = None
        # The pending save the open dialog asks about, and the question it asks ("" for the 80% warning).
        self._asking: tuple[str, str] = ("", "")
        # Pending saves already answered, by the question answered: a different question (e.g. Save
        # update turning into Make room) is asked again.
        self._answered: dict[str, str] = {}
        # The jobs carrying answers (owner → pending_id, action), and why a Make room or
        # Save update failed (pending_id → message), shown when it is asked again.
        self._answers: dict[str, tuple[str, str]] = {}
        self._failed: dict[str, str] = {}
        self._warn_full = False
        self._detached = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.next)
        cache.pendingSavesChanged.connect(self.next)
        cache.diskNearlyFull.connect(self._nearly_full)
        cache.autoLoadPauseChanged.connect(self._pause_changed)
        cache.cacheAdminDone.connect(self._answer_done)

    def detach(self) -> None:
        self._detached = True
        self._retry.stop()
        self.cache.pendingSavesChanged.disconnect(self.next)
        self.cache.diskNearlyFull.disconnect(self._nearly_full)
        self.cache.autoLoadPauseChanged.disconnect(self._pause_changed)
        self.cache.cacheAdminDone.disconnect(self._answer_done)
        self._close()

    @staticmethod
    def question(entry: dict[str, Any]) -> str:
        """Which question a pending save needs now, and what it says: a new room plan or
        budget makes it a different question (asked again; an open one is replaced)."""
        room = entry.get("room")
        impossible = entry.get("reason") == "over_budget" and isinstance(room, dict) and not room.get("possible", True)
        kind = "too_large" if impossible else str(entry.get("reason", ""))
        if kind == "needs_approval":
            return kind
        paths = sorted(room.get("paths") or ()) if isinstance(room, dict) else None
        return json.dumps([kind, paths, store_options().get("budget")])

    @staticmethod
    def kind(question: str) -> str:
        return question if question == "needs_approval" else str(json.loads(question)[0])

    def _nearly_full(self) -> None:
        # Asked after the event that crossed 80%: a save it held is asked about first.
        self._warn_full = True
        QTimer.singleShot(0, self.next)

    def _pause_changed(self, paused: bool) -> None:
        if not paused:
            # Below 80% again (or ignored): the warning no longer applies.
            self._warn_full = False
            if self.dialog is not None and self._asking == ("", "full"):
                self._close()
                self.next()

    def _close(self) -> None:
        dialog, self.dialog, self._asking = self.dialog, None, ("", "")
        if dialog is not None:
            # Unanswered: no ``finished`` handler runs. (close() would be refused by a
            # question without an escape button.)
            dialog.blockSignals(True)
            dialog.done(0)
            dialog.deleteLater()

    def _pending(self) -> list[dict[str, Any]]:
        return sorted(self.cache.pending_saves.values(),
                      key=lambda entry: float(entry.get("created_at") or 0))

    def next(self) -> None:
        """Ask the next question, if none is open."""
        if self._detached:
            return
        pending = {entry["pending_id"]: entry for entry in self._pending() if entry.get("pending_id")}
        for answered in set(self._answered) - set(pending):
            del self._answered[answered]
        for failed in set(self._failed) - set(pending):
            del self._failed[failed]
        if self.dialog is not None:
            pending_id, question = self._asking
            if not pending_id or pending_id in pending and self.question(pending[pending_id]) == question:
                return
            self._close()  # Its save was answered elsewhere, superseded, expired or changed.
        modal = QApplication.activeModalWidget()
        if modal is not None:
            self._retry.start(self.RETRY_MS)  # e.g. Settings is open: ask when it closes.
            return
        entry = next((entry for entry in pending.values()
                      if self._answered.get(entry["pending_id"]) != self.question(entry)), None)
        if entry is not None:
            self._ask_pending(entry)
        elif self._warn_full and self.cache.auto_load_paused:
            self._ask_nearly_full()
        else:
            self._warn_full = False

    def _open(self, box: QMessageBox, asking: tuple[str, str], answer: Callable[[QAbstractButton | None], None]) -> None:
        self.dialog, self._asking = box, asking

        def finished() -> None:
            clicked = box.clickedButton()
            if self.dialog is box:
                self.dialog, self._asking = None, ("", "")
            box.deleteLater()
            answer(clicked)
            QTimer.singleShot(0, self.next)
        box.finished.connect(finished)
        box.open()

    def _ask_pending(self, entry: dict[str, Any]) -> None:
        pending_id, path = entry["pending_id"], entry.get("path", "")
        question = self.question(entry)
        kind = self.kind(question)
        # The budget in effect now (Settings may have changed it since the save was held).
        budget = int(store_options().get("budget") or entry.get("budget") or 0)
        # The newest measurement: a save restored from the store (after a restart) has none of its own.
        usage = int(self.cache.disk_usage if self.cache.disk_usage is not None else entry.get("usage") or 0)
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Question)
        if kind == "needs_approval":
            growth = max(0, int(entry.get("bytes", 0)) - int(entry.get("replaces", 0)))
            box.setWindowTitle("Save the cache update?")
            box.setText(f"{_name(path)} changed: save the update to the disk cache "
                        f"(+{byte_size(growth)}, {byte_size(usage + growth)} of {byte_size(budget)})?")
            box.setInformativeText("The disk cache is 80% full. Either way, the updated data stays in RAM.")
            confirm = box.addButton("Save update", QMessageBox.ButtonRole.AcceptRole)
            decline = box.addButton("Don't cache this update now", QMessageBox.ButtonRole.RejectRole)
        else:
            box.setWindowTitle("Disk cache full")
            box.setText(f"Not enough room in the disk cache for {_name(path)} "
                        f"({byte_size(int(entry.get('bytes', 0)))}, {byte_size(usage)} of {byte_size(budget)} used).")
            if kind == "too_large":
                box.setInformativeText(f"{_name(path)} alone is larger than the disk cache budget. Raise the budget "
                                       "in Settings → Cache to cache it. The loaded data stays in RAM.")
                confirm = None
            else:
                box.setInformativeText(room_text(entry.get("room")) + "\nThe loaded data stays in RAM either way.")
                confirm = box.addButton("Make room", QMessageBox.ButtonRole.AcceptRole)
            decline = box.addButton("Don't cache this folder now", QMessageBox.ButtonRole.RejectRole)
        if pending_id in self._failed and confirm is not None:
            box.setInformativeText(f"{confirm.text()} failed: {self._failed[pending_id]}\n\n"
                                   + box.informativeText())
        box.setToolTip(path)
        box.setEscapeButton(decline)

        def answer(clicked: QAbstractButton | None) -> None:
            # Closing the question any other way is "not now": nothing is removed.
            if confirm is not None and clicked is confirm:
                room = entry.get("room")
                self._answer(pending_id, question, "adopt", make_room=kind == "over_budget",
                             room_paths=list(room.get("paths") or ()) if isinstance(room, dict) else None)
            else:
                self._answer(pending_id, question, "discard")
        self._open(box, (pending_id, question), answer)

    def _answer(self, pending_id: str, question: str, action: str, *, make_room: bool = False,
                room_paths: list[str] | None = None) -> None:
        params: dict[str, Any] = {"pending_id": pending_id}
        if action == "adopt":
            params["make_room"] = make_room
            if make_room and room_paths is not None:
                # Removes exactly what the question said, or nothing (then asked again).
                params["room_paths"] = room_paths
        self._answered[pending_id] = question
        self._failed.pop(pending_id, None)
        owner = self.cache.cache_admin(action, **params)
        if owner:
            self._answers[owner] = (pending_id, action)
        else:
            logging.warning("Disk cache %s %s: not queued; asking again", action, pending_id)
            del self._answered[pending_id]
            self._retry.start(5 * self.RETRY_MS)

    def _answer_done(self, owner: str, action: str, message: str) -> None:
        """An answer's job ended; if it failed, nothing changed in the store."""
        pending_id, action = self._answers.pop(owner, ("", action))
        if not pending_id or not message:
            return
        if action == "adopt":
            # Nothing was saved: ask again, saying why, so the user can retry.
            self._answered.pop(pending_id, None)
            self._failed[pending_id] = message
            self.next()
        else:
            # Still "not now"; the save waits in the store until it expires.
            self.notify(f"Disk cache: couldn't drop a waiting save — {message}")

    def _ask_nearly_full(self) -> None:
        self._warn_full = False
        budget = int(store_options().get("budget") or 0)
        usage = int(self.cache.disk_usage or 0)
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Disk cache nearly full")
        share = usage / budget if budget else 1.0
        box.setText(f"Disk cache is {int(share * 100)}% full ({byte_size(usage)} of {byte_size(budget)}). "
                    "Automatic loading of new folders is paused until you free space.")
        box.setInformativeText("Folders with cached data still open from the cache. Loading a folder yourself "
                               "(right-click › Load data) still works.")
        # No escape button: the pause stays unless the user chooses Ignore.
        purge = box.addButton("Open purge settings", QMessageBox.ButtonRole.AcceptRole)
        ignore = box.addButton("Ignore this time", QMessageBox.ButtonRole.ActionRole)

        def answer(clicked: QAbstractButton | None) -> None:
            if clicked is purge:
                QTimer.singleShot(0, self.open_purge_settings)
            elif clicked is ignore:
                self.cache.ignore_disk_nearly_full()
        self._open(box, ("", "full"), answer)
