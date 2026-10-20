"""g² pair correlations of velocity-space events (D12, collinear; D13, back-to-back).

The estimator (roadmaps/dld-front-panel-port.md D12; the legacy ``calc_any_g2_type``,
``corr_1d_cart`` and ``corr_radial``, re-derived here, not copied):

    g²(Δ) = [H_in(Δ) / P_in] / [H_between(Δ) / P_between]

- ``H_in`` counts **in-shot pairs**: two distinct events of the same shot, with their
  separation Δ in a bin. ``H_between`` counts **between-shot pairs**: one event from each of
  two different shots. Shots are independent, so between-shot pairs carry the product of the
  mean densities and no correlation: the reference that g² is measured against.
- Pairs are **ordered** throughout: each unordered pair counts twice, once from each event,
  so ``P_in = Σ_s n_s (n_s − 1)`` and ``P_between = Σ_{s≠t} n_s n_t = (Σ n)² − Σ n²`` (twice
  the unordered Σ n_s(n_s−1)/2 and Σ_{s<t} n_s n_t: the factor 2 cancels in the ratio). A 1D
  collinear histogram is then symmetric in Δ by construction, and every count is an integer,
  so an incremental update is exactly a full recompute.
- Dividing each histogram by its pair total makes g² a ratio of pair *distributions*. Bin
  volumes (the window area × bin width, the shell volume) cancel and need no division. The
  normalisation fixes the mean of g² over all pairs at 1, which removes shot-to-shot atom
  number noise (technical noise would otherwise raise g² everywhere), at a cost: the bump
  itself is in that mean, so the whole curve is divided by 1 + β, β ≈ ∫(g² − 1) A(Δ) dΔ /
  ∫ A(Δ) dΔ (A the cloud's autocorrelation; (σ_c / (√2 σ))³ for a Gaussian peak of width σ_c
  in a Gaussian cloud of width σ on each axis, 3·10⁻⁴ at σ_c = σ/10: the "1 / number of
  modes" of a thermal source). The baseline drops to 1/(1 + β) with the peak, so the peak
  over the *fitted* baseline, (b + A)/b, is free of it; a baseline fixed at 1 (the legacy
  fit) is not.
- The reference must match the shots: a cloud that moves (pointing jitter) or changes size
  from shot to shot makes the between-shot pairs broader than the in-shot ones, and the ratio
  a broad bump at 0 ((1 + j²/σ²)^{3/2} for a jitter j) that a baseline fixed at 1 reads as
  bunching. Hence the free baseline, the note when it isn't 1, the "slope, not a peak" check
  on the fitted width, and ``recentre`` (each shot's robust centre moved to 0 before
  counting, off by default; ``robust_centre``). A reference matched per shot (pairs with shots of similar centre and size) is a
  later option (notes.md).

Geometries (``CorrelationSpec``):
- ``"1d"`` (``corr_1d_cart``): the histogram of one component Δv_axis of the separation,
  with the other two components windowed, |Δv_⊥| ≤ ``window`` (a half-width) each. The
  window must be much narrower than the correlation length or the peak is diluted (by about
  1 − w²/(6σ_c²) per windowed axis for a Gaussian peak).
- ``"radial"`` (``corr_radial``): the histogram of |Δv|. Bin centres are the pair-weighted
  mean radius of each shell for a flat pair density, ¾ (b⁴ − a⁴)/(b³ − a³), not the edge
  midpoint (which the legacy code admits is wrong).

Modes: ``"cl"`` (collinear) uses Δ = v₁ − v₂; ``"bb"`` (back-to-back, D13) uses
Δ = v₁ + v₂ − 2·origin, so pairs emitted back to back from a source at ``origin`` (moving
at it: a halo's centre) peak at 0. Without an origin, 0 is used: the data must already be
centred, and a source moving at δ puts the peak at 2δ.

Pairs are found with ``scipy.spatial.KDTree`` (``sparse_distance_matrix`` within the
largest separation, Chebyshev on axes scaled so the 1D slab becomes a cube), then filtered
and binned exactly from the input coordinates: never a Python loop over events. New shots
are compared with the earlier ones held in trees grouped like a binary counter (a block of
2ᵏ shots is rebuilt only when it merges), so building from S shots costs O(N log S) in tree
builds plus the pairs themselves.

Live reuse (``PairCounts``): the state holds each shot's in-shot histogram and its
between-shot histogram ``R_s`` (ordered pairs with an event of s first, against every other
shot held), with the pair totals. Adding a shot compares it with the shots held (once per
pair) and updates both sides; removing one subtracts the same counts. Each shot's in-shot
histogram is also kept in a caller's ``cache`` (a plain dict, keyed by
``(shot, fingerprint, spec.key())``), so a rebuild after a parameter change that keeps the
binning, or another plot of the same folder, reads instead of recounting. Between-shot
counts depend on the other shots, so they live only in the state.

The between-shot reference can be **banded** (``partners=K``): each shot is paired with the
K shots on either side of it in the order added, instead of all others: ~S·2K shot pairs
instead of S², for long runs. P_between then sums n_s n_t over those pairs only. Unbiased
when shots are interchangeable; when the cloud drifts slowly through a run it is closer to
each shot's own conditions than the all-pairs reference, but noisier (fewer pairs).

Errors: the shot bootstrap (``bootstrap.bootstrap_shots``) of the per-shot counts, cheap
because no pairs are recounted. The state also keeps the shot-pair matrix B[s, t, bin]
(ordered pairs with an event of s first against shot t; up to ``MATRIX_LIMIT`` numbers), so
a replicate with shot multiplicities c has numerator c·H_in / c·P_in and reference
cᵀBc / Σ_{s≠t partners} c_s c_t n_s n_t: the reference is resampled too, and a shot's copies
never pair with each other (B[s, s] = 0). The same matrix gives the exact delete-one-shot
jackknife (``jackknife_se``). Past the limit the state drops it and each drawn shot keeps
its reference against all the others (c·R / c·Q), noted as optimistic (notably below ~10
shots). ``counting_se`` (g² √(1/H_in + 1/H_between)) is reported beside them but
underestimates: pairs sharing an event aren't independent.

The peak fit (``peak_model``, ``fit_peak``): b + A exp(−(Δ − c)²/2σ²), centred at 0 for
radial g², averaged over each bin by ``fits.fit_histogram`` (exact edges; r²-weighted over
radial shells), weighted by the bootstrap SE (floored at a one-count error for bins with
few pairs). g²(0) = (b + A)/b. Its SE is the larger of the spread of refits of
``FIT_RESAMPLES`` bootstrap replicates (× √(S/(S − 1))) and the jackknife of refits of the
delete-one-shot curves, since neighbouring bins share shots and the single fit's covariance
is too small; below ``ROUGH_SHOTS`` shots it is noted as rough. With no peak (a failed fit,
a slope) there is no g²(0); ``near_zero``, the pooled g² of the bins nearest 0, says what
the data show instead. ``baseline="fixed"`` fits 1 + A·Gaussian as the legacy code did.

``cancelled`` is polled between shots and between blocks of query points, and raises
``results.Cancelled``. A time ``budget`` (seconds) stops adding shots once spent: the result
then covers the shots already added (``shots_used``, ``complete`` False, a note) and is the
g² of exactly those shots, never a mix; a later ``update`` continues from there.

Pure NumPy/SciPy, no Qt, no I/O; inputs are never written to.
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Hashable
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal, MutableMapping, Sequence, cast

import numpy as np
import numpy.typing as npt
from scipy.spatial import KDTree

from helab.analysis.bootstrap import DEFAULT_N_BOOT, DEFAULT_SEED, BootstrapResult, bootstrap_shots
from helab.analysis.estimates import Estimate, finite_or_none
from helab.analysis.fits import MAX_EVALUATIONS, FitModel, FitResult, ModelParameter, Role, fit_histogram
from helab.analysis.results import Cancelled

Array = npt.NDArray[np.float64]
Counts = npt.NDArray[np.int64]
Geometry = Literal["1d", "radial"]
Mode = Literal["cl", "bb"]
ShotId = int
CacheKey = tuple[ShotId, Hashable, str]
Cancel = Callable[[], bool] | None

CHUNK = 2048  # query points per sparse_distance_matrix call: bounds the pairs held at once
PAD = 1e-9  # the tree's search radius is widened by this share, then pairs are filtered exactly
MIN_PAIRS = 100  # fewer in-shot pairs in range than this: a note (g² is mostly noise)
# The shot-pair matrix B[s, t, bin] the bootstrap resamples the reference from is kept up to
# this many numbers (64 MB): S²·bins, so 400 shots of 50 bins. Beyond it the state drops it.
MATRIX_LIMIT = 8_000_000
FIT_RESAMPLES = 200  # bootstrap replicates refitted for g²(0)'s SE
REFIT_EVALUATIONS = 1000  # per refit of a resampled curve, started from the fit (``_warm``)
SLOPE_WIDTH = 1 / 3  # a fitted σ above this share of the reach is a slope, not a peak
BASELINE_SE = 2.0  # a fitted baseline this many SEs from 1 gets a note
JACKKNIFE_REFITS = 100  # up to this many shots, g²(0)'s SE also refits the delete-one curves
ROUGH_SHOTS = 10  # below this many shots g²(0)'s error is noted as rough
FAILED_FITS = 0.2  # a larger share of failed replicate fits is noted
NEAR_BINS = 3  # "g² near 0": the pooled g² of this many bins nearest 0, when there's no peak
RECENTRE_WINDOW = 3.0  # re-centring: events within this many robust σ (1.4826 MAD) of the median


@dataclass(frozen=True)
class CorrelationSpec:
    """What to histogram. ``edges`` (strictly increasing, m/s): Δv_axis for ``"1d"`` (any
    sign), |Δv| for ``"radial"`` (from ≥ 0). ``window``: the 1D half-width on each other
    component. ``origin``: the BB source's velocity (m/s, in the events' column order), None
    for 0. ``partners``: None compares every shot with every other; K pairs each with the K
    before and after it. ``events_key``: anything upstream that changes the events but not
    their fingerprints (the release time, a mask), so cached in-shot counts aren't reused
    across it. ``recentre`` moves each shot's robust centre (``robust_centre``) to 0 first
    (off by default), so a cloud that moves from shot to shot (pointing jitter) doesn't make
    the reference broader than the shots. In-shot separations don't change, but each centre
    comes from the shot's own events, so the reference narrows by its error: g² near 0 dips
    by about 1.5/n (n events per shot; 0.4 % at 400). For BB the origin becomes per shot:
    relative to each shot's centre."""
    geometry: Geometry
    edges: tuple[float, ...]
    mode: Mode = "cl"
    axis: int = 0
    window: float = math.inf
    origin: tuple[float, float, float] | None = None
    partners: int | None = None
    events_key: str = ""
    recentre: bool = False  # subtract each shot's mean velocity before counting

    def __post_init__(self) -> None:
        edges = tuple(float(edge) for edge in self.edges)
        object.__setattr__(self, "edges", edges)
        if len(edges) < 2 or not all(math.isfinite(edge) for edge in edges) or \
                any(b <= a for a, b in zip(edges, edges[1:])):
            raise ValueError("edges must be at least 2 finite, strictly increasing numbers")
        if self.geometry not in ("1d", "radial"):
            raise ValueError(f"unknown geometry {self.geometry!r}")
        if self.mode not in ("cl", "bb"):
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.geometry == "radial" and edges[0] < 0:
            raise ValueError("radial edges start at 0 or above")
        if self.geometry == "1d":
            if self.axis not in (0, 1, 2):
                raise ValueError("axis must be 0, 1 or 2")
            if not (self.window > 0 and math.isfinite(self.window)):
                raise ValueError("a 1D correlation needs a finite window > 0")
        if self.origin is not None:
            if self.mode != "bb":
                raise ValueError("an origin is for back-to-back (bb) correlations")
            origin = tuple(float(x) for x in self.origin)
            if len(origin) != 3 or not all(math.isfinite(x) for x in origin):
                raise ValueError("origin must be 3 finite numbers")
            object.__setattr__(self, "origin", origin)
        if self.partners is not None and self.partners < 1:
            raise ValueError("partners must be at least 1 (or None for all shots)")

    @property
    def bins(self) -> int:
        return len(self.edges) - 1

    @property
    def centres(self) -> Array:
        edges = np.asarray(self.edges)
        a, b = edges[:-1], edges[1:]
        if self.geometry == "radial":
            return cast(Array, 0.75 * (b ** 4 - a ** 4) / (b ** 3 - a ** 3))
        return cast(Array, (a + b) / 2)

    def key(self) -> str:
        """The binning key of cached in-shot counts: everything they depend on (not
        ``partners``, which only changes the between-shot reference)."""
        return json.dumps({"geometry": self.geometry, "mode": self.mode, "edges": list(self.edges),
                           "axis": self.axis if self.geometry == "1d" else None,
                           "window": self.window if self.geometry == "1d" else None,
                           "origin": list(self.origin) if self.origin else None,
                           "events_key": self.events_key, "recentre": self.recentre}, sort_keys=True)

    def as_record(self) -> dict[str, Any]:
        return {"geometry": self.geometry, "mode": self.mode, "edges": list(self.edges),
                "axis": self.axis if self.geometry == "1d" else None,
                "window": finite_or_none(self.window) if self.geometry == "1d" else None,
                "origin": list(self.origin) if self.origin else None,
                "partners": self.partners, "events_key": self.events_key, "recentre": self.recentre}

    # How pairs are searched: query points scale(v) against tree points scale(v) (CL) or
    # scale(2·origin − v) (BB); a separation inside the bins has Minkowski-p distance ≤ radius.
    @property
    def _scale(self) -> Array:
        scale = np.ones(3)
        if self.geometry == "1d":
            reach = max(abs(self.edges[0]), abs(self.edges[-1]))
            scale[self.axis] = self.window / reach if reach > 0 else 1.0
        return scale

    @property
    def _radius(self) -> float:
        radius = self.window if self.geometry == "1d" else self.edges[-1]
        return radius * (1 + PAD) + 1e-300

    @property
    def _p(self) -> float:
        return math.inf if self.geometry == "1d" else 2.0

    @property
    def _origin2(self) -> Array:
        return 2 * np.asarray(self.origin if self.origin else (0.0, 0.0, 0.0))


