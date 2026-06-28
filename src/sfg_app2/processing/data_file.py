from __future__ import annotations


from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from sfg_app2.processing.despike import remove_outliers_movmedian
from .spectrum_data import SpectrumDataMixin
from .processed_spectrum import ProcessedSpectrum



class DataFile(SpectrumDataMixin):
    """A single SFG spectroscopy data file: raw frame data + metadata.

    Expects a CSV with columns: Frame, Wavelength, Intensity.
    Metadata is parsed best-effort from the filename and can be
    supplemented or corrected manually.
    """

    REQUIRED_COLUMNS = ("Frame", "Wavelength", "Intensity")

    def __init__(
        self, 
        path: str | Path,
        filename_fields: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ):
        self.path = Path(path)
        self._raw_df = self._load_csv(self.path)
        self.metadata = self._parse_filename_metadata(self.path, filename_fields)
        if metadata:
            self.metadata.update(metadata)  # manual values always win
        self.history: list[str] = []

    # ---- loading ----------------------------------------------------
    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        missing = set(DataFile.REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"{path.name}: missing required column(s) {missing}. "
                f"Found: {list(df.columns)}"
            )
        return df

    @staticmethod
    def _parse_filename_metadata(path: Path, fields: Optional[list[str]]) -> dict:
        """Best-effort metadata from an underscore-separated filename.

        If `fields` is given (e.g. ["sample", "polarization", "date"]),
        parts map positionally. If not given, or if there's a mismatch,
        nothing is lost — raw parts are kept under a fallback key.
        """
        parts = path.stem.split("_")
        metadata: dict = {"source_filename": path.name}

        if fields:
            for i, name in enumerate(fields):
                metadata[name] = parts[i] if i < len(parts) else None
            if len(parts) > len(fields):
                metadata["extra_filename_parts"] = parts[len(fields):]
        else:
            metadata["filename_parts"] = parts

        return metadata

    # ------------------------------------------
    
    def remove_cosmic_rays(self, window: int = 5, threshold_factor: float = 3.0) -> ProcessedSpectrum:
        cleaned_frames = []
        for frame_id, group in self._raw_df.groupby("Frame"):
            group = group.sort_values("Wavelength").copy()
            group["Intensity"] = remove_outliers_movmedian(
                group["Intensity"].to_numpy(), window, threshold_factor
            )
            cleaned_frames.append(group)
        cleaned_df = pd.concat(cleaned_frames, ignore_index=True)
        return ProcessedSpectrum(
            cleaned_df, metadata=self.metadata, history=self.history + ["remove_cosmic_rays"]
        )

    def __repr__(self) -> str:
        return f"DataFile({self.path.name}, n_frames={self.n_frames}, metadata={self.metadata})"