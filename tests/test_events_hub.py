"""The event hub (``helab/utils/events.py``): once per key, with no time limit (Tony,
2026-10-26: no per-minute cap), hooks, and delivery by tray, status bar or log.

Each test makes its own ``EventHub`` with a fake notifier, so the app's hub is never
touched (tests of the module-level ``hub``/``notify``/``reset`` patch ``events._hub``). No real
desktop notification is shown: the tray class is a fake wherever a tray is available.
"""
from __future__ import annotations

import logging
import time
from types import MappingProxyType
from typing import Any, Callable, Iterator, Optional

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from helab.utils import events

FOLDER = "/data/root/run_A"
OTHER = "/data/root/run_B"


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, title: str, message: str) -> str:
        self.sent.append((title, message))
        return "fake"


def make_hub() -> tuple[events.EventHub, FakeNotifier]:
    fake = FakeNotifier()
    return events.EventHub(fake), fake


def low(hub: events.EventHub, message: str, folder: str = FOLDER, **options: Any) -> Optional[events.Event]:
    return hub.notify(events.LOW_COUNTS, message, desktop=True, path=folder, **options)


# Once per key

def test_a_keyed_event_is_delivered_once() -> None:
    hub, fake = make_hub()
    hooked: list[events.Event] = []
    hub.add_hook(hooked.append)
    key = (FOLDER, 6, (1234, 5678))
    assert not hub.seen(key)
    first = hub.notify("custom", "shot 6", key=key)
    assert first is not None and hub.seen(key)
    assert hub.notify("custom", "shot 6 again", key=key) is None  # Ignored: no hook, no history.
    assert hooked == [first] and hub.history == [first]
    # Another key goes; events without a key always go.
    assert hub.notify("custom", "shot 7", key=(FOLDER, 7, (1, 2))) is not None
    assert hub.notify("custom", "plain") is not None and hub.notify("custom", "plain") is not None
    assert len(hooked) == 4 and fake.sent == []  # None asked for a desktop notification.


def test_a_keyed_desktop_event_seen_before_is_not_shown_again() -> None:
    hub, fake = make_hub()
    assert low(hub, "Shot 6", key="shot-6") is not None
    assert low(hub, "Shot 6", key="shot-6") is None  # It never happened.
    assert low(hub, "Shot 7", key="shot-7") is not None
    assert [message for _, message in fake.sent] == ["Shot 6", "Shot 7"]


def test_only_the_newest_keys_are_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "SEEN_LIMIT", 3)
    hub, _ = make_hub()
    for key in range(4):
        assert hub.notify("custom", f"key {key}", key=key) is not None
    assert not hub.seen(0) and all(hub.seen(key) for key in (1, 2, 3))
    assert hub.notify("custom", "key 0, forgotten", key=0) is not None  # Delivered again.
    assert hub.notify("custom", "key 3", key=3) is None
    assert not hub.seen(1)  # Key 0 coming back pushed out the oldest one left.


def test_history_keeps_the_newest_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "HISTORY_LIMIT", 2)
    hub, _ = make_hub()
    for n in range(5):
        hub.notify("custom", f"event {n}")
    assert [event.message for event in hub.history] == ["event 3", "event 4"]


# No time limit (Tony, 2026-10-26: a notification per shot; shots are ~30 s apart)

def test_every_desktop_event_is_shown_however_close_together() -> None:
    hub, fake = make_hub()
    shown = [low(hub, f"Shot {shot}", key=("run", shot)) for shot in range(6, 11)]
    assert all(event is not None and event.shown and event.desktop for event in shown)
    assert [message for _, message in fake.sent] == [f"Shot {shot}" for shot in range(6, 11)]
    assert not hasattr(events, "RATE_SECONDS")


def test_events_without_desktop_are_not_shown() -> None:
    hub, fake = make_hub()
    quiet = hub.notify(events.LOW_COUNTS, "quiet", path=FOLDER)
    assert quiet is not None and not quiet.desktop and not quiet.shown and fake.sent == []


# Hooks

