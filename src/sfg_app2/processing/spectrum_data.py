from __future__ import annotations
import numpy as np
import pandas as pd
import logging
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


class SpectrumDataMixin:
    """Shared read-only access to Frame/Wavelength data.
    Requires self._raw_df with columns: Frame, Wavelength, Intensity.
    """

    @property
    def data(self) -> pd.DataFrame:
        return self._raw_df

    @property
    def n_frames(self) -> int:
        return self._raw_df["Frame"].nunique()

    @property
    def wavelength(self) -> np.ndarray:
        return np.sort(self._raw_df["Wavelength"].unique())

    def frame(self, frame_id) -> pd.DataFrame:
        sub = self._raw_df[self._raw_df["Frame"] == frame_id]
        if sub.empty:
            raise ValueError(f"No frame '{frame_id}' found")
        return sub.sort_values("Wavelength").reset_index(drop=True)

    def average_spectrum(self):
        from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

        grouped = self._raw_df.groupby("Wavelength")["Intensity"]
        result = grouped.agg(["mean", "std", "count"]).reset_index()
        result = result.rename(columns={"mean": "Intensity", "std": "Intensity_std"})
        result = result.sort_values("Wavelength").reset_index(drop=True)

        result["Frame"] = 1  # collapsed to a single pseudo-frame

        return ProcessedSpectrum(
            result[["Frame", "Wavelength", "Intensity", "Intensity_std", "count"]],
            metadata=self.metadata,
            history=self.history + ["average_spectrum"],
        )
    
    def upconvert_to_wavenumber(self, upconversion_wavelength: float):
        """Add a Wavenumber (cm^-1) column derived from Wavelength (nm) and
        the upconversion wavelength, via energy conservation:
            wavenumber_IR = (1e7 / Wavelength) - (1e7 / upconversion_wavelength)
        Returns a new ProcessedSpectrum; does not modify self.
        """
        from .processed_spectrum import ProcessedSpectrum  # deferred, avoids circular import

        if "upconvert_to_wavenumber" in self.history:
            logger.warning(
                "Spectrum has already been upconverted once (history=%s). "
                "Applying it again will overwrite the existing Wavenumber column "
                "based on the *original* Wavelength column, not a double conversion — "
                "but check this is actually what you intend.",
                self.history,
            )

        df = self.data.copy()
        df["Wavenumber"] = (1e7 / df["Wavelength"]) - (1e7 / upconversion_wavelength)

        return ProcessedSpectrum(
            df,
            metadata=self.metadata,
            history=self.history + [f"upconvert_to_wavenumber({upconversion_wavelength})"],
        )

    def plot(
        self,
        ax=None,
        frame_id=None,
        x: str = "Wavelength",
        label: str = None,
        **kwargs
    ) -> plt.Axes:
        """Plot Intensity vs x-axis column (default: Wavelength).

        Parameters
        ----------
        ax : matplotlib Axes, optional
            Axes to plot on. Uses current axes if None.
        frame_id : int, optional
            Plot a single frame. Plots all frames if None.
        x : str
            Column to use as x-axis. Use "Wavenumber" after upconversion.
        label : str, optional
            Custom legend label. Auto-generates "Frame N" if None.
        **kwargs
            Passed directly to matplotlib plot().
        """
        if ax is None:
            ax = plt.gca()

        if x not in self.data.columns:
            raise ValueError(
                f"Column '{x}' not found. Available columns: {list(self.data.columns)}. "
                f"Have you called .upconvert_to_wavenumber() yet?"
            )

        if frame_id is not None:
            data = self.frame(frame_id)
            ax.plot(
                data[x], data["Intensity"],
                label=label or f"Frame {frame_id}",
                **kwargs
            )
        else:
            frame_ids = self.data["Frame"].unique()
            for fid in frame_ids:
                data = self.frame(fid)
                ax.plot(
                    data[x], data["Intensity"],
                    label=label if len(frame_ids) == 1 else (label or f"Frame {fid}"),
                    **kwargs
                )

        ax.set_xlabel(x)
        ax.set_ylabel("Intensity")
        return ax