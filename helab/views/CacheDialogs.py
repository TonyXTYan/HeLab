"""The disk cache's questions to the user, one at a time: a save that doesn't fit (Make room),
an update to a cached folder over 80% of the budget (Save update), an analysis result that doesn't
fit (Make room or Discard, result caching R2), the 80% warning that pauses automatic loads of
new folders, and (caching v2, store-v4) the one-time question about an older HeLab's store-v3: Keep
using it, Ignore it or Clear it… (Q19.4, Q22.3). See roadmaps/cache-storage-and-settings.md."""
from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QWidget

from helab.utils import folder_cache
from helab.utils.accessible import identify_buttons
from helab.utils.folder_cache import FolderCache
from helab.utils.number_format import byte_size


def _name(path: str) -> str:
    return os.path.basename(path.rstrip(os.sep)) or path


def room_text(room: dict[str, Any] | None) -> str:
    """What Make room removes, from the helper's room plan: other folders' cached data, then (store-v4,
    D8) raw pulses whose raw files are still in their folders, then raw pulses that are the only copy,
    each of those folders named."""
    if not room:
        return "Make room removes the least recently used cached data of other folders until this fits."
    count = len(room.get("paths") or ())
    raw, only = list(room.get("raw_paths") or ()), list(room.get("only_copy_paths") or ())
    if not count and not raw and not only:
        return "There is room now: Make room saves it without removing anything."
    parts: list[str] = []
    if count:
        since = room.get("newest_last_used")
        when = ""
        if isinstance(since, (int, float)):
            day = datetime.fromtimestamp(since)
            when = f" not used since {day.day} {day:%b}"
        parts.append(f"Make room removes cached data for {count} folder{'' if count == 1 else 's'} "
                     f"({byte_size(int(room.get('bytes', 0)), 'disk')}){when}, least recently used first.")
    if raw:
        parts.append(f"{'Then it' if count else 'Make room'} removes the cached raw pulses of "
                     f"{len(raw)} folder{'' if len(raw) == 1 else 's'} (read again from their raw files when needed).")
    if only:
        names = ", ".join(_name(path) for path in only[:5]) + (" …" if len(only) > 5 else "")
        parts.append(f"It also removes cached raw pulses that are the only copy: their raw files are gone from "
                     f"{names}.")
    if raw or only:
        parts[-1] += f" ({byte_size(int(room.get('raw_bytes', 0)), 'disk')} of raw pulses in all.)"
    return " ".join(parts)


def room_items(room: dict[str, Any]) -> list[str]:
    """What the user was told Make room removes, as ``adopt``'s ``room_paths`` names it."""
    return ([str(path) for path in room.get("paths") or ()]
            + [f"raw:{path}" for path in room.get("raw_paths") or ()]
            + [f"raw-only:{path}" for path in room.get("only_copy_paths") or ()])


def legacy_text(legacy: dict[str, Any] | None) -> str:
    """store-v3 beside store-v4, for a question or a row: its size and whether it counts."""
    if not legacy or not legacy.get("present"):
        return ""
    size = byte_size(int(legacy.get("bytes") or 0), "disk")
    choice = legacy.get("choice")
    state = {"keep": "kept, counted in the budget", "ignore": "ignored"}.get(str(choice), "not answered yet: kept")
    return f"{size} · {state}"


def ask_clear_old_stores(parent: QWidget, cache: FolderCache, confirm: Callable[[str, str, str], bool] | None = None,
                         others: Callable[[], list[int]] | None = None) -> str:
    """Clear old stores… (Q28.5): store-v3 (any older store, as they come), after the user saw its size, and only
    while no other HeLab runs (as a cache move). The job's owner, or "" when nothing was asked of the store."""
    from helab.utils.cache_locks import other_instances
    from helab.utils.constants import app_folder
    legacy = cache.legacy or {}
    if not legacy.get("present"):
        return ""
    running = (others or (lambda: other_instances(app_folder())))()
    if running:
        QMessageBox.information(parent, "Clear old stores", "Another HeLab is running. Quit it first: it may still use "
                                "the older disk cache.")
        return ""
    text = (f"Remove the disk cache of an older HeLab (store-v3, {byte_size(int(legacy.get('bytes') or 0), 'disk')})? "
            "This HeLab no longer reads it; an older HeLab started later would begin an empty one. This can't be undone.")
    asked = (confirm("Clear old stores", text, "Remove") if confirm is not None
             else _confirm(parent, "Clear old stores", text))
    if not asked:
        return ""
    return cache.cache_admin("clear_legacy") or ""


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning, title, text, QMessageBox.StandardButton.Cancel, parent)
    remove = box.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
    identify_buttons(box, "disk_cache_clear_old")
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is remove