@dataclass(frozen=True)
class ShotEvents:
    """One shot's events in velocity space ((n, 3), m/s, ``velocity.VELOCITY_AXES`` order).
    ``shot`` is its shot number and ``fingerprint`` anything hashable that changes when its
    events do (the TXY file's ``dataset_view.Fingerprint``). Rows with a non-finite value
    (no velocity) are left out."""
    shot: ShotId
    fingerprint: Hashable
    events: Array = field(repr=False)


@dataclass(frozen=True)
class InShot:
    """A shot's in-shot histogram (ordered pairs per bin) and the events it used: the value
    kept in a caller's cache."""
    counts: Counts = field(repr=False)
    events: int

    def __post_init__(self) -> None:
        self.counts.flags.writeable = False

    @property
    def pairs(self) -> int:
        return self.events * (self.events - 1)


def _check(cancelled: Cancel) -> None:
    if cancelled is not None and cancelled():
        raise Cancelled()


def _finite(events: npt.ArrayLike) -> Array:
    values = np.asarray(events, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"events must be (n, 3), not {values.shape}")
    return values[np.all(np.isfinite(values), axis=1)]


def robust_centre(events: Array) -> Array:
    """A shot's centre for ``recentre``, as ``release._origin`` finds the rest cloud's: the
    mean of the events within ±``RECENTRE_WINDOW`` robust σ (1.4826 MAD) of the median on
    every axis, the window found twice (about the median, then about what it kept), so a
    background or another cloud doesn't pull it. The median when fewer than 2 are kept."""
    chosen = events
    for _ in range(2):
        if len(chosen) < 2:
            break
        middle = np.median(chosen, axis=0)
        spread = 1.4826 * np.median(np.abs(chosen - middle), axis=0)
        kept = events[np.all(np.abs(events - middle) <= RECENTRE_WINDOW * spread, axis=1)]
        if len(kept) < 2:
            break
        chosen = kept
    return cast(Array, chosen.mean(axis=0) if len(chosen) >= 2 else np.median(events, axis=0))


