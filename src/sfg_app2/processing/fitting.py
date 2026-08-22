from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import lmfit


# ── Lineshape registry ──────────────────────────────────────────────────────
# Extensible by design: a new lineshape is one register_lineshape() call
# away, and the UI builds its parameter controls from ParamSpec metadata
# rather than hardcoded fields.

@dataclass
class ParamSpec:
    name: str            # short key, e.g. "amplitude" — combined with a
                          # peak index to form the lmfit parameter name
    display_name: str
    default: float
    min: float
    max: float
    unit: str = ""


@dataclass
class LineshapeSpec:
    key: str
    display_name: str
    params: list[ParamSpec]
    chi: Callable[..., np.ndarray]   # (omega, **named params) -> complex array


_REGISTRY: dict[str, LineshapeSpec] = {}


def register_lineshape(spec: LineshapeSpec) -> None:
    _REGISTRY[spec.key] = spec


def get_lineshape(key: str) -> LineshapeSpec:
    return _REGISTRY[key]


def available_lineshapes() -> list[LineshapeSpec]:
    return list(_REGISTRY.values())


def _lorentzian_chi(omega, amplitude, center, width):
    # `width` is the full width; gamma = width/2 preserves the existing
    # convention used elsewhere in this codebase.
    gamma = width / 2.0
    return amplitude / (omega - center + 1j * gamma)


register_lineshape(LineshapeSpec(
    key="lorentzian",
    display_name="Lorentzian",
    params=[
        ParamSpec("amplitude", "Amplitude", default=1.0, min=-np.inf, max=np.inf),
        ParamSpec("center", "Center", default=0.0, min=-np.inf, max=np.inf, unit="cm⁻¹"),
        ParamSpec("width", "Width (full)", default=10.0, min=0.0, max=np.inf, unit="cm⁻¹"),
    ],
    chi=_lorentzian_chi,
))


# ── Model spec — Qt-free, JSON-serializable (fit templates + provenance) ────

@dataclass
class FitParam:
    value: float
    vary: bool = True
    min: float = -np.inf
    max: float = np.inf
    expr: str | None = None

    def to_dict(self) -> dict:
        return {"value": self.value, "vary": self.vary,
                "min": self.min, "max": self.max, "expr": self.expr}

    @staticmethod
    def from_dict(d: dict) -> "FitParam":
        return FitParam(
            value=d["value"], vary=d.get("vary", True),
            min=d.get("min", -np.inf), max=d.get("max", np.inf), expr=d.get("expr"),
        )


@dataclass
class PeakInstance:
    lineshape_key: str
    params: dict[str, FitParam]

    def to_dict(self) -> dict:
        return {"lineshape_key": self.lineshape_key,
                "params": {k: v.to_dict() for k, v in self.params.items()}}

    @staticmethod
    def from_dict(d: dict) -> "PeakInstance":
        return PeakInstance(
            lineshape_key=d["lineshape_key"],
            params={k: FitParam.from_dict(v) for k, v in d["params"].items()},
        )


@dataclass
class FitModelSpec:
    nonresonant: dict[str, FitParam]   # "amplitude", "phase"
    peaks: list[PeakInstance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nonresonant": {k: v.to_dict() for k, v in self.nonresonant.items()},
            "peaks": [p.to_dict() for p in self.peaks],
        }

    @staticmethod
    def from_dict(d: dict) -> "FitModelSpec":
        return FitModelSpec(
            nonresonant={k: FitParam.from_dict(v) for k, v in d.get("nonresonant", {}).items()},
            peaks=[PeakInstance.from_dict(p) for p in d.get("peaks", [])],
        )

    @staticmethod
    def empty() -> "FitModelSpec":
        return FitModelSpec(
            nonresonant={
                "amplitude": FitParam(value=0.0),   # min/max default to -inf/inf
                "phase": FitParam(value=0.0, vary=False, min=-np.pi, max=np.pi),
            },
            peaks=[],
        )


