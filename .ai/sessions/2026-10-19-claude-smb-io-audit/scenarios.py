"""Offscreen HeLab on a local test share with the I/O trace on: each scenario's source operations.

    python scenarios.py OUT_DIR --session 1     # empty disk cache: browse, load, Live, tab switch…
    python scenarios.py OUT_DIR --session 2     # restart on session 1's cache: cache first
    python trace_summary.py OUT_DIR/trace.jsonl --under OUT_DIR

Nothing here touches a real share or Tony's settings: the test share is built under OUT_DIR from
tests_sample_data, a new tab's default folders are replaced by it, settings are a private ini file
and the cache, temp and app folders are private too. Run from anywhere; it imports this checkout.

Phases are marked in the trace (``op`` "phase"). A hook in this (GUI) process records any call it
makes on the share (os.stat, os.scandir, open…) as ``gui:<call>`` lines: there should be none.
Timeouts are shortened (per-file reads 3/4/5 s instead of 15/20/30 s); the read gate
(``HELAB_TEST_READ_GATE``) holds one file of the "stuck" folder forever.
"""
from __future__ import annotations

import argparse
import builtins
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GATE_CLOSED = 9999  # The stuck folder's file whose read never starts.


def build_share(out: Path) -> dict[str, Path]:
    """The test share: a data root with dated runs, a Live run, a stuck and a broken folder, and a
    sibling folder without a .helab-root (RAM only)."""
    share, ramshare = out / "share", out / "ramshare"
    template = (REPO / "tests_sample_data" / "goodish" / "d_txy_forc1.txt").read_bytes()
    rows = template.splitlines(keepends=True)
    body = b"".join(rows[:3000])  # ~100 kB, as a small shot.
    (out / "template.txt").write_bytes(body)
    old = time.time() - 3600
    folders: dict[str, Path] = {}

    def run(path: Path, shots: range) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        for shot in shots:
            (path / f"d{shot}.txt").write_bytes(b"raw tdc data\n")
            (path / f"d_txy_forc{shot}.txt").write_bytes(body)
        return path

    share.mkdir(parents=True)
    (share / ".helab-root").write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                                                   "label": "trace share", "created_at": "2026-10-19T00:00:00Z"}))
    folders["run_a"] = run(share / "2026" / "10" / "18" / "run_a", range(1, 121))
    folders["run_b"] = run(share / "2026" / "10" / "18" / "run_b", range(1, 41))
    folders["run_live"] = run(share / "2026" / "10" / "19" / "run_live", range(1, 31))
    folders["run_c"] = run(share / "2026" / "10" / "19" / "run_c", range(1, 301))
    folders["run_stall"] = run(share / "2026" / "10" / "19" / "run_stall", range(1, 11))
    folders["stuck"] = run(share / "2026" / "10" / "19" / "stuck", [*range(1, 20), GATE_CLOSED])  # type: ignore[arg-type]
    folders["broken"] = share / "2026" / "10" / "19" / "broken"
    folders["broken"].mkdir()
    (share / "notes").mkdir()
    for name in ("readme.txt", "log.txt"):
        (share / "notes" / name).write_text("notes\n")
    folders["run_r"] = run(ramshare / "run_r", range(1, 121))
    for path in sorted({p for p in share.rglob("*")} | {p for p in ramshare.rglob("*")} | {share, ramshare},
                       key=lambda p: -len(p.parts)):
        os.utime(path, (old, old), follow_symlinks=False)
    folders["broken"].chmod(0)
    gate = out / "gate"
    gate.mkdir()
    for shot in [*range(1, 401), *range(1001, 1051), *range(2001, 2011)]:
        (gate / f"d_txy_forc{shot}.txt.go").touch()
    return {"share": share, "ramshare": ramshare, **folders}