def _tree_points(spec: CorrelationSpec, events: Array) -> Array:
    points = spec._origin2 - events if spec.mode == "bb" else events
    return points * spec._scale


def _separations(spec: CorrelationSpec, a: Array, b: Array) -> Array:
    """Each pair's separation vector from the events themselves (symmetric in floating
    point: −(a − b) is b − a, and a + b is b + a)."""
    return (a + b) - spec._origin2 if spec.mode == "bb" else a - b


def _values(spec: CorrelationSpec, d: Array) -> tuple[Array, npt.NDArray[np.bool_]]:
    """The histogrammed value of each separation and which pairs pass the window."""
    if spec.geometry == "1d":
        others = [axis for axis in range(3) if axis != spec.axis]
        keep = (np.abs(d[:, others[0]]) <= spec.window) & (np.abs(d[:, others[1]]) <= spec.window)
        return d[:, spec.axis], keep
    return cast(Array, np.sqrt((d * d).sum(axis=1))), np.ones(len(d), dtype=bool)


def _bin_index(spec: CorrelationSpec, values: Array) -> npt.NDArray[np.intp]:
    """Bins [e_k, e_k+1), the last closed (``np.histogram``'s rule); −1 outside."""
    edges = np.asarray(spec.edges)
    index = np.searchsorted(edges, values, side="right") - 1
    index[values == edges[-1]] = spec.bins - 1
    index[(index < 0) | (index >= spec.bins)] = -1
    return index


def _pairs(spec: CorrelationSpec, queries: Array, tree: KDTree, cancelled: Cancel
           ) -> Iterable[tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]]:
    """(query index, tree index) of every candidate pair, a block of query points at a time."""
    scaled = queries * spec._scale
    for start in range(0, len(scaled), CHUNK):
        _check(cancelled)
        block = KDTree(scaled[start:start + CHUNK])
        found = block.sparse_distance_matrix(tree, spec._radius, p=spec._p, output_type="ndarray")
        yield found["i"].astype(np.intp) + start, found["j"].astype(np.intp)


def in_shot_counts(spec: CorrelationSpec, events: npt.ArrayLike, cancelled: Cancel = None) -> InShot:
    """One shot's in-shot histogram of ordered pairs of distinct events."""
    points = _finite(events)
    counts = np.zeros(spec.bins, dtype=np.int64)
    if len(points) >= 2:
        tree = KDTree(_tree_points(spec, points))
        for i, j in _pairs(spec, points, tree, cancelled):
            distinct = i != j
            i, j = i[distinct], j[distinct]
            values, keep = _values(spec, _separations(spec, points[i], points[j]))
            index = _bin_index(spec, values[keep])
            counts += np.bincount(index[index >= 0], minlength=spec.bins).astype(np.int64)
    return InShot(counts, len(points))


@dataclass
class _Block:
    """Events of some held shots in one tree. ``owners`` holds each event's position in
    ``slots`` (the shots' state slots)."""
    slots: list[int]
    events: Array
    owners: npt.NDArray[np.intp]
    tree: KDTree

    @classmethod
    def of(cls, spec: CorrelationSpec, parts: Sequence[tuple[int, Array]]) -> _Block:
        slots = [slot for slot, _ in parts]
        events = np.concatenate([events for _, events in parts]) if parts else np.empty((0, 3))
        owners = np.repeat(np.arange(len(parts), dtype=np.intp), [len(events) for _, events in parts])
        return cls(slots, events, owners, KDTree(_tree_points(spec, events)))


def _cross(spec: CorrelationSpec, new: Array, block: _Block, cancelled: Cancel) -> tuple[Counts, Counts]:
    """Pairs of ``new``'s events with each block shot's, (len(slots), bins) each: (the new
    shot's event first; the block shot's event first)."""
    bins = spec.bins
    forward = np.zeros(len(block.slots) * bins, dtype=np.int64)
    backward = np.zeros(len(block.slots) * bins, dtype=np.int64)
    if not len(new) or not len(block.events):
        return forward.reshape(len(block.slots), bins), backward.reshape(len(block.slots), bins)
    for i, j in _pairs(spec, new, block.tree, cancelled):
        values, keep = _values(spec, _separations(spec, new[i], block.events[j]))
        values, owners = values[keep], block.owners[j[keep]]
        index = _bin_index(spec, values)
        inside = index >= 0
        forward += np.bincount(owners[inside] * bins + index[inside], minlength=len(forward)).astype(np.int64)
        # From the other event's side the separation is −Δ for CL, the same for BB, and
        # |Δ| the same either way.
        back = _bin_index(spec, -values) if spec.mode == "cl" and spec.geometry == "1d" else index
        inside = back >= 0
        backward += np.bincount(owners[inside] * bins + back[inside], minlength=len(backward)).astype(np.int64)
    return forward.reshape(len(block.slots), bins), backward.reshape(len(block.slots), bins)


