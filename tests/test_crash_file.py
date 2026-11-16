"""What HeLab keeps for after a crash (LR-15, Tony 2026-11-05): a hard crash leaves every thread's
Python stack in ``logs/crash-<pid>.txt`` (an I/O helper's ``helper-crash-<pid>.txt``), removed at a
clean exit while empty; the console's output in ``console-<pid>.txt``; Qt's messages in the log; the
last run's crash named at start; a memory line each minute while Live is on. The startup tidy counts
these files with the logs and removes empty ones. Crashes and the console run in child processes
(``faulthandler`` and the console belong to pytest here), each with its own temporary folder."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, cast

import pytest
from pytestqt.qtbot import QtBot

import test_accessible_names as an  # (Also imports QtWebEngine before the app starts.)
from helab.utils import app_log, console_tee, crash_file

ROOT = Path(__file__).resolve().parents[1]

CHILD = """
import os, sys, threading
sys.path.insert(0, sys.argv[1])
folder, name, how = sys.argv[2], sys.argv[3], sys.argv[4]
for kind in ("CACHES", "TEMPS"):
    os.environ[f"HELAB_DIR_{kind}_OVERRIDE"] = folder
os.environ["HELAB_APP_DIR_OVERRIDE"] = folder
if name == "HELPER":  # As an I/O helper starts: standard library only, the folder from the app.
    os.environ["HELAB_HELPER_CRASH_DIR"] = os.path.join(folder, "logs")
    from helab.utils import crash_file
    path = crash_file.start_for_helper()
    assert not [m for m in sys.modules if m.startswith("PyQt6")]
else:
    from helab.utils import app_log
    path = app_log.start_crash_file(folder, getattr(app_log, name))
print(path, flush=True)
if how == "armed":  # As ``main`` arms the last resort at quit, then exits cleanly well before it is due.
    from helab.utils import crash_file
    assert crash_file.exit_after(600)
if how == "crash":
    import faulthandler
    ready = threading.Event()
    def waiting():
        ready.set()
        threading.Event().wait()
    threading.Thread(target=waiting, name="helper-like", daemon=True).start()
    ready.wait()
    faulthandler._sigsegv()
"""


def child(folder: Path, name: str, how: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    result = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), str(folder), name, how],
                            capture_output=True, text=True, timeout=60)
    return result, Path(result.stdout.strip().splitlines()[0])


@pytest.mark.parametrize("name,file", [("CRASH_NAME", "crash-{pid}.txt"), ("HELPER_CRASH_NAME", "helper-crash-{pid}.txt"),
                                       ("HELPER", "helper-crash-{pid}.txt")])
def test_a_hard_crash_leaves_every_threads_stack_in_the_crash_file(tmp_path: Path, name: str, file: str) -> None:
    result, path = child(tmp_path, name, "crash")
    assert result.returncode != 0
    assert path.parent == tmp_path / "logs" and path.name.endswith(".txt")
    assert path.name == file.format(pid=path.name.split("-")[-1].removesuffix(".txt"))
    text = path.read_text()
    assert "Fatal Python error: Segmentation fault" in text or "Windows fatal exception: access violation" in text, text
    assert "Current thread 0x" in text and "Thread 0x" in text and "waiting" in text, text  # (Every thread.)


def test_a_clean_exit_removes_the_empty_crash_file(tmp_path: Path) -> None:
    result, path = child(tmp_path, "CRASH_NAME", "exit")
    assert result.returncode == 0, result.stderr
    assert path.name.startswith("crash-") and not path.exists()


def test_a_clean_exit_with_the_last_resort_armed_leaves_the_file_for_the_tidy(tmp_path: Path) -> None:
    """Armed at quit (``exit_after``), the timer may still write during teardown, so a clean exit doesn't remove
    the file; nothing was written, and the next start's tidy removes empty ones."""
    result, path = child(tmp_path, "CRASH_NAME", "armed")
    assert result.returncode == 0, result.stderr
    assert path.exists() and path.read_text() == ""


