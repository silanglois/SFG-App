from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class HDSFGResult:
    """Output of the HD-SFG processing pipeline.

    Contains the complex χ⁽²⁾ (from the per-frame mean -- mathematically
    identical to normalizing the once-averaged signal, since every step
    of the pipeline up to normalization is linear), its derived phase
    and homodyne intensity (always computed from that single averaged
    χ, never by averaging each frame's own phase/intensity separately --
    see step_normalize()'s docstring for why), and per-frame statistics
    (95% CI error bars, signal-frame variability only).

    Attributes
    ----------
    wavenumber:    uniform wavenumber axis (cm⁻¹)
    complex_chi:   complex χ⁽²⁾ (per-frame mean)
    phase:         phase in degrees (-180, 180], from complex_chi
    homodyne:      |χ⁽²⁾|², from complex_chi
    real_err:      95% CI on real part (per-frame)
    imag_err:      95% CI on imaginary part (per-frame)
    phase_err:     95% CI on phase (per-frame)
    homodyne_err:  95% CI on homodyne (per-frame)
    n_frames:      number of frames processed
    metadata:      inherited from signal DataFile
    history:       processing step labels
    provenance:    full parameter record
    """
    wavenumber: np.ndarray
    complex_chi: np.ndarray
    phase: np.ndarray
    homodyne: np.ndarray

    real_err: np.ndarray
    imag_err: np.ndarray
    phase_err: np.ndarray
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
            "Real_err":      self.real_err,
            "Imag_err":      self.imag_err,
            "Phase_err":     self.phase_err,
            "Homodyne_err":  self.homodyne_err,
        })

    # ── Plotting ──────────────────────────────────────────────────────────────

    def plot(
        self,
        ax=None,
        component: str = "imaginary",
        show_error: bool = True,
        xlim: tuple[float, float] | None = None,
        **kwargs,
    ):
        """Plot one component of the HD-SFG result.

        Parameters
        ----------
        component : 'real' | 'imaginary' | 'phase' | 'homodyne'
        show_error : show 95% CI bands (only meaningful when n_frames > 1)
        xlim : optional (x_min, x_max) wavenumber range to display
        """
        import matplotlib.pyplot as plt

        if ax is None:
            ax = plt.gca()

        wn = self.wavenumber
        comp = component.lower()

        y, y_err = {
            "real":      (self.complex_chi.real, self.real_err),
            "imaginary": (self.complex_chi.imag, self.imag_err),
            "phase":     (self.phase,            self.phase_err),
            "homodyne":  (self.homodyne,          self.homodyne_err),
        }.get(comp, (self.complex_chi.imag, self.imag_err))

        label = kwargs.pop("label", component)
        ax.plot(wn, y, label=label, **kwargs)
        ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

        if show_error and self.n_frames > 1:
            ax.fill_between(wn, y - y_err, y + y_err, alpha=0.3)

        if xlim:
            ax.set_xlim(*xlim)

        ax.set_xlabel("Wavenumber (cm$^{-1}$)")
        ylabel = {
            "real":      r"Re($\chi^{(2)}$) (a.u.)",
            "imaginary": r"Im($\chi^{(2)}$) (a.u.)",
            "phase":     "Phase (°)",
            "homodyne":  r"$|\chi^{(2)}|^2$ (a.u.)",
        }.get(comp, "Amplitude (a.u.)")
        ax.set_ylabel(ylabel)

        return ax

    def __repr__(self) -> str:
        return (
            f"HDSFGResult(n_frames={self.n_frames}, "
            f"wavenumber=[{self.wavenumber[0]:.0f}–{self.wavenumber[-1]:.0f}] cm⁻¹)"
        )
