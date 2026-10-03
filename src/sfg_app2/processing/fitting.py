from __future__ import annotations
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import lmfit

from .kinds import normalize_kind

logger = logging.getLogger(__name__)


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
    # Optional click-to-place seeding. (center, amplitude, width) -> a
    # partial {param_name: value}; anything omitted falls back to the
    # name-matching in default_peak() and then to ParamSpec.default.
    # Only needed by lineshapes whose parameters aren't literally named
    # "center"/"amplitude"/"width" -- e.g. Voigt, which has to split one
    # measured width across two broadening mechanisms.
    seed: Callable[[float, float | None, float | None], dict[str, float]] | None = None
    # Contract: `chi` must be linear in its "amplitude" parameter
    # (chi(amplitude=a) == a * chi(amplitude=1)). seed_amplitudes() relies
    # on it to solve for every spectrum's amplitudes with centers/widths
    # held fixed, without needing a starting guess.


_REGISTRY: dict[str, LineshapeSpec] = {}


class UnknownLineshapeError(KeyError):
    """A fit references a lineshape this build doesn't have registered.

    Subclasses KeyError so existing handlers keep working, but carries a
    readable `message` -- str() on a KeyError re-quotes its argument,
    which reads badly in a dialog.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def register_lineshape(spec: LineshapeSpec) -> None:
    _REGISTRY[spec.key] = spec


def get_lineshape(key: str) -> LineshapeSpec:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownLineshapeError(
            f"Unknown lineshape {key!r}. This fit was probably saved by a "
            f"version of the app with lineshapes this one doesn't have. "
            f"Available here: {', '.join(sorted(_REGISTRY)) or '(none)'}."
        ) from None


def available_lineshapes() -> list[LineshapeSpec]:
    return list(_REGISTRY.values())


# Gaussian FWHM = 2*sqrt(2*ln2)*sigma. Both Gaussian-broadened lineshapes
# below take a *full width* like the Lorentzian does, and convert
# internally, so every width in the UI means the same kind of quantity.
_FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))


def _lorentzian_chi(omega, amplitude, center, width):
    # `width` is the full width; gamma = width/2 preserves the existing
    # convention used elsewhere in this codebase.
    gamma = width / 2.0
    return amplitude / (omega - center + 1j * gamma)


def _voigt_chi(omega, amplitude, center, width, gauss_width):
    """Lorentzian convolved with a Gaussian spread of centers.

    The homogeneous (`width`) and inhomogeneous (`gauss_width`) parts are
    both full widths. The prefactor is fixed by requiring that
    gauss_width -> 0 reproduce _lorentzian_chi exactly (w(z) ~ i/(sqrt(pi)z)
    for large |z| makes the two expressions agree); test_voigt_reduces_to_
    lorentzian pins that down.
    """
    from scipy.special import wofz

    omega = np.asarray(omega, dtype=float)
    gamma = width / 2.0
    sigma = gauss_width / _FWHM_PER_SIGMA
    if sigma <= 0:
        # Also the numerically right branch: z would blow up.
        return amplitude / (omega - center + 1j * gamma)
    denom = sigma * np.sqrt(2.0)
    z = (omega - center + 1j * gamma) / denom
    return amplitude * (-1j * np.sqrt(np.pi) / denom) * wofz(z)


def _gaussian_chi(omega, amplitude, center, width):
    """The Voigt with no homogeneous component.

    Not just a real Gaussian: the real part is the Kramers-Kronig
    partner (a Dawson function), which is what keeps the coherent sum
    with other peaks physically meaningful.
    """
    return _voigt_chi(omega, amplitude, center, 0.0, width)


def _voigt_seed(center, amplitude, width):
    """Split one measured width across both broadening mechanisms.

    f_V ~= 0.5346*f_L + sqrt(0.2166*f_L^2 + f_G^2), so taking
    f_L = f_G = 0.64*f puts the resulting Voigt width back at ~f.
    """
    if width is None:
        return {}
    return {"width": 0.64 * width, "gauss_width": 0.64 * width}


def _amplitude_spec():
    return ParamSpec("amplitude", "Amplitude", default=1.0, min=-np.inf, max=np.inf)


def _center_spec():
    return ParamSpec("center", "Center", default=0.0, min=-np.inf, max=np.inf, unit="cm⁻¹")


register_lineshape(LineshapeSpec(
    key="lorentzian",
    display_name="Lorentzian",
    params=[
        _amplitude_spec(),
        _center_spec(),
        ParamSpec("width", "Width (full)", default=10.0, min=0.0, max=np.inf, unit="cm⁻¹"),
    ],
    chi=_lorentzian_chi,
))


register_lineshape(LineshapeSpec(
    key="gaussian",
    display_name="Gaussian",
    params=[
        _amplitude_spec(),
        _center_spec(),
        ParamSpec("width", "Width (full)", default=10.0, min=0.0, max=np.inf, unit="cm⁻¹"),
    ],
    chi=_gaussian_chi,
))


register_lineshape(LineshapeSpec(
    key="voigt",
    display_name="Voigt",
    params=[
        _amplitude_spec(),
        _center_spec(),
        ParamSpec("width", "Lorentzian width", default=10.0, min=0.0, max=np.inf, unit="cm⁻¹"),
        ParamSpec("gauss_width", "Gaussian width", default=10.0, min=0.0, max=np.inf, unit="cm⁻¹"),
    ],
    chi=_voigt_chi,
    seed=_voigt_seed,
))


# ── Model spec — Qt-free, JSON-serializable (fit templates + provenance) ────

@dataclass
class FitParam:
    value: float
    vary: bool = True
    min: float = -np.inf
    max: float = np.inf
    expr: str | None = None
    # Batch-fit only (see fit_global_batch): when True, this parameter
    # is optimized as one value shared across every spectrum in a batch
    # run, rather than independently per spectrum. Ignored everywhere
    # else (single-spectrum "Run fit", Sequential fit).
    shared: bool = False

    def to_dict(self) -> dict:
        return {"value": self.value, "vary": self.vary,
                "min": self.min, "max": self.max, "expr": self.expr,
                "shared": self.shared}

    @staticmethod
    def from_dict(d: dict) -> "FitParam":
        return FitParam(
            value=d["value"], vary=d.get("vary", True),
            min=d.get("min", -np.inf), max=d.get("max", np.inf), expr=d.get("expr"),
            shared=d.get("shared", False),
        )


AMPLITUDE_SIGN_RULES = ("+", "-", "free")


@dataclass
class PeakInstance:
    lineshape_key: str
    params: dict[str, FitParam]
    # Per-polarization sign rule for this peak's amplitude: polarization
    # label ("ssp", "ppp", ...) -> "+" | "-" | "free". A missing label
    # means free. Only consulted when a dataset carries a polarization
    # (BatchDataset.polarization) -- see apply_sign_constraints().
    amplitude_signs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"lineshape_key": self.lineshape_key,
             "params": {k: v.to_dict() for k, v in self.params.items()}}
        # Omitted when empty so a fit without sign rules serializes
        # exactly as it did before they existed.
        if self.amplitude_signs:
            d["amplitude_signs"] = dict(self.amplitude_signs)
        return d

    @staticmethod
    def from_dict(d: dict) -> "PeakInstance":
        return PeakInstance(
            lineshape_key=d["lineshape_key"],
            params={k: FitParam.from_dict(v) for k, v in d["params"].items()},
            amplitude_signs=dict(d.get("amplitude_signs", {})),
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


# ── Per-polarization amplitude sign rules ───────────────────────────────────
# A sign rule narrows a peak amplitude's bounds for one fit only. Every fit
# path applies it through apply_sign_constraints() just before building
# lmfit parameters, and hands the result back through
# restore_amplitude_bounds(), so the narrowed bounds never leak into the
# model the user keeps editing (a "+" fit followed by a "-" fit would
# otherwise end with min=max=0).

def _ruled_amplitude(peak: PeakInstance, polarization: str) -> tuple[str, FitParam] | None:
    """(rule, amplitude param) when a rule applies to this peak's amplitude
    for `polarization`. Fixed, Shared or expression-bound amplitudes are
    exempt: a sign rule only makes sense for a value this dataset fits on
    its own."""
    rule = peak.amplitude_signs.get(polarization)
    fp = peak.params.get("amplitude")
    if rule not in ("+", "-") or fp is None or not fp.vary or fp.shared or fp.expr:
        return None
    return rule, fp


def _rule_violations(spec: FitModelSpec, polarization: str, mirrored: bool) -> int:
    count = 0
    for peak in spec.peaks:
        ruled = _ruled_amplitude(peak, polarization)
        if ruled is not None:
            value = -ruled[1].value if mirrored else ruled[1].value
            count += (ruled[0] == "+" and value < 0) or (ruled[0] == "-" and value > 0)
    return count


def _can_mirror(spec: FitModelSpec) -> bool:
    """Negating every amplitude (peaks and background) leaves |chi|^2
    unchanged -- but only counts as the same starting model if nothing
    that would have to flip is pinned (fixed, Shared, or an expression)."""
    amplitudes = [p.params["amplitude"] for p in spec.peaks if "amplitude" in p.params]
    amplitudes.append(spec.nonresonant["amplitude"])
    return all(fp.value == 0 or (fp.vary and not fp.shared and not fp.expr and fp.min <= -fp.value <= fp.max)
               for fp in amplitudes)


def apply_sign_constraints(spec: FitModelSpec, polarization: str | None,
                           mirror_ok: bool = False) -> FitModelSpec:
    """`spec` with each peak's amplitude bounds intersected with its rule
    for `polarization` ("+" -> min >= 0, "-" -> max <= 0), and a starting
    value that contradicts the rule flipped to the allowed side. Returns
    `spec` itself when nothing applies.

    `mirror_ok` is for homodyne data, where the whole model negated fits
    exactly as well: when that mirror image breaks fewer rules, start
    from it, rather than flipping single amplitudes into a start whose
    relative signs no longer match the data (a reliable way to end in a
    local minimum)."""
    if polarization is None or not any(_ruled_amplitude(p, polarization) for p in spec.peaks):
        return spec
    out = deepcopy(spec)
    if (mirror_ok and _can_mirror(out)
            and _rule_violations(out, polarization, True) < _rule_violations(out, polarization, False)):
        for peak in out.peaks:
            if "amplitude" in peak.params:
                peak.params["amplitude"].value *= -1
        out.nonresonant["amplitude"].value *= -1
    for peak in out.peaks:
        ruled = _ruled_amplitude(peak, polarization)
        if ruled is None:
            continue
        rule, fp = ruled
        if rule == "+":
            fp.min = max(fp.min, 0.0)
            if fp.value < 0:
                fp.value = -fp.value
        else:
            fp.max = min(fp.max, 0.0)
            if fp.value > 0:
                fp.value = -fp.value
        fp.value = float(np.clip(fp.value, fp.min, fp.max))
    return out


def restore_amplitude_bounds(fitted: FitModelSpec, original: FitModelSpec) -> FitModelSpec:
    """Puts `original`'s amplitude bounds back on `fitted` in place (and
    returns it) -- the inverse of apply_sign_constraints() for a result's
    spec. A FitResult's param_results keep the narrowed bounds, which is
    what makes at_bound flag an amplitude pinned at 0 by its rule."""
    for fitted_peak, orig_peak in zip(fitted.peaks, original.peaks):
        fp, op = fitted_peak.params.get("amplitude"), orig_peak.params.get("amplitude")
        if fp is not None and op is not None:
            fp.min, fp.max = op.min, op.max
    return fitted


def _local_height_and_width(omega: np.ndarray, y: np.ndarray, idx: int,
                             min_width: float) -> tuple[float, float]:
    """Local baseline + half-width-at-half-max walk around omega[idx].
    No fitting, just array inspection -- safe to call synchronously on
    a single click. Works regardless of whether omega is ascending or
    descending, since widths are always measured as abs(omega diffs)."""
    n = len(omega)
    radius0 = max(n // 20, 5)
    lo, hi = max(idx - radius0, 0), min(idx + radius0 + 1, n)
    window = y[lo:hi]
    q = max(len(window) // 4, 1)
    flanks = np.concatenate([window[:q], window[-q:]])
    baseline = float(np.median(flanks))
    height = max(float(y[idx]) - baseline, 0.0)

    half = baseline + height / 2.0
    search_cap = max(n // 4, radius0)
    j = idx
    while j + 1 < n and (j - idx) < search_cap and y[j] > half:
        j += 1
    right = abs(float(omega[j]) - float(omega[idx])) if y[j] <= half else 0.0
    k = idx
    while k - 1 >= 0 and (idx - k) < search_cap and y[k] > half:
        k -= 1
    left = abs(float(omega[idx]) - float(omega[k])) if y[k] <= half else 0.0

    if right > 0 and left > 0:
        hwhm = (right + left) / 2.0
    elif right > 0 or left > 0:
        hwhm = right or left
    else:
        # Flat/noisy neighborhood: no HWHM crossing found within the
        # search cap -- fall back to a few local sample spacings rather
        # than anything view-dependent.
        spacing = np.median(np.abs(np.diff(omega[lo:hi]))) if hi - lo > 1 else min_width
        hwhm = max(2.0 * float(spacing), min_width) / 2.0

    return height, max(2.0 * hwhm, min_width)


def estimate_peak_seed(omega: np.ndarray, response: np.ndarray, idx: int,
                        squared: bool, min_width: float = 1.0) -> tuple[float, float]:
    """(amplitude, width) initial guess for a peak clicked at omega[idx],
    replacing the old "2% of the current view" heuristic with an
    estimate driven by the data itself -- no optimization, runs
    synchronously on a single click.

    `response` should already have the model's *currently fitted* peaks
    and non-resonant background subtracted out by the caller, so an
    existing nearby peak/background isn't double-counted as if it
    belonged to the new one (the coherent sum means |sum|^2 != sum(|.|^2),
    so this matters whenever other peaks/background are present).

    squared=True: response is |chi|^2 (homodyne intensity) -- amplitude
      relates to height via height = (amplitude / (width/2))^2.
    squared=False: response is |chi| (phase-resolved magnitude) -- linear:
      height = amplitude / (width/2).

    Both relations are the Lorentzian ones. For a Gaussian-broadened
    lineshape the profile is area-conserving, so the same amplitude
    gives a lower peak and this under-estimates it -- acceptable for a
    starting guess the optimizer refines, and the reason LineshapeSpec
    has its own `seed` hook for anything that needs better.
    """
    height, width = _local_height_and_width(omega, response, idx, min_width)
    half_width = width / 2.0
    amplitude = np.sqrt(height) * half_width if squared else height * half_width
    return max(float(amplitude), 0.5), width


def default_peak(lineshape_key: str, center: float,
                  amplitude: float | None = None, width: float | None = None) -> PeakInstance:
    """Seed a new peak for click-to-place: center comes from the click,
    amplitude/width from a caller-supplied data heuristic if given, else
    the lineshape's own defaults."""
    spec = get_lineshape(lineshape_key)
    seeded = spec.seed(center, amplitude, width) if spec.seed else {}
    params = {}
    for p in spec.params:
        if p.name in seeded:
            value = seeded[p.name]
        elif p.name == "center":
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