def test_the_last_resort_writes_through_a_descriptor_of_its_own(tmp_path: Path) -> None:
    """Review R5: the timer's output is an OS descriptor this module keeps (a duplicate of the crash file's), not
    the Python file object, which Python 3.13.5 closed under it in the interpreter's last collection (the stuck
    teardown itself: ``tests/test_quit_confirms.py``). Arming again closes the one before; ``end`` closes the file
    object and leaves the timer's descriptor, and the file, alone."""
    import faulthandler
    from helab.utils import crash_file
    assert crash_file._crash is None and crash_file._armed is None
    assert crash_file.exit_after(3600) is False  # (No crash file: nothing to arm.)
    path = crash_file.start(str(tmp_path))
    try:
        assert crash_file._crash is not None
        file = crash_file._crash[0]
        assert crash_file.exit_after(3600)
        first = crash_file._armed
        assert isinstance(first, int) and first != file.fileno() and os.path.samestat(os.fstat(first), os.stat(path))
        assert crash_file.exit_after(3600)
        second = crash_file._armed
        assert isinstance(second, int) and os.path.samestat(os.fstat(second), os.stat(path))
        if second != first:  # (The first one's number may be given out again.)
            with pytest.raises(OSError):
                os.fstat(first)
        crash_file.end()
        assert file.closed and os.path.exists(path)  # armed: not removed, though empty
        os.write(second, b"still open\n")  # as the timer writes, after the file object has gone
        assert Path(path).read_text() == "still open\n"
    finally:
        faulthandler.cancel_dump_traceback_later()
        crash_file.end()
        if crash_file._armed is not None:
            os.close(crash_file._armed)
            crash_file._armed = None


def test_no_crash_file_where_it_cant_be_written(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "logs").write_text("a file, not a folder")
    assert app_log.start_crash_file(str(tmp_path)) is None  # (Fails before faulthandler is touched.)
    assert "No crash file" in caplog.text
    monkeypatch.delenv(crash_file.HELPER_DIR_ENV, raising=False)
    assert crash_file.start_for_helper() is None  # (No folder named: none.)
    monkeypatch.setenv(crash_file.HELPER_DIR_ENV, str(tmp_path / "logs"))
    assert crash_file.start_for_helper() is None


def put(folder: Path, name: str, age: float, size: int) -> None:
    path = folder / "logs" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def test_the_tidy_counts_crash_files_with_the_logs_and_removes_empty_ones(tmp_path: Path) -> None:
    put(tmp_path, "helab-101.log", 5 * 3600, 10)
    put(tmp_path, "crash-101.txt", 5 * 3600, 30)  # A crash's stack: kept while the count allows.
    put(tmp_path, "helper-crash-102.txt", 4 * 3600, 0)  # A killed helper's: nothing in it.
    put(tmp_path, "crash-103.txt", 3 * 3600, 0)
    put(tmp_path, "helper-crash-104.txt", 10, 0)  # Just made (a helper starting): never deleted.
    put(tmp_path, "helab-105.log", 2 * 3600, 10)
    files = {file.path.rsplit(os.sep, 1)[-1]: file.pid for file in app_log.scan_logs(str(tmp_path))}
    assert files == {"helab-101.log": 101, "crash-101.txt": 101, "helper-crash-102.txt": 102,
                     "crash-103.txt": 103, "helper-crash-104.txt": 104, "helab-105.log": 105}
    assert app_log.tidy_logs(str(tmp_path), keep=10) == 50
    assert {path.name for path in (tmp_path / "logs").iterdir()} == {
        "helab-101.log", "crash-101.txt", "helper-crash-104.txt", "helab-105.log"}
    assert app_log.tidy_logs(str(tmp_path), keep=2) == 10  # The oldest by mtime go, crash files with them.
    assert {path.name for path in (tmp_path / "logs").iterdir()} == {"helper-crash-104.txt", "helab-105.log"}


