"""The types the shared numerics' results are made of, for scripts' ``cache_types`` (result
caching R2, ``helab.analysis.result_codec``): what a saved result of a DLD plot may hold, and
``FIT_MODEL``, which saves a fit model by its key and data (its functions can't be saved) and
rebuilds it: a registered model (``fits.MODELS``) or the arrival-time profile from its fixed
constants; any other model (one a script builds, as Correlations' g² peak) comes back without its
functions, for the script's ``cache_unpack`` to put its own in. Qt-free."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, NoReturn

from helab.analysis import fits
from helab.analysis.bootstrap import BootstrapResult
from helab.analysis.estimates import Estimate
from helab.analysis.fits import FitModel, FitResult, ModelParameter
from helab.analysis.peaks import Peak
from helab.analysis.physics import ResolvedConstants
from helab.analysis.release import ReleaseTime
from helab.analysis.result_codec import Declared, Reducer
from helab.analysis.stats import CropBox


def _unavailable(*_: Any) -> NoReturn:
    raise ValueError("the fit model of a saved result can't be evaluated")


def _reduce(model: FitModel) -> dict[str, Any]:
    return {"key": model.key, "title": model.title, "parameters": model.parameters, "fixed": dict(model.fixed),
            "min_bins": model.min_bins, "slice": model.slice,
            "extras": [[extra.name, extra.title, list(extra.gates)] for extra in model.extras]}


def _rebuild(value: Any) -> FitModel:
    key, fixed = str(value["key"]), {str(name): float(number) for name, number in dict(value["fixed"]).items()}
    registered = fits.MODELS.get(key)
    if registered is not None and dict(registered.fixed) == fixed:
        return registered
    if key == "arrival_time":
        return fits.arrival_time_model(fixed["fall_distance"], fixed["g"])
    return FitModel(key, str(value["title"]), tuple(value["parameters"]), _unavailable, _unavailable, _unavailable,
                    min_bins=int(value["min_bins"]), slice=bool(value["slice"]),
                    extras=tuple(fits.Extra(str(name), str(title), _unavailable, tuple(gates))
                                 for name, title, gates in value["extras"]),
                    fixed=MappingProxyType(fixed))


FIT_MODEL = Reducer("helab.fit_model", FitModel, _reduce, _rebuild)

# What a fit, a bootstrap, a release-time detection and a crop box are made of.
COMMON: tuple[Declared, ...] = (FIT_MODEL, ModelParameter, FitResult, Estimate, BootstrapResult, Peak, ReleaseTime,
                                ResolvedConstants, CropBox)


def unavailable_model(model: FitModel) -> bool:
    """Whether ``model`` came back from a saved result without its functions (``FIT_MODEL``)."""
    return model.function is _unavailable