class SourceHook:
    """Records this process's own calls on the share (it should make none) into the trace."""

    def __init__(self, roots: list[Path], note: Callable[[dict[str, Any]], None]) -> None:
        self.roots = [os.path.normcase(str(root)) for root in roots]
        self.note, self.paused, self.count = note, False, 0
        for module, names in ((os, ("stat", "lstat", "scandir", "listdir", "open")),
                              (os.path, ("exists", "isdir", "isfile", "getmtime", "getsize")),
                              (builtins, ("open",))):
            for name in names:
                setattr(module, name, self.recording(name, getattr(module, name)))

    def recording(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def call(target: Any = ".", *args: Any, **kwargs: Any) -> Any:
            if (not self.paused and isinstance(target, (str, os.PathLike))
                    and any(os.path.normcase(os.fspath(target)).startswith(root) for root in self.roots)):
                self.count += 1
                self.note({"op": f"gui:{name}", "path": os.fspath(target), "reason": "GUI process"})
            return real(target, *args, **kwargs)
        return call


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--session", type=int, default=1)
    parser.add_argument("--idle", type=float, default=60.0, help="seconds of each idle phase")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if args.session == 1:
        if out.exists():
            for path in out.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
            shutil.rmtree(out)
        out.mkdir(parents=True)
        folders = build_share(out)
    else:
        folders = {name: Path(value) for name, value in json.loads((out / "folders.json").read_text()).items()}
    (out / "folders.json").write_text(json.dumps({name: str(path) for name, path in folders.items()}))
    trace = out / "trace.jsonl"
    for kind in ("caches", "temps", "app"):
        (out / kind).mkdir(exist_ok=True)
    os.environ.update({
        "HELAB_DIR_CACHES_OVERRIDE": str(out / "caches"), "HELAB_DIR_TEMPS_OVERRIDE": str(out / "temps"),
        "HELAB_APP_DIR_OVERRIDE": str(out / "app"), "HELAB_TEST_VOLUME_ID": "trace-volume",
        "HELAB_IO_TRACE": str(trace), "HELAB_TEST_READ_GATE": str(out / "gate"), "QT_QPA_PLATFORM": "offscreen"})
    sys.path.insert(0, str(REPO))  # This checkout's helab (helpers follow it through PYTHONPATH).

    def note(record: dict[str, Any]) -> None:
        line = json.dumps({"t": time.time(), "pid": os.getpid(), "reason": "", "path": "", **record}) + "\n"
        descriptor = os.open(str(trace), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, line.encode("ascii"))
        finally:
            os.close(descriptor)

    def phase(name: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {name}", flush=True)
        note({"op": "phase", "name": f"S{args.session} {name}"})

    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before the QApplication)
    from PyQt6.QtCore import QEventLoop, QSettings
    from PyQt6.QtWidgets import QApplication
    app = QApplication(["helab-trace-scenarios"])
    settings_file = str(out / "settings.ini")

    class PrivateSettings(QSettings):
        def __init__(self, *values: Any, **kwargs: Any) -> None:
            if len(values) == 2 and all(isinstance(value, str) for value in values) and not kwargs:
                super().__init__(settings_file, QSettings.Format.IniFormat)
            else:
                super().__init__(*values, **kwargs)

    import helab.utils.constants as constants
    import helab.views.FolderTabWidget as tab_widget
    import helab.views.HelabMainWindow as main_window
    import helab.views.SettingsDialog as settings_dialog
    from helab.resources.icons import IconsInitUtil
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import IORequest, IOService, get_io_service
    from helab.views.FolderExplorer import FolderExplorer
    for module in (constants, main_window, settings_dialog):
        setattr(module, "QSettings", PrivateSettings)
    tab_widget.DEV_POTENTIAL_DATA_PATHS = [str(folders["share"])]
    tab_widget.DEFAULT_DATA_PATH = str(folders["share"])
    IOService.TIMEOUTS = (3.0, 4.0, 5.0)
    IconsInitUtil.initialise_icons()
    hook = SourceHook([folders["share"], folders["ramshare"]], note)

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)

    def wait(condition: Callable[[], bool], timeout: float = 60.0, what: str = "") -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition():
                return True
            pump(0.05)
        print(f"  (timed out waiting: {what})", flush=True)
        return False

    service = get_io_service()
    cache = get_folder_cache(service)
    from PyQt6.QtCore import QTimer
    from helab.utils.cache_paths import current_mounts
    seen_mounts: list[list[list[str]]] = [sorted([[m.path, m.source] for m in current_mounts()])]

    def watch_mounts() -> None:
        now = sorted([[m.path, m.source] for m in current_mounts()])
        if now != seen_mounts[-1]:
            gone = [m for m in seen_mounts[-1] if m not in now]
            added = [m for m in now if m not in seen_mounts[-1]]
            note({"op": "mount_table_changed", "reason": "OS mount table", "added": added, "gone": gone})
            seen_mounts.append(now)
    mount_timer = QTimer()
    mount_timer.timeout.connect(watch_mounts)
    mount_timer.start(500)

    def idle() -> bool:
        return not service.pending and not service.active and not service.retired and not cache._deliveries

    def settle(timeout: float = 60.0) -> None:
        wait(idle, timeout, "I/O idle")
        pump(1.0)
        wait(idle, timeout, "I/O idle")

    window = main_window.HelabMainWindow()
    window.resize(1400, 900)
    window.show()

    def explorer() -> FolderExplorer:
        current = window.tab_widget.currentWidget()
        assert isinstance(current, FolderExplorer)
        return current

    def listed(tab: FolderExplorer, path: Path) -> bool:
        node = tab.model.nodes.get(str(path))
        return node is not None and node.loaded

    def expand(tab: FolderExplorer, path: Path) -> None:
        wait(lambda: str(path) in tab.model.nodes, 30, f"node {path}")
        tab.tree.expand(tab.model.path_index(str(path)))
        wait(lambda: listed(tab, path), 30, f"listing {path}")

    def select(tab: FolderExplorer, path: Path) -> None:
        wait(lambda: str(path) in tab.model.nodes, 30, f"node {path}")
        tab.tree.setCurrentIndex(tab.model.path_index(str(path)))

    def shown(tab: FolderExplorer, path: Path) -> bool:
        return tab.folder_opened_path == str(path) and tab.folder_opened_data is not None and not tab.loading

    def open_branch(tab: FolderExplorer, *paths: Path) -> None:
        for path in paths:
            expand(tab, path)

    share = folders["share"]
    day18, day19 = share / "2026" / "10" / "18", share / "2026" / "10" / "19"
    phase("startup")
    wait(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer) and listed(explorer(), share),
         60, "first listing")
    settle()
    phase(f"idle {args.idle:.0f} s, tree open")
    pump(args.idle)
    tab1 = explorer()
    if args.session == 1:
        phase("expand 2026/10/18 and 19")
        open_branch(tab1, share / "2026", share / "2026" / "10", day18, day19)
        settle()
        phase("select and load run_a (120 shots)")
        select(tab1, folders["run_a"])
        wait(lambda: shown(tab1, folders["run_a"]), 60, "run_a shown")
        settle()
        phase("select and load run_b (40 shots)")
        select(tab1, folders["run_b"])
        wait(lambda: shown(tab1, folders["run_b"]), 60, "run_b shown")
        settle()
        phase("reselect run_a within 10 s")
        select(tab1, folders["run_a"])
        pump(3.0)
        settle()
        phase("idle 15 s")
        pump(15.0)
        phase("reselect run_b after 15 s (disk cached)")
        select(tab1, folders["run_b"])
        wait(lambda: shown(tab1, folders["run_b"]), 60, "run_b shown")
        settle()
        phase("second tab: RAM-only folder, load run_r")
        window.add_new_folder_explorer_tab(target_path=str(folders["ramshare"]))
        tab2 = explorer()
        wait(lambda: listed(tab2, folders["ramshare"]), 60, "ramshare listing")
        select(tab2, folders["run_r"])
        wait(lambda: shown(tab2, folders["run_r"]), 60, "run_r shown")
        settle()
        for number in range(1, 5):
            target = 0 if number % 2 else 1
            phase(f"tab switch {number} (to tab {target + 1}) after 15 s")
            window.tab_widget.setCurrentIndex(target)
            pump(3.0)
            settle()
            pump(12.0)
        window.tab_widget.setCurrentIndex(0)
        settle()
        phase("toolbar Refresh")
        window.tab_widget.refresh_current_folder_explorer()
        pump(1.0)
        settle()
        phase("right-click Retry / Refresh on run_b (shown)")
        tab1.refresh_folder(str(folders["run_b"]))
        pump(1.0)
        settle()
        phase("select and load run_live")
        select(tab1, folders["run_live"])
        wait(lambda: shown(tab1, folders["run_live"]), 60, "run_live shown")
        settle()
        phase("Live on, writer adds 12 shots every 4 s (1004 written over 7.5 s, 1009 stalls 8 s mid-file)")
        window.on_live_button_clicked()
        writer = subprocess.Popen([sys.executable, str(HERE / "fake_writer.py"), str(folders["run_live"]), str(trace),
                                   "--first", "1001", "--count", "12", "--every", "4", "--slow", "1004",
                                   "--stall", "1009", "--template", str(out / "template.txt")])
        while writer.poll() is None:
            pump(0.5)
        phase("Live on, writer done: 15 s to settle")
        pump(15.0)
        phase(f"Live on, nothing new, {args.idle:.0f} s")
        pump(args.idle)
        phase("Live off (saves new shots)")
        window.on_live_button_clicked()
        pump(1.0)
        settle()
        phase("load run_stall while its new shot 2001 stalls 8 s mid-file (selected 6.5 s in)")
        writer = subprocess.Popen([sys.executable, str(HERE / "fake_writer.py"), str(folders["run_stall"]), str(trace),
                                   "--first", "2001", "--count", "1", "--every", "0", "--stall", "2001",
                                   "--template", str(out / "template.txt")])
        pump(6.5)
        select(tab1, folders["run_stall"])
        wait(lambda: shown(tab1, folders["run_stall"]), 60, "run_stall shown")
        while writer.poll() is None:
            pump(0.5)
        settle()
        phase("simulated mount change (a listing reports another mount table), 30 s")
        from helab.utils.cache_paths import current_mounts
        real = sorted([[mount.path, mount.source] for mount in current_mounts()])
        fake = sorted([*real, ["/Volumes/HeLabTraceFake", "//trace@fake-server/fake"]])
        cache._on_event(IORequest("trace:mounts", 0, "", "list", {}, 60.0), {"kind": "mounts_seen", "mounts": fake})
        pump(30.0)
        phase("a listing reports the real mount table again, 15 s")
        tab1.model.request_scan(str(day19), force=True)
        pump(15.0)
        settle()
        phase("select a folder that can't be listed (permission), 20 s")
        select(tab1, folders["broken"])
        pump(20.0)
        phase("select a folder whose file read hangs (timeouts 3/4/5 s), until it fails")
        select(tab1, folders["stuck"])
        wait(lambda: bool(tab1.load_error), 60, "stuck load error")
        settle()
        phase(f"idle {args.idle:.0f} s at the end")
        pump(args.idle)
    else:
        phase("expand to run_a (saved badges)")
        open_branch(tab1, share / "2026", share / "2026" / "10", day18)
        settle()
        phase("select run_a: cached data, checked beside it")
        select(tab1, folders["run_a"])
        wait(lambda: shown(tab1, folders["run_a"]), 60, "run_a shown")
        settle()
        phase("run_b gained a shot since: select it")
        hook.paused = True
        (folders["run_b"] / "d41.txt").write_bytes(b"raw tdc data\n")
        (folders["run_b"] / "d_txy_forc41.txt").write_bytes((out / "template.txt").read_bytes())
        old = time.time() - 60
        os.utime(folders["run_b"] / "d_txy_forc41.txt", (old, old))
        hook.paused = False
        select(tab1, folders["run_b"])
        wait(lambda: shown(tab1, folders["run_b"]), 60, "run_b shown")
        settle()
        phase("RAM-only tab: load run_r (no .helab-root)")
        window.add_new_folder_explorer_tab(target_path=str(folders["ramshare"]))
        tab2 = explorer()
        wait(lambda: listed(tab2, folders["ramshare"]), 60, "ramshare listing")
        select(tab2, folders["run_r"])
        wait(lambda: shown(tab2, folders["run_r"]), 60, "run_r shown")
        settle()
        phase("idle 15 s")
        pump(15.0)
        phase("reselect run_r after 15 s (RAM only, unchanged)")
        select(tab2, folders["ramshare"])
        pump(2.0)
        settle()
        select(tab2, folders["run_r"])
        wait(lambda: shown(tab2, folders["run_r"]), 60, "run_r shown")
        settle()
        phase("idle 15 s, then reselect run_a in tab 1 (disk cached, unchanged)")
        window.tab_widget.setCurrentIndex(0)
        pump(15.0)
        select(tab1, folders["run_b"])
        pump(2.0)
        settle()
        select(tab1, folders["run_a"])
        wait(lambda: shown(tab1, folders["run_a"]), 60, "run_a shown")
        settle()
        phase(f"idle {args.idle:.0f} s at the end")
        pump(args.idle)
    phase("quit")
    window.close()
    wait(lambda: not window.isVisible(), 60, "window closed")
    pump(2.0)
    note({"op": "phase", "name": f"S{args.session} end"})
    print(f"GUI-process calls on the share: {hook.count}", flush=True)
    folders["broken"].chmod(0o755)
    os._exit(0)


if __name__ == "__main__":
    main()
