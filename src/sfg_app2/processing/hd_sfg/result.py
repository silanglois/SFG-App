from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class HDSFGResult:
    """Output of the HD-SFG processing pipeline.

    Contains the full complex χ⁽²⁾, derived phase, homodyne intensity,
    and per-frame statistics (95% CI error bars).

    Attributes
    ----------
    wavenumber:           uniform wavenumber axis (cm⁻¹)
    complex_chi:          complex χ⁽²⁾ from averaged data
    phase:                phase in degrees [0, 360] from averaged data
    homodyne:             |χ⁽²⁾|² from averaged data
    complex_chi_avg:      per-frame mean complex χ⁽²⁾ (may differ from above
                          when n_frames > 1, since this averages iFFT outputs)
    real_err:             95% CI on real part (per-frame)
    imag_err:             95% CI on imaginary part (per-frame)
    phase_avg:            per-frame mean phase
    phase_err:            95% CI on phase (per-frame)
    homodyne_avg:         per-frame mean homodyne
    homodyne_err:         95% CI on homodyne (per-frame)
    n_frames:             number of frames processed
    metadata:             inherited from signal DataFile
    history:              processing step labels
    provenance:           full parameter record
    """
    wavenumber: np.ndarray
    complex_chi: np.ndarray
    phase: np.ndarray
    homodyne: np.ndarray

    complex_chi_avg: np.ndarray
    real_err: np.ndarray
    imag_err: np.ndarray
    phase_avg: np.ndarray
    phase_err: np.ndarray
    homodyne_avg: np.ndarray
    homodyne_err: np.ndarray

    n_frames: int
    metadata: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    # ── DataFrame export ──────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        """Export all computed quantities to a single DataFrame.
        Compatible with pd.read_csv for round-tripping.
        """
        return pd.DataFrame({
            "Wavenumber":    self.wavenumber,
            "Real":          self.complex_chi.real,
            "Imaginary":     self.complex_chi.imag,
            "Phase":         self.phase,
            "Homodyne":      self.homodyne,
            "Real_avg":      self.complex_chi_avg.real,
            "Imag_avg":      self.complex_chi_avg.imag,
            "Real_err":      self.real_err,
            "Imag_err":      self.imag_err,
            "Phase_avg":     self.phase_avg,
            "Phase_err":     self.phase_err,
            "Homodyne_avg":  self.homodyne_avg,
            "Homodyne_err":  self.homodyne_err,
        })

    # ── Plotting ──────────────────────────────────────────────────────────────

    def plot(
        self,
        ax=None,
        component: str = "imaginary",
        use_per_frame_avg: bool = False,
        show_error: bool = True,
        xlim: tuple[float, float] | None = None,
        **kwargs,
    ):
        """Plot one component of the HD-SFG result.

        Parameters
        ----------
        component : 'real' | 'imaginary' | 'phase' | 'homodyne'
        use_per_frame_avg : if True, plot per-frame average with error bands
                            instead of averaged-data result
        show_error : show 95% CI bands (only when use_per_frame_avg=True)
        xlim : optional (x_min, x_max) wavenumber range to display
        """
        import matplotlib.pyplot as plt

        if ax is None:
            ax = plt.gca()

        wn = self.wavenumber
        comp = component.lower()

        if use_per_frame_avg:
            y, y_err = {
                "real":      (self.complex_chi_avg.real, self.real_err),
                "imaginary": (self.complex_chi_avg.imag, self.imag_err),
                "phase":     (self.phase_avg,            self.phase_err),
                "homodyne":  (self.homodyne_avg,         self.homodyne_err),
            }.get(comp, (self.complex_chi_avg.imag, self.imag_err))
        else:
            y = {
                "real":      self.complex_chi.real,
                "imaginary": self.complex_chi.imag,
                "phase":     self.phase,
                "homodyne":  self.homodyne,
            }.get(comp, self.complex_chi.imag)
            y_err = None

        label = kwargs.pop("label", component)
        ax.plot(wn, y, label=label, **kwargs)
        ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

        if use_per_frame_avg and show_error and y_err is not None:
            ax.fill_between(wn, y - y_err, y + y_err, alpha=0.3)

        if xlim:
            ax.set_xlim(*xlim)

        ax.set_xlabel("Wavenumber (cm$^{-1}$)")
        ylabel = {
            "real":      r"Re($\chi^{(2)}$)",
            "imaginary": r"Im($\chi^{(2)}$)",
            "phase":     "Phase (°)",
            "homodyne":  r"$|\chi^{(2)}|^2$",
        }.get(comp, "Amplitude")
        ax.set_ylabel(ylabel)

        return ax

    def __repr__(self) -> str:
        return (
            f"HDSFGResult(n_frames={self.n_frames}, "
            f"wavenumber=[{self.wavenumber[0]:.0f}–{self.wavenumber[-1]:.0f}] cm⁻¹)"
        )