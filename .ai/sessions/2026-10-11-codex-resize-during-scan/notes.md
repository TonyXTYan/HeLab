# Window resizing during recursive basic scans

Investigated 2026-10-11 after Tony reported that manually starting a large recursive
basic scan, then resizing, leaves the GUI apparently frozen until the scans finish.
The original app had already been closed. The investigation initially left
application code unchanged; Tony then authorized the fix, documentation and pytest updates.

## Finding

The main suspect is `HelabMainWindow.resizeEvent()` (lines 1212–1221): every resize
disables updates for the entire window, calls Qt's base handler, then schedules an
independent 100 ms timer to re-enable updates. This also disables child painting.
The handler dates to commit `59550a86`, before the current isolated I/O system.

A reduced window using this exact production handler reproduces sustained repaint
loss with real `FolderExplorer` recursive scans and real `IOService` helpers. The
event loop and scan completion remain responsive. The restore timers fire and
`updatesEnabled()` returns true, yet the tree stops receiving paint events.
Therefore timer starvation is **not** the explanation in this reproduction.

Replacing only the handler in the experimental subclass with
`QMainWindow.resizeEvent()` keeps painting active. A separate updating-label control
reproduces the same paint loss even without scans, after either one resize or a burst.
The scan makes the missing visual progress particularly noticeable.

## Evidence

Python 3.13.15, PyQt 6.11.0 / Qt 6.11.0, Qt **offscreen** platform on macOS. The probe
uses a reduced main window to avoid application startup, native settings writes,
the real source volume and production cache. Private cache/temp/app directories
are supplied through the existing environment overrides. Native icon requests
are suppressed. The comparison's `native_handler` flag means the ordinary Qt base
resize handler, **not** the native Cocoa platform.

| Probe | Production resize handler | Ordinary Qt handler |
| --- | --- | --- |
| Recursive scan, root + 100 child folders | 101 completed in 7.16 s | 101 completed in 7.83 s |
| Largest 20 ms heartbeat gap during scan | 24.2 ms | 21.8 ms |
| Tree paint events, including setup | 5, last about 0.20 s into scan | 166, continuing during scan |
| Resize restore callbacks | All 8 fired | None needed |
| Label repainting after 800 ms, single resize | 0 events | Continued painting |
| Label repainting after 800 ms, resize burst | 0 events | 20 events |

Two recursive-scan probes and four idle controls passed. These are investigation
probes, not a production regression suite. The exact native recovery at scan
completion and the underlying Qt repaint-manager mechanism remain unverified.

The runnable probe is [test_resize_probe.py](test_resize_probe.py). It now freezes
the original handler locally so the historical comparison still works after its
removal from the application. Run from the
repository root:

```bash
venv/bin/pytest -q -s .ai/sessions/2026-10-11-codex-resize-during-scan/test_resize_probe.py -p no:cacheprovider
```

## Recommended fix and verification

Remove the main-window resize override and its delayed re-enable callback, allowing
Qt to handle resizing and painting normally. Remove the now-unused `QResizeEvent`
import if it has no other use. Keep scan scheduling and I/O lanes unchanged.

Add a focused regression that checks ongoing paint delivery and event-loop/input
responsiveness after single and repeated resizes while scan work remains active;
checking only `updatesEnabled()` would miss the reproduced failure. Check native
macOS with the reported manual recursive scan, confirming visible progress and
Cancel work before completion, then validate focused tests and strict typing.

Qt documents that disabling updates also disables child widgets' painting, and
that resize handling is followed by painting without custom drawing in the handler:
[QWidget documentation](https://doc.qt.io/qt-6/qwidget.html#updatesEnabled-prop),
[resizeEvent](https://doc.qt.io/qt-6/qwidget.html#resizeEvent).

## Implementation

Removed `HelabMainWindow.resizeEvent()`, its delayed re-enable callback and unused
`QResizeEvent` import. The main window inherits Qt's normal resize handling.
Removed the obsolete commented test that expected global update suppression.
Scan scheduling, shared subscriptions and I/O lanes are unchanged.

`tests/test_window_resize.py` adds single/repeated-resize cases for an updating
label and a recursive basic scan. The scan uses real model/cache event delivery,
100 child nodes and a held started request, so it remains active while the test
observes ongoing tree paint events and a heartbeat, then clicks the real scan
toolbar control and verifies cancellation. The reduced test window avoids full
application startup, native settings writes and production filesystem access.

Before the fix, the label's single-resize case failed because paint delivery never
resumed; the other three cases passed. They also cover supported behavior after
the fix without depending on how consistently the old Qt repaint failure appears.
Native checks remain in
[MANUAL_TODO](../../MANUAL_TODO.md). Tony authorized committing these changes after validation.

Validation (Python 3.13.15, offscreen Qt):

- `venv/bin/pytest -q tests/test_window_resize.py`: **4 passed** (final test setup).
- `venv/bin/pytest -q -n 4 --ignore=tests/test_typing.py`: **623 passed, 1 skipped,
  2 xfailed**. The typing wrapper tests were excluded because the strict tools
  were run directly below. Three warnings report Dash's fixed-port collision
  between parallel workers; no test failed.
- `venv/bin/mypy helab tests --strict`: no issues in 92 source files.
- `venv/bin/pyright helab tests`: 0 errors, 0 warnings.
- `git diff --check`: clean.

The final test window constructs only the scan toolbar and tab widget, avoiding
the menu setup and its native QSettings/global-service configuration. After this
test-only isolation change, the four resize cases and both type checkers passed
again. Native macOS/Windows behavior has not yet been checked.