def default_peak(lineshape_key: str, center: float,
                  amplitude: float | None = None, width: float | None = None) -> PeakInstance:
    """Seed a new peak for click-to-place: center comes from the click,
    amplitude/width from a caller-supplied data heuristic if given, else
    the lineshape's own defaults."""
    spec = get_lineshape(lineshape_key)
    params = {}
    for p in spec.params:
        if p.name == "center":
            value = center
        elif p.name == "amplitude" and amplitude is not None:
            value = amplitude
        elif p.name == "width" and width is not None:
            value = width
        else:
            value = p.default
        params[p.name] = FitParam(value=value, min=p.min, max=p.max)
    return PeakInstance(lineshape_key=lineshape_key, params=params)


# ── Building the composite model ────────────────────────────────────────────
# The coherent sum must happen *before* squaring for homodyne (|sum|^2 is
# not sum(|.|^2) -- cross terms). lmfit.Model composition (`Model + Model`)
# sums *outputs*, which would lose that interference, so it isn't used here.
# lmfit.Model also validates declared parameter names against the wrapped
# function's actual introspected signature — a plain `**kwargs` function
# (needed since the parameter set is dynamic, one entry per peak) has none,
# so `Model(..., param_names=...)` doesn't work for this case either. Instead
# this builds an `lmfit.Parameters` directly and fits with `lmfit.minimize()`
# against a custom residual closure — the standard lmfit pattern for a
# dynamic/variable-arity model (also how lmfit's own global-fitting cookbook
# examples are built).

def build_homodyne_params(spec: FitModelSpec) -> lmfit.Parameters:
    params = lmfit.Parameters()
    for name, fp in spec.nonresonant.items():
        params.add(f"nr_{name}", value=fp.value, vary=fp.vary, min=fp.min, max=fp.max, expr=fp.expr)
    for i, peak in enumerate(spec.peaks):
        for name, fp in peak.params.items():
            params.add(f"p{i}_{name}", value=fp.value, vary=fp.vary, min=fp.min, max=fp.max, expr=fp.expr)
    return params


def _chi_eff(omega: np.ndarray, params: lmfit.Parameters, spec: FitModelSpec) -> np.ndarray:
    omega = np.asarray(omega, dtype=float)
    p = params.valuesdict()
    # np.full (not a bare scalar multiply) so chi always has omega's shape,
    # even with zero peaks -- otherwise the non-resonant term alone never
    # gets broadcast against omega, and callers that plot/subtract against
    # the full-length data array fail (matplotlib in particular: it does
    # not auto-broadcast a 0-d y against an N-point x).
    nr = p["nr_amplitude"] * np.exp(1j * p["nr_phase"])
    chi = np.full(omega.shape, nr, dtype=complex)
    for i, peak in enumerate(spec.peaks):
        ls = get_lineshape(peak.lineshape_key)
        kwargs = {name: p[f"p{i}_{name}"] for name in peak.params}
        chi = chi + ls.chi(omega, **kwargs)
    return chi


def evaluate_homodyne(omega: np.ndarray, spec: FitModelSpec) -> np.ndarray:
    """Evaluate the model curve at the spec's current values, with no
    fitting — used for the live parameter-table preview."""
    params = build_homodyne_params(spec)
    return np.abs(_chi_eff(omega, params, spec)) ** 2


def evaluate_chi(omega: np.ndarray, spec: FitModelSpec) -> np.ndarray:
    """The complex chi_eff itself (before squaring) -- lets the UI show
    Re(chi)/Im(chi) as a fit-quality diagnostic even in homodyne mode,
    where only |chi|^2 is actually measured/fit against."""
    params = build_homodyne_params(spec)
    return _chi_eff(omega, params, spec)