def _chi_eff(omega: np.ndarray, params: lmfit.Parameters, spec: FitModelSpec,
             key_fn: Callable[[str], str] = lambda k: k) -> np.ndarray:
    """`key_fn` maps a *local* parameter key ("nr_amplitude", "p0_center",
    ...) to the actual name to look up in `params` -- defaults to the
    identity, i.e. `params` uses the local keys directly, exactly as
    build_homodyne_params() produces them. fit_global_batch() is the one
    caller that passes something else: there, `params` is one shared
    lmfit.Parameters covering every dataset in a batch, so each dataset's
    local keys are looked up under a per-dataset-prefixed (or, for a
    shared parameter, unprefixed/common) name instead."""
    omega = np.asarray(omega, dtype=float)
    p = params.valuesdict()
    # np.full (not a bare scalar multiply) so chi always has omega's shape,
    # even with zero peaks -- otherwise the non-resonant term alone never
    # gets broadcast against omega, and callers that plot/subtract against
    # the full-length data array fail (matplotlib in particular: it does
    # not auto-broadcast a 0-d y against an N-point x).
    nr = p[key_fn("nr_amplitude")] * np.exp(1j * p[key_fn("nr_phase")])
    chi = np.full(omega.shape, nr, dtype=complex)
    for i, peak in enumerate(spec.peaks):
        ls = get_lineshape(peak.lineshape_key)
        kwargs = {name: p[key_fn(f"p{i}_{name}")] for name in peak.params}
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
    """err is a 95% CI half-width (1.96*SEM, per processing.pr_sfg.steps),
    not a raw SEM -- convert back to SEM before inverting, so the returned
    weight stays on the same 1/sigma footing as compute_weights()'s
    "measurement_error" mode."""
    sem = err / 1.96
    positive = sem[sem > 0]
    fallback = float(np.nanmedian(positive)) if positive.size else 1.0
    return np.where(sem > 0, sem, fallback)