def test_hooks_get_every_event() -> None:
    hub, fake = make_hub()
    hooked: list[events.Event] = []
    remove = hub.add_hook(hooked.append)
    before = time.time()
    hub.notify(events.LOW_COUNTS, "Shot 6", title="HeLab: low counts", desktop=True, shot=6)
    hub.notify(events.LOW_COUNTS, "Shot 7", title="HeLab: low counts", desktop=True, shot=7)
    hub.notify(events.LIVE_ERROR, "Live stopped", path=FOLDER)
    after = time.time()
    assert [(event.kind, event.message, event.desktop, event.shown) for event in hooked] == [
        (events.LOW_COUNTS, "Shot 6", True, True),
        (events.LOW_COUNTS, "Shot 7", True, True),
        (events.LIVE_ERROR, "Live stopped", False, False)]
    shown, second, error = hooked
    assert shown.title == second.title == "HeLab: low counts" and error.title == "HeLab"
    # The notifier's answer is recorded only for an event it delivered.
    assert dict(shown.data) == {"shot": 6, "delivered": "fake"}
    assert dict(second.data) == {"shot": 7, "delivered": "fake"} and dict(error.data) == {"path": FOLDER}
    assert isinstance(shown.data, MappingProxyType)
    with pytest.raises(TypeError):
        shown.data["shot"] = 8  # type: ignore[index]
    assert all(before <= event.at <= after for event in hooked)  # Wall-clock time.
    assert hooked == hub.history and fake.sent == [("HeLab: low counts", "Shot 6"), ("HeLab: low counts", "Shot 7")]
    remove()
    remove()  # Removing twice is harmless.
    hub.notify("custom", "after removal")
    assert len(hooked) == 3


def test_a_hook_that_raises_stops_neither_the_others_nor_the_notification(
        caplog: pytest.LogCaptureFixture) -> None:
    hub, fake = make_hub()
    calls: list[str] = []

    def broken(event: events.Event) -> None:
        calls.append("broken")
        raise RuntimeError("hook failed")

    hub.add_hook(broken)
    hub.add_hook(lambda event: calls.append("after"))
    with caplog.at_level(logging.ERROR):
        event = low(hub, "Shot 6")
    assert event is not None and event.shown and fake.sent == [("HeLab", "Shot 6")]
    assert calls == ["broken", "after"] and hub.history == [event]
    assert any(record.getMessage() == f"Event hook failed for {events.LOW_COUNTS}" and record.exc_info
               for record in caplog.records)


def test_a_hook_may_remove_itself_while_called() -> None:
    hub, _ = make_hub()
    calls: list[str] = []
    removers: list[Callable[[], None]] = []

    def once(event: events.Event) -> None:
        calls.append(event.message)
        removers[0]()

    removers.append(hub.add_hook(once))
    hub.add_hook(lambda event: calls.append("other " + event.message))
    hub.notify("custom", "first")
    hub.notify("custom", "second")
    assert calls == ["first", "other first", "other second"]


def test_a_notifier_that_raises_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        def deliver(self, title: str, message: str) -> str:
            raise OSError("no notification service")

    hub = events.EventHub(Broken())
    with caplog.at_level(logging.ERROR):
        event = low(hub, "Shot 6")
    assert event is not None and event.shown and "delivered" not in event.data
    assert any(record.getMessage() == "Notification failed: Shot 6" for record in caplog.records)


# The app's hub

def test_the_module_functions_use_one_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "_hub", None)
    made = events.hub()
    assert events.hub() is made and isinstance(made.notifier, events.DesktopNotifier)
    assert made.notifier is made.desktop
    fake = FakeNotifier()
    fresh = events.reset(fake)
    assert events.hub() is fresh is not made
    event = events.notify(events.LOW_COUNTS, "Shot 6", desktop=True, path=FOLDER, key="k")
    assert event is not None and event.shown and fake.sent == [("HeLab", "Shot 6")]
    assert events.notify(events.LOW_COUNTS, "Shot 6", desktop=True, path=FOLDER, key="k") is None


class Signal:
    def __init__(self, broken: bool = False) -> None:
        self.slots: list[Callable[[str], None]] = []
        self.broken = broken

    def connect(self, slot: Callable[[str], None]) -> None:
        if self.broken:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        self.slots.append(slot)

    def emit(self, path: str) -> None:
        for slot in self.slots:
            slot(path)


class Feed:
    """A LiveFeed's part the hub uses: ``paths`` and the ``ended`` signal."""

    def __init__(self, *paths: str, broken: bool = False) -> None:
        self.watched = set(paths)
        self.ended = Signal(broken)

    def paths(self) -> set[str]:
        return set(self.watched)

    def stop(self, path: str) -> None:
        self.watched.discard(path)
        self.ended.emit(path)