@dataclass
class _Entry:
    shot: ShotId
    fingerprint: Hashable
    events: Array
    in_shot: InShot
    cross: Counts  # R_s: ordered pairs with this shot's event first, against the shots it pairs with
    cross_pairs: int  # Q_s: Σ n_s n_t over those shots
    # This shot's row of the shot-pair matrix: partner slot → its pairs with this shot's
    # event first (every partner, zeros included); None once the state dropped the matrix.
    pairs: dict[int, Counts] | None = None


class PairCounts:
    """The per-shot pair counts of a set of shots, updated a shot at a time (see the module
    docstring). Not thread-safe: one analysis run uses it at a time."""

    def __init__(self, spec: CorrelationSpec, cache: MutableMapping[CacheKey, InShot] | None = None) -> None:
        self.spec = spec
        self.cache = cache
        self._entries: dict[int, _Entry] = {}  # slot → entry, in the order added
        self._next = 0
        self._blocks: list[_Block] = []
        self.cache_hits = 0
        self.matrix_kept = True  # False once the shot-pair matrix outgrew MATRIX_LIMIT

    @property
    def shots(self) -> tuple[ShotId, ...]:
        return tuple(entry.shot for entry in self._entries.values())

    @property
    def fingerprints(self) -> dict[ShotId, Hashable]:
        return {entry.shot: entry.fingerprint for entry in self._entries.values()}

    def __len__(self) -> int:
        return len(self._entries)

    def _in_shot(self, shot: ShotEvents, events: Array, cancelled: Cancel) -> InShot:
        key: CacheKey = (shot.shot, shot.fingerprint, self.spec.key())
        if self.cache is not None:
            found = self.cache.get(key)
            if found is not None:
                self.cache_hits += 1
                return found
        counted = in_shot_counts(self.spec, events, cancelled)
        if self.cache is not None:
            self.cache[key] = counted
        return counted

    def _partners(self) -> list[_Block]:
        """The trees a newly added shot is compared with: every held shot's (all pairs), or
        a temporary one of the last K shots added (banded)."""
        if self.spec.partners is None:
            return self._blocks
        last = list(self._entries.items())[-self.spec.partners:]
        return [_Block.of(self.spec, [(slot, entry.events) for slot, entry in last])] if last else []

    def add(self, shot: ShotEvents, cancelled: Cancel = None) -> None:
        """Add a shot (a shot number already held is an error: ``remove`` it first). Nothing
        changes if it's cancelled."""
        if any(entry.shot == shot.shot for entry in self._entries.values()):
            raise ValueError(f"shot {shot.shot} is already held")
        _check(cancelled)
        events = _finite(shot.events)
        if self.spec.recentre and len(events):
            events = events - robust_centre(events)
        self._insert(shot.shot, shot.fingerprint, events, self._in_shot(shot, events, cancelled), cancelled)

    def _insert(self, shot: ShotId, fingerprint: Hashable, events: Array, in_shot: InShot, cancelled: Cancel) -> None:
        updates: list[tuple[_Block, Counts, Counts]] = []
        forward = np.zeros(self.spec.bins, dtype=np.int64)
        for block in self._partners():
            ahead, back = _cross(self.spec, events, block, cancelled)
            forward += ahead.sum(axis=0)
            updates.append((block, ahead, back))
        # Apply only once every count is in, so a cancelled add leaves the state as it was.
        slot = self._next
        self._next += 1
        held = len(self._entries) + 1
        if self.matrix_kept and held * held * self.spec.bins > MATRIX_LIMIT:
            self.matrix_kept = False
            for entry in self._entries.values():
                entry.pairs = None
        row_of_new: dict[int, Counts] | None = {} if self.matrix_kept else None
        cross_pairs = 0
        for block, ahead, back in updates:
            for row, other_slot in enumerate(block.slots):
                other = self._entries[other_slot]
                other.cross = other.cross + back[row]
                other.cross_pairs += len(other.events) * len(events)
                cross_pairs += len(other.events) * len(events)
                if row_of_new is not None and other.pairs is not None:
                    other.pairs[slot] = back[row].copy()
                    row_of_new[other_slot] = ahead[row].copy()
        self._entries[slot] = _Entry(shot, fingerprint, events, in_shot, forward, cross_pairs, row_of_new)
        if self.spec.partners is None:
            self._blocks.append(_Block.of(self.spec, [(slot, events)]))
            # Merge like a binary counter: a block is rebuilt when one as large follows it.
            while len(self._blocks) >= 2 and len(self._blocks[-2].slots) <= len(self._blocks[-1].slots):
                second, first = self._blocks.pop(), self._blocks.pop()
                parts = [(s, self._entries[s].events) for s in (*first.slots, *second.slots)]
                self._blocks.append(_Block.of(self.spec, parts))

    def remove(self, shot: ShotId, cancelled: Cancel = None) -> None:
        """Drop a held shot and its pairs. Banded, every shot's partners shift, so the
        between-shot counts are rebuilt (in-shot counts kept)."""
        slot = next((s for s, entry in self._entries.items() if entry.shot == shot), None)
        if slot is None:
            raise KeyError(shot)
        _check(cancelled)
        if self.spec.partners is not None:
            kept = [entry for s, entry in self._entries.items() if s != slot]
            self._rebuild(kept, cancelled)
            return
        removed = self._entries[slot]
        blocks: list[_Block] = []
        updates: list[tuple[_Block, Counts]] = []
        for block in self._blocks:
            if slot in block.slots:
                parts = [(s, self._entries[s].events) for s in block.slots if s != slot]
                block = _Block.of(self.spec, parts)
            if block.slots:
                blocks.append(block)
                updates.append((block, _cross(self.spec, removed.events, block, cancelled)[1]))
        for block, back in updates:
            for row, s in enumerate(block.slots):
                other = self._entries[s]
                other.cross = other.cross - back[row]
                other.cross_pairs -= len(other.events) * len(removed.events)
                if other.pairs is not None:
                    other.pairs.pop(slot, None)
        del self._entries[slot]
        self._blocks = blocks

    def _rebuild(self, entries: list[_Entry], cancelled: Cancel) -> None:
        """Count the between-shot pairs of ``entries`` again, in their order, keeping their
        in-shot counts. Nothing changes if it's cancelled."""
        fresh = PairCounts(self.spec, None)
        fresh.matrix_kept = self.matrix_kept
        for entry in entries:
            fresh._insert(entry.shot, entry.fingerprint, entry.events, entry.in_shot, cancelled)
        self._entries, self._next, self._blocks = fresh._entries, fresh._next, fresh._blocks
        self.matrix_kept = fresh.matrix_kept

    def update(self, shots: Sequence[ShotEvents], cancelled: Cancel = None, budget: float | None = None,
               clock: Callable[[], float] = time.monotonic) -> tuple[ShotId, ...]:
        """Make the state hold ``shots``: drop held shots that are gone or whose fingerprint
        changed, then add the rest in order until ``budget`` seconds are spent (checked
        before each add). Returns the shots of ``shots`` not added for lack of time. Banded
        (``partners``), shots are paired in the order added: new shots belong at the end
        (Live's order); a dropped or changed shot recounts the between-shot pairs in
        ``shots``' order."""
        start = clock()
        wanted = {shot.shot: shot for shot in shots}
        if len(wanted) != len(shots):
            raise ValueError("shot numbers must be unique")
        stale = {entry.shot for entry in self._entries.values()
                 if entry.shot not in wanted or wanted[entry.shot].fingerprint != entry.fingerprint}
        if stale and self.spec.partners is not None:
            # Banded: partners follow the order, so count again in ``shots``' order, keeping
            # the in-shot counts of the shots that stay; the old state stays until it's done.
            kept = {entry.shot: entry for entry in self._entries.values() if entry.shot not in stale}
            fresh = PairCounts(self.spec, self.cache)
            fresh.matrix_kept = self.matrix_kept
            left: tuple[ShotId, ...] = ()
            for index, shot in enumerate(shots):
                if budget is not None and clock() - start >= budget:
                    left = tuple(s.shot for s in shots[index:])
                    break
                entry = kept.get(shot.shot)
                if entry is None:
                    fresh.add(shot, cancelled)
                else:
                    fresh._insert(entry.shot, entry.fingerprint, entry.events, entry.in_shot, cancelled)
            self._entries, self._next, self._blocks = fresh._entries, fresh._next, fresh._blocks
            self.matrix_kept = fresh.matrix_kept
            self.cache_hits += fresh.cache_hits
            return left
        for shot_id in stale:
            self.remove(shot_id, cancelled)
        held = set(self.shots)
        pending = [shot for shot in shots if shot.shot not in held]
        for index, shot in enumerate(pending):
            if budget is not None and clock() - start >= budget:
                return tuple(s.shot for s in pending[index:])
            self.add(shot, cancelled)
        return ()

    def arrays(self) -> tuple[Counts, Counts, Counts, Counts]:
        """Per held shot, in the order added: (H_in (S, bins), P_in (S,), R (S, bins), Q (S,))."""
        entries = list(self._entries.values())
        bins = self.spec.bins
        if not entries:
            empty = np.zeros((0, bins), dtype=np.int64)
            return empty, np.zeros(0, dtype=np.int64), empty.copy(), np.zeros(0, dtype=np.int64)
        return (np.array([e.in_shot.counts for e in entries], dtype=np.int64),
                np.array([e.in_shot.pairs for e in entries], dtype=np.int64),
                np.array([e.cross for e in entries], dtype=np.int64),
                np.array([e.cross_pairs for e in entries], dtype=np.int64))

    def held_arrays(self) -> list[npt.NDArray[Any]]:
        """Every array the state holds (events, counts, the trees' points and indices), for
        the RAM budget; the cache's ``InShot`` counts are the caller's."""
        held: list[npt.NDArray[Any]] = []
        for entry in list(self._entries.values()):
            held += [entry.events, entry.in_shot.counts, entry.cross, *(entry.pairs or {}).values()]
        for block in list(self._blocks):
            held += [block.events, block.owners, block.tree.data, block.tree.indices]
        return held

    def sizes(self) -> tuple[int, ...]:
        """Events used per held shot, in ``arrays()``' order."""
        return tuple(len(entry.events) for entry in self._entries.values())

    def matrix(self) -> tuple[Counts, npt.NDArray[np.bool_]] | None:
        """The shot-pair matrix in ``arrays()``' order: (B (S, S, bins), ordered pairs with
        shot s's event first against shot t; partner (S, S), which shot pairs are in the
        reference). The diagonal is 0 and not a partner. None once dropped (``matrix_kept``)."""
        entries = list(self._entries.items())
        if not self.matrix_kept or any(entry.pairs is None for _, entry in entries):
            return None
        position = {slot: index for index, (slot, _) in enumerate(entries)}
        size = len(entries)
        counts = np.zeros((size, size, self.spec.bins), dtype=np.int64)
        partner = np.zeros((size, size), dtype=bool)
        for index, (_, entry) in enumerate(entries):
            assert entry.pairs is not None
            for other, row in entry.pairs.items():
                counts[index, position[other]] = row
                partner[index, position[other]] = True
        return counts, partner


