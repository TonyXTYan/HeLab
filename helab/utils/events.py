"""HeLab's one place for events worth telling someone about (roadmaps/dld-front-panel-port.md,
Decided, "Hooks"): a low-count shot during Live, Live stopping on an error. Code that raises
such an event calls ``notify`` and nothing else, so hooks (sounds, scripts, remote notices)
can attach here later without touching it.

- ``notify(kind, message, ...)`` records an ``Event``, gives it to every hook (``add_hook``)
  and, for an event that asks for it (``desktop=True``), shows a desktop notification.
- **Once per key:** an event with a ``key`` (a shot's path, number and fingerprint) is
  delivered once; the same key again is ignored (the last ``SEEN_LIMIT`` keys are kept). No
  time limit (Tony, 2026-10-26): each shot's notification shows, a typical shot being ~30 s
  apart. Hooks get every event (``Event.shown`` says whether it asked for a notification).
- **Delivery** (``DesktopNotifier``): ``QSystemTrayIcon.showMessage`` where the system has a
  tray that shows messages, else the main window's status bar (``set_status_sink``) and the
  log. No new dependency.
- **Live:** ``is_live(path)`` says whether Live watches a folder now, from the main window's
  ``LiveFeed``s (each registers itself, ``watch_feed``), so a plot can tell a shot Live just
  added from a historical one without reaching the window. The tray icon is hidden again once
  Live watches no folder.

GUI thread only: plots call it from ``render``/``update``, never from ``compute``.
"""
from __future__ import annotations

import logging
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Protocol

LOW_COUNTS = "low_counts"  # a shot below a plot's low-count rule(s), during Live (Shot trends)
LIVE_ERROR = "live_error"  # Live stopped checking a folder on an error (LiveController._live_halt)
CLOCK_SKEW = "clock_skew"  # a folder's files dated ahead of this computer's clock (ClockSkewWarning)
DAMAGED_RAW = "damaged_raw"  # a raw file Live's auto-convert found damaged (Q18.5), once per file
RAW_OVERWRITTEN = "raw_overwritten"  # a raw file overwritten in place since store-v4 cached it (Q28.6), once per shot
SEEN_LIMIT = 4096
HISTORY_LIMIT = 256


@dataclass(frozen=True)
class Event:
    kind: str
    message: str
    title: str = "HeLab"
    data: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    at: float = 0.0  # wall-clock time
    desktop: bool = False  # it asked for a desktop notification
    shown: bool = False  # … and it was shown (delivered, or its delivery failed and was logged)


Hook = Callable[[Event], None]


class Notifier(Protocol):
    def deliver(self, title: str, message: str) -> str:
        """Show the notification; how (``tray``, ``status``, ``log``)."""
        ...


class _Feed(Protocol):
    def paths(self) -> set[str]: ...


class DesktopNotifier:
    """A system notification from a tray icon (made when first needed), else the status bar's
    notice and a log line."""

    def __init__(self) -> None:
        self._tray: Any = None
        self._status: Optional[weakref.WeakMethod[Callable[..., None]]] = None
        self._status_function: Optional[Callable[[str], None]] = None

    def set_status_sink(self, sink: Optional[Callable[..., None]]) -> None:
        """Where a notification goes without a tray: the main window's ``show_status_notice``
        (held weakly when it is a bound method, so the window can close)."""
        self._status, self._status_function = None, None
        if sink is None:
            return
        if hasattr(sink, "__self__") and hasattr(sink, "__func__"):
            self._status = weakref.WeakMethod(sink)
        else:
            self._status_function = sink

    def _sink(self) -> Optional[Callable[[str], None]]:
        if self._status is not None:
            return self._status()
        return self._status_function

    def _tray_icon(self) -> Any:
        from PyQt6.QtWidgets import QApplication, QStyle, QSystemTrayIcon
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return None
        if not (QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()):
            return None
        if self._tray is not None:
            try:
                self._tray.isVisible()
            except RuntimeError:  # Its Qt object went with the app (tests, quitting): made again.
                self._tray = None
        if self._tray is None:
            icon = app.windowIcon()
            if icon.isNull():
                style = app.style()
                if style is not None:
                    icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            self._tray = QSystemTrayIcon(icon, app)
            self._tray.setToolTip("HeLab")
        if not self._tray.isVisible():
            self._tray.show()
        return self._tray

    def hide(self) -> None:
        """Take the tray icon away (Live watches no folder any more); the next notification shows
        it again."""
        if self._tray is None:
            return
        try:
            self._tray.hide()
        except RuntimeError:  # Its Qt object is gone already.
            self._tray = None

    def deliver(self, title: str, message: str) -> str:
        try:
            tray = self._tray_icon()
        except Exception:  # A broken tray must never break a plot.
            logging.exception("System notification failed")
            tray = None
        if tray is not None:
            from PyQt6.QtWidgets import QSystemTrayIcon
            tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 10_000)
            logging.info("%s: %s", title, message)
            return "tray"
        logging.warning("%s: %s", title, message)
        sink = self._sink()
        if sink is not None:
            sink(f"{title}: {message}")
            return "status"
        return "log"