def evaluate_peak_component(omega: np.ndarray, peak: PeakInstance) -> np.ndarray:
    """|contribution of a single peak alone|^2 (non-resonant term excluded)
    -- used for the toggleable per-peak component curves. Note this is
    only a physically meaningful "component" in isolation; the peaks
    interfere with each other and the non-resonant term in the real
    (coherent) total, so this curve is a visual aid, not a literal
    decomposition of the total."""
    ls = get_lineshape(peak.lineshape_key)
    kwargs = {name: fp.value for name, fp in peak.params.items()}
    return np.abs(ls.chi(omega, **kwargs)) ** 2


# ── Weighting ────────────────────────────────────────────────────────────────
# lmfit convention: residual = weights * (data - model), so weights = 1/sigma.

def compute_weights(mode: str, intensity: np.ndarray,
                     intensity_std: np.ndarray | None = None,
                     count: np.ndarray | None = None) -> np.ndarray | None:
    if mode == "none":
        return None
    if mode == "statistical":
        sigma = np.sqrt(np.clip(np.abs(intensity), 1e-12, None))
        return 1.0 / sigma
    if mode == "measurement_error":
        if intensity_std is None or count is None:
            return None
        sem = intensity_std / np.sqrt(np.clip(count, 1, None))
        positive = sem[sem > 0]
        fallback = float(np.nanmedian(positive)) if positive.size else 1.0
        sem = np.where(sem > 0, sem, fallback)
        return 1.0 / sem
    raise ValueError(f"Unknown weighting mode: {mode!r}")


def _sigma_from_ci95(err: np.ndarray) -> np.ndarray:
    """err is a 95% CI half-width (1.96*SEM, per processing.hd_sfg.steps),
    not a raw SEM -- convert back to SEM before inverting, so the returned
    weight stays on the same 1/sigma footing as compute_weights()'s
    "measurement_error" mode."""
    sem = err / 1.96
    positive = sem[sem > 0]
    fallback = float(np.nanmedian(positive)) if positive.size else 1.0
    return np.where(sem > 0, sem, fallback)