def compute_phase_resolved_weights(mode: str, real: np.ndarray, imag: np.ndarray,
                                real_err: np.ndarray | None = None,
                                imag_err: np.ndarray | None = None,
                                ) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Per-channel weights for fit_phase_resolved(). Unlike compute_weights(),
    there is no "statistical" mode here -- the shot-noise justification for
    1/sqrt(intensity) doesn't carry over to signed Real/Imaginary values,
    so only "none" and "measurement_error" are supported."""
    if mode == "none":
        return None, None
    if mode == "measurement_error":
        if real_err is None or imag_err is None:
            return None, None
        return 1.0 / _sigma_from_ci95(real_err), 1.0 / _sigma_from_ci95(imag_err)
    raise ValueError(f"Unknown phase-resolved weighting mode: {mode!r}")


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


def _is_at_bound(par) -> bool:
    """Whether a fitted lmfit Parameter sits on one of its finite bounds.
    lmfit's bound transform only approaches a bound asymptotically, so
    "on" means closer than a millionth of the larger of the bound's own
    size and the parameter's standard error -- a fixed absolute tolerance
    misses a bound at 0 (a sign rule's), where a pinned amplitude ends up
    around 1e-9 rather than exactly 0."""
    stderr = par.stderr if par.stderr is not None and np.isfinite(par.stderr) else 0.0
    for bound in (par.min, par.max):
        if bound is None or not np.isfinite(bound):
            continue
        tol = max(1e-6 * max(abs(bound), abs(stderr)), 1e-9)
        if abs(par.value - bound) <= tol:
            return True
    return False


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
            param_results[name] = ParamResult(
                value=par.value, stderr=par.stderr, vary=par.vary,
                min=par.min, max=par.max, expr=par.expr, at_bound=_is_at_bound(par),
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
    """Folds fitted values back into a copy of `orig_spec`. Settings that
    lmfit doesn't know about (the Shared flag, per-polarization sign
    rules) are carried over from `orig_spec`, or a single "Run fit"
    would silently clear them."""
    nonresonant = {}
    for name, fp in orig_spec.nonresonant.items():
        r = results[f"nr_{name}"]
        nonresonant[name] = FitParam(value=r.value, vary=r.vary, min=r.min, max=r.max, expr=r.expr,
                                     shared=fp.shared)

    peaks = []
    for i, peak in enumerate(orig_spec.peaks):
        params = {}
        for name, fp in peak.params.items():
            r = results[f"p{i}_{name}"]
            params[name] = FitParam(value=r.value, vary=r.vary, min=r.min, max=r.max, expr=r.expr,
                                    shared=fp.shared)
        peaks.append(PeakInstance(lineshape_key=peak.lineshape_key, params=params,
                                  amplitude_signs=dict(peak.amplitude_signs)))

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


def fit_phase_resolved(omega: np.ndarray, real: np.ndarray, imag: np.ndarray, spec: FitModelSpec,
                    weights_real: np.ndarray | None = None, weights_imag: np.ndarray | None = None,
                    method: str = "leastsq") -> FitResult:
    """Fit the Real and Imaginary parts of chi_eff simultaneously (one
    joint least-squares problem) against measured phase-resolved data,
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
    """`payload` is processing.provenance.parse_fit_json()'s return value.

    Returns None for a fit this build can't represent -- including one
    referencing a lineshape it doesn't have registered, which a file
    written by a newer version can legitimately contain. Every caller
    already treats None as "no fit to restore", so rejecting it here
    degrades gracefully instead of raising out of a table rebuild later.
    """
    if not payload or "model" not in payload:
        return None
    spec = FitModelSpec.from_dict(payload["model"])
    for peak in spec.peaks:
        if peak.lineshape_key not in _REGISTRY:
            logger.warning(
                "Ignoring a saved fit: unknown lineshape %r (have: %s).",
                peak.lineshape_key, ", ".join(sorted(_REGISTRY)),
            )
            return None
    return spec