Baseline = Literal["free", "fixed"]
NoBootErrors = Literal["counting", "jackknife"]  # the per-bin SE without a bootstrap


def _peak_names(spec: CorrelationSpec, baseline: Baseline) -> tuple[str, ...]:
    centred = spec.geometry == "radial"
    return ("amplitude", *(() if centred else ("centre",)), "sigma", *(("baseline",) if baseline == "free" else ()))


def peak_curve(spec: CorrelationSpec, baseline: Baseline, x: npt.ArrayLike, *values: float) -> Array:
    """The peak model at points ``x``: b + A exp(−(x − c)²/2σ²), with b = 1 for a fixed
    baseline and c = 0 radially (parameters in ``peak_model``'s order)."""
    named = dict(zip(_peak_names(spec, baseline), values))
    points = np.asarray(x, dtype=np.float64)
    centre, level = named.get("centre", 0.0), named.get("baseline", 1.0)
    return level + named["amplitude"] * np.exp(-0.5 * ((points - centre) / named["sigma"]) ** 2)


def peak_model(spec: CorrelationSpec, baseline: Baseline = "free") -> FitModel:
    """The g² peak model for ``spec``: the point model ``peak_curve``. Fit it with
    ``fit_peak``, which has ``fits.fit_histogram`` average it over each bin (its exact edges;
    weighted by r² over radial shells, the pair density of a flat reference), so wide bins
    (equal-volume first shells) don't bias the peak. ``FitResult.evaluate`` (and
    ``CorrelationResult.curve``) give the model itself at points, for drawing."""
    names = _peak_names(spec, baseline)
    radial = spec.geometry == "radial"

    def point(x: Array, *values: float) -> Array:
        return peak_curve(spec, baseline, x, *values)

    def guesses(x: Array, y: Array, errors: Array) -> list[Array]:
        level = float(np.median(y)) if baseline == "free" else 1.0
        excess = y - level
        top = int(np.argmax(np.abs(excess)))
        weight = np.clip(excess * np.sign(excess[top]), 0, None)
        total = float(weight.sum())
        centre = 0.0 if radial else float(x[top])
        spread = math.sqrt(float((weight * (x - centre) ** 2).sum()) / total) if total > 0 else 0.0
        span = float(x[-1] - x[0]) if len(x) > 1 else 1.0
        named = {"amplitude": float(excess[top]), "centre": centre,
                 "sigma": max(spread, span / max(len(x), 1), 1e-300), "baseline": level}
        return [np.array([named[name] for name in names])]

    def bounds(x: Array, y: Array) -> tuple[Array, Array]:
        span = float(x[-1] - x[0]) or 1.0
        step = span / max(len(x) - 1, 1)
        top = float(np.max(np.abs(y))) or 1.0
        low = {"amplitude": -2 * top, "centre": float(x[0]) - span, "sigma": step / 100, "baseline": 0.0}
        high = {"amplitude": math.inf, "centre": float(x[-1]) + span, "sigma": 10 * span, "baseline": 2 * top + 1}
        return np.array([low[name] for name in names]), np.array([high[name] for name in names])

    roles: dict[str, tuple[str, Role]] = {
        "amplitude": ("Amplitude", "shape"), "centre": ("Centre", "position"), "sigma": ("σ", "width"),
        "baseline": ("Baseline", "shape")}
    return FitModel(f"g2_peak_{spec.geometry}_{baseline}",
                    f"{'b' if baseline == 'free' else '1'} + Gaussian{' at 0' if radial else ''}",
                    tuple(ModelParameter(name, *roles[name]) for name in names), point, guesses, bounds)


