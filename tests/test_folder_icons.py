from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QColor, QIcon, QImage

from helab.models.SnapshotFileSystemModel import FolderNode, SnapshotFileSystemModel
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer


def png_icon() -> str:
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return base64.b64encode(data.data()).decode("ascii")


def queued_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def icon_producer(cache: FolderCache, path: str) -> IORequest:
    job = cache.jobs[("icons", path)]
    return next(request for request in cache.service.pending if request.owner == job.owner)


def test_native_icon_delivery_is_shared_and_rendering_stays_memory_only(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = queued_service(monkeypatch)
    first, second = SnapshotFileSystemModel(service=service), SnapshotFileSystemModel(service=service)
    path = str(tmp_path)
    index = first.setRootPath(path, scan=False)
    second.setRootPath(path, scan=False)
    fallback = first.data(index, int(Qt.ItemDataRole.DecorationRole))
    assert isinstance(fallback, QIcon) and not fallback.isNull()
    assert first.request_folder_icons([path]) and second.request_folder_icons([path])
    assert len(service.pending) == 1
    request = icon_producer(first.cache, path)
    first.close_cleanup()
    assert not request.cancelled.is_set()
    service.resultReady.emit(request, {"kind": "folder_icon", "path": path, "png": png_icon()})
    service.resultReady.emit(request, {"kind": "done"})

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Painting an icon performed I/O or submitted work")

    monkeypatch.setattr(os, "stat", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)
    monkeypatch.setattr(service, "submit", forbidden)
    icon = second.data(second.path_index(path), int(Qt.ItemDataRole.DecorationRole))
    assert isinstance(icon, QIcon)
    assert icon.pixmap(16, 16).toImage().pixelColor(8, 8) == QColor("red")
    assert second.request_folder_icons([path])
    assert second.root and second.root.state == "idle"
    second.close_cleanup()
    service.shutdown()


def test_icon_errors_keep_folder_available_until_manual_refresh(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = queued_service(monkeypatch)
    model = SnapshotFileSystemModel(service=service)
    path = str(tmp_path)
    index = model.setRootPath(path, scan=False)
    assert model.request_folder_icons([path])
    request = icon_producer(model.cache, path)
    service.resultReady.emit(request, {"kind": "error", "timeout": True})
    service.pending.remove(request)
    assert model.root and model.root.state == "idle" and not model.root.error
    assert not model.cache.scan_history(path)["blocked"]
    icon = model.data(index, int(Qt.ItemDataRole.DecorationRole))
    assert isinstance(icon, QIcon) and not icon.isNull()
    assert model.request_folder_icons([path]) and not service.pending
    model.cache.refresh_folder_icons([path])
    assert model.request_folder_icons([path]) and len(service.pending) == 1
    model.close_cleanup()
    service.shutdown()


def test_refresh_rejects_icons_from_cancelled_lookup(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = queued_service(monkeypatch)
    model = SnapshotFileSystemModel(service=service)
    path = str(tmp_path)
    model.setRootPath(path, scan=False)
    assert model.request_folder_icons([path])
    old = icon_producer(model.cache, path)
    model.cache.refresh_folder_icons([path])
    assert old.cancelled.is_set()
    assert model.request_folder_icons([path])
    service.resultReady.emit(old, {"kind": "folder_icon", "path": path, "png": png_icon()})
    assert path not in model.cache.folder_icons
    model.close_cleanup()
    service.shutdown()


def test_icon_cache_is_bounded_and_invalid_png_uses_fallback(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = queued_service(monkeypatch)
    cache = FolderCache(service)
    monkeypatch.setattr(cache, "MAX_FOLDER_ICONS", 2)
    cache.remember_folder_icon("first", png_icon())
    cache.remember_folder_icon("second", "invalid png")
    cache.remember_folder_icon("third", png_icon())
    assert list(cache.folder_icons) == ["second", "third"]
    assert cache.folder_icons["second"].isNull()
    service.shutdown()


def test_icon_jobs_are_bounded_and_cancelled_on_navigation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = queued_service(monkeypatch)
    model = SnapshotFileSystemModel(service=service)
    path = str(tmp_path)
    model.setRootPath(path, scan=False)
    children = [str(tmp_path / str(i)) for i in range(100)]
    for child in children:
        model.nodes[child] = FolderNode(child, model.root)
    assert model.request_folder_icons(["/unrelated", *children, *children])
    request = icon_producer(model.cache, path)
    assert request.payload["paths"] == children[:64]
    model.setRootPath(str(tmp_path / "next"), scan=False)
    assert request.cancelled.is_set()
    service.resultReady.emit(request, {"kind": "folder_icon", "path": children[0], "png": png_icon()})
    assert children[0] not in model.cache.folder_icons
    model.close_cleanup()
    service.shutdown()


def test_visible_icon_requests_do_not_enable_basic_scanning(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = queued_service(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    path = str(tmp_path)
    browser = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(browser)
    qtbot.waitUntil(lambda: browser.model.root is not None)
    browser.model.cache.cancel(browser.model.owner, "list")
    browser._load_visible_icons()
    assert not service.pending
    browser.show()
    qtbot.waitUntil(lambda: ("icons", path) in browser.model.cache.jobs)
    assert not browser.auto_scan_visible
    assert all(request.operation == "icons" for request in service.pending)
    browser.close_cleanup()
    service.shutdown()


def test_real_icon_helper_transports_png(tmp_path: Path) -> None:
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-m", "helab.io_helper"],
                            input=json.dumps({"operation": "icons", "path": str(tmp_path),
                                              "paths": [str(tmp_path)]}) + "\n",
                            text=True, capture_output=True, env=environment, timeout=15, check=True)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["kind"] == "done"
    assert events[0]["kind"] == "folder_icon"
    image = QImage.fromData(base64.b64decode(events[0]["png"]), "PNG")
    assert not image.isNull() and image.width() == 32


@pytest.mark.skipif(sys.platform != "darwin" or not os.environ.get("HELAB_TEST_NATIVE_ICONS"),
                    reason="Opt-in macOS native icon check requires access to desktop services")
def test_macos_custom_folder_and_volume_icons(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    swift = shutil.which("swift")
    if swift is None:
        pytest.skip("Swift is required to create the native custom-icon fixture")
    folders = tmp_path / "folders"
    folders.mkdir()
    plain, custom = folders / "plain folder", folders / "custom folder"
    plain.mkdir()
    custom.mkdir()
    fixture = """import AppKit
let icon = NSImage(contentsOfFile: CommandLine.arguments[2])!
if !NSWorkspace.shared.setIcon(icon, forFile: CommandLine.arguments[1], options: []) { exit(1) }
"""
    environment = dict(os.environ, QT_QPA_PLATFORM="cocoa",
                       CLANG_MODULE_CACHE_PATH=str(tmp_path / "clang-modules"),
                       SWIFT_MODULECACHE_PATH=str(tmp_path / "swift-modules"))
    subprocess.run([swift, "-e", fixture, str(custom),
                    "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/AlertStopIcon.icns"],
                   env=environment, capture_output=True, text=True, timeout=60, check=True)
    result = subprocess.run([sys.executable, "-m", "helab.io_helper"],
                            input=json.dumps({"operation": "icons", "path": str(tmp_path),
                                              "paths": [str(plain), str(custom), "/"]}) + "\n",
                            env=environment, capture_output=True, text=True, timeout=15, check=True)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["kind"] == "done"
    images = {event["path"]: QImage.fromData(base64.b64decode(event["png"]), "PNG")
              for event in events if event["kind"] == "folder_icon"}
    assert all(not image.isNull() for image in images.values())
    assert images[str(custom)] != images[str(plain)]
    assert images["/"] != images[str(plain)]

    # Exercise the real queue and view too; the parent remains offscreen while
    # the icon helper uses Cocoa. Save a render for checking the 16px row layout.
    monkeypatch.setenv("QT_QPA_PLATFORM", "cocoa")
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    browser = FolderExplorer(str(folders), str(folders), str(folders), [0, 4, 5])
    qtbot.addWidget(browser)
    browser.resize(650, 260)
    browser.show()
    qtbot.waitUntil(lambda: all(str(path) in browser.model.cache.folder_icons for path in (plain, custom)),
                    timeout=15000)
    icons = browser.model.cache.folder_icons
    assert icons[str(custom)].pixmap(16, 16).toImage() != icons[str(plain)].pixmap(16, 16).toImage()
    assert browser.grab().save(str(tmp_path / "folder-icons.png"))
    browser.close_cleanup()
    service.shutdown()
