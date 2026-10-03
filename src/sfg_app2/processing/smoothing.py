"""Background smoothing: a small registry of 1-D smoothers.

Each method declares its parameters (SmoothingParam), so the GUI builds
its spinbox rows from the registry rather than knowing about any one
method -- the same idea as the fitting lineshape registry. A
SmoothingSpec (method key + parameter values) is what gets stored in
configs and provenance; ``smooth(y, spec)`` applies it.

All windows and widths are in *points* of the array being smoothed (not
nm or cm⁻¹): the homodyne background is on the camera's wavelength grid
and the heterodyne one on its uniform wavenumber grid, and a point count
is the one unit that means the same thing on both.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter, uniform_filter1d
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmoothingParam:
    name: str
    label: str
    default: float
    minimum: float
    maximum: float
    is_int: bool = True
    decimals: int = 0
    tooltip: str = ""


@dataclass(frozen=True)
class SmoothingMethod:
    key: str
    display_name: str
    params: tuple[SmoothingParam, ...]
    func: Callable[[np.ndarray, dict], np.ndarray]


_REGISTRY: dict[str, SmoothingMethod] = {}


def register_smoothing(method: SmoothingMethod):
    _REGISTRY[method.key] = method


def smoothing_methods() -> list[SmoothingMethod]:
    return list(_REGISTRY.values())


def get_smoothing(key: str) -> SmoothingMethod:
    return _REGISTRY[key]


def _odd_window(window, n: int) -> int:
    """Clamp a window to the array length and force it odd (>= 1)."""
    w = max(1, int(round(window)))
    if n > 0:
        w = min(w, n if n % 2 == 1 else n - 1)
    if w % 2 == 0:
        w += 1
    return max(w, 1)


def _savgol(y, p):
    window = _odd_window(p["window"], y.size)
    order = int(p["order"])
    if window < 3:
        return y
    order = max(0, min(order, window - 1))
    return savgol_filter(y, window, order, mode="interp")


def _moving_average(y, p):
    window = _odd_window(p["window"], y.size)
    return y if window < 2 else uniform_filter1d(y, window, mode="nearest")


def _gaussian(y, p):
    sigma = float(p["sigma"])
    return y if sigma <= 0 else gaussian_filter1d(y, sigma, mode="nearest")


def _median(y, p):
    window = _odd_window(p["window"], y.size)
    return y if window < 2 else median_filter(y, size=window, mode="nearest")


_WINDOW_TIP = "Window length in data points (forced odd)."

register_smoothing(SmoothingMethod("none", "None", (), lambda y, p: y))
register_smoothing(SmoothingMethod(
    "savgol", "Savitzky–Golay",
    (SmoothingParam("window", "Window", 11, 3, 2001, tooltip=_WINDOW_TIP),
     SmoothingParam("order", "Order", 3, 0, 10,
                    tooltip="Polynomial order (kept below the window length).")),
    _savgol,
))
register_smoothing(SmoothingMethod(
    "moving_average", "Moving average",
    (SmoothingParam("window", "Window", 9, 1, 2001, tooltip=_WINDOW_TIP),),
    _moving_average,
))
register_smoothing(SmoothingMethod(
    "gaussian", "Gaussian",
    (SmoothingParam("sigma", "Sigma", 3.0, 0.0, 500.0, is_int=False, decimals=1,
                    tooltip="Gaussian standard deviation in data points."),),
    _gaussian,
))
register_smoothing(SmoothingMethod(
    "median", "Median",
    (SmoothingParam("window", "Window", 9, 1, 2001,
                    tooltip=_WINDOW_TIP + " Robust against leftover spikes."),),
    _median,
))


@dataclass
class SmoothingSpec:
    method: str = "none"
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.method not in _REGISTRY:
            logger.warning("Unknown smoothing method %r; using none", self.method)
            self.method, self.params = "none", {}
        # Fill missing params with defaults and drop unknown ones, so a
        # spec is always complete for its method.
        method = _REGISTRY[self.method]
        self.params = {
            p.name: self._coerce(p, self.params.get(p.name, p.default)) for p in method.params
        }

    @staticmethod
    def _coerce(p: SmoothingParam, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(p.default)
        return int(round(value)) if p.is_int else value

    @property
    def is_active(self) -> bool:
        return self.method != "none"

    def to_dict(self) -> dict:
        return {"method": self.method, **self.params}

    @classmethod
    def from_dict(cls, data) -> "SmoothingSpec":
        if isinstance(data, SmoothingSpec):
            return cls(data.method, dict(data.params))
        if not isinstance(data, dict):
            return cls()
        data = dict(data)
        method = data.pop("method", "none")
        params = data.pop("params", None) or data
        return cls(str(method), dict(params))

    def describe(self) -> str:
        method = _REGISTRY[self.method]
        if not self.is_active:
            return "None"
        parts = ", ".join(
            f"{p.label.lower()} {self.params[p.name]:.{p.decimals}f}" if not p.is_int
            else f"{p.label.lower()} {self.params[p.name]}"
            for p in method.params
        )
        return f"{method.display_name} ({parts})" if parts else method.display_name


def smooth(y, spec: SmoothingSpec | dict | None) -> np.ndarray:
    """Smooth a 1-D array; returns the input unchanged when inactive."""
    y = np.asarray(y, dtype=float)
    if spec is None:
        return y
    if not isinstance(spec, SmoothingSpec):
        spec = SmoothingSpec.from_dict(spec)
    if not spec.is_active or y.size < 2:
        return y
    return np.asarray(_REGISTRY[spec.method].func(y, spec.params), dtype=float)