def fit_kind_from_provenance_payload(payload: dict | None) -> str | None:
    """"homodyne" | "phase_resolved" | None, from the same payload dict --
    see fit_model_spec_from_provenance_payload()."""
    if not payload or not payload.get("kind"):
        return None
    # Fits saved before the rename say "heterodyne".
    return normalize_kind(payload["kind"])


def describe_local_params(spec: FitModelSpec) -> list[tuple[str, str]]:
    """(local_key, human_label) pairs for every parameter in `spec`, in
    the same local-key vocabulary as _local_params()/FitResult.param_results
    ("nr_amplitude", "p0_center", ...) paired with a display label
    ("Non-resonant Amplitude", "Peak 1 Center") -- mirrors
    FittingTab._batch_param_columns()'s labeling, kept here (Qt-free)
    so any caller, including read-only display dialogs, can build a
    parameter table without duplicating that private method."""
    rows = [(f"nr_{name}", f"Non-resonant {name.capitalize()}") for name in spec.nonresonant]
    for i, peak in enumerate(spec.peaks):
        ls = get_lineshape(peak.lineshape_key)
        for p in ls.params:
            rows.append((f"p{i}_{p.name}", f"Peak {i + 1} {p.display_name}"))
    return rows


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
    kind: str                      # "homodyne" | "phase_resolved"
    omega: np.ndarray
    intensity: np.ndarray | None = None
    intensity_std: np.ndarray | None = None
    count: np.ndarray | None = None
    real: np.ndarray | None = None
    imag: np.ndarray | None = None
    real_err: np.ndarray | None = None
    imag_err: np.ndarray | None = None
    # Selects each peak's amplitude sign rule (PeakInstance.amplitude_signs).
    polarization: str | None = None


def _check_one_kind(datasets: list[BatchDataset]) -> None:
    kinds = {d.kind for d in datasets}
    if len(kinds) > 1:
        raise ValueError(f"All datasets in a batch must share one kind, got: {sorted(kinds)}")


def fit_one_dataset(dataset: BatchDataset, spec: FitModelSpec,
                     weighting: str = "none", fit_range: tuple[float, float] | None = None,
                     ) -> FitResult | None:
    """Fit a single dataset against `spec` -- the one per-dataset fit
    primitive every batch/sequential/interactive caller shares. Returns
    None (rather than raising) if fitting fails for any reason (e.g. an
    empty fit window, an invalid model), so a caller looping over many
    datasets can treat a bad one as "no result" and keep going. The
    dataset's polarization sign rules are applied for this fit only."""
    mask = np.ones_like(dataset.omega, dtype=bool)
    if fit_range is not None:
        lo, hi = fit_range
        mask = (dataset.omega >= lo) & (dataset.omega <= hi)
    omega = dataset.omega[mask]
    constrained = apply_sign_constraints(spec, dataset.polarization, mirror_ok=dataset.kind == "homodyne")

    try:
        if dataset.kind == "phase_resolved":
            real, imag = dataset.real[mask], dataset.imag[mask]
            real_err = dataset.real_err[mask] if dataset.real_err is not None else None
            imag_err = dataset.imag_err[mask] if dataset.imag_err is not None else None
            w_real, w_imag = compute_phase_resolved_weights(weighting, real, imag, real_err, imag_err)
            result = fit_phase_resolved(omega, real, imag, constrained, weights_real=w_real, weights_imag=w_imag)
        else:
            intensity = dataset.intensity[mask]
            intensity_std = dataset.intensity_std[mask] if dataset.intensity_std is not None else None
            count = dataset.count[mask] if dataset.count is not None else None
            weights = compute_weights(weighting, intensity, intensity_std, count)
            result = fit_homodyne(omega, intensity, constrained, weights=weights)
    except Exception:
        return None
    restore_amplitude_bounds(result.spec, spec)
    return result


