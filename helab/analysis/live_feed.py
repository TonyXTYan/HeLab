"""The newest revision of each folder Live watches (``LiveFeed``), which plots following Live
(``helab.analysis.follow.Follow``) are offered. Its signals are Qt's, so it lives apart from the
Qt-free follow logic."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from helab.analysis.dataset_view import DatasetView, revise, view_of
from helab.utils import events

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset


class LiveFeed(QObject):
    """The newest revision of each folder Live watches, for the plots following it.

    The main window publishes every dataset a Live tab shows; a dataset that adds shots becomes
    the next revision of the folder's view and is announced (``revised``). ``ended`` when Live
    stops for the folder. Memory only: nothing here reads a file."""
    revised = pyqtSignal(object)  # DatasetView
    ended = pyqtSignal(str)  # The folder's path.

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._latest: dict[str, DatasetView] = {}
        events.hub().watch_feed(self)  # Plots ask the hub whether Live watches a folder.

    def latest(self, path: str) -> Optional[DatasetView]:
        """The newest revision of ``path``'s data while Live watches it."""
        return self._latest.get(path)

    def paths(self) -> set[str]:
        return set(self._latest)

    def publish(self, dataset: Dataset, root: tuple[str, str, str] | None = None) -> DatasetView:
        """``dataset``, the data a Live tab now shows, as the newest revision of its folder."""
        base = self._latest.get(dataset.path)
        view = revise(base, dataset, root) if base is not None else view_of(dataset, root)
        self._latest[dataset.path] = view
        if view is not base:
            self.revised.emit(view)
        return view

    def stop(self, path: str) -> None:
        if self._latest.pop(path, None) is not None:
            self.ended.emit(path)