def result_room_text(room: dict[str, Any] | None) -> str:
    """What Make room removes for an analysis result: other saved results only, never cached data."""
    if not room:
        return ("Make room removes the least recently shown saved analysis results until this fits. "
                "Cached data isn't touched.")
    count = len(room.get("result_ids") or ())
    if not count:
        return "There is room now: Make room saves it without removing anything."
    since = room.get("newest_last_used")
    when = ""
    if isinstance(since, (int, float)):
        day = datetime.fromtimestamp(since)
        when = f" not shown since {day.day} {day:%b}"
    return (f"Make room removes {count} saved analysis result{'' if count == 1 else 's'} "
            f"({byte_size(int(room.get('bytes', 0)), 'disk')}){when}, least recently shown first. "
            "Cached data isn't touched.")


# The store-v3 question's place in ``CacheDialogs._asking`` (no pending save of that id exists).
LEGACY_QUESTION = "store-v3"


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
        # The store-v3 question (store-v4): asked once a session until answered; closing it answers nothing.
        self._legacy_asked = False
        self._detached = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.next)
        cache.pendingSavesChanged.connect(self.next)
        cache.diskNearlyFull.connect(self._nearly_full)
        cache.autoLoadPauseChanged.connect(self._pause_changed)
        cache.cacheAdminDone.connect(self._answer_done)
        cache.legacyChanged.connect(self.next)

    def detach(self) -> None:
        self._detached = True
        self._retry.stop()
        self.cache.pendingSavesChanged.disconnect(self.next)
        self.cache.diskNearlyFull.disconnect(self._nearly_full)
        self.cache.autoLoadPauseChanged.disconnect(self._pause_changed)
        self.cache.cacheAdminDone.disconnect(self._answer_done)
        self.cache.legacyChanged.disconnect(self.next)
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
        paths = sorted(room.get("paths") or room.get("result_ids") or ()) if isinstance(room, dict) else None
        return json.dumps([kind, paths, folder_cache.store_options().get("budget")])

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
        return sorted([*self.cache.pending_saves.values(), *self.cache.pending_results.values()],
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
            if (not pending_id or pending_id in pending and self.question(pending[pending_id]) == question
                    or pending_id == LEGACY_QUESTION):
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
        elif self._legacy_due():
            self._ask_legacy()
        elif self._warn_full and self.cache.auto_load_paused:
            self._ask_nearly_full()
        else:
            self._warn_full = False

    def _open(self, box: QMessageBox, asking: tuple[str, str], answer: Callable[[QAbstractButton | None], None]) -> None:
        identify_buttons(box, "disk_cache_question")
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
        budget = int(folder_cache.store_options().get("budget") or entry.get("budget") or 0)
        # The newest measurement: a save restored from the store (after a restart) has none of its own.
        usage = int(self.cache.disk_usage if self.cache.disk_usage is not None else entry.get("usage") or 0)
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Question)
        old_stores: QAbstractButton | None = None
        if entry.get("result"):
            # An analysis result (R2): only other saved results make room for it.
            label = str(entry.get("label") or "a plot")
            box.setWindowTitle("Disk cache full")
            box.setText(f"Not enough room in the disk cache to save {label}'s result for {_name(path)} "
                        f"({byte_size(int(entry.get('bytes', 0)), 'disk')}, {byte_size(usage, 'disk')} of {byte_size(budget, 'disk')} used).")
            if kind == "too_large":
                box.setInformativeText("Removing every other saved analysis result isn't enough. Free space in "
                                       "Settings → Cache (Clear cached data, Remove old entries) or raise the budget. "
                                       "The plot stays as it is.")
                confirm = None
            else:
                box.setInformativeText(result_room_text(entry.get("room")) + "\nThe plot stays as it is either way.")
                confirm = box.addButton("Make room", QMessageBox.ButtonRole.AcceptRole)
            decline = box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        elif kind == "needs_approval":
            growth = max(0, int(entry.get("bytes", 0)) - int(entry.get("replaces", 0)))
            box.setWindowTitle("Save the cache update?")
            box.setText(f"{_name(path)} changed: save the update to the disk cache "
                        f"(+{byte_size(growth, 'disk')}, {byte_size(usage + growth, 'disk')} of {byte_size(budget, 'disk')})?")
            box.setInformativeText("The disk cache is 80% full. Either way, the updated data stays in RAM.")
            confirm = box.addButton("Save update", QMessageBox.ButtonRole.AcceptRole)
            decline = box.addButton("Don't cache this update now", QMessageBox.ButtonRole.RejectRole)
        else:
            box.setWindowTitle("Disk cache full")
            box.setText(f"Not enough room in the disk cache for {_name(path)} "
                        f"({byte_size(int(entry.get('bytes', 0)), 'disk')}, {byte_size(usage, 'disk')} of {byte_size(budget, 'disk')} used).")
            if kind == "too_large":
                box.setInformativeText(f"{_name(path)} alone is larger than the disk cache budget. Raise the budget "
                                       "in Settings → Cache to cache it. The loaded data stays in RAM.")
                confirm = None
            else:
                box.setInformativeText(room_text(entry.get("room")) + "\nThe loaded data stays in RAM either way.")
                confirm = box.addButton("Make room", QMessageBox.ButtonRole.AcceptRole)
            if (self.cache.legacy or {}).get("counted"):
                # An older HeLab's store-v3 counts in the budget (D9, Q28.5): clearing it may make room instead.
                old_stores = box.addButton("Clear old stores…", QMessageBox.ButtonRole.ActionRole)
            decline = box.addButton("Don't cache this folder now", QMessageBox.ButtonRole.RejectRole)
        if pending_id in self._failed and confirm is not None:
            box.setInformativeText(f"{confirm.text()} failed: {self._failed[pending_id]}\n\n"
                                   + box.informativeText())
        box.setToolTip(path)
        box.setEscapeButton(decline)

        def answer(clicked: QAbstractButton | None) -> None:
            # Closing the question any other way is "not now": nothing is removed.
            result = bool(entry.get("result"))
            if old_stores is not None and clicked is old_stores:
                ask_clear_old_stores(self.parent_widget, self.cache)  # (Then this save is asked again.)
                return
            if confirm is not None and clicked is confirm:
                room = entry.get("room")
                listed: list[str] | None = None
                if isinstance(room, dict):
                    listed = [str(item) for item in room.get("result_ids") or ()] if result else room_items(room)
                self._answer(pending_id, question, "adopt_result" if result else "adopt",
                             make_room=kind == "over_budget", room_paths=listed)
            else:
                self._answer(pending_id, question, "discard_result" if result else "discard")
        self._open(box, (pending_id, question), answer)

    def _answer(self, pending_id: str, question: str, action: str, *, make_room: bool = False,
                room_paths: list[str] | None = None) -> None:
        params: dict[str, Any] = {"pending_id": pending_id}
        if action in ("adopt", "adopt_result"):
            params["make_room"] = make_room
            if make_room and room_paths is not None:
                # Removes exactly what the question said, or nothing (then asked again).
                params["room_ids" if action == "adopt_result" else "room_paths"] = room_paths
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
        if action in ("adopt", "adopt_result"):
            # Nothing was saved: ask again, saying why, so the user can retry.
            self._answered.pop(pending_id, None)
            self._failed[pending_id] = message
            self.next()
        else:
            # Still "not now"; the save waits in the store until it expires.
            self.notify(f"Disk cache: couldn't drop a waiting save — {message}")

    def _legacy_due(self) -> bool:
        legacy = self.cache.legacy or {}
        return bool(legacy.get("present")) and legacy.get("choice") is None and not self._legacy_asked

    def _ask_legacy(self) -> None:
        """Caching v2 (Q19.4): an older HeLab's store-v3 is in the cache folder. Keep using it (read for what
        the new cache lacks, counted in the budget; what HeLab does until answered, Q22.3), Ignore it (left
        on disk, unused) or Clear it… (asked again with its size). Closing it answers nothing."""
        self._legacy_asked = True
        legacy = self.cache.legacy or {}
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("An older disk cache")
        box.setText(f"The cache folder also holds an older HeLab's disk cache (store-v3, "
                    f"{byte_size(int(legacy.get('bytes') or 0), 'disk')}).")
        box.setInformativeText("Keep using it: HeLab reads its records and saved analysis where the new cache "
                               "has none, and it counts toward the disk budget. Ignore it: it stays on disk, unused. "
                               "Clear it: it is removed, after asking. Settings → Cache can change this later.")
        keep = box.addButton("Keep using it", QMessageBox.ButtonRole.AcceptRole)
        ignore = box.addButton("Ignore it", QMessageBox.ButtonRole.RejectRole)
        clear = box.addButton("Clear it…", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep)

        def answer(clicked: QAbstractButton | None) -> None:
            if clicked is keep:
                self.cache.cache_admin("legacy_choice", choice="keep")
            elif clicked is ignore:
                self.cache.cache_admin("legacy_choice", choice="ignore")
            elif clicked is clear:
                ask_clear_old_stores(self.parent_widget, self.cache)
        self._open(box, (LEGACY_QUESTION, "store-v3"), answer)

    def _ask_nearly_full(self) -> None:
        self._warn_full = False
        budget = int(folder_cache.store_options().get("budget") or 0)
        usage = int(self.cache.disk_usage or 0)
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Disk cache nearly full")
        share = usage / budget if budget else 1.0
        box.setText(f"Disk cache is {int(share * 100)}% full ({byte_size(usage, 'disk')} of {byte_size(budget, 'disk')}). "
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
