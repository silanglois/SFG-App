from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class HDSFGConfig:
    """All parameters for the HD-SFG processing pipeline.
    Mirrors the configurable values in the original processing script.
    """
    # ── Upconversion ──────────────────────────────────────────────────────────
    upconversion_wavelength: float = 1030.7   # nm (wv in original script)

    # ── Interpolation ─────────────────────────────────────────────────────────
    # None = use same number of points as input
    n_interpolation_points: int | None = None

    # ── Smoothing — background (Savitzky-Golay) ───────────────────────────────
    bg_smoothing_window: int = 0     # LengthSm — must be odd
    bg_smoothing_order: int = 3      # orderSm

    # ── Smoothing — signal / reference (Savitzky-Golay) ──────────────────────
    sig_smoothing_window: int = 0    # LengthSm2 — must be odd, 0 = no smoothing
    sig_smoothing_order: int = 2     # orderSm2

    # ── Background offset ─────────────────────────────────────────────────────
    bg_offset: float = 0.0           # OffSetBg — constant added to sample bg

    # ── Edge window applied to delta before FFT ───────────────────────────────
    edge_left: int = 15              # Zero_L_smooth
    edge_right: int = 15             # Zero_R_smooth

    # ── FFT mask window ───────────────────────────────────────────────────────
    # 1: Box-Car
    # 2: Box-Car + Happ-Genzel (left edge only)
    # 3: Double Happ-Genzel (both edges)
    # 4: Masking Happ-Genzel (with attenuated region)
    window_type: int = 3

    fft_start: int = 30              # fft_x_st
    fft_end: int = 110               # fft_x_end
    hg_left: int = 10                # L_HG1
    hg_right: int = 10               # L_HG2 (type 3 only)

    # type 4 only
    mask_start: int = 150            # L_x_st
    mask_end: int = 160              # L_x_ed
    mask_transition: int = 5         # L_mask
    mask_factor: float = 0.08        # L_factor

    # ── Exposure times ────────────────────────────────────────────────────────
    sample_exposure: float = 300.0   # seconds
    reference_exposure: float = 30.0   # seconds

    # ── Phase correction ──────────────────────────────────────────────────────
    phase_correction_deg: float = 0.0   # phase_corr — additional rotation in degrees

    # ── Despiking ─────────────────────────────────
    despike: bool = True
    despike_window: int = 50
    despike_threshold: float = 10

    # ── Frame exclusion ────────────────────────────
    # keys: "signal"/"background"/"reference"/"reference_background"
    exclude_frames: dict = field(default_factory=dict)

    def __post_init__(self):
        self.edge_left  = int(self.edge_left)
        self.edge_right = int(self.edge_right)
        self.fft_start  = int(self.fft_start)
        self.fft_end    = int(self.fft_end)
        if self.bg_smoothing_window > 0 and self.bg_smoothing_window % 2 == 0:
            self.bg_smoothing_window += 1
        if self.sig_smoothing_window > 0 and self.sig_smoothing_window % 2 == 0:
            self.sig_smoothing_window += 1