def _shell_weight(r: Array) -> Array:
    return r * r


def fit_peak(spec: CorrelationSpec, model: FitModel, g2: npt.ArrayLike, sigma: npt.ArrayLike,
             max_evaluations: int = MAX_EVALUATIONS) -> FitResult:
    """Fit ``model`` to g² per bin, averaged over each of ``spec``'s bins (exact edges; r²
    weights over radial shells)."""
    return fit_histogram(spec.centres, g2, model, sigma=sigma, edges=spec.edges, max_evaluations=max_evaluations,
                         binned=_shell_weight if spec.geometry == "radial" else True)


def _warm(model: FitModel, fitted: FitResult) -> FitModel:
    """``model`` started from ``fitted``'s parameters: refits of resampled curves (g²(0)'s
    error) are small perturbations of the fit, and starting each from scratch made noisy,
    sparse curves take ~0.8 s a refit (hundreds of them per run)."""
    start = fitted.values

    def guesses(x: Array, y: Array, errors: Array) -> list[Array]:
        return [start.copy()]
    return replace(model, guesses=guesses)


def _peak_value(fit: FitResult, baseline: Baseline) -> float:
    """g²(0) relative to the fitted baseline: (b + A)/b (1 + A for a fixed baseline)."""
    amplitude = fit["amplitude"].value
    if baseline == "fixed":
        return 1 + amplitude
    level = fit["baseline"].value
    return (level + amplitude) / level if level > 0 else math.nan


@dataclass(frozen=True)
class CorrelationResult:
    """g² per bin with its pair counts. ``se`` is the bootstrap SE when there was one
    (``se_method`` "shot bootstrap"), else ``counting_se``; ``jackknife_se`` is the
    delete-one-shot jackknife's (nan without the shot-pair matrix). ``failure`` is "" when
    g² can be shown. ``shots_used`` are the shots counted (all of them unless the time budget
    ran out: ``complete`` False). ``g2_zero`` is the peak over the fitted baseline,
    (b + A)/b, its SE from refitting bootstrap replicates (nan when there's no peak: a
    slope, a failed fit); ``baseline`` is b (1 when fixed; nan when undetermined, as under a
    slope). ``near_zero`` is the pooled g² of the bins nearest 0 ± its bootstrap SE: what to
    show when there's no peak ("no peak: g² near 0 is …"). Arrays are read-only."""
    spec: CorrelationSpec
    centres: Array = field(repr=False)
    g2: Array = field(repr=False)
    se: Array = field(repr=False)
    counting_se: Array = field(repr=False)
    se_method: str
    in_counts: Counts = field(repr=False)
    between_counts: Counts = field(repr=False)
    in_pairs: int
    between_pairs: int
    shots_used: tuple[ShotId, ...]
    shots_total: int
    complete: bool
    failure: str = ""
    notes: tuple[str, ...] = ()
    fit: FitResult | None = None
    g2_zero: Estimate = Estimate(math.nan)
    baseline: Estimate = Estimate(1.0, 0.0)
    baseline_mode: Baseline = "free"
    g2_zero_method: str = ""
    jackknife_se: Array = field(default_factory=lambda: np.empty(0), repr=False)
    near_zero: Estimate = Estimate(math.nan)  # pooled g² of the NEAR_BINS bins nearest 0, ± bootstrap SE
    bootstrap: BootstrapResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for array in (self.centres, self.g2, self.se, self.counting_se, self.in_counts, self.between_counts,
                      self.jackknife_se):
            array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def edges(self) -> Array:
        return np.asarray(self.spec.edges)

    def curve(self, x: npt.ArrayLike) -> Array:
        """The fitted peak at points ``x`` (not bin-averaged: to draw); nan without a fit."""
        points = np.asarray(x, dtype=np.float64)
        if self.fit is None or not self.fit.ok:
            return np.full(points.shape, math.nan)
        return peak_curve(self.spec, self.baseline_mode, points, *(float(v) for v in self.fit.values))

    def as_record(self) -> dict[str, Any]:
        """Strict JSON (nan as None) for a result's record."""
        def listed(array: Array) -> list[float | None]:
            return [finite_or_none(float(x)) for x in array]
        return {"spec": self.spec.as_record(), "centres": listed(self.centres), "g2": listed(self.g2),
                "se": listed(self.se), "counting_se": listed(self.counting_se), "se_method": self.se_method,
                "jackknife_se": listed(self.jackknife_se),
                "in_counts": [int(x) for x in self.in_counts],
                "between_counts": [int(x) for x in self.between_counts],
                "in_pairs": self.in_pairs, "between_pairs": self.between_pairs,
                "shots_used": list(self.shots_used), "shots_total": self.shots_total, "complete": self.complete,
                "failure": self.failure, "notes": list(self.notes),
                "fit": self.fit.as_record() if self.fit is not None else None,
                "g2_zero": self.g2_zero.as_record(), "g2_zero_method": self.g2_zero_method,
                "near_zero": self.near_zero.as_record(),
                "baseline": self.baseline.as_record(), "baseline_mode": self.baseline_mode,
                "bootstrap": self.bootstrap.as_record() if self.bootstrap is not None else None,
                "method": "in-shot over between-shot ordered pairs, each over its pair total"}


def _ratio(h_in: Array, p_in: float, h_between: Array, p_between: float) -> Array:
    with np.errstate(divide="ignore", invalid="ignore"):
        g2 = (h_in / p_in) / (h_between / p_between) if p_in > 0 and p_between > 0 else np.full(h_in.shape, math.nan)
    return cast(Array, np.where(h_between > 0, g2, math.nan))


def _resampler(state: PairCounts) -> tuple[Callable[[Array], Array], bool]:
    """g² for shot multiplicities c (S,): [c·H_in / c·P_in] / [cᵀBc / Σ_{s≠t partners} c_s c_t n_s n_t]
    from the shot-pair matrix, so a replicate resamples the reference too and a shot's
    copies never pair with each other (B[s, s] = 0). Without the matrix (too many shots),
    each drawn shot keeps its reference against all others: [c·R / c·Q] (False)."""
    h_in_s, p_in_s, cross_s, q_s = (array.astype(np.float64) for array in state.arrays())
    matrix = state.matrix()
    if matrix is not None:
        counts, partner = matrix
        pairs_of = counts.astype(np.float64)
        sizes = np.array(state.sizes(), dtype=np.float64)
        reference_pairs = np.outer(sizes, sizes) * partner

        def full(c: Array) -> Array:
            reference = c @ np.tensordot(c, pairs_of, axes=(0, 0))
            return _ratio(c @ h_in_s, float(c @ p_in_s), reference, float(c @ reference_pairs @ c))
        return full, True

    def approximate(c: Array) -> Array:
        return _ratio(c @ h_in_s, float(c @ p_in_s), c @ cross_s, float(c @ q_s))
    return approximate, False


