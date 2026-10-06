"""The fit job: which spectra, fit how. Qt-free.

The Fitting tab reads as one sentence of numbered chips
(① spectra → ② model → ③ strategy → ④ fit range/weighting → Fit), and
every chip's one-line summary, readiness and the Fit button's wording
come from here, so they are unit-testable without a GUI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sfg_app2.processing.fitting import FitModelSpec, get_lineshape

SINGLE = "single"
INDEPENDENT = "independent"
SEQUENTIAL = "sequential"
GLOBAL = "global"
MULTI_MODES = (INDEPENDENT, SEQUENTIAL, GLOBAL)

MODE_LABELS = {
    INDEPENDENT: "Independent",
    SEQUENTIAL: "Sequential",
    GLOBAL: "Global",
}
MODE_DESCRIPTIONS = {
    INDEPENDENT: "Each spectrum is fit on its own, all from the same starting model.",
    SEQUENTIAL: "Spectra are fit in list order; each fit starts from the previous one's result "
                "(for a temperature, concentration or time series).",
    GLOBAL: "All spectra are fit together: parameters marked Shared take one common value, "
            "the rest are fit per spectrum (e.g. polarizations of one sample).",
}

# When a sequential run pauses for review.
PAUSE_NEVER = "never"
PAUSE_EACH = "each"
PAUSE_MARKED = "marked"
PAUSE_LABELS = {
    PAUSE_NEVER: "Never",
    PAUSE_EACH: "After every spectrum",
    PAUSE_MARKED: "At marked spectra",
}


@dataclass(eq=False)
class JobSpectrum:
    """One spectrum in the job. `entry` is a Spectra Library entry or a
    file-loaded stand-in (same .label/.spectrum/.kind); `pause` marks a
    sequential review point."""
    entry: object
    pause: bool = False

    @property
    def label(self) -> str:
        return self.entry.label

    @property
    def kind(self) -> str:
        return self.entry.kind


@dataclass
class FitJob:
    spectra: list[JobSpectrum] = field(default_factory=list)
    reference: int = 0                 # index into spectra: the one shown/edited
    mode: str = INDEPENDENT            # used only with 2+ spectra
    pause: str = PAUSE_NEVER           # sequential only
    seed_amplitudes: bool = True       # global only

    # ── spectra ──────────────────────────────────────────────────────────

    def entries(self) -> list:
        return [s.entry for s in self.spectra]

    def contains(self, entry) -> bool:
        return any(s.entry is entry for s in self.spectra)

    def add(self, entry) -> bool:
        """False (and nothing added) if `entry` is already in the job."""
        if self.contains(entry):
            return False
        self.spectra.append(JobSpectrum(entry))
        return True

    def remove(self, indices) -> None:
        ref_entry = self.reference_entry()
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.spectra):
                del self.spectra[i]
        self.reference = next(
            (i for i, s in enumerate(self.spectra) if s.entry is ref_entry), 0
        )

    def move(self, src: int, dst: int) -> None:
        ref_entry = self.reference_entry()
        item = self.spectra.pop(src)
        self.spectra.insert(dst, item)
        self.reference = next(
            (i for i, s in enumerate(self.spectra) if s.entry is ref_entry), 0
        )

    def reference_entry(self):
        if not self.spectra:
            return None
        return self.spectra[min(self.reference, len(self.spectra) - 1)].entry

    def kinds(self) -> set[str]:
        return {s.kind for s in self.spectra}

    # ── mode ─────────────────────────────────────────────────────────────

    def effective_mode(self) -> str:
        """SINGLE with fewer than two spectra, else the chosen mode."""
        return SINGLE if len(self.spectra) < 2 else self.mode

    def pause_flags(self) -> list[bool]:
        """Per spectrum: pause for review after it fits (sequential)."""
        if self.pause == PAUSE_EACH:
            return [True] * len(self.spectra)
        if self.pause == PAUSE_MARKED:
            return [s.pause for s in self.spectra]
        return [False] * len(self.spectra)

    def problems(self) -> list[str]:
        """Why the job can't run as configured, if anything."""
        out = []
        if not self.spectra:
            out.append("Add a spectrum to fit.")
        if len(self.kinds()) > 1:
            out.append("The job mixes conventional and phase-resolved spectra; "
                       "fit them in separate jobs.")
        return out

    # ── chip summaries / Fit button ─────────────────────────────────────

    def spectra_summary(self) -> str:
        n = len(self.spectra)
        if n == 0:
            return "Choose spectra"
        if n == 1:
            return self.spectra[0].label
        return f"{n} spectra"

    def strategy_summary(self, spec: FitModelSpec) -> str:
        mode = self.effective_mode()
        if mode == SINGLE:
            return "Single spectrum"
        if mode == GLOBAL:
            shared = shared_param_summary(spec)
            return f"Global · {shared} shared" if shared else "Global · nothing shared yet"
        if mode == SEQUENTIAL:
            pause = {PAUSE_NEVER: "", PAUSE_EACH: " · review each",
                     PAUSE_MARKED: " · review marked"}[self.pause]
            return f"Sequential{pause}"
        return "Independent"

    def run_label(self) -> str:
        n = len(self.spectra)
        mode = self.effective_mode()
        if mode == SINGLE:
            return "Fit spectrum"
        return {
            INDEPENDENT: f"Fit {n} independently",
            SEQUENTIAL: f"Fit {n} in sequence",
            GLOBAL: f"Fit {n} globally",
        }[mode]


