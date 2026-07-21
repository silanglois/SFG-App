from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from sfg_app2.processing.despike import remove_outliers_movmedian
from .spectrum_data import SpectrumDataMixin
from .processed_spectrum import ProcessedSpectrum

logger = logging.getLogger(__name__)


class UnrecognizedFormatError(ValueError):
    """Raised when a file matches neither the long nor wide spectrum format."""

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
        try:
            raw = pd.read_csv(path)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
            raise UnrecognizedFormatError(
                f"{path.name}: could not be parsed as CSV ({e})"
            ) from e

        # Case 1: already long format
        missing_long = set(DataFile.REQUIRED_COLUMNS) - set(raw.columns)
        if not missing_long:
            return raw

        # Case 2: wide format — Wavelength + one column per frame
        if "Wavelength" not in raw.columns:
            raise UnrecognizedFormatError(
                f"{path.name}: columns don't match long format (missing "
                f"{missing_long}) or wide format (no 'Wavelength' column). "
                f"Found: {list(raw.columns)}"
            )

        df = raw.copy()

        first_row = df.iloc[0]
        if pd.to_numeric(first_row, errors="coerce").isna().any():
            df = df.iloc[1:].reset_index(drop=True)

        df = df.apply(pd.to_numeric, errors="coerce")

        frame_cols = [c for c in df.columns if c != "Wavelength"]
        if not frame_cols:
            raise UnrecognizedFormatError(
                f"{path.name}: wide format detected but no frame columns "
                f"found alongside 'Wavelength'."
            )

        long_df = df.melt(
            id_vars="Wavelength",
            value_vars=frame_cols,
            var_name="Frame",
            value_name="Intensity",
        )
        long_df["Frame"] = pd.to_numeric(long_df["Frame"], errors="coerce")
        if long_df["Frame"].isna().any():
            raise UnrecognizedFormatError(
                f"{path.name}: wide format frame column headers aren't "
                f"all numeric: {frame_cols}"
            )
        long_df["Frame"] = long_df["Frame"].astype(int)
        long_df = long_df.dropna(subset=["Intensity"]).reset_index(drop=True)

        if long_df.empty:
            raise UnrecognizedFormatError(
                f"{path.name}: no usable numeric data found after parsing "
                f"as wide format."
            )

        return long_df[["Frame", "Wavelength", "Intensity"]]


    # ---- batch loading -------------------------------------------------

    @classmethod
    def load_many(
        cls,
        paths: list[str | Path],
        filename_fields: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> list["DataFile"]:
        """Load multiple files, skipping (and logging a warning for) any
        that don't match a recognized format instead of raising.
        """
        loaded = []
        for p in paths:
            p = Path(p)
            try:
                loaded.append(cls(p, filename_fields=filename_fields, metadata=metadata))
            except UnrecognizedFormatError as e:
                logger.warning("Skipping %s: %s", p.name, e)
            except Exception as e:
                logger.warning("Skipping %s due to unexpected error: %s", p.name, e)
        return loaded
    
    # ---- filename parsing -------------------------------------------

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