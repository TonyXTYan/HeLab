"""The settle time's limits and default (Q33.7): a file modified more recently than this may still be being
written, so no read takes it. Standard library only, so both sides import it: the I/O helpers
(``helab.io_ops.fingerprints``, which apply the value each request carries) and the app (the settings row and
Settings → General's box)."""
from __future__ import annotations

import math

DEFAULT_SETTLE_SECONDS = 5.0
# Below 2 s a file still being written can't be told apart (``fingerprints.RACY_SECONDS``).
MIN_SETTLE_SECONDS, MAX_SETTLE_SECONDS = 2.0, 60.0


def settle_seconds(value: object) -> float | None:
    """A settle time as the setting or a request may hold it (seconds, from MIN_SETTLE_SECONDS to
    MAX_SETTLE_SECONDS, a number out of range taking the nearest), or None for one that isn't a finite
    number."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return max(MIN_SETTLE_SECONDS, min(MAX_SETTLE_SECONDS, number))