def compute_heterodyne_weights(mode: str, real: np.ndarray, imag: np.ndarray,
                                real_err: np.ndarray | None = None,
                                imag_err: np.ndarray | None = None,
                                ) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Per-channel weights for fit_heterodyne(). Unlike compute_weights(),
    there is no "statistical" mode here -- the shot-noise justification for
    1/sqrt(intensity) doesn't carry over to signed Real/Imaginary values,
    so only "none" and "measurement_error" are supported."""
    if mode == "none":
        return None, None
    if mode == "measurement_error":
        if real_err is None or imag_err is None:
            return None, None
        return 1.0 / _sigma_from_ci95(real_err), 1.0 / _sigma_from_ci95(imag_err)
    raise ValueError(f"Unknown heterodyne weighting mode: {mode!r}")


# ── Fit result ───────────────────────────────────────────────────────────────

@dataclass
class ParamResult:
    value: float
    stderr: float | None
    vary: bool
    min: float
    max: float
    expr: str | None
    at_bound: bool


@dataclass
class FitResult:
    spec: FitModelSpec                    # best-fit values folded back in
    param_results: dict[str, ParamResult]  # keyed like the lmfit params ("nr_amplitude", "p0_center", ...)
    redchi: float
    r_squared: float
    aic: float
    bic: float
    success: bool
    message: str
    lmfit_result: object = None            # raw lmfit.minimizer.MinimizerResult
    lmfit_minimizer: object = None         # the lmfit.Minimizer used, needed by conf_interval()

    @staticmethod
    def from_lmfit(result, orig_spec: FitModelSpec, data: np.ndarray, best_fit: np.ndarray,
                    minimizer=None) -> "FitResult":
        param_results: dict[str, ParamResult] = {}
        for name, par in result.params.items():
            at_bound = (
                (par.min is not None and np.isfinite(par.min) and np.isclose(par.value, par.min, rtol=1e-6, atol=1e-9))
                or (par.max is not None and np.isfinite(par.max) and np.isclose(par.value, par.max, rtol=1e-6, atol=1e-9))
            )
            param_results[name] = ParamResult(
                value=par.value, stderr=par.stderr, vary=par.vary,
                min=par.min, max=par.max, expr=par.expr, at_bound=at_bound,
            )

        best_spec = _spec_from_param_results(orig_spec, param_results)

        # unweighted residual for R^2 -- result.residual is the *weighted*
        # residual when weights are given, which would bias this metric
        raw_residual = data - best_fit
        ss_res = float(np.sum(raw_residual ** 2))
        ss_tot = float(np.sum((data - np.mean(data)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

        return FitResult(
            spec=best_spec, param_results=param_results,
            redchi=result.redchi, r_squared=r_squared,
            aic=result.aic, bic=result.bic,
            success=result.success, message=result.message,
            lmfit_result=result, lmfit_minimizer=minimizer,
        )


def _spec_from_param_results(orig_spec: FitModelSpec, results: dict[str, ParamResult]) -> FitModelSpec:
    nonresonant = {}
    for name in orig_spec.nonresonant:
        r = results[f"nr_{name}"]
        nonresonant[name] = FitParam(value=r.value, vary=r.vary, min=r.min, max=r.max, expr=r.expr)

    peaks = []
    for i, peak in enumerate(orig_spec.peaks):
        params = {}
        for name in peak.params:
            r = results[f"p{i}_{name}"]
            params[name] = FitParam(value=r.value, vary=r.vary, min=r.min, max=r.max, expr=r.expr)
        peaks.append(PeakInstance(lineshape_key=peak.lineshape_key, params=params))

    return FitModelSpec(nonresonant=nonresonant, peaks=peaks)


def fit_homodyne(omega: np.ndarray, intensity: np.ndarray, spec: FitModelSpec,
                  weights: np.ndarray | None = None, method: str = "leastsq") -> FitResult:
    params = build_homodyne_params(spec)

    def _residual(p, omega, data, weights):
        model = np.abs(_chi_eff(omega, p, spec)) ** 2
        resid = data - model
        if weights is not None:
            resid = resid * weights
        return resid

    # kept as an explicit Minimizer (not the lmfit.minimize() convenience
    # function) so the FitResult can retain it -- lmfit.conf_interval()
    # needs the Minimizer instance, not just its result.
    minimizer = lmfit.Minimizer(_residual, params, fcn_args=(omega, intensity, weights))
    result = minimizer.minimize(method=method)
    best_fit = np.abs(_chi_eff(omega, result.params, spec)) ** 2
    return FitResult.from_lmfit(result, spec, data=intensity, best_fit=best_fit, minimizer=minimizer)


def fit_heterodyne(omega: np.ndarray, real: np.ndarray, imag: np.ndarray, spec: FitModelSpec,
                    weights_real: np.ndarray | None = None, weights_imag: np.ndarray | None = None,
                    method: str = "leastsq") -> FitResult:
    """Fit the Real and Imaginary parts of chi_eff simultaneously (one
    joint least-squares problem) against measured heterodyne data,
    reusing the same complex model (_chi_eff) that homodyne mode only
    ever squares. The residual is the concatenation of the (optionally
    weighted) real and imaginary residuals -- lmfit.Minimizer only cares
    about the sum of squares, so concatenation vs. interleaving makes no
    difference to the fit, and concatenation keeps resid[:n]/resid[n:]
    easy to separate when debugging."""
    params = build_homodyne_params(spec)

    def _residual(p, omega, real, imag, weights_real, weights_imag):
        chi = _chi_eff(omega, p, spec)
        resid_real = real - chi.real
        resid_imag = imag - chi.imag
        if weights_real is not None:
            resid_real = resid_real * weights_real
        if weights_imag is not None:
            resid_imag = resid_imag * weights_imag
        return np.concatenate([resid_real, resid_imag])

    minimizer = lmfit.Minimizer(_residual, params, fcn_args=(omega, real, imag, weights_real, weights_imag))
    result = minimizer.minimize(method=method)
    best_chi = _chi_eff(omega, result.params, spec)
    data = np.concatenate([real, imag])
    best_fit = np.concatenate([best_chi.real, best_chi.imag])
    return FitResult.from_lmfit(result, spec, data=data, best_fit=best_fit, minimizer=minimizer)


def fit_model_spec_from_provenance_payload(payload: dict | None) -> FitModelSpec | None:
    """`payload` is processing.provenance.parse_fit_json()'s return value."""
    if not payload or "model" not in payload:
        return None
    return FitModelSpec.from_dict(payload["model"])


