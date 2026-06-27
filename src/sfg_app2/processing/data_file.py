# src/sfg_app2/processing/data_file.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


class DataFile:
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

    # ---- raw data access ----------------------------------------------
    @property
    def raw_data(self) -> pd.DataFrame:
        """Unmodified frame/wavelength/intensity data, exactly as loaded."""
        return self._raw_df

    @property
    def n_frames(self) -> int:
        return self._raw_df["frame"].nunique()

    @property
    def wavelength(self) -> np.ndarray:
        """Unique wavelength axis (assumes all frames share the same axis)."""
        return np.sort(self._raw_df["wavelength"].unique())

    # ---- frame access / averaging --------------------------------------
    def frame(self, frame_id) -> pd.DataFrame:
        """Return a single frame's data, sorted by wavelength."""
        sub = self._raw_df[self._raw_df["frame"] == frame_id]
        if sub.empty:
            raise ValueError(f"No frame '{frame_id}' in {self.path.name}")
        return sub.sort_values("wavelength").reset_index(drop=True)

    def average_spectrum(self) -> pd.DataFrame:
        """Mean intensity per wavelength across frames, with std as a noise estimate."""
        grouped = self._raw_df.groupby("wavelength")["intensity"]
        result = grouped.agg(["mean", "std", "count"]).reset_index()
        result = result.rename(columns={"mean": "intensity", "std": "intensity_std"})
        return result.sort_values("wavelength").reset_index(drop=True)

    def __repr__(self) -> str:
        return f"DataFile({self.path.name}, n_frames={self.n_frames}, metadata={self.metadata})"