def test_helab_and_its_helpers_start_their_crash_files() -> None:
    """``main`` once it logs to its file; each I/O helper as it starts."""
    main = (ROOT / "helab" / "main.py").read_text()
    assert main.index("app_log.start_crash_file(app_folder())") > main.index("app_log.start_log_file(app_folder())")
    helper = (ROOT / "helab" / "io_helper.py").read_text()
    assert helper.index("crash_file.start_for_helper()") < helper.index("json.loads(sys.stdin.readline())")
    service = (ROOT / "helab" / "utils" / "io_service.py").read_text()
    assert "env[crash_file.HELPER_DIR_ENV] = app_log.log_folder(app_folder())" in service


# The console file (``console_tee``): fd 1 and 2, C-level writes and child processes' too.

TEE_CHILD = """
import atexit, os, sys
sys.path.insert(0, sys.argv[1])
os.environ.pop("HELAB_NO_CONSOLE_FILE", None)
from helab.utils import console_tee
tee = console_tee.start(sys.argv[2])
atexit.register(tee.stop)  # (As main does.)
print("python-stdout", flush=True)
os.write(2, b"fd-stderr\\n")  # (As C code writes.)
os.system("echo from-a-child-process")  # (It inherits fd 1.)
print(tee.path, flush=True)
"""


