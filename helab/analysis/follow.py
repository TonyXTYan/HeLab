"""Plots following Live (roadmaps/live-monitoring.md, "Plots following Live: L3").

Live is HeLab's, never a plot's: the main window publishes each new dataset Live shows to a
``LiveFeed`` as the next revision of the folder's view (``revise``), and each plot of that
folder that follows Live (``Follow``) reruns on the newest revision when its policy allows.

Hold and coalesce: a running analysis is never cancelled for new data. Revisions that arrive
meanwhile wait in one slot per plot (the newest replaces the one before: no backlog), and when
the run ends the next one takes the newest. A script's ``LivePolicy`` may space reruns out: at
least N new shots since the last run's input, and/or a delay after that run ended.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from helab.analysis.dataset_view import DatasetView, revise, view_of
from helab.analysis.parameters import ParameterSpec

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset

MAX_EVERY_SHOTS = 100_000
MAX_DELAY = 3600.0


@dataclass(frozen=True)
class LivePolicy:
    """When a plot following Live reruns: once ``every_shots`` new shots have come since the
    input of its last run, and not sooner than ``min_delay`` seconds after that run ended. The
    default reruns on every new shot. A script declares its own (``DatasetAnalysis.live_policy``)
    and the plot's settings start from it."""
    every_shots: int = 1
    min_delay: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= self.every_shots <= MAX_EVERY_SHOTS:
            raise ValueError(f"every_shots must be 1…{MAX_EVERY_SHOTS:,}, not {self.every_shots}")
        if not 0.0 <= self.min_delay <= MAX_DELAY or not math.isfinite(self.min_delay):
            raise ValueError(f"min_delay must be 0…{MAX_DELAY:g} s, not {self.min_delay}")

    def text(self) -> str:
        """``every shot``, ``every 5 shots, 10 s apart``."""
        every = "every shot" if self.every_shots == 1 else f"every {self.every_shots:,} shots"
        return every + (f", {self.min_delay:g} s apart" if self.min_delay else "")


# A plot's Live settings, beside (not among) its analysis's parameters: they decide when it
# runs, not what it computes, so they are no part of a result's parameters or reuse key.
LIVE_GROUP = "Live"
FOLLOW, EVERY, DELAY = "live_follow", "live_every", "live_delay"


def live_specs(policy: LivePolicy, page: str = "") -> tuple[ParameterSpec, ...]:
    """The Live group of a plot's settings, starting from its script's policy."""
    script = f"The script's default: {policy.text()}."
    return (
        ParameterSpec(FOLLOW, "Follow Live", "bool", True, group=LIVE_GROUP, page=page,
                      tip="While Live watches this plot's folder, run it again on the newest shots. Off: the "
                          "plot stays at the data it shows (pinned); on again, it catches up."),
        ParameterSpec(EVERY, "Rerun every N new shots", "int", policy.every_shots, (1, MAX_EVERY_SHOTS),
                      group=LIVE_GROUP, page=page, when=(FOLLOW, "True"),
                      tip=f"Run again once this many new shots have come since the last run's data. {script}"),
        ParameterSpec(DELAY, "Wait after a run", "float", policy.min_delay, (0.0, MAX_DELAY), " s",
                      group=LIVE_GROUP, page=page, when=(FOLLOW, "True"),
                      tip=f"Run again no sooner than this after the last run ended. {script}"))


def policy_of(values: Mapping[str, Any], default: LivePolicy) -> LivePolicy:
    """The policy set in a plot's Live settings (``default`` if they don't make a valid one)."""
    try:
        return LivePolicy(int(values.get(EVERY, default.every_shots)), float(values.get(DELAY, default.min_delay)))
    except (TypeError, ValueError):
        return default


def newer(view: DatasetView, than: DatasetView) -> bool:
    """Whether ``view`` is later data of the folder than ``than``: a later revision of the same
    input, or another input of it (e.g. data loaded again before Live started)."""
    if view.identity == than.identity:
        return view.revision > than.revision
    return view is not than


def changes(view: DatasetView, since: DatasetView) -> tuple[int, int]:
    """How ``view``'s shots differ from ``since``'s, by number and fingerprint: (shots it adds,
    shots it changes or lacks). Live only adds; data loaded again may change shots in place."""
    added = set(view.shots) - set(since.shots)
    other = {shot for shot in since.shots
             if shot not in view.shots or view.fingerprints.get(shot) != since.fingerprints.get(shot)}
    return len(added), len(other)


def shots_text(added: int, other: int, new: str = "new") -> str:
    """``3 new shots``, or ``3 new or changed shots`` when not all are additions."""
    count = added + other
    return f"{count:,} {new}{' or changed' if other else ''} shot{'' if count == 1 else 's'}"


class Follow:
    """One plot's following state. ``ran`` is the input of its run in flight or of its last
    run; ``pending`` the newest revision not run yet (one slot). Turning Follow Live off pins
    the plot at its revision: what waits is dropped and no revision is taken until it is on
    again. Live going off for the folder stops new revisions, but those already waiting still
    run as the policy allows: they came while Live was on."""

    def __init__(self, view: DatasetView, policy: LivePolicy = LivePolicy(), on: bool = True) -> None:
        self.policy = policy
        self.on = on
        self.ran = view
        self.pending: Optional[DatasetView] = None
        self.running = False
        self.finished_at = -math.inf  # Monotonic: when the last run ended.

    @property
    def latest(self) -> DatasetView:
        """The newest data this plot has: what waits, else what ran."""
        return self.pending or self.ran

    def offer(self, view: DatasetView) -> bool:
        """A newer revision of the plot's folder; kept (replacing what waited) if following and
        newer than what the plot has. Whether it was kept."""
        if not self.on or not newer(view, self.latest):
            return False
        self.pending = view
        return True

    def changes(self) -> tuple[int, int]:
        """How the data waiting differs from what ran: (shots added, shots changed or gone)."""
        return changes(self.pending, self.ran) if self.pending is not None else (0, 0)

    def waiting(self) -> int:
        """New (or changed) shots waiting for the next run (0 when nothing waits)."""
        return sum(self.changes())

    def due(self, now: float) -> tuple[Optional[DatasetView], float]:
        """The revision to run now (None: none), and the seconds until the policy's delay lets
        the waiting one run (0 when it isn't the delay that holds it). Live's next revisions run
        once ``every_shots`` new shots wait; another input of the folder (data loaded again
        before Live, with any shot added, changed or gone) runs once whatever their number."""
        if self.running or self.pending is None or not self.on:
            return None, 0.0
        waiting = self.waiting()
        if not waiting or (self.pending.identity == self.ran.identity and waiting < self.policy.every_shots):
            return None, 0.0
        left = self.finished_at + self.policy.min_delay - now
        if left > 0:
            return None, left
        return self.pending, 0.0

    def start(self, view: DatasetView) -> None:
        """A run on ``view`` starts (a following rerun, or the user's): it is what ran now."""
        self.running = True
        self.ran = view
        if self.pending is not None and not newer(self.pending, view):
            self.pending = None

    def end(self, now: float) -> None:
        self.running = False
        self.finished_at = now

    def pin(self, at: Optional[DatasetView] = None) -> None:
        """Follow Live off: the plot stays at ``at``, the data it shows (default: what ran). A run
        in flight on newer data isn't the plot's any more (``AnalysisInstance`` drops its result)."""
        self.on = False
        self.pending = None
        if at is not None:
            self.ran = at

    def unpin(self) -> None:
        self.on = True


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
