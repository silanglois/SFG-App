from __future__ import annotations
import logging
import pandas as pd

from .processed_spectrum import ProcessedSpectrum

logger = logging.getLogger(__name__)


def normalize(sample, reference) -> ProcessedSpectrum:
    """Normalize a sample spectrum by a reference spectrum (sample / reference).
    Both are averaged across frames first. Warns (via logging) if either
    input's history shows no background subtraction step.
    """
    for name, spectrum in (("sample", sample), ("reference", reference)):
        if "subtract_background" not in spectrum.history:
            logger.warning(
                "%s spectrum has not been background-subtracted (history=%s). "
                "Normalizing un-subtracted data is usually not physically meaningful.",
                name.capitalize(), spectrum.history,
            )

    sample_avg = sample.average_spectrum().frame(1)
    ref_avg = reference.average_spectrum().frame(1)

    sample_wavelength = sample_avg["Wavelength"].to_numpy()
    ref_lookup = pd.Series(
        ref_avg["Intensity"].to_numpy(), index=ref_avg["Wavelength"].to_numpy()
    )

    normalized_intensity = sample_avg["Intensity"].to_numpy() / ref_lookup.loc[sample_wavelength].to_numpy()

    df = pd.DataFrame({
        "Frame": 1,
        "Wavelength": sample_wavelength,
        "Intensity": normalized_intensity,
    })

    return ProcessedSpectrum(
        df,
        metadata=sample.metadata,
        history=sample.history + ["normalize"],
    )