class EventHub:
    def __init__(self, notifier: Optional[Notifier] = None) -> None:
        self.desktop = DesktopNotifier()
        self.notifier: Notifier = notifier if notifier is not None else self.desktop
        self._hooks: list[Hook] = []
        self._seen: OrderedDict[Any, None] = OrderedDict()
        self.history: list[Event] = []  # the newest ``HISTORY_LIMIT`` events, for a later log view
        self._feeds: weakref.WeakSet[Any] = weakref.WeakSet()

    # Hooks

    def add_hook(self, hook: Hook) -> Callable[[], None]:
        """Call ``hook`` with every event from now on; returns what removes it."""
        self._hooks.append(hook)

        def remove() -> None:
            if hook in self._hooks:
                self._hooks.remove(hook)
        return remove

    # Live

    def watch_feed(self, feed: _Feed) -> None:
        """A ``LiveFeed`` whose folders count as watched by Live (held weakly). When Live stops
        watching its last folder (``ended``), the tray icon goes."""
        try:
            ended = getattr(feed, "ended", None)
            if ended is not None:
                ended.connect(self._live_ended)
        except RuntimeError:  # Its Qt object is gone (its window closed): it watches nothing.
            return
        self._feeds.add(feed)

    def _live_ended(self, path: str) -> None:
        try:
            live = any(feed.paths() for feed in list(self._feeds))
        except RuntimeError:
            live = False
        if not live:
            self.desktop.hide()

    def is_live(self, path: str) -> bool:
        return any(path in feed.paths() for feed in list(self._feeds))

    # Events

    def seen(self, key: Any) -> bool:
        return key in self._seen

    def notify(self, kind: str, message: str, *, title: str = "HeLab", key: Any = None, desktop: bool = False,
               **data: Any) -> Optional[Event]:
        """Record an event and give it to the hooks; with ``desktop``, show it. None when ``key``
        was delivered before (nothing happens)."""
        if key is not None:
            if key in self._seen:
                return None
            self._seen[key] = None
            while len(self._seen) > SEEN_LIMIT:
                self._seen.popitem(last=False)
        if desktop:
            try:
                data = {**data, "delivered": self.notifier.deliver(title, message)}
            except Exception:
                logging.exception("Notification failed: %s", message)
        event = Event(kind, message, title, MappingProxyType(dict(data)), time.time(), desktop, desktop)
        self.history.append(event)
        del self.history[:-HISTORY_LIMIT]
        for hook in list(self._hooks):
            try:
                hook(event)
            except Exception:  # A hook never breaks what raised the event.
                logging.exception("Event hook failed for %s", kind)
        return event


_hub: Optional[EventHub] = None


def hub() -> EventHub:
    """The app's one ``EventHub``."""
    global _hub
    if _hub is None:
        _hub = EventHub()
    return _hub


def reset(notifier: Optional[Notifier] = None) -> EventHub:
    """A fresh hub (tests: with a fake notifier); the Live feeds stay registered."""
    global _hub
    feeds = list(_hub._feeds) if _hub is not None else []
    _hub = EventHub(notifier)
    for feed in feeds:
        _hub.watch_feed(feed)
    return _hub


def notify(kind: str, message: str, **options: Any) -> Optional[Event]:
    """``hub().notify``: the one call code raising an event makes."""
    return hub().notify(kind, message, **options)