class GoneFeed:
    """A feed whose Qt object went with its window: asking it anything raises."""

    def paths(self) -> set[str]:
        raise RuntimeError("wrapped C/C++ object has been deleted")


def test_live_feeds_say_which_folders_live_watches(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, _ = make_hub()
    hidden: list[bool] = []
    monkeypatch.setattr(hub.desktop, "hide", lambda: hidden.append(True))
    first, second = Feed(FOLDER), Feed(OTHER)
    hub.watch_feed(first)
    hub.watch_feed(second)
    hub.watch_feed(Feed(FOLDER, broken=True))  # Its Qt object is gone: not watched.
    assert len(hub._feeds) == 2
    assert hub.is_live(FOLDER) and hub.is_live(OTHER) and not hub.is_live("/elsewhere")
    first.stop(FOLDER)
    assert not hub.is_live(FOLDER) and hidden == []  # Live still watches OTHER.
    second.stop(OTHER)
    assert hidden == [True]


def test_a_feed_without_an_ended_signal_is_watched_and_one_gone_counts_as_not_live(
        monkeypatch: pytest.MonkeyPatch) -> None:
    hub, _ = make_hub()
    hidden: list[bool] = []
    monkeypatch.setattr(hub.desktop, "hide", lambda: hidden.append(True))

    class Plain:
        def paths(self) -> set[str]:
            return {FOLDER}

    plain = Plain()
    hub.watch_feed(plain)
    assert hub.is_live(FOLDER)
    hub._live_ended(OTHER)
    assert hidden == []  # Live still watches FOLDER.
    # A feed that raises when asked: Live is taken to watch nothing. (Alone here: the feeds are a
    # WeakSet, so with another feed that watches a folder it depends on which is asked first.)
    other, _ = make_hub()
    monkeypatch.setattr(other.desktop, "hide", lambda: hidden.append(True))
    gone = GoneFeed()
    other.watch_feed(gone)
    other._live_ended(FOLDER)
    assert hidden == [True]


def test_a_reset_hub_keeps_the_live_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "_hub", None)
    feed = Feed(FOLDER)
    events.hub().watch_feed(feed)
    fresh = events.reset(FakeNotifier())
    assert fresh.is_live(FOLDER) and feed in set(fresh._feeds)


# Delivery

class FakeTray:
    """``QSystemTrayIcon``'s part ``DesktopNotifier`` uses; never shows anything."""

    available = True
    messages = True
    made: list["FakeTray"] = []
    MessageIcon = QSystemTrayIcon.MessageIcon

    def __init__(self, icon: QIcon, parent: Any) -> None:
        self.icon = icon
        self.parent = parent
        self.tooltip = ""
        self.visible = False
        self.gone = False
        self.shown: list[tuple[str, str, Any, int]] = []
        FakeTray.made.append(self)

    @staticmethod
    def isSystemTrayAvailable() -> bool:
        return FakeTray.available

    @staticmethod
    def supportsMessages() -> bool:
        return FakeTray.messages

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def isVisible(self) -> bool:
        if self.gone:
            raise RuntimeError("wrapped C/C++ object of type QSystemTrayIcon has been deleted")
        return self.visible

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def showMessage(self, title: str, message: str, icon: Any, msecs: int) -> None:
        self.shown.append((title, message, icon, msecs))