def model_summary(spec: FitModelSpec) -> str:
    n = len(spec.peaks)
    if n == 0:
        return "Add peaks"
    shapes = sorted({get_lineshape(p.lineshape_key).display_name for p in spec.peaks})
    text = f"{n} peak{'s' if n != 1 else ''}"
    if spec.nonresonant["amplitude"].vary or spec.nonresonant["amplitude"].value != 0.0:
        text += " + NR"
    if len(shapes) == 1:
        text += f" · {shapes[0]}"
    return text


def fit_settings_summary(fit_range: tuple[float, float] | None, weighting_label: str) -> str:
    if fit_range is None:
        return f"Full range · {weighting_label}"
    lo, hi = fit_range
    return f"{lo:.0f}–{hi:.0f} · {weighting_label}"


# Groups for the Strategy chip's "Share:" toggles, and for the summary.
SHARE_GROUPS = (
    ("center", "Peak centers"),
    ("width", "Peak widths"),
    ("nr_amplitude", "NR amplitude"),
    ("nr_phase", "NR phase"),
)


def _group_params(spec: FitModelSpec, group: str) -> list:
    if group == "nr_amplitude":
        return [spec.nonresonant["amplitude"]]
    if group == "nr_phase":
        return [spec.nonresonant["phase"]]
    if group == "width":
        # every width-like shape parameter (width, gauss_width, ...)
        return [fp for p in spec.peaks for name, fp in p.params.items()
                if name not in ("center", "amplitude")]
    return [p.params[group] for p in spec.peaks if group in p.params]


def share_state(spec: FitModelSpec, group: str) -> bool | None:
    """True if every parameter in `group` is Shared, False if none, None
    for a mix (or an empty group)."""
    params = _group_params(spec, group)
    if not params:
        return False
    shared = [fp.shared for fp in params]
    if all(shared):
        return True
    if not any(shared):
        return False
    return None


def set_share(spec: FitModelSpec, group: str, shared: bool) -> None:
    for fp in _group_params(spec, group):
        fp.shared = shared


def shared_param_summary(spec: FitModelSpec) -> str:
    names = []
    for group, label in SHARE_GROUPS:
        state = share_state(spec, group)
        if state is True:
            names.append(label.lower().replace("peak ", ""))
        elif state is None:
            names.append(f"some {label.lower().replace('peak ', '')}")
    return ", ".join(names)


def any_shared(spec: FitModelSpec) -> bool:
    return any(fp.shared for fp in spec.nonresonant.values()) or any(
        fp.shared for p in spec.peaks for fp in p.params.values()
    )
