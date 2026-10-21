"""The I/O helper's dispatcher (``helab.io_helper.main``), run in this process: one request line on
stdin, events on stdout. Every operation reaches its handler with the request's fields; refusals and
failures end in one ``error`` event and no ``done``. Helpers are otherwise tested as subprocesses,
where a dispatch mistake shows only as a vague failure. The handlers here are stubs: nothing is
listed, read or written."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest

from helab import io_helper
from helab.io_ops import infra, stores
from helab.io_ops.fingerprints import DEFAULT_CHECK_LEVEL
from helab.utils.data_roots import VolumeUnverified

Call = tuple[str, tuple[Any, ...], dict[str, Any]]

# Allowed by the tests' source guard (inside the temp folder), and never touched: handlers are stubs.
FOLDER = os.path.join(tempfile.gettempdir(), "helab-dispatch-no-such-folder")
PATH = os.path.join(FOLDER, "run_1")
OTHER = os.path.join(FOLDER, "run_2")
OUTPUT = os.path.join(FOLDER, "output")
CACHE = {"directory": os.path.join(FOLDER, "cache", "store-v3"), "budget": 1 << 30}
# A path the source guard refuses (tests/test_real_data_guard.py); it doesn't exist.
MOUNTED = ("\\\\no-such-server\\share\\run_1" if sys.platform == "win32"
           else "/Volumes/helab-no-such-share/run_1")

# Every handler ``main`` looks up in ``helab.io_helper``.
HANDLERS = ("list_folder", "folder_icons", "scan", "save_scan_history", "save_subtrees", "live_check",
            "save_held", "load", "read_cached", "cache_move_job", "cache_admin", "verify_known_roots",
            "verify_volumes", "trace_check", "create_root", "reassign_root", "remove_root")


@pytest.fixture(autouse=True)
def helper_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``main`` sets the process's pause flag and trace state; each test gets them back as they were."""
    monkeypatch.setattr(infra.Pause, "flag", None)
    monkeypatch.setattr(infra.Pause, "last_check", 0.0)
    monkeypatch.setattr(infra, "TRACE", None)
    monkeypatch.setattr(infra, "_trace_request", {})
    monkeypatch.setattr(infra, "_trace_fd", None)
    yield
    if infra._trace_fd is not None:
        os.close(infra._trace_fd)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    """Every handler replaced by a stub that records its arguments, all into one list."""
    made: list[Call] = []

    def stub(name: str) -> Callable[..., None]:
        def record(*args: Any, **kwargs: Any) -> None:
            made.append((name, args, kwargs))
        return record

    for name in HANDLERS:
        monkeypatch.setattr(io_helper, name, stub(name))
    return made