def fit_kind_from_provenance_payload(payload: dict | None) -> str | None:
    """"homodyne" | "heterodyne" | None, from the same payload dict --
    see fit_model_spec_from_provenance_payload()."""
    if not payload:
        return None
    return payload.get("kind")


# ── Sequential batch fitting ────────────────────────────────────────────────
# Phase 1 of "batch fitting": each dataset in a series is fit
# independently (no parameter linking across datasets -- that's a
# separate, not-yet-built "global fitting" mode), but seeded from the
# previous dataset's converged values, which works well for a smoothly
# varying concentration/time series. Deliberately Qt-free/UI-free so
# it's unit-testable without a QApplication; the caller (FittingTab)
# supplies a `progress_cb` that owns any UI (progress dialog, cancel
# button) and converts its own selected spectra into BatchDataset.

@dataclass
class BatchDataset:
    label: str
    kind: str                      # "homodyne" | "heterodyne"
    omega: np.ndarray
    intensity: np.ndarray | None = None
    intensity_std: np.ndarray | None = None
    count: np.ndarray | None = None
    real: np.ndarray | None = None
    imag: np.ndarray | None = None
    real_err: np.ndarray | None = None
    imag_err: np.ndarray | None = None


def fit_sequential_batch(datasets: list[BatchDataset], template: FitModelSpec,
                          weighting: str = "none", fit_range: tuple[float, float] | None = None,
                          progress_cb: Callable[[int, int, str], bool] | None = None,
                          ) -> list[FitResult | None]:
    """Fit each dataset independently, in list order, each one seeded
    from the previous dataset's converged parameter values (peak
    topology/bounds/vary-state come from `template` and never change
    across the batch -- only values carry forward). A dataset that
    raises during fitting contributes None and does not advance the
    seed (the next dataset still seeds from the last dataset that
    produced a FitResult, success or not -- see module docs). If
    `progress_cb` returns False, the loop stops immediately without
    fitting the remaining datasets and returns only what was already
    fit (a list shorter than `datasets`, not None-padded).
    """
    kinds = {d.kind for d in datasets}
    if len(kinds) > 1:
        raise ValueError(f"All datasets in a batch must share one kind, got: {sorted(kinds)}")

    results: list[FitResult | None] = []
    current_spec = deepcopy(template)
    for i, ds in enumerate(datasets):
        if progress_cb is not None and not progress_cb(i, len(datasets), ds.label):
            break

        mask = np.ones_like(ds.omega, dtype=bool)
        if fit_range is not None:
            lo, hi = fit_range
            mask = (ds.omega >= lo) & (ds.omega <= hi)
        omega = ds.omega[mask]

        try:
            if ds.kind == "heterodyne":
                real, imag = ds.real[mask], ds.imag[mask]
                real_err = ds.real_err[mask] if ds.real_err is not None else None
                imag_err = ds.imag_err[mask] if ds.imag_err is not None else None
                w_real, w_imag = compute_heterodyne_weights(weighting, real, imag, real_err, imag_err)
                result = fit_heterodyne(omega, real, imag, current_spec,
                                        weights_real=w_real, weights_imag=w_imag)
            else:
                intensity = ds.intensity[mask]
                intensity_std = ds.intensity_std[mask] if ds.intensity_std is not None else None
                count = ds.count[mask] if ds.count is not None else None
                weights = compute_weights(weighting, intensity, intensity_std, count)
                result = fit_homodyne(omega, intensity, current_spec, weights=weights)
        except Exception:
            results.append(None)
            continue

        results.append(result)
        current_spec = deepcopy(result.spec)

    return results