def _jackknife(resample: Callable[[Array], Array], held: int, bins: int, cancelled: Cancel) -> tuple[Array, Array]:
    """The delete-one-shot jackknife SE per bin, √((S − 1)/S Σ (g²₍ₛ₎ − mean)²), and the
    delete-one curves g²₍ₛ₎ (S, bins)."""
    values = []
    for index in range(held):
        _check(cancelled)
        c = np.ones(held)
        c[index] = 0
        values.append(resample(c))
    table = np.array(values).reshape(held, bins)
    complete = np.isfinite(table).all(axis=0)
    spread = ((table - table.mean(axis=0)) ** 2).sum(axis=0)
    return cast(Array, np.where(complete, np.sqrt((held - 1) / held * np.where(complete, spread, 0.0)), math.nan)), table


def _zero_error(fitted: FitResult, model: FitModel, baseline: Baseline, boot: BootstrapResult | None,
                curves: Array | None, spec: CorrelationSpec, sigma: Array, cancelled: Cancel,
                noted: list[str]) -> tuple[float, str]:
    """g²(0)'s SE (neighbouring bins share shots, so the single fit's covariance is too
    small): the larger of the spread of refits of up to ``FIT_RESAMPLES`` bootstrap
    replicates, inflated by √(S/(S − 1)) (the bootstrap's small-sample shrinkage), and the
    jackknife of refits of the S delete-one curves (up to ``JACKKNIFE_REFITS`` shots). Both
    fall short with few shots (scatter/SE 1.16 at 40 shots, 1.29 at 4 before this), so below
    ``ROUGH_SHOTS`` it is noted as rough. Without a bootstrap, the covariance's, said so."""
    held = boot.shots if boot is not None else (len(curves) if curves is not None else 0)
    model = _warm(model, fitted)
    parts: list[str] = []
    errors: list[float] = []
    if boot is not None and len(boot.replicates):
        replicas = []
        for row in boot.replicates[:FIT_RESAMPLES]:
            _check(cancelled)
            refit = fit_peak(spec, model, row, sigma, REFIT_EVALUATIONS)
            replicas.append(_peak_value(refit, baseline) if refit.ok else math.nan)
        found = np.array(replicas)
        found = found[np.isfinite(found)]
        failed = len(replicas) - len(found)
        if failed > FAILED_FITS * len(replicas):
            noted.append(f"g²(0)'s error: {failed} of {len(replicas)} replicate fits failed or were undefined")
        if len(found) >= 2 and held >= 2:
            errors.append(float(np.std(found, ddof=1)) * math.sqrt(held / (held - 1)))
            parts.append(f"refits of {len(found)} of {len(replicas)} bootstrap replicates (× √(S/(S − 1)))")
    if curves is not None and 2 <= len(curves) <= JACKKNIFE_REFITS:
        leave_out = []
        for row in curves:
            _check(cancelled)
            refit = fit_peak(spec, model, row, sigma, REFIT_EVALUATIONS)
            leave_out.append(_peak_value(refit, baseline) if refit.ok else math.nan)
        values = np.array(leave_out)
        if np.all(np.isfinite(values)):
            count = len(values)
            errors.append(math.sqrt((count - 1) / count * float(((values - values.mean()) ** 2).sum())))
            parts.append(f"refits of the {count} delete-one-shot curves (jackknife)")
    if errors:
        if held < ROUGH_SHOTS:
            noted.append(f"only {held} shots: g²(0)'s error is rough (it tends to be low below {ROUGH_SHOTS})")
        return max(errors), "the larger of " + " and ".join(parts) if len(parts) > 1 else parts[0]
    if baseline == "free":
        where = model.names.index("baseline")
        se = fitted.derived(lambda p: float((p[where] + p[0]) / p[where])).se
    else:
        se = fitted["amplitude"].se
    return se, "the fit's covariance (too small: neighbouring bins are correlated)"


def _near_zero(spec: CorrelationSpec, h_in: Counts, p_in: int, h_between: Counts, p_between: int,
               boot: BootstrapResult | None) -> Estimate:
    """The pooled g² of the ``NEAR_BINS`` bins nearest Δ = 0 (ΣH_in/P_in over ΣH_between/P_between),
    ± the bootstrap SE of the same between-pair-weighted mean (else a counting SE): what to
    say when there's no peak to fit."""
    order = np.argsort(np.abs(spec.centres), kind="stable")
    bins = np.array([b for b in order if h_between[b] > 0][:NEAR_BINS], dtype=np.intp)
    if not len(bins) or p_in <= 0 or p_between <= 0:
        return Estimate(math.nan)
    inside, reference = float(h_in[bins].sum()), float(h_between[bins].sum())
    value = (inside / p_in) / (reference / p_between)
    if boot is not None and len(boot.replicates):
        weights = h_between[bins].astype(np.float64)
        rows = boot.replicates[:, bins]
        finite = np.isfinite(rows)
        with np.errstate(divide="ignore", invalid="ignore"):  # a replicate with none of these bins: nan, dropped
            pooled = (np.where(finite, rows, 0.0) * weights).sum(axis=1) / (finite * weights).sum(axis=1)
        pooled = pooled[np.isfinite(pooled)]
        se = float(np.std(pooled, ddof=1)) if len(pooled) >= 2 else math.nan
    else:
        se = value * math.sqrt(1 / inside + 1 / reference) if inside > 0 else math.nan
    return Estimate(value, se)