def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], line: str) -> list[dict[str, Any]]:
    """``main`` with ``line`` on stdin; the events it printed."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(line))
    capsys.readouterr()
    io_helper.main()
    return [json.loads(out) for out in capsys.readouterr().out.splitlines() if out.startswith("{")]


def send(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
         request: dict[str, Any]) -> list[dict[str, Any]]:
    return run(monkeypatch, capsys, json.dumps(request) + "\n")


def refused_notes() -> list[str]:
    """Paths the source guard refused so far, cleared (else ``no_real_data`` fails the test)."""
    refused: list[str] = []
    for note in Path(os.environ["HELAB_TEST_SOURCE_GUARD"]).glob("*.txt"):
        refused += note.read_text(encoding="utf-8").splitlines()
        note.unlink()
    return refused


LIVE = {"memory": [["d_1.txt", 10, 5]], "known": {"d_1.txt": 1}, "live_since": 12.5, "identity": "root://u/run",
        "seen": {"d_2.txt": [3, 4]}, "check_level": "full", "listed_mtime": 99, "seen_names": ["d_1.txt"],
        "identity_root": {"uuid": "u"}, "recent": {"d_1.txt": 1.0}}
HELD = {"held": [["d_1.txt", 10, 5]], "held_problematic": ["d_3.txt"], "identity": "root://u/run",
        "identity_root": {"uuid": "u"}, "no_cache": 1, "recent": {"d_1.txt": 2.0},
        "held_raw_times": [[1, 123]]}
LOAD = {"memory": [["d_1.txt", 10, 5]], "base_signature": "base", "signature": "sig", "limits": {"ram": 9},
        "allow_large": 1, "no_cache": 1, "full_check": 1, "cache_base": 1, "check_level": "high",
        "allow_missing": 1, "memory_check": {"quick": True}, "memory_raw_times": [[1, 2]]}

# (request, handler, positional arguments, keyword arguments)
ROUTES: list[tuple[dict[str, Any], str, tuple[Any, ...], dict[str, Any]]] = [
    ({"operation": "list", "path": PATH, "cache": CACHE}, "list_folder", (PATH,), {"cache_options": CACHE}),
    ({"operation": "list", "path": PATH}, "list_folder", (PATH,), {"cache_options": None}),
    ({"operation": "icons", "paths": [PATH, OTHER]}, "folder_icons", ([PATH, OTHER],), {}),
    ({"operation": "scan", "path": PATH, "cache": CACHE, "scan_manual": True, "automatic": True,
      "scan_operation_id": "op-7", "scan_revision": 7}, "scan", (PATH,),
     {"cache_options": CACHE, "manual": True, "automatic": True, "operation_id": "op-7", "revision": 7}),
    ({"operation": "details", "path": PATH}, "scan", (PATH,),
     {"cache_options": None, "manual": False, "automatic": False, "operation_id": "", "revision": 0}),
    ({"operation": "scan_history", "path": PATH, "cache": CACHE, "outcome": {"ok": False}, "guard": {"g": 1},
      "verified_volumes": [["/v", "dev"]]}, "save_scan_history", (CACHE, PATH, {"ok": False}, {"g": 1}),
     {"verified_volumes": [["/v", "dev"]]}),
    ({"operation": "subtree_save", "cache": CACHE, "records": [{"path": PATH}]}, "save_subtrees",
     (CACHE, [{"path": PATH}]), {"verified_volumes": None}),
    ({"operation": "load", "live": True, "path": PATH, "output": OUTPUT, **LIVE}, "live_check", (PATH, OUTPUT),
     {"memory": LIVE["memory"], "known": LIVE["known"], "since": 12.5, "identity": "root://u/run",
      "seen": LIVE["seen"], "check_level": "full", "listed_mtime": 99, "seen_names": ["d_1.txt"],
      "identity_root": {"uuid": "u"}, "recent": LIVE["recent"]}),
    ({"operation": "load", "live": True, "path": PATH, "output": OUTPUT}, "live_check", (PATH, OUTPUT),
     {"memory": None, "known": None, "since": None, "identity": "", "seen": None,
      "check_level": DEFAULT_CHECK_LEVEL, "listed_mtime": None, "seen_names": None, "identity_root": None,
      "recent": None}),
    ({"operation": "load", "save_memory": True, "held_dir": OTHER, "path": PATH, "cache": CACHE,
      "output": OUTPUT, **HELD}, "save_held",
     (PATH, infra.emit, CACHE, HELD["held"], ["d_3.txt"], OTHER),
     {"identity": "root://u/run", "identity_root": {"uuid": "u"}, "no_cache": True, "recent": HELD["recent"],
      "output": OUTPUT, "raw_times": [[1, 123]]}),
    ({"operation": "load", "save_memory": True, "held_dir": OTHER, "path": PATH}, "save_held",
     (PATH, infra.emit, None, [], [], OTHER),
     {"identity": "", "identity_root": None, "no_cache": False, "recent": None, "output": None,
      "raw_times": None}),
    ({"operation": "load", "path": PATH, "output": OUTPUT, "cache": CACHE, **LOAD}, "load", (PATH, OUTPUT),
     {"cache_options": CACHE, "memory": LOAD["memory"], "base_signature": "base", "expected": "sig",
      "limits": {"ram": 9}, "allow_large": True, "no_cache": True, "full_check": True, "cache_base": True,
      "check_level": "high", "allow_missing": True, "memory_check": {"quick": True},
      "memory_raw_times": [[1, 2]]}),
    # A save without its held folder is a plain load.
    ({"operation": "load", "save_memory": True, "held_dir": "", "path": PATH, "output": OUTPUT}, "load",
     (PATH, OUTPUT),
     {"cache_options": None, "memory": None, "base_signature": "", "expected": "", "limits": None,
      "allow_large": False, "no_cache": False, "full_check": False, "cache_base": False,
      "check_level": DEFAULT_CHECK_LEVEL, "allow_missing": False, "memory_check": None, "memory_raw_times": None}),
    ({"operation": "cached", "path": PATH, "output": OUTPUT, "cache": CACHE, "limits": {"ram": 9},
      "allow_large": 1, "verified_volumes": [["/v", "dev"]]}, "read_cached", (PATH, OUTPUT),
     {"cache_options": CACHE, "limits": {"ram": 9}, "allow_large": True, "verified_volumes": [["/v", "dev"]]}),
    ({"operation": "cache_move", "move": {"to": OTHER}}, "cache_move_job", ({"to": OTHER},), {}),
    ({"operation": "cache_admin", "cache": CACHE, "action": "purge", "params": {"days": 30, "kinds": ["x"]}},
     "cache_admin", (CACHE, "purge"), {"days": 30, "kinds": ["x"]}),
    ({"operation": "cache_admin", "cache": CACHE, "action": "inventory"}, "cache_admin", (CACHE, "inventory"), {}),
    ({"operation": "roots_verify", "cache": CACHE, "volume_ids": [["/v", "dev", "id"]]}, "verify_known_roots",
     (CACHE,), {"volume_ids": [["/v", "dev", "id"]]}),
    ({"operation": "volumes_verify", "cache": CACHE}, "verify_volumes", (CACHE,), {}),
    ({"operation": "trace_check", "temps": FOLDER, "folder": OTHER}, "trace_check", (FOLDER, OTHER, infra.emit), {}),
    ({"operation": "root_create", "path": PATH, "cache": CACHE}, "create_root", (PATH, CACHE), {}),
    ({"operation": "root_create", "path": PATH}, "create_root", (PATH, None), {}),
    ({"operation": "root_reassign", "path": PATH, "cache": CACHE, "old_uuid": "old", "keep": "smb://h/s"},
     "reassign_root", (PATH, CACHE, "old", "smb://h/s"), {}),
    ({"operation": "root_remove", "path": PATH, "cache": CACHE, "uuid": "u", "location": "smb://h/s"},
     "remove_root", (PATH, CACHE, "u", "smb://h/s"), {}),
    ({"operation": "root_remove", "path": PATH, "cache": CACHE, "uuid": "u"}, "remove_root",
     (PATH, CACHE, "u", ""), {}),
]


@pytest.mark.parametrize(("request_", "handler", "args", "kwargs"), ROUTES,
                         ids=[f"{route[0]['operation']}-{index}" for index, route in enumerate(ROUTES)])
def test_each_operation_reaches_its_handler_alone_with_the_requests_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call],
    request_: dict[str, Any], handler: str, args: tuple[Any, ...], kwargs: dict[str, Any],
) -> None:
    events = send(monkeypatch, capsys, request_)
    assert calls == [(handler, args, kwargs)]
    assert events == [{"kind": "done"}]


def test_the_routing_table_covers_every_handler_and_named_operation() -> None:
    routed = {route[0]["operation"] for route in ROUTES} | {"invalidate", "resolve", "drives"}
    assert {route[1] for route in ROUTES} == set(HANDLERS)
    assert set(io_helper.CACHE_ONLY) | io_helper.SOURCE_OPERATIONS <= routed


def test_invalidate_removes_the_folders_datasets_on_the_local_lane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call],
) -> None:
    opened: list[Call] = []

    class Store:
        def __enter__(self) -> Store:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def remove(self, kinds: tuple[str, ...], paths: list[str]) -> SimpleNamespace:
            opened.append(("remove", (kinds, paths), {}))
            return SimpleNamespace(kinds=kinds, paths=paths, datasets=1, dataset_bytes=2048)

        def next_deadline(self) -> float:
            return 1234.5

        def measure_usage(self) -> SimpleNamespace:
            return SimpleNamespace(event=lambda: {"usage": 4096, "usage_seq": ["store", 3]})

    def open_store(*args: Any, **kwargs: Any) -> Store:
        opened.append(("open", args, kwargs))
        return Store()

    monkeypatch.setattr(stores, "_cache_store", open_store)
    events = send(monkeypatch, capsys, {"operation": "invalidate", "path": PATH, "cache": CACHE})
    assert opened == [("open", (CACHE["directory"], [PATH]), {"local_lane": True}),
                      ("remove", (("datasets",), [PATH]), {})]
    assert events == [
        {"kind": "removed", "kinds": ["datasets"], "paths": [PATH], "datasets": 1, "bytes": 2048},
        {"kind": "admin_result", "action": "invalidate", "next_deadline": 1234.5, "usage": 4096,
         "usage_seq": ["store", 3]},
        {"kind": "done"}]
    assert not calls


@pytest.mark.parametrize("operation", io_helper.CACHE_ONLY)
@pytest.mark.parametrize("cache", [None, {}])
def test_cache_only_operations_are_refused_without_the_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call],
    operation: str, cache: dict[str, Any] | None,
) -> None:
    request: dict[str, Any] = {"operation": operation, "path": PATH, "output": OUTPUT, "records": [],
                               "action": "inventory", "old_uuid": "u", "keep": "", "uuid": "u"}
    if cache is not None:
        request["cache"] = cache
    events = send(monkeypatch, capsys, request)
    assert events == [{"kind": "error", "message": "The disk cache is off for this session"}]
    assert not calls


def test_an_unknown_operation_is_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call],
) -> None:
    events = send(monkeypatch, capsys, {"operation": "frobnicate", "path": PATH})
    assert events == [{"kind": "error", "message": "Unknown operation: frobnicate"}]
    assert not calls


@pytest.mark.parametrize("line", ["", "not json\n", "{}\n", '{"path": "x"}\n'],
                         ids=["closed stdin", "not json", "empty request", "no operation"])
def test_an_unreadable_request_is_one_error_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call], line: str,
) -> None:
    events = run(monkeypatch, capsys, line)
    assert len(events) == 1 and events[0]["kind"] == "error" and events[0]["message"]
    assert "unverified" not in events[0] and not calls


@pytest.mark.parametrize(("failure", "expected"), [
    (ValueError("The .helab-root changed"), {"kind": "error", "message": "The .helab-root changed"}),
    (PermissionError("denied"), {"kind": "error", "message": "denied"}),
    (VolumeUnverified("/media/usb/run_1"),
     {"kind": "error", "message": "The volume of /media/usb/run_1 is not yet verified", "unverified": True}),
], ids=["ValueError", "PermissionError", "VolumeUnverified"])
def test_a_failing_handler_ends_in_an_error_and_no_done(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: Exception,
    expected: dict[str, Any],
) -> None:
    def failing(*_: Any, **__: Any) -> None:
        infra.emit({"kind": "cache_warning", "message": "before failing"})
        raise failure

    monkeypatch.setattr(io_helper, "read_cached", failing)
    events = send(monkeypatch, capsys, {"operation": "cached", "path": PATH, "output": OUTPUT, "cache": CACHE})
    assert events == [{"kind": "cache_warning", "message": "before failing"}, expected]


def test_resolve_names_the_first_existing_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (tmp_path / "a_file").write_text("not a folder")
    candidates = ["", str(tmp_path / "missing"), str(tmp_path / "a_file"), str(first), str(second)]
    events = send(monkeypatch, capsys, {"operation": "resolve", "candidates": candidates})
    assert events == [{"kind": "resolved", "path": str(first)}, {"kind": "done"}]


def test_resolve_without_an_existing_candidate_is_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    for candidates in ([str(tmp_path / "missing"), ""], []):
        events = send(monkeypatch, capsys, {"operation": "resolve", "candidates": candidates})
        assert events == [{"kind": "error", "message": "No available default data folder"}]


def test_drives_are_listed_only_on_windows(monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    events = send(monkeypatch, capsys, {"operation": "drives"})
    if sys.platform == "win32":
        assert [event["kind"] for event in events] == ["drives", "done"]
        assert all(path.endswith(":\\") for path in events[0]["paths"]) and events[0]["paths"]
    else:
        assert events == [{"kind": "error", "message": "Drive enumeration is only supported on Windows"}]


@pytest.mark.parametrize("operation", sorted(io_helper.SOURCE_OPERATIONS))
def test_source_operations_refuse_real_data_before_their_handler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call], operation: str,
) -> None:
    assert infra.SOURCE_GUARD is not None  # (tests/conftest.py; io_helper imports it)
    request: dict[str, Any] = {"operation": operation, "path": MOUNTED, "output": OUTPUT, "cache": CACHE,
                               "old_uuid": "u", "keep": "", "uuid": "u"}
    if operation == "icons":
        request = {"operation": operation, "paths": [PATH, MOUNTED]}
    events = send(monkeypatch, capsys, request)
    assert len(events) == 1 and events[0]["kind"] == "error"
    assert "Tests never touch real data" in events[0]["message"]
    assert not calls and refused_notes() == [MOUNTED]


def test_a_cache_key_is_not_a_source_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call],
) -> None:
    """A cached read names its folder only as a cache key: the guard leaves it to the handler."""
    events = send(monkeypatch, capsys, {"operation": "cached", "path": MOUNTED, "output": OUTPUT, "cache": CACHE})
    assert [call[:2] for call in calls] == [("read_cached", (MOUNTED, OUTPUT))]
    assert events == [{"kind": "done"}] and not refused_notes()


def test_the_pause_flag_is_the_requests_control_folder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call], tmp_path: Path,
) -> None:
    send(monkeypatch, capsys, {"operation": "list", "path": PATH, "control": str(tmp_path)})
    assert infra.Pause.flag == os.path.join(str(tmp_path), "pause")
    send(monkeypatch, capsys, {"operation": "list", "path": PATH})
    assert infra.Pause.flag is None and len(calls) == 2


@pytest.mark.parametrize("fails", [False, True], ids=["done", "error"])
def test_a_traced_request_notes_its_start_and_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], calls: list[Call], tmp_path: Path,
    fails: bool,
) -> None:
    def failing(*_: Any, **__: Any) -> None:
        raise ValueError("listing failed")

    if fails:
        monkeypatch.setattr(io_helper, "list_folder", failing)
    events = send(monkeypatch, capsys, {"operation": "list", "path": PATH, "automatic": True,
                                        "trace": {"dir": str(tmp_path), "tab": "tab-1"}})
    assert events[-1]["kind"] == ("error" if fails else "done")
    lines = [json.loads(line) for line in (tmp_path / f"{os.getpid()}.jsonl").read_text("ascii").splitlines()]
    assert [line["op"] for line in lines] == ["request", "request_end"]
    assert all(line["request"] == "list" and line["target"] == PATH and line["tab"] == "tab-1"
               and line["flags"] == ["automatic"] for line in lines)
    assert lines[1].get("error") == ("listing failed" if fails else None)
