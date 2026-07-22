from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

from .matcher import MatchedSet
from .processed_spectrum import ProcessedSpectrum
from .baseline import subtract_background
from .normalization import normalize
from .utils import OffsetSpec

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Processing parameters for one MatchedSet.

    All steps are individually toggleable via the run_* flags,
    so you can skip cosmic ray removal or normalization for specific files.
    """
    # cosmic ray removal
    run_despike: bool = True
    despike_window: int = 5
    despike_threshold: float = 3.0

    # background subtraction
    run_background: bool = True
    bg_offset: OffsetSpec = None        # offset applied to signal background
    ref_bg_offset: OffsetSpec = None    # offset applied to reference background

    # normalization
    run_normalize: bool = True

    # upconversion
    run_upconvert: bool = True
    upconversion_wavelength: Optional[float] = None  # required if run_upconvert=True


def process_matched(matched: MatchedSet, config: PipelineConfig) -> ProcessedSpectrum:
    """Run the full pipeline on one MatchedSet using the provided config.
    Returns the final ProcessedSpectrum.
    """
    provenance = {
        "signal":               matched.signal.path.name if matched.signal else None,
        "background":           matched.background.path.name if matched.background else None,
        "reference":            matched.reference.path.name if matched.reference else None,
        "reference_background": matched.reference_background.path.name
                                if matched.reference_background else None,
        "despike": {
            "applied":           config.run_despike,
            "window":            config.despike_window,
            "threshold_factor":  config.despike_threshold,
        },
        "background_subtraction": {
            "applied":      config.run_background,
            "signal_offset": str(config.bg_offset),
            "ref_offset":    str(config.ref_bg_offset),
        },
        "normalization": {
            "applied": config.run_normalize,
        },
        "upconversion": {
            "applied":            config.run_upconvert,
            "wavelength_nm":      config.upconversion_wavelength,
        },
    }

    signal = matched.signal
    background = matched.background
    reference = matched.reference
    ref_background = matched.reference_background

    # ── Despike ──────────────────────────────────────────────────────────────
    if config.run_despike:
        signal = signal.remove_cosmic_rays(config.despike_window, config.despike_threshold)
        if background:
            background = background.remove_cosmic_rays(config.despike_window, config.despike_threshold)
        if reference:
            reference = reference.remove_cosmic_rays(config.despike_window, config.despike_threshold)
        if ref_background:
            ref_background = ref_background.remove_cosmic_rays(config.despike_window, config.despike_threshold)

    # ── Average frames ────────────────────────────────────────────────────────
    signal = signal.average_spectrum()
    if background:
        background = background.average_spectrum()
    if reference:
        reference = reference.average_spectrum()
    if ref_background:
        ref_background = ref_background.average_spectrum()

    # ── Background subtraction ───────────────────────────────────────────────
    if config.run_background:
        if background is None:
            logger.warning(
                "%s: run_background=True but no background file — skipping subtraction.",
                matched.signal.path.name,
            )
        else:
            signal = subtract_background(signal, background, offset=config.bg_offset)

        if config.run_normalize and reference is not None:
            if ref_background is None:
                logger.warning(
                    "%s: no reference background — reference will not be background-subtracted.",
                    matched.signal.path.name,
                )
            else:
                reference = subtract_background(reference, ref_background, offset=config.ref_bg_offset)

    # ── Normalization ─────────────────────────────────────────────────────────
    if config.run_normalize:
        if reference is None:
            logger.warning(
                "%s: run_normalize=True but no reference file — skipping normalization.",
                matched.signal.path.name,
            )
        else:
            signal = normalize(signal, reference)

    # ── Upconversion ──────────────────────────────────────────────────────────
    if config.run_upconvert:
        if config.upconversion_wavelength is None:
            logger.warning(
                "%s: run_upconvert=True but no upconversion_wavelength provided — skipping.",
                matched.signal.path.name,
            )
        else:
            signal = signal.upconvert_to_wavenumber(config.upconversion_wavelength)

    signal.provenance = provenance
    
    return signal


def process_batch(
    matched_sets: list[MatchedSet],
    default_config: PipelineConfig,
    per_file_configs: dict[str, PipelineConfig] = None,
) -> dict[str, ProcessedSpectrum]:
    """Process a list of MatchedSets, returning a dict keyed by signal filename.

    Parameters
    ----------
    matched_sets : list[MatchedSet]
        Output of DataFileMatcher.match().
    default_config : PipelineConfig
        Parameters used for all files unless overridden.
    per_file_configs : dict[str, PipelineConfig], optional
        Filename-keyed overrides — only the files that need different settings.
        Keys are signal filenames (path.name), not full paths.
    """
    per_file_configs = per_file_configs or {}
    results: dict[str, ProcessedSpectrum] = {}

    for matched in matched_sets:
        key = matched.signal.path.name

        if not matched.is_complete():
            logger.warning(
                "%s: MatchedSet is incomplete — skipping. "
                "Use .with_background()/.with_reference() to fix manually.",
                key,
            )
            continue

        config = per_file_configs.get(key, default_config)

        try:
            results[key] = process_matched(matched, config)
            logger.info("Processed %s successfully.", key)
        except Exception as e:
            logger.warning(
                "%s: pipeline failed with %s: %s — skipping.",
                key, type(e).__name__, e,
            )

    logger.info(
        "Batch complete: %d/%d files processed successfully.",
        len(results), len(matched_sets),
    )

    return results