@pytest.fixture
def tray(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> Iterator[type[FakeTray]]:
    """A system tray that shows messages, as on a desktop; the app's window icon unset."""
    monkeypatch.setattr(QtWidgets, "QSystemTrayIcon", FakeTray)
    monkeypatch.setattr(FakeTray, "available", True)
    monkeypatch.setattr(FakeTray, "messages", True)
    monkeypatch.setattr(FakeTray, "made", [])
    icon = qapp.windowIcon()
    qapp.setWindowIcon(QIcon())
    yield FakeTray
    qapp.setWindowIcon(icon)


def test_a_tray_that_shows_messages_delivers(tray: type[FakeTray], caplog: pytest.LogCaptureFixture) -> None:
    desktop = events.DesktopNotifier()
    sink: list[str] = []
    desktop.set_status_sink(sink.append)
    with caplog.at_level(logging.INFO):
        assert desktop.deliver("HeLab: low counts", "Shot 6") == "tray"
    (made,) = tray.made
    assert made.tooltip == "HeLab" and made.visible and not made.icon.isNull()  # The warning icon.
    assert made.shown == [("HeLab: low counts", "Shot 6", QSystemTrayIcon.MessageIcon.Warning, 10_000)]
    assert sink == []  # Not the status bar as well.
    assert any(record.levelno == logging.INFO and record.getMessage() == "HeLab: low counts: Shot 6"
               for record in caplog.records)
    # Made once: hidden when Live watched no folder, the next notification shows it again.
    desktop.hide()
    assert not made.visible
    assert desktop.deliver("HeLab", "again") == "tray"
    assert tray.made == [made] and made.visible and len(made.shown) == 2


def test_a_tray_whose_qt_object_is_gone_is_made_again(tray: type[FakeTray]) -> None:
    desktop = events.DesktopNotifier()
    assert desktop.deliver("HeLab", "first") == "tray"
    tray.made[0].gone = True
    assert desktop.deliver("HeLab", "second") == "tray"
    first, second = tray.made
    assert [message for _, message, _, _ in second.shown] == ["second"]
    assert [message for _, message, _, _ in first.shown] == ["first"]


def test_the_app_icon_is_the_tray_icon_when_set(tray: type[FakeTray], qapp: QApplication) -> None:
    from PyQt6.QtGui import QPixmap
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    qapp.setWindowIcon(QIcon(pixmap))
    desktop = events.DesktopNotifier()
    assert desktop.deliver("HeLab", "x") == "tray"
    assert tray.made[0].icon.cacheKey() == qapp.windowIcon().cacheKey()


@pytest.mark.parametrize("available, messages", [(False, True), (True, False)])
def test_without_a_tray_that_shows_messages_the_status_bar_is_told(
        tray: type[FakeTray], available: bool, messages: bool, caplog: pytest.LogCaptureFixture) -> None:
    tray.available, tray.messages = available, messages
    desktop = events.DesktopNotifier()
    sink: list[str] = []
    desktop.set_status_sink(sink.append)  # A plain callable is held as it is.
    with caplog.at_level(logging.WARNING):
        assert desktop.deliver("HeLab: low counts", "Shot 6") == "status"
    assert sink == ["HeLab: low counts: Shot 6"] and tray.made == []
    assert any(record.levelno == logging.WARNING and record.getMessage() == "HeLab: low counts: Shot 6"
               for record in caplog.records)
    desktop.set_status_sink(None)
    assert desktop.deliver("HeLab", "only logged") == "log"
    assert sink == ["HeLab: low counts: Shot 6"]


def test_without_an_application_nothing_is_made(monkeypatch: pytest.MonkeyPatch, tray: type[FakeTray]) -> None:
    class NoApplication:
        @staticmethod
        def instance() -> None:
            return None

    monkeypatch.setattr(QtWidgets, "QApplication", NoApplication)
    desktop = events.DesktopNotifier()
    assert desktop.deliver("HeLab", "x") == "log" and tray.made == []


def test_a_broken_tray_falls_back_to_the_status_bar(monkeypatch: pytest.MonkeyPatch, tray: type[FakeTray],
                                                    caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> bool:
        raise RuntimeError("no D-Bus")

    monkeypatch.setattr(FakeTray, "isSystemTrayAvailable", staticmethod(broken))
    desktop = events.DesktopNotifier()
    sink: list[str] = []
    desktop.set_status_sink(sink.append)
    with caplog.at_level(logging.ERROR):
        assert desktop.deliver("HeLab", "x") == "status"
    assert sink == ["HeLab: x"]
    assert any(record.getMessage() == "System notification failed" and record.exc_info
               for record in caplog.records)


def test_hiding_without_a_tray_does_nothing() -> None:
    desktop = events.DesktopNotifier()
    desktop.hide()
    assert desktop._tray is None


def test_a_hub_without_a_tray_tells_the_status_bar(tray: type[FakeTray]) -> None:
    tray.available = False
    hub = events.EventHub()
    sink: list[str] = []
    hub.desktop.set_status_sink(sink.append)
    first = low(hub, "Shot 6", title="HeLab: low counts")
    last = low(hub, "Shot 7", title="HeLab: low counts")
    assert first is not None and first.data["delivered"] == "status"
    assert last is not None and last.data["delivered"] == "status"
    assert sink == ["HeLab: low counts: Shot 6", "HeLab: low counts: Shot 7"]