def g2_from_counts(state: PairCounts, *, shots_total: int | None = None, n_boot: int = DEFAULT_N_BOOT,
                   seed: int | None = DEFAULT_SEED, fit: bool = True, baseline: Baseline = "free",
                   cancelled: Cancel = None, notes: Sequence[str] = (),
                   errors: NoBootErrors = "counting") -> CorrelationResult:
    """g², its errors and the peak fit from a state's counts. ``n_boot`` 0 skips the
    bootstrap: the counting SE is used (or with ``errors`` "jackknife" the delete-one-shot
    jackknife's, where the shot-pair matrix gives it; ``se_method`` says which), and g²(0)'s SE
    comes from the jackknife refits, else the fit's covariance.
    ``baseline`` "free" (default) fits b + A·Gaussian and reports (b + A)/b; "fixed" fits
    1 + A·Gaussian, as the legacy code did (a reference that doesn't match the shots then
    shows as a peak)."""
    spec = state.spec
    h_in_s, p_in_s, cross_s, q_s = state.arrays()
    h_in, h_between = h_in_s.sum(axis=0), cross_s.sum(axis=0)
    p_in, p_between = int(p_in_s.sum()), int(q_s.sum())
    g2 = _ratio(h_in.astype(np.float64), p_in, h_between.astype(np.float64), p_between)
    with np.errstate(divide="ignore", invalid="ignore"):
        counting = cast(Array, np.where(h_in > 0, g2 * np.sqrt(1 / h_in + 1 / h_between), math.nan))
    held = len(state)
    total = held if shots_total is None else shots_total
    noted = list(notes)
    if held < total:
        noted.append(f"stopped at the time budget: {held:,} of {total:,} shots used")
    if spec.mode == "bb" and spec.origin is None:
        noted.append("back-to-back about 0: the events must be centred on the source")
    if spec.partners is not None:
        noted.append(f"between-shot pairs from the {spec.partners} shots either side of each shot")
    small = int(np.count_nonzero(p_in_s == 0))
    if small:
        noted.append(f"{small:,} shot{'s' if small > 1 else ''} with fewer than 2 events")
    failure = ""
    if held == 0:
        failure = "no shots"
    elif held < 2 or p_between == 0:
        failure = "needs at least 2 shots with events for the between-shot reference"
    elif int(h_in.sum()) == 0:
        failure = "no in-shot pairs in range"
    elif int(h_between.sum()) == 0:
        failure = "no between-shot pairs in range"
    elif int(h_in.sum()) < MIN_PAIRS:
        noted.append(f"only {int(h_in.sum()):,} in-shot pairs in range: g² is mostly noise")
    boot: BootstrapResult | None = None
    se, method = counting, "pair counting (underestimates: pairs share events)"
    jackknife = np.full(spec.bins, math.nan)
    curves: Array | None = None
    if not failure:
        resample, exact = _resampler(state)
        if exact:
            jackknife, curves = _jackknife(resample, held, spec.bins, cancelled)
        if n_boot:
            def statistic(draw: list[Any]) -> Array:
                return resample(np.bincount(np.asarray(draw, dtype=np.intp), minlength=held).astype(np.float64))
            boot = bootstrap_shots(list(range(held)), statistic, n_boot=n_boot, seed=seed, cancelled=cancelled)
            se, method = np.asarray(boot.se, dtype=np.float64), "shot bootstrap"
            noted.extend(boot.notes)
            if not exact:
                noted.append("too many shots for the shot-pair matrix: the bootstrap keeps each shot's reference "
                             "against all the others, so its error is optimistic, notably below ~10 shots")
        elif errors == "jackknife" and exact and np.isfinite(jackknife).any():
            se = np.where(np.isfinite(jackknife), jackknife, counting)
            method = "delete-one-shot jackknife"
    centres = spec.centres
    fitted: FitResult | None = None
    zero, level, zero_method = Estimate(math.nan), Estimate(1.0, 0.0), ""
    near = Estimate(math.nan) if failure else _near_zero(spec, h_in, p_in, h_between, p_between, boot)
    if not failure and fit:
        # Bins with few pairs get at least a one-count error (a bootstrap of 0 counts is 0).
        with np.errstate(divide="ignore", invalid="ignore"):
            floor = np.sqrt(np.maximum(h_in, 1)) * (p_between / p_in) / h_between
        sigma = np.fmax(np.where(np.isfinite(se), se, 0.0), floor)
        model = peak_model(spec, baseline)
        fitted = fit_peak(spec, model, g2, sigma)
        peak = False
        if fitted.ok:
            width = fitted["sigma"].value
            reach = max(abs(spec.edges[0]), abs(spec.edges[-1]))
            slope = width > SLOPE_WIDTH * reach
            if baseline == "free":
                level = fitted["baseline"]
                # A slope leaves b undetermined (it trades off against A and σ): not recorded.
                if slope or not math.isfinite(level.se) or level.se > 0.5 * abs(level.value):
                    level = Estimate(math.nan)
                elif abs(level.value - 1) > BASELINE_SE * level.se:
                    noted.append(f"the baseline is {level.text(digits=2)}, not 1: the reference doesn't match the "
                                 "shots (a cloud moving or changing between shots? try re-centring), or the peak "
                                 "holds a large share of the pairs")
            if slope:
                noted.append(f"the fitted width (σ = {width:.3g}) is comparable to the range: a slope, not a peak; "
                             "no g²(0)")
                amplitude = fitted["amplitude"]
                raised = math.isfinite(near.se) and near.value - 1 > 2 * near.se
                if amplitude.value > 0 and (raised or amplitude.value > 2 * amplitude.se):
                    noted.append("a peak wider than the range may be real: widen the range (σ_c under a third of "
                                 "it), unless the reference doesn't match the shots (try re-centring)")
            else:
                peak = True
                zero_se, zero_method = _zero_error(fitted, model, baseline, boot, curves, spec, sigma, cancelled,
                                                   noted)
                zero = Estimate(_peak_value(fitted, baseline), zero_se)
        else:
            level = Estimate(math.nan) if baseline == "free" else level
        if not peak and math.isfinite(near.value):
            noted.append(f"no peak: g² near 0 is {near.text(digits=2)} (the {NEAR_BINS} bins nearest 0)")
    return CorrelationResult(spec, centres, g2, np.asarray(se, dtype=np.float64), counting, method,
                             h_in.astype(np.int64), h_between.astype(np.int64), p_in, p_between,
                             state.shots, total, held >= total, failure, tuple(dict.fromkeys(noted)),
                             fitted, zero, level, baseline, zero_method, np.asarray(jackknife, dtype=np.float64),
                             near, boot)


def correlate(shots: Sequence[ShotEvents], spec: CorrelationSpec, *,
              cache: MutableMapping[CacheKey, InShot] | None = None, state: PairCounts | None = None,
              cancelled: Cancel = None, budget: float | None = None,
              clock: Callable[[], float] = time.monotonic, n_boot: int = DEFAULT_N_BOOT,
              seed: int | None = DEFAULT_SEED, fit: bool = True, baseline: Baseline = "free",
              errors: NoBootErrors = "counting") -> CorrelationResult:
    """g² of ``shots`` (see the module docstring). Pass the ``state`` of the previous run
    (same ``spec``) to update it instead of starting again (Live), and a ``cache`` to reuse
    in-shot counts by fingerprint; ``budget`` limits the time spent adding shots."""
    if state is None:
        state = PairCounts(spec, cache)
    elif state.spec != spec:
        raise ValueError("the state was counted with another spec")
    elif cache is not None:
        state.cache = cache
    state.update(shots, cancelled, budget, clock)
    return g2_from_counts(state, shots_total=len(shots), n_boot=n_boot, seed=seed, fit=fit, baseline=baseline,
                          cancelled=cancelled, errors=errors)


def linear_edges(low: float, high: float, bins: int) -> tuple[float, ...]:
    """``bins`` equal bins from low to high (a 1D axis: symmetric about 0 to see a CL peak's both sides)."""
    return tuple(float(x) for x in np.linspace(low, high, bins + 1))


def radial_edges(high: float, bins: int) -> tuple[float, ...]:
    """Radial edges from 0 to ``high`` with equal shell volumes (r_k = high (k/bins)^⅓), so
    every bin has about the same number of between-shot pairs near the peak."""
    return tuple(float(high * (k / bins) ** (1 / 3)) for k in range(bins + 1))
