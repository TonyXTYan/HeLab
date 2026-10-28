"""``reconstruct(pulses, profile, backend=…)``: raw pulses to TXY hits through one backend interface.

A backend is registered by name with the callable that runs it and a check of whether it can run
here (its package installed, a GPU present) and with a given profile. Stage 1 has ``reference``
(``backends/reference.py``, the plain-Python port); stage 2 adds ``numpy``, ``numba``, ``cython``,
``rust``, ``mlx``, each a module in ``backends/`` that calls ``register_backend`` on import **and**
a line in ``_MODULES`` below, so the backend is found by name in any process (a spawned worker of
the timing harness's process pool imports only what ``_MODULES`` names); callers don't change.
Every backend must give the reference's output byte for byte (``check``).

Hits are an ``(n, 3)`` float64 array of T (s, from the trigger), X and Y (m), sorted by T.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Callable, Mapping, Protocol

import numpy as np
import numpy.typing as npt

from helab.convert.profile import DetectorProfile
from helab.convert.raw import RawPulses

Hits = npt.NDArray[np.float64]
DEFAULT_BACKEND = "reference"


class BackendError(RuntimeError):
    """No such backend, or it can't run here or with this profile."""


class NoRowsError(ValueError):
    """The raw file has no rows. MATLAB stops with an index error at ``t_zero = raw(1,2)`` and
    writes no TXY; every backend raises this instead (when the profile subtracts time zero)."""


class Run(Protocol):
    def __call__(self, pulses: RawPulses, profile: DetectorProfile) -> Hits: ...


@dataclass(frozen=True)
class Backend:
    """``unavailable(profile)`` gives why the backend can't run here, or with this profile when
    one is given, or None when it can. ``releases_gil``: threads converting different shots run
    in parallel (the timing harness's ``threads`` mode is only worth timing then)."""
    name: str
    run: Run
    unavailable: Callable[[DetectorProfile | None], str | None]
    releases_gil: bool = False
    description: str = ""


_BACKENDS: dict[str, Backend] = {}
# Every backend's name and the module that registers it on import, imported on first use. A new
# backend adds its line here; one registered only from its own module is missing in spawned
# processes.
_MODULES = {"reference": "helab.convert.backends.reference",
            "cython": "helab.convert.backends.cython",
            "numba": "helab.convert.backends.numba_backend"}


def register_backend(backend: Backend) -> None:
    if backend.name in _BACKENDS and _BACKENDS[backend.name] is not backend:
        raise BackendError(f"Backend {backend.name!r} is already registered")
    _BACKENDS[backend.name] = backend


def backends() -> Mapping[str, Backend]:
    for name in _MODULES:
        _load(name)
    return dict(_BACKENDS)


def get_backend(name: str) -> Backend:
    _load(name)
    try:
        return _BACKENDS[name]
    except KeyError:
        raise BackendError(f"No backend {name!r} (have {sorted(backends())})") from None


def available_backends(profile: DetectorProfile | None = None) -> list[str]:
    return sorted(name for name, backend in backends().items() if backend.unavailable(profile) is None)


def reconstruct(pulses: RawPulses, profile: DetectorProfile, backend: str = DEFAULT_BACKEND) -> Hits:
    chosen = get_backend(backend)
    reason = chosen.unavailable(profile)
    if reason is not None:
        raise BackendError(f"Backend {backend!r} can't run: {reason}")
    return chosen.run(pulses, profile)


def _load(name: str) -> None:
    if name not in _BACKENDS and name in _MODULES:
        importlib.import_module(_MODULES[name])