def advance_seed(current_spec: FitModelSpec, result: FitResult | None) -> FitModelSpec:
    """The sequential-fit reseed rule, single-sourced since both
    fit_sequential_batch's own loop and an interactive stepped runner
    (e.g. FittingTab's checkpoint-pausing sequential mode) need it:
    carry forward a dataset's converged values (success or not -- a
    non-converged result's values aren't necessarily garbage) unless
    fitting raised outright (result is None), in which case keep
    whatever seed was already in flight."""
    return deepcopy(result.spec) if result is not None else current_spec


def fit_sequential_batch(datasets: list[BatchDataset], template: FitModelSpec,
                          weighting: str = "none", fit_range: tuple[float, float] | None = None,
                          progress_cb: Callable[[int, int, str], bool] | None = None,
                          ) -> list[FitResult | None]:
    """Fit each dataset in list order, each one seeded from the
    previous dataset's converged parameter values via advance_seed()
    (peak topology/bounds/vary-state come from `template` and never
    change across the run -- only values carry forward). If
    `progress_cb` returns False, the loop stops immediately without
    fitting the remaining datasets and returns only what was already
    fit (a list shorter than `datasets`, not None-padded).
    """
    _check_one_kind(datasets)

    results: list[FitResult | None] = []
    current_spec = deepcopy(template)
    for i, ds in enumerate(datasets):
        if progress_cb is not None and not progress_cb(i, len(datasets), ds.label):
            break
        result = fit_one_dataset(ds, current_spec, weighting, fit_range)
        results.append(result)
        current_spec = advance_seed(current_spec, result)

    return results


def fit_independent_batch(datasets: list[BatchDataset], template: FitModelSpec,
                           weighting: str = "none", fit_range: tuple[float, float] | None = None,
                           progress_cb: Callable[[int, int, str], bool] | None = None,
                           ) -> list[FitResult | None]:
    """Fit each dataset independently against the same starting
    `template` -- no seeding, order doesn't affect the result of any
    individual dataset. Same cancellation contract as
    fit_sequential_batch(): progress_cb returning False stops the loop
    immediately and returns a short, non-padded list."""
    _check_one_kind(datasets)

    results: list[FitResult | None] = []
    for i, ds in enumerate(datasets):
        if progress_cb is not None and not progress_cb(i, len(datasets), ds.label):
            break
        results.append(fit_one_dataset(ds, template, weighting, fit_range))

    return results


# ── Global (shared-parameter) batch fitting ─────────────────────────────────
# Phase 2 of "batch fitting" (see the comment above fit_independent_batch):
# one or more parameters marked FitParam.shared=True are optimized as a
# single value common to every dataset in the batch, in one simultaneous
# least-squares problem, rather than independently per dataset. Everything
# else about the model (peak topology, bounds, non-shared values) stays
# per-dataset, same as fit_independent_batch. This is lmfit's own
# documented pattern for global fitting across multiple datasets: one
# shared lmfit.Parameters object, a residual that concatenates every
# dataset's own residual, fed to a single Minimizer -- the same
# concatenation trick fit_phase_resolved() already uses across the
# real/imaginary channels of one spectrum, just extended across datasets.

def _local_params(template: FitModelSpec) -> list[tuple[str, FitParam]]:
    """(local_key, FitParam) pairs in the same key convention
    build_homodyne_params()/_chi_eff() use ("nr_amplitude", "p0_center",
    ...) -- the vocabulary every dataset's parameters are named from,
    before per-dataset prefixing."""
    items = [(f"nr_{name}", fp) for name, fp in template.nonresonant.items()]
    for i, peak in enumerate(template.peaks):
        items += [(f"p{i}_{name}", fp) for name, fp in peak.params.items()]
    return items


def _dataset_param_name(dataset_index: int, local_key: str, shared: bool) -> str:
    """Maps a local per-spectrum key to its name in a global batch's one
    shared lmfit.Parameters: a shared parameter is added once, under its
    bare local key, so every dataset's residual reads the exact same
    lmfit Parameter object; a non-shared parameter gets a per-dataset
    prefix so each dataset keeps its own independent value."""
    return local_key if shared else f"d{dataset_index}_{local_key}"


def build_global_params(datasets: list[BatchDataset], template: FitModelSpec,
                        seeds: list[FitModelSpec] | None = None) -> lmfit.Parameters:
    """One lmfit.Parameters covering every dataset: each FitParam.shared
    parameter in `template` is added once (common to all datasets); every
    other parameter is added once per dataset (independent, same as
    today's per-dataset fits), with that dataset's polarization sign
    rules applied to its amplitude bounds. `seeds[i]`, when given,
    supplies dataset i's starting values for its non-shared parameters
    (see seed_amplitudes()); bounds, vary and topology always come from
    `template`."""
    params = lmfit.Parameters()
    local = _local_params(template)
    for local_key, fp in local:
        if fp.shared:
            params.add(local_key, value=fp.value, vary=fp.vary, min=fp.min, max=fp.max, expr=fp.expr)
    for i, ds in enumerate(datasets):
        constrained = apply_sign_constraints(template, ds.polarization, mirror_ok=ds.kind == "homodyne")
        seed_values = dict(_local_params(seeds[i])) if seeds is not None else {}
        for local_key, fp in _local_params(constrained):
            if fp.shared:
                continue
            value = seed_values[local_key].value if local_key in seed_values else fp.value
            value = float(np.clip(value, fp.min, fp.max))
            params.add(_dataset_param_name(i, local_key, False),
                        value=value, vary=fp.vary, min=fp.min, max=fp.max, expr=fp.expr)
    return params


