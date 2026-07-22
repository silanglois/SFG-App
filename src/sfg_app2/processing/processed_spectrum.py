from __future__ import annotations
import pandas as pd
from .spectrum_data import SpectrumDataMixin


class ProcessedSpectrum(SpectrumDataMixin):
    """Output of a processing step (despike, baseline, normalize, ...)."""

    def __init__(
        self,
        df: pd.DataFrame,
        metadata: dict,
        history: list[str],
        provenance: dict | None = None,   # new — stores full processing details
    ):
        self._raw_df = df
        self.metadata = metadata
        self.history = history
        self.provenance = provenance or {}

    def __repr__(self) -> str:
        return f"ProcessedSpectrum(n_frames={self.n_frames}, history={self.history})"

    def to_csv(self, path, **kwargs) -> None:
        """Export processed data — relevant since you mentioned exporting later."""
        self._raw_df.to_csv(path, index=False, **kwargs)