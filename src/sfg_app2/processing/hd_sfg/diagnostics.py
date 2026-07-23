from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


@dataclass
class HDSFGDiagnostics:
    """Intermediate arrays from the HD-SFG pipeline, captured during processing.
    Used for visual inspection in notebooks or a future review UI.

    All arrays share the same uniform wavenumber/time axis unless noted.
    """
    wavenumber: np.ndarray          # uniform grid (cm⁻¹), max→min

    # ── Raw interpolated + smoothed ───────────────────────────────────────────
    sig_frames_raw: list[np.ndarray]    # per-frame, interpolated only
    sig_frames_sm: list[np.ndarray]     # per-frame, smoothed
    sig_avg_raw: np.ndarray             # averaged across frames, interpolated
    sig_avg_sm: np.ndarray              # averaged, smoothed
    bg_raw: np.ndarray                  # background, interpolated
    bg_sm: np.ndarray                   # background, smoothed
    ref_raw: np.ndarray                 # reference, interpolated
    ref_sm: np.ndarray                  # reference, smoothed
    ref_bg_raw: np.ndarray              # ref background, interpolated
    ref_bg_sm: np.ndarray               # ref background, smoothed

    # ── Delta (signal - background) ───────────────────────────────────────────
    edge_window: np.ndarray             # Hann-Genzel edge window
    sig_delta: np.ndarray               # averaged signal delta (before edge window)
    sig_delta_windowed: np.ndarray      # averaged signal delta × edge window
    ref_delta: np.ndarray               # reference delta
    ref_delta_windowed: np.ndarray

    # ── FFT domain ────────────────────────────────────────────────────────────
    time_axis: np.ndarray               # time axis for FFT plots (seconds)
    fft_mask: np.ndarray                # FFT mask window
    sig_fft: np.ndarray                 # complex FFT of sig_delta_windowed (shifted)
    ref_fft: np.ndarray                 # complex FFT of ref_delta_windowed (shifted)
    sig_fft_masked: np.ndarray          # sig_fft × fft_mask
    ref_fft_masked: np.ndarray          # ref_fft × fft_mask

    # ── iFFT result ───────────────────────────────────────────────────────────
    sig_ifft: np.ndarray                # complex iFFT of sig_fft_masked
    ref_ifft: np.ndarray                # complex iFFT of ref_fft_masked

    # ── Final ─────────────────────────────────────────────────────────────────
    chi_from_avg: np.ndarray            # normalized result from averaged data

    # ── Plot helpers ──────────────────────────────────────────────────────────

    def plot_raw(self, ax=None, xlim: tuple | None = None, frame_idx: int | None = None):
        """Step 1 — interpolated signal (raw + smoothed), background, and delta.

        If frame_idx is given, shows that specific frame's raw and smoothed versions.
        Otherwise shows the averaged signal (raw and smoothed).
        """
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        wn = self.wavenumber

        if frame_idx is not None and frame_idx < len(self.sig_frames_sm):
            sig_raw = self.sig_frames_raw[frame_idx]
            sig_sm  = self.sig_frames_sm[frame_idx]
            base_label = f"Frame {frame_idx}"
        else:
            sig_raw = self.sig_avg_raw
            sig_sm  = self.sig_avg_sm
            base_label = "Signal (avg)"

        # raw — faded dashed, smoothed — solid
        ax.plot(wn, sig_raw, alpha=0.3, linestyle="--",
                label=f"{base_label} (raw)")
        ax.plot(wn, sig_sm, label=f"{base_label} (smoothed)")

        ax.plot(wn, self.bg_sm, linestyle="--", alpha=0.7,
                label="Background (smoothed)")

        # delta uses smoothed signal vs smoothed background
        ax.plot(wn, sig_sm - self.bg_sm, alpha=0.6,
                label="Delta (unwindowed)")

        ax.axhline(0, color="gray", linewidth=0.5)
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Intensity")
        ax.set_title(
            f"Step 1 — {'Frame ' + str(frame_idx) if frame_idx is not None else 'Averaged'} "
            f"signal, background & delta"
        )
        if xlim:
            ax.set_xlim(*xlim)
        ax.legend(fontsize=8)
        return ax

    def plot_edge_window(self, ax=None, xlim: tuple | None = None):
        """Step 2 — delta with edge window applied."""
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        wn = self.wavenumber
        ax2 = ax.twinx()
        ax.plot(wn, self.sig_delta, label="Delta (raw)", alpha=0.5, linestyle="--")
        ax.plot(wn, self.sig_delta_windowed, label="Delta (windowed)", linewidth=1.5)
        ax2.plot(wn, self.edge_window, color="gray", linewidth=0.8,
                 linestyle=":", label="Edge window")
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Delta intensity")
        ax2.set_ylabel("Window weight", color="gray")
        ax.set_title("Step 2 — Edge window applied to delta")
        ax.axhline(0, color="gray", linewidth=0.5)
        if xlim:
            ax.set_xlim(*xlim)
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)
        return ax

    def plot_fft(self, ax=None, tlim: tuple | None = (-5e-12, 5e-12)):
        """Step 3 — FFT with mask window overlaid."""
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        t = self.time_axis
        ax2 = ax.twinx()

        sig_fft_im = self.sig_fft.imag
        scale = max(abs(sig_fft_im)) if max(abs(sig_fft_im)) > 0 else 1.0
        mask_scaled = self.fft_mask * scale

        ax.plot(t, sig_fft_im, label="Signal FFT (imag)", linewidth=1)
        ax.plot(t, self.ref_fft.imag, label="Reference FFT (imag)",
                linestyle="--", alpha=0.7)
        ax2.plot(t, self.fft_mask, color="firebrick", linewidth=0.8,
                 linestyle=":", label="FFT mask")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("FFT amplitude (imaginary)")
        ax2.set_ylabel("Mask weight", color="firebrick")
        ax.set_title("Step 3 — FFT and mask window")
        if tlim:
            ax.set_xlim(*tlim)
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)
        return ax

    def plot_fft_masked(self, ax=None, tlim: tuple | None = (-5e-12, 5e-12)):
        """Step 4 — FFT after masking (filtered signal)."""
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        t = self.time_axis
        ax.plot(t, self.sig_fft_masked.imag, label="Signal FFT masked (imag)")
        ax.plot(t, self.ref_fft_masked.imag, label="Reference FFT masked (imag)",
                linestyle="--", alpha=0.7)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("FFT amplitude (imaginary)")
        ax.set_title("Step 4 — Masked FFT")
        if tlim:
            ax.set_xlim(*tlim)
        ax.legend(fontsize=8)
        return ax

    def plot_ifft(self, ax=None, xlim: tuple | None = None):
        """Step 5 — iFFT result in frequency domain."""
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        wn = self.wavenumber
        ax.plot(wn, self.sig_ifft.imag, label="Signal iFFT (imag)")
        ax.plot(wn, self.sig_ifft.real, label="Signal iFFT (real)", linestyle="--")
        ax.plot(wn, self.ref_ifft.imag, label="Reference iFFT (imag)", alpha=0.6)
        ax.axhline(0, color="gray", linewidth=0.5)
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Amplitude")
        ax.set_title("Step 5 — iFFT result")
        if xlim:
            ax.set_xlim(*xlim)
        ax.legend(fontsize=8)
        return ax

    def plot_final(self, ax=None, xlim: tuple | None = None):
        """Step 6 — final normalized complex χ."""
        if ax is None:
            _, ax = plt.subplots(figsize=(8, 4))

        wn = self.wavenumber
        ax.plot(wn, self.chi_from_avg.imag, label="Im(χ⁽²⁾)")
        ax.plot(wn, self.chi_from_avg.real, label="Re(χ⁽²⁾)", linestyle="--")
        ax.axhline(0, color="gray", linewidth=0.5)
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("χ⁽²⁾ (arb. units)")
        ax.set_title("Step 6 — Final normalized result")
        if xlim:
            ax.set_xlim(*xlim)
        ax.legend(fontsize=8)
        return ax

    def plot_all(
        self,
        xlim: tuple | None = (2800, 3800),
        tlim: tuple | None = (-5e-12, 5e-12),
        figsize: tuple = (16, 12),
    ):
        """Full diagnostic figure — all six steps in one view."""
        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

        self.plot_raw(ax=fig.add_subplot(gs[0, 0]), xlim=xlim)
        self.plot_edge_window(ax=fig.add_subplot(gs[0, 1]), xlim=xlim)
        self.plot_fft(ax=fig.add_subplot(gs[1, 0]), tlim=tlim)
        self.plot_fft_masked(ax=fig.add_subplot(gs[1, 1]), tlim=tlim)
        self.plot_ifft(ax=fig.add_subplot(gs[2, 0]), xlim=xlim)
        self.plot_final(ax=fig.add_subplot(gs[2, 1]), xlim=xlim)

        fig.suptitle("HD-SFG Processing Diagnostics", fontsize=13, y=1.01)
        return fig