@dataclass
class GlobalFitResult:
    redchi: float          # over the whole combined residual -- not meaningful per-dataset
    aic: float
    bic: float
    success: bool
    message: str
    shared_keys: list[str]         # local keys (e.g. "nr_amplitude") that were fit jointly
    per_dataset: list["FitResult"]  # one FitResult-shaped view per dataset, same order as `datasets`
    lmfit_result: object = None
    lmfit_minimizer: object = None
    # True when each dataset started from its own seed_amplitudes() solution
    # (fit_polarization_set) rather than from the template's values.
    seeded: bool = False


def _unpack_global_result(lmfit_result, template: FitModelSpec, datasets: list[BatchDataset],
                           prepared: list[tuple], kind: str, shared_map: dict[str, bool],
                           ) -> list[FitResult]:
    """Splits one combined MinimizerResult back into one FitResult per
    dataset: demaps that dataset's global param names back to local keys
    (folding the shared value in identically for every dataset), then
    reuses _spec_from_param_results() exactly as the single-dataset path
    does. redchi here is a per-dataset diagnostic, *not* the same
    quantity as GlobalFitResult.redchi: that dataset's own
    sum-of-squared-residuals over (n_points - n_locally_free_params),
    counting shared parameters as contributing 0 free params for this
    dataset alone (their value is fixed by the joint fit, not free to
    move independently here) -- there is no single well-defined "reduced
    chi-square" split evenly across datasets in a joint fit."""
    local = _local_params(template)
    per_dataset = []
    for i, _ds in enumerate(datasets):
        local_results: dict[str, ParamResult] = {}
        for local_key, _fp in local:
            actual_key = _dataset_param_name(i, local_key, shared_map[local_key])
            par = lmfit_result.params[actual_key]
            local_results[local_key] = ParamResult(
                value=par.value, stderr=par.stderr, vary=par.vary,
                min=par.min, max=par.max, expr=par.expr, at_bound=_is_at_bound(par),
            )
        best_spec = restore_amplitude_bounds(_spec_from_param_results(template, local_results), template)

        if kind == "phase_resolved":
            omega, real, imag, _w_real, _w_imag = prepared[i]
            best_chi = evaluate_chi(omega, best_spec)
            raw_residual = np.concatenate([real - best_chi.real, imag - best_chi.imag])
            data = np.concatenate([real, imag])
        else:
            omega, intensity, _weights = prepared[i]
            best_fit = evaluate_homodyne(omega, best_spec)
            raw_residual = intensity - best_fit
            data = intensity

        ss_res = float(np.sum(raw_residual ** 2))
        ss_tot = float(np.sum((data - np.mean(data)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

        n_free_local = sum(
            1 for local_key, _fp in local
            if not shared_map[local_key] and local_results[local_key].vary
        )
        dof = max(len(data) - n_free_local, 1)
        redchi = ss_res / dof

        per_dataset.append(FitResult(
            spec=best_spec, param_results=local_results,
            redchi=redchi, r_squared=r_squared,
            aic=float("nan"), bic=float("nan"),   # only well-defined for the whole joint fit
            success=lmfit_result.success, message=lmfit_result.message,
            lmfit_result=None, lmfit_minimizer=None,
        ))
    return per_dataset


def fit_global_batch(datasets: list[BatchDataset], template: FitModelSpec,
                      weighting: str = "none", fit_range: tuple[float, float] | None = None,
                      method: str = "leastsq", iter_cb=None,
                      seeds: list[FitModelSpec] | None = None) -> GlobalFitResult:
    """Jointly fits every dataset in `datasets` against one shared
    lmfit.Parameters: any FitParam marked shared=True in `template` is
    optimized as a single value common to every dataset; everything else
    stays independent per dataset (same freedom as fit_independent_batch).
    `iter_cb(params, iteration, resid)` is lmfit's own per-iteration hook,
    if the caller wants incremental progress/cancellation on what is
    otherwise one atomic, non-incremental Minimizer.minimize() call.
    `seeds` gives each dataset its own starting values -- see
    build_global_params()."""
    _check_one_kind(datasets)
    kind = datasets[0].kind
    local = _local_params(template)
    shared_map = {local_key: fp.shared for local_key, fp in local}

    prepared: list[tuple] = []
    for ds in datasets:
        mask = np.ones_like(ds.omega, dtype=bool)
        if fit_range is not None:
            lo, hi = fit_range
            mask = (ds.omega >= lo) & (ds.omega <= hi)
        omega = ds.omega[mask]
        if kind == "phase_resolved":
            real, imag = ds.real[mask], ds.imag[mask]
            real_err = ds.real_err[mask] if ds.real_err is not None else None
            imag_err = ds.imag_err[mask] if ds.imag_err is not None else None
            w_real, w_imag = compute_phase_resolved_weights(weighting, real, imag, real_err, imag_err)
            prepared.append((omega, real, imag, w_real, w_imag))
        else:
            intensity = ds.intensity[mask]
            intensity_std = ds.intensity_std[mask] if ds.intensity_std is not None else None
            count = ds.count[mask] if ds.count is not None else None
            weights = compute_weights(weighting, intensity, intensity_std, count)
            prepared.append((omega, intensity, weights))

    params = build_global_params(datasets, template, seeds=seeds)

    def _key_fn_for(dataset_index: int):
        return lambda local_key: _dataset_param_name(dataset_index, local_key, shared_map[local_key])

    def _residual(p):
        parts = []
        for i, pack in enumerate(prepared):
            key_fn = _key_fn_for(i)
            if kind == "phase_resolved":
                omega, real, imag, w_real, w_imag = pack
                chi = _chi_eff(omega, p, template, key_fn=key_fn)
                r_real = real - chi.real
                r_imag = imag - chi.imag
                if w_real is not None:
                    r_real = r_real * w_real
                if w_imag is not None:
                    r_imag = r_imag * w_imag
                parts.append(r_real)
                parts.append(r_imag)
            else:
                omega, intensity, weights = pack
                model = np.abs(_chi_eff(omega, p, template, key_fn=key_fn)) ** 2
                r = intensity - model
                if weights is not None:
                    r = r * weights
                parts.append(r)
        return np.concatenate(parts)

    minimizer = lmfit.Minimizer(_residual, params, iter_cb=iter_cb)
    result = minimizer.minimize(method=method)

    per_dataset = _unpack_global_result(result, template, datasets, prepared, kind, shared_map)
    shared_keys = [local_key for local_key, fp in local if fp.shared]

    return GlobalFitResult(
        redchi=result.redchi, aic=result.aic, bic=result.bic,
        success=result.success, message=result.message,
        shared_keys=shared_keys, per_dataset=per_dataset,
        lmfit_result=result, lmfit_minimizer=minimizer,
    )


# ── Polarization sets: shared peak shapes, per-spectrum amplitudes ──────────
# The same sample measured in several polarization combinations shares its
# resonances (centers/widths) but not its amplitudes, which can differ by
# orders of magnitude or in sign. Starting a global fit from one template's
# amplitudes for every spectrum tends to land in a bad local minimum, so
# fit_polarization_set() first solves each spectrum's own amplitudes with
# everything else held at the template (seed_amplitudes), then runs the
# joint fit from those per-spectrum starting points.
#
# With centers/widths fixed, chi is linear in the amplitudes (see the
# LineshapeSpec contract). Phase-resolved data constrains chi itself, so the
# amplitudes are one bounded linear least-squares solve -- no starting
# guess, no local minima. Homodyne data only constrains |chi|^2, which is
# quadratic in them; the local minima there are essentially the choice of
# each amplitude's sign, so those are enumerated explicitly.

def _free_amplitude(fp: FitParam) -> bool:
    """Whether a dataset solves for this value on its own in stage 2."""
    return fp.vary and not fp.shared and not fp.expr and fp.min < fp.max


def _peak_unit_chi(omega: np.ndarray, peak: PeakInstance) -> np.ndarray:
    """The peak's chi at amplitude 1 and its current shape parameters."""
    ls = get_lineshape(peak.lineshape_key)
    kwargs = {name: fp.value for name, fp in peak.params.items()}
    kwargs["amplitude"] = 1.0
    return ls.chi(omega, **kwargs)


def _copy_amplitude_values(dst: FitModelSpec, src: FitModelSpec) -> FitModelSpec:
    """Peak amplitudes and non-resonant amplitude/phase values from `src`
    onto `dst` (in place); every other setting stays `dst`'s."""
    for d_peak, s_peak in zip(dst.peaks, src.peaks):
        if "amplitude" in d_peak.params and "amplitude" in s_peak.params:
            d_peak.params["amplitude"].value = s_peak.params["amplitude"].value
    for name in ("amplitude", "phase"):
        if name in dst.nonresonant and name in src.nonresonant:
            dst.nonresonant[name].value = src.nonresonant[name].value
    return dst


def _seed_phase_resolved(dataset: BatchDataset, spec: FitModelSpec, weighting: str,
                      fit_range: tuple[float, float] | None) -> FitModelSpec:
    from scipy.optimize import lsq_linear

    omega = dataset.omega
    mask = np.ones_like(omega, dtype=bool)
    if fit_range is not None:
        mask = (omega >= fit_range[0]) & (omega <= fit_range[1])
    omega = omega[mask]
    real, imag = dataset.real[mask], dataset.imag[mask]
    real_err = dataset.real_err[mask] if dataset.real_err is not None else None
    imag_err = dataset.imag_err[mask] if dataset.imag_err is not None else None
    w_real, w_imag = compute_phase_resolved_weights(weighting, real, imag, real_err, imag_err)
    w_real = np.ones_like(real) if w_real is None else w_real
    w_imag = np.ones_like(imag) if w_imag is None else w_imag

    out = deepcopy(spec)
    columns, lower, upper, targets = [], [], [], []
    offset = np.zeros(omega.shape, dtype=complex)
    for i, peak in enumerate(out.peaks):
        fp = peak.params.get("amplitude")
        if fp is None:
            ls = get_lineshape(peak.lineshape_key)
            offset += ls.chi(omega, **{name: p.value for name, p in peak.params.items()})
            continue
        unit = _peak_unit_chi(omega, peak)
        if _free_amplitude(fp):
            columns.append(unit)
            lower.append(fp.min)
            upper.append(fp.max)
            targets.append(("peak", i))
        else:
            offset += fp.value * unit

    ones = np.ones(omega.shape, dtype=complex)
    amp, phase = out.nonresonant["amplitude"], out.nonresonant["phase"]
    if _free_amplitude(amp) and _free_amplitude(phase):
        # A*e^{i*phi} = c + i*s: two unbounded real unknowns.
        columns += [ones, 1j * ones]
        lower += [-np.inf, -np.inf]
        upper += [np.inf, np.inf]
        targets += [("nr_c",), ("nr_s",)]
    elif _free_amplitude(amp):
        columns.append(np.exp(1j * phase.value) * ones)
        lower.append(amp.min)
        upper.append(amp.max)
        targets.append(("nr_amplitude",))
    else:
        offset += amp.value * np.exp(1j * phase.value) * ones

    if not columns:
        return out

    a = np.vstack([np.column_stack([c.real for c in columns]) * w_real[:, None],
                   np.column_stack([c.imag for c in columns]) * w_imag[:, None]])
    b = np.concatenate([(real - offset.real) * w_real, (imag - offset.imag) * w_imag])
    lower, upper = np.array(lower, dtype=float), np.array(upper, dtype=float)
    if np.all(np.isinf(lower)) and np.all(np.isinf(upper)):
        x = np.linalg.lstsq(a, b, rcond=None)[0]
    else:
        x = lsq_linear(a, b, bounds=(lower, upper), method="bvls").x

    values = dict(zip(targets, x))
    for target, value in values.items():
        if target[0] == "peak":
            out.peaks[target[1]].params["amplitude"].value = float(value)
        elif target[0] == "nr_amplitude":
            amp.value = float(value)
    if ("nr_c",) in values:
        c, s = values[("nr_c",)], values[("nr_s",)]
        amp.value = float(np.hypot(c, s))
        phase.value = float(np.clip(np.arctan2(s, c), phase.min, phase.max))
    return out


def _seed_homodyne(dataset: BatchDataset, spec: FitModelSpec, weighting: str,
                    fit_range: tuple[float, float] | None, max_starts: int) -> FitModelSpec:
    import itertools

    omega = dataset.omega
    mask = np.ones_like(omega, dtype=bool)
    if fit_range is not None:
        mask = (omega >= fit_range[0]) & (omega <= fit_range[1])
    omega, intensity = omega[mask], dataset.intensity[mask]
    if omega.size == 0:
        return deepcopy(spec)
    peak_intensity = float(np.max(np.abs(intensity))) or 1.0

    # Amplitude-only problem: every shape parameter is held where it is.
    frozen = deepcopy(spec)
    for peak in frozen.peaks:
        for name, fp in peak.params.items():
            if name != "amplitude" or not _free_amplitude(fp):
                fp.vary = False
    for fp in frozen.nonresonant.values():
        if not _free_amplitude(fp):
            fp.vary = False

    # |amplitude| guesses from the data itself: each peak's local height
    # over baseline, scaled by its own unit lineshape at its maximum, so
    # the guess is right regardless of lineshape or width.
    magnitudes: dict[int, float] = {}
    toggles: list[object] = []   # peak indices / "nr" whose sign is enumerated
    signs: dict[object, float] = {}
    for i, peak in enumerate(frozen.peaks):
        fp = peak.params.get("amplitude")
        if fp is None or not fp.vary:
            continue
        unit = np.abs(_peak_unit_chi(omega, peak))
        idx = int(np.argmax(unit))
        height, _width = _local_height_and_width(omega, intensity, idx, min_width=1.0)
        height = max(height, 1e-3 * peak_intensity)
        magnitudes[i] = np.sqrt(height) / max(float(unit[idx]), 1e-12)
        if fp.min < 0 < fp.max:
            toggles.append(i)
        else:
            signs[i] = 1.0 if fp.min >= 0 else -1.0

    nr_amp, nr_phase = frozen.nonresonant["amplitude"], frozen.nonresonant["phase"]
    if nr_amp.vary:
        nr_amp.value = np.sqrt(max(float(np.percentile(intensity, 10)), 1e-6 * peak_intensity))
        # A free phase already covers the sign.
        if nr_amp.min < 0 < nr_amp.max and not nr_phase.vary:
            toggles.append("nr")

    # Flipping every amplitude at once leaves |chi|^2 unchanged, so with no
    # sign rule to break that symmetry one sign can be fixed for free.
    if toggles and not signs:
        toggles = toggles[1:]

    n = len(toggles)
    if 2 ** n <= max_starts:
        patterns = list(itertools.product((1.0, -1.0), repeat=n))
    else:
        rng = np.random.default_rng(0)
        patterns = [tuple([1.0] * n)] + [tuple(row) for row in rng.choice((1.0, -1.0), size=(max_starts - 1, n))]

    best, best_score = None, np.inf
    for pattern in patterns:
        start = deepcopy(frozen)
        chosen = dict(signs)
        chosen.update(zip(toggles, pattern))
        for i, magnitude in magnitudes.items():
            fp = start.peaks[i].params["amplitude"]
            fp.value = float(np.clip(chosen.get(i, 1.0) * magnitude, fp.min, fp.max))
        if "nr" in chosen:
            start.nonresonant["amplitude"].value *= chosen["nr"]
        result = fit_one_dataset(dataset, start, weighting, fit_range)
        if result is None or not np.isfinite(result.redchi):
            continue
        if result.redchi < best_score:
            best, best_score = result, result.redchi

    out = deepcopy(spec)
    return _copy_amplitude_values(out, best.spec) if best is not None else out


def seed_amplitudes(dataset: BatchDataset, template: FitModelSpec, weighting: str = "none",
                     fit_range: tuple[float, float] | None = None, max_starts: int = 64,
                     ) -> FitModelSpec:
    """`template` with this dataset's own best peak amplitudes and
    non-resonant amplitude/phase, solved with every other parameter held
    at the template's value (centers/widths are what a polarization set
    shares). The dataset's polarization sign rules are respected. Only
    values change: bounds, vary flags and Shared marks are `template`'s,
    so the result can go straight into fit_global_batch(seeds=...)."""
    constrained = apply_sign_constraints(template, dataset.polarization)
    if dataset.kind == "phase_resolved":
        solved = _seed_phase_resolved(dataset, constrained, weighting, fit_range)
    else:
        solved = _seed_homodyne(dataset, constrained, weighting, fit_range, max_starts)
    return _copy_amplitude_values(deepcopy(template), solved)


def fit_polarization_set(datasets: list[BatchDataset], template: FitModelSpec,
                          weighting: str = "none", fit_range: tuple[float, float] | None = None,
                          progress_cb: Callable[[int, int, str], bool] | None = None,
                          iter_cb=None, max_starts: int = 64) -> GlobalFitResult | None:
    """seed_amplitudes() on every dataset, then the joint fit from two
    starting points -- each dataset's own seed, and the template itself --
    keeping whichever ends with the lower combined redchi. Seeds solved
    against a poor shape guess can occasionally steer the joint fit
    somewhere worse than the plain start would have, and the joint fit
    costs little next to the time a user spends rescuing a bad one, so
    trying both makes this never worse than fit_global_batch() alone.
    `result.seeded` says which start won.

    `progress_cb` covers the seeding stage (same contract as
    fit_independent_batch: returning False cancels, and this then returns
    None); `iter_cb` covers both joint fits."""
    _check_one_kind(datasets)
    seeds = []
    for i, ds in enumerate(datasets):
        if progress_cb is not None and not progress_cb(i, len(datasets), ds.label):
            return None
        seeds.append(seed_amplitudes(ds, template, weighting, fit_range, max_starts=max_starts))
    from_seeds = fit_global_batch(datasets, template, weighting=weighting, fit_range=fit_range,
                                  iter_cb=iter_cb, seeds=seeds)
    from_seeds.seeded = True
    from_template = fit_global_batch(datasets, template, weighting=weighting, fit_range=fit_range,
                                     iter_cb=iter_cb)
    template_wins = np.isfinite(from_template.redchi) and (
        not np.isfinite(from_seeds.redchi) or from_template.redchi < from_seeds.redchi)
    return from_template if template_wins else from_seeds