def test_the_console_is_kept_in_the_logs_folder_and_still_reaches_the_terminal(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    result = subprocess.run([sys.executable, "-c", TEE_CHILD, str(ROOT), str(logs)], capture_output=True, text=True,
                            timeout=60, env={k: v for k, v in os.environ.items() if k != "HELAB_NO_CONSOLE_FILE"})
    assert result.returncode == 0, result.stderr
    assert "python-stdout" in result.stdout and "from-a-child-process" in result.stdout  # The terminal, as before.
    assert "fd-stderr" in result.stderr
    path = Path(result.stdout.strip().splitlines()[-1])
    assert path.parent == logs and path.name.startswith("console-") and path.name.endswith(".txt")
    kept = path.read_text()
    # (A child process on Windows inherits the OS's standard handles, which dup2 on the C runtime's
    # descriptors may leave: there only HeLab's own writes are checked.)
    for text in ("python-stdout", "fd-stderr", *(() if sys.platform == "win32" else ("from-a-child-process",))):
        assert text in kept, kept


REBIND_CHILD = """
import atexit, logging, os, sys
sys.path.insert(0, sys.argv[1])
os.environ.pop("HELAB_NO_CONSOLE_FILE", None)
from helab.utils import console_tee
handler = logging.StreamHandler(sys.stderr)  # (As coloredlogs holds the sys.stderr it was installed with.)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
console_tee.writes_past_its_descriptor = lambda stream: True  # (As a Windows console's streams do.)
tee = console_tee.start(sys.argv[2])
atexit.register(tee.stop)
assert handler.stream is sys.stderr and sys.stderr is not sys.__stderr__
logging.info("a-logged-line")
print("printed-to-stdout", flush=True)
print(tee.path, flush=True)
"""


def test_a_console_python_writes_past_its_descriptor_still_reaches_the_file(tmp_path: Path) -> None:
    """On a Windows console, ``sys.stderr`` writes to the console's handle, so after ``dup2`` the log's console
    lines were lost to the terminal and the file alike (the TDC PC's console showed nothing after "Logging to").
    Such streams, and the logging handlers holding them, are pointed at the descriptors."""
    logs = tmp_path / "logs"
    result = subprocess.run([sys.executable, "-c", REBIND_CHILD, str(ROOT), str(logs)], capture_output=True,
                            text=True, timeout=60,
                            env={k: v for k, v in os.environ.items() if k != "HELAB_NO_CONSOLE_FILE"})
    assert result.returncode == 0, result.stderr
    assert "a-logged-line" in result.stderr and "printed-to-stdout" in result.stdout
    kept = Path(result.stdout.strip().splitlines()[-1]).read_text()
    assert "a-logged-line" in kept and "printed-to-stdout" in kept, kept


def test_a_terminal_that_takes_nothing_never_stops_the_pump(tmp_path: Path) -> None:
    """2026-11-09, the TDC PC: a stall dump went into the tee's pipe while its pump waited on the terminal; the
    pipe full, ``faulthandler`` (holding the GIL) waited too, and HeLab froze until force quit. The pump hands
    chunks to the terminal's own thread and never waits: the file gets everything, the terminal what it takes."""
    read, write = os.pipe()  # (The terminal: nobody reads it, so it fills and its writes block.)
    path = tmp_path / "console-1.txt"
    tee = console_tee.ConsoleTee(str(path))
    terminal = console_tee._Terminal(write)
    chunk = b"x" * 65536
    pump_read, pump_write = os.pipe()
    pump = threading.Thread(target=tee._pump, args=(pump_read, terminal), daemon=True)
    tee._writer.start()  # (The file's writer, as ``start`` starts it.)
    pump.start()
    try:
        count = console_tee.TERMINAL_CHUNKS + 40
        for _ in range(count):
            view = memoryview(chunk)
            while view:
                view = view[os.write(pump_write, view):]
        os.close(pump_write)
        pump.join(timeout=20)
        assert not pump.is_alive()  # It read to the end, the terminal stuck all along.
        tee._chunks.put(None)
        tee._writer.join(timeout=20)
        assert path.stat().st_size == count * len(chunk)
        assert terminal.dropped > 0 and terminal.thread.is_alive()
    finally:
        def drain() -> None:  # (The terminal takes output again: its thread writes what it held, then ends.)
            while os.read(read, 65536):
                pass
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        terminal.close(timeout=20)
        os.close(write)
        reader.join(timeout=5)
        os.close(read)
        tee.stop()
    assert not terminal.thread.is_alive()


class WholeCharacterConsole:
    """A stand-in for a Windows console's raw stream: ``write`` takes UTF-8 bytes up to the last whole character
    and says how many it took (as ``_WindowsConsoleIO.write``), so an incomplete tail isn't taken."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, data: Any) -> int:
        raw = bytes(data)
        taken = len(raw)
        for back in range(1, min(4, len(raw)) + 1):
            byte = raw[-back]
            if byte & 0xC0 != 0x80:  # (The last lead or ASCII byte: is its character whole?)
                length = 1 if byte < 0x80 else 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
                taken = len(raw) - back if length > back else len(raw)
                break
        self.text += raw[:taken].decode("utf-8", "replace")
        return taken


@pytest.mark.parametrize("split", range(1, len("σ → · é 𝛼".encode("utf-8"))))
def test_a_character_split_across_two_reads_reaches_a_console_whole(split: int) -> None:
    """The pump's reads end wherever the pipe's contents do: on a console, a character split across two of them
    is written whole once its rest comes (it was lost or garbled)."""
    text = "σ → · é 𝛼"
    data = text.encode("utf-8")
    read, write = os.pipe()
    console = WholeCharacterConsole()
    terminal = console_tee._Terminal(write, console)
    try:
        terminal.put(data[:split])
        terminal.put(data[split:])
        terminal.close(timeout=20)
        assert not terminal.thread.is_alive() and console.text == text
    finally:
        os.close(write)
        os.close(read)


def test_a_console_gets_a_replacement_for_bytes_left_incomplete_at_the_end() -> None:
    read, write = os.pipe()
    console = WholeCharacterConsole()
    terminal = console_tee._Terminal(write, console)
    try:
        terminal.put("ok σ".encode("utf-8")[:-1])  # (Its last character never completed.)
        terminal.close(timeout=20)
        assert not terminal.thread.is_alive() and console.text == "ok �"
    finally:
        os.close(write)
        os.close(read)
    piped_read, piped_write = os.pipe()  # (Not a console: the bytes go on as they are.)
    terminal = console_tee._Terminal(piped_write)
    try:
        terminal.put("σ".encode("utf-8")[:1])
        terminal.put("σ".encode("utf-8")[1:])
        terminal.close(timeout=20)
        assert os.read(piped_read, 16) == "σ".encode("utf-8")
    finally:
        os.close(piped_write)
        os.close(piped_read)


def test_handler_streams_are_swapped_after_loggings_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handlers are listed under logging's lock (another thread adding a logger meanwhile changed the dict
    while it was walked), waiting for it at most ``LOGGING_LOCK_SECONDS``."""
    import io

    old, new = io.StringIO(), io.StringIO()
    handler = logging.StreamHandler(old)
    logger = logging.getLogger("helab.test.console-tee-swap")
    logger.addHandler(handler)
    lock = cast(Any, logging)._lock
    try:
        lock.acquire()
        swapper = threading.Thread(target=console_tee._swap_handler_streams, args=(old, new), daemon=True)
        try:
            swapper.start()
            time.sleep(0.3)
            assert swapper.is_alive() and handler.stream is old  # (Waiting for the lock.)
        finally:
            lock.release()
        swapper.join(timeout=10)
        assert not swapper.is_alive() and handler.stream is new
        monkeypatch.setattr(console_tee, "LOGGING_LOCK_SECONDS", 0.05)
        held = threading.Event()
        done = threading.Event()

        def hold() -> None:
            with lock:
                held.set()
                done.wait(10)

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        try:
            assert held.wait(10)
            console_tee._swap_handler_streams(new, old)  # (The lock held elsewhere: done without it, at once.)
            assert handler.stream is old
        finally:
            done.set()
            holder.join(timeout=10)
    finally:
        logger.removeHandler(handler)


def test_the_console_file_is_off_under_the_test_suite(tmp_path: Path) -> None:
    assert os.environ.get(console_tee.OFF_ENV)  # (conftest)
    assert console_tee.start(str(tmp_path)) is None and not list(tmp_path.glob("console-*"))


def test_the_console_file_rotates_once_at_its_cap_and_is_tidied_with_the_logs(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    path = tmp_path / "logs" / "console-404.txt"
    tee = console_tee.ConsoleTee(str(path), cap=10)
    tee.write(b"12345678")
    tee.write(b"abcdef")  # Past the cap: the first file becomes .1.
    tee.write(b"ghij")
    tee.write(b"klmnop")  # And again: the newest output is always kept.
    tee.stop()
    assert tee.rotations == 2 and path.read_bytes() == b"klmnop"
    assert Path(f"{path}.1").read_bytes() == b"abcdefghij"
    assert console_tee.CAP == 20 * 1000 * 1000
    found = {Path(file.path).name: file.pid for file in app_log.scan_logs(str(tmp_path))}
    assert found == {"console-404.txt": 404, "console-404.txt.1": 404}


HELD_FILE_CHILD = r"""
import logging, os, sys, time
sys.path.insert(0, sys.argv[1])
from helab.utils import console_tee
report = os.fdopen(os.dup(1), "w", buffering=1)
tee = console_tee.ConsoleTee(os.path.join(sys.argv[2], "console-held.txt"))
real_write, held = tee.write, [False]

def held_write(chunk: bytes) -> None:
    if not held[0]:
        held[0] = True
        time.sleep(3)  # (A file write held up: a busy disk, an antivirus scan of the file.)
    real_write(chunk)
tee.write = held_write
tee.start()
logger = logging.getLogger("held")
logger.addHandler(logging.StreamHandler(sys.stderr))  # (As coloredlogs' handler, first in the app.)
logger.propagate = False
worst = 0.0
for _ in range(2000):  # (200 kB: past any pipe's buffer.)
    started = time.monotonic()
    logger.warning("x" * 99)
    worst = max(worst, time.monotonic() - started)
while tee._chunks.qsize():  # (The file's writer catching up: stop waits only 2 s for it.)
    time.sleep(0.05)
time.sleep(0.2)
tee.stop()
print(f"{worst:.3f}", file=report)
"""


def test_a_held_up_file_write_never_holds_a_log_line(tmp_path: Path) -> None:
    """GT-3: the pump wrote each chunk to the file before reading the next, so a file write held 3 s filled the
    pipe and every thread's logging waited 3 s in it (the watchdog's stall line too). The file has its own writer."""
    result = subprocess.run([sys.executable, "-c", HELD_FILE_CHILD, str(ROOT), str(tmp_path)], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert float(result.stdout.strip()) < 1.0, result.stdout  # (3.0 s before.)
    assert (tmp_path / "console-held.txt").read_text().count("x" * 99) == 2000  # (Every line kept.)


def test_what_the_files_writer_couldnt_hold_is_noted_where_it_was(tmp_path: Path) -> None:
    tee = console_tee.ConsoleTee(str(tmp_path / "console-405.txt"))
    tee._chunks.put(b"before")
    tee._chunks.put(None)
    tee._write_file()
    tee.lost = 70_000  # (While the queue was full.)
    tee._chunks.put(b"after")
    tee._chunks.put(None)
    tee._write_file()
    tee.stop()
    assert (tmp_path / "console-405.txt").read_bytes() == (
        b"before\n[console file: 70,000 bytes of output lost around here: its writes were held up]\nafter")
    assert console_tee.FILE_CHUNKS == 1024


# Qt's messages in the log.

def test_qts_warnings_go_to_the_log_with_their_category_once_a_minute(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(app_log, "_qt_seen", {})
    with caplog.at_level(logging.DEBUG, logger="qt"):
        app_log.qt_message("QtWarningMsg", "qt.qpa.fonts", "Populating font family aliases took 120 ms")
        app_log.qt_message("QtWarningMsg", "qt.qpa.fonts", "Populating font family aliases took 120 ms")
        app_log.qt_message("QtCriticalMsg", "default", "QPainter::begin: Paint device returned engine == 0")
        app_log.qt_message("QtDebugMsg", "qt.core", "a debug line")
    lines = [(record.levelno, record.getMessage()) for record in caplog.records if record.name == "qt"]
    assert lines == [(logging.WARNING, "[qt.qpa.fonts] Populating font family aliases took 120 ms"),
                     (logging.ERROR, "[default] QPainter::begin: Paint device returned engine == 0")]
    assert "a debug line" in capsys.readouterr().err  # (Below a warning: the console only, as Qt prints it.)
    monkeypatch.setattr(app_log, "REPEAT_SECONDS", 0.0)
    with caplog.at_level(logging.WARNING, logger="qt"):
        app_log.qt_message("QtWarningMsg", "qt.qpa.fonts", "Populating font family aliases took 120 ms")
    assert caplog.records[-1].getMessage().endswith("(and 1 more like it since)")


def test_qts_message_handler_is_installed(caplog: pytest.LogCaptureFixture) -> None:
    from PyQt6.QtCore import qInstallMessageHandler, qWarning
    previous = app_log.install_qt_messages()
    try:
        with caplog.at_level(logging.WARNING, logger="qt"):
            qWarning("LR-15 check: a warning from Qt's side")
    finally:
        qInstallMessageHandler(previous)
    assert any("LR-15 check: a warning from Qt's side" in record.getMessage() for record in caplog.records)


# The last run's crash, named at start.

def test_the_last_runs_crash_file_is_named_at_start(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    put(tmp_path, "helab-101.log", 5 * 3600, 10)  # The run before the last.
    put(tmp_path, "crash-101.txt", 5 * 3600, 40)  # (Its crash: named when it was the last run.)
    put(tmp_path, "helper-crash-150.txt", 5.5 * 3600, 40)  # A helper of that run (before its log ended).
    put(tmp_path, "helab-202.log", 3600, 10)  # The last run.
    put(tmp_path, "crash-202.txt", 3600, 40)
    put(tmp_path, "helper-crash-303.txt", 2 * 3600, 40)  # A helper's crash while it ran.
    put(tmp_path, "helper-crash-304.txt", 2 * 3600, 0)  # (Empty: nothing.)
    with caplog.at_level(logging.WARNING):
        assert app_log.note_previous_crash(str(tmp_path)) == ["crash-202.txt", "helper-crash-303.txt"]
    assert f"The previous run crashed: see {tmp_path / 'logs' / 'crash-202.txt'}" in caplog.text
    (tmp_path / "logs" / "crash-202.txt").write_text("")
    os.utime(tmp_path / "logs" / "crash-202.txt", (time.time() - 3600, time.time() - 3600))
    assert app_log.previous_crashes(str(tmp_path)) == ["helper-crash-303.txt"]
    assert app_log.previous_crashes(str(tmp_path / "none")) == []


# The memory line while Live is on.

def test_the_memory_line_says_what_grows(qtbot: QtBot, tmp_path: Path) -> None:
    from types import SimpleNamespace
    import numpy as np
    from helab.analysis.results import RamResults
    results = RamResults()
    array = np.zeros(1000)
    for job in ("a", "b"):
        results.add(cast(Any, SimpleNamespace(job_id=job, data={"x": array, "y": array[:10], "z": np.ones(5)})))
    assert results.usage() == (2, 8000 + 2 * 40)  # (A buffer and its views count once.)
    line = app_log.memory_line(2 << 30, 1 << 30, 1 << 29, 8 << 30, results.usage(), 3, [("run_1", 1234, 57)])
    assert line.startswith("Memory while Live: RSS 2.0 GiB · RAM budget 1.5 GiB of 8.0 GiB "
                           "(datasets 1.0 GiB, plots 512 MiB) · results 2 (7.9 KiB)")
    assert line.endswith(" · open plots 3 · Live run_1: 1,234 shots, revision 57")


@pytest.mark.no_auto_data_root  # RAM only: no save left for the quit to wait for.
def test_the_main_window_logs_memory_each_minute_only_while_live_is_on(
        qtbot: QtBot, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from helab.views.explorer_live import LiveSession
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = an.run_folder(tmp_path)
    window = HelabMainWindow()
    qtbot.addWidget(window)
    window.show()
    try:
        assert window.memory_log_timer.interval() == 60_000 and window.memory_log_timer.isActive()
        qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
        window.add_new_folder_explorer_tab(target_path=str(run))
        explorer = window.tab_widget.currentWidget()
        assert isinstance(explorer, FolderExplorer)
        qtbot.waitUntil(lambda: explorer.displayed_dataset is not None
                        and explorer.displayed_dataset.path == str(run), timeout=30_000)
        assert window.log_memory() == ""  # Live off: nothing.
        dataset = explorer.displayed_dataset
        assert dataset is not None
        explorer.live = LiveSession(str(run), time.time(), set(dataset.data), dataset)
        try:
            with caplog.at_level(logging.INFO):
                line = window.log_memory()
            assert line.startswith("Memory while Live: RSS ") and " · open plots 0 · Live run: 3 shots, revision " in line
            assert line in caplog.text
        finally:
            explorer.live = None
    finally:
        an.quit_window(qtbot, window)


def test_main_starts_them_all_in_order() -> None:
    main = (ROOT / "helab" / "main.py").read_text()
    order = ["app_log.start_log_file(app_folder())", "app_log.start_crash_file(app_folder())",
             "console_tee.start(app_log.log_folder(app_folder()))", "atexit.register(console.stop)",
             "app_log.install_qt_messages()", "logging.captureWarnings(True)", "app_log.note_previous_crash(app_folder())"]
    assert [main.index(part) for part in order] == sorted(main.index(part) for part in order)
