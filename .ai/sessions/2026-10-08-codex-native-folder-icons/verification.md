# Native folder icons restored

The old QFileSystemModel supplied native icons in the name column. Commit
54f79b1 replaced it with a memory-only snapshot model, dropping those icons.

The name column now shows a generic folder icon immediately. After viewport
changes, a separate native Qt helper resolves up to 64 visible folder icons in
the shared background I/O lane. Native folder, volume and macOS Finder custom
icons are transferred as 32px PNGs, displayed at 16px with 2x pixel density,
and retained in a bounded (4096 icon) session cache shared across tabs.

Rendering never queries the source filesystem, reads the disk cache or submits
work. Listings do not perform icon lookup. Icon work pauses cooperatively and
has a 5-second no-progress timeout; failed lookup retains a generic icon without
changing folder availability or scan history. Refresh invalidates visible icons
and cancels conflicting icon work, allowing a fresh lookup. Hidden tabs submit
no new icon work; navigation/closure use existing shared-job cancellation.

The helper retains the native Qt platform plugin (Cocoa on macOS). Offscreen
Qt cannot resolve Finder custom icons. No windows are created, and the helper
sets QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM to avoid a Dock entry.
API reference: https://doc.qt.io/qt-6/qfileiconprovider.html

Validation:

- Focused browser, cache, queue, responsiveness and icon tests: 142 passed,
  1 opt-in macOS test skipped in the ordinary headless run.
- The opt-in macOS test passed separately with desktop-service access. It used
  NSWorkspace to customize a temporary folder, verified custom/ordinary/volume
  icon images were distinct, then exercised the real I/O queue and folder view.
- The saved UI render was inspected: ordinary blue folder and custom red icon
  appear beside their names and fit the existing 16px row layout.
- Strict mypy for helab and tests passed (85 source files).
- Pyright for helab and tests: zero errors, warnings or information messages.
- git diff --check passed.

Validation completed before committing.
