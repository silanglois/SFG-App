from __future__ import annotations
import numpy as np
import pandas as pd

from sfg_app2.processing.processed_spectrum import ProcessedSpectrum


class SpectrumDataMixin:
    """Shared read-only access to frame/wavelength data.
    Requires self._raw_df with columns: frame, wavelength, intensity.
    """

    @property
    def raw_data(self) -> pd.DataFrame:
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

    def average_spectrum(self) -> ProcessedSpectrum:
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