from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def build_provenance_from_history(spectrum) -> dict:
    """Fallback provenance for spectra not processed via the pipeline."""
    return {
        "source": spectrum.metadata.get("source_filename", "unknown"),
        "history": spectrum.history,
        "note": "Loaded directly from file — full provenance unavailable.",
    }


def load_csv_skip_comments(path: Path) -> pd.DataFrame:
    """Load CSV, skipping # comment lines in the header."""
    return pd.read_csv(path, comment="#")


def format_markers(markers) -> str:
    if not markers:
        return "none"
    return ";".join(f"{x:.6g}:{y:.6g}" for x, y in markers)


def parse_markers(text: str | None) -> list[list[float]]:
    text = (text or "").strip().lower()
    if not text or text == "none":
        return []
    points = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        x_str, _, y_str = chunk.partition(":")
        try:
            points.append([float(x_str), float(y_str)])
        except ValueError:
            continue
    return points


def format_homodyne_provenance(provenance: dict) -> list[str]:
    lines = []

    d = provenance.get("despike", {})

    def comp(key, label):
        c = d.get(key) or {}
        return [
            f"# Despike {label} window:      {c.get('window', 'N/A')}",
            f"# Despike {label} threshold:   {c.get('threshold', 'N/A')}",
        ]

    lines += comp("signal", "signal")
    lines += comp("background", "background")
    lines += comp("reference", "reference")
    lines += comp("reference_background", "reference_background")

    excl = provenance.get("excluded_frames", {})

    def excl_line(key, label):
        ids = excl.get(key) or []
        return f"# Excluded frames {label}:      {','.join(map(str, ids)) if ids else 'none'}"

    lines.append(excl_line("signal", "signal"))
    lines.append(excl_line("background", "background"))
    lines.append(excl_line("reference", "reference"))
    lines.append(excl_line("reference_background", "reference_background"))

    bg = provenance.get("background_subtraction", {})
    if bg.get("applied"):
        lines += [
            "# Background subtraction: applied",
            f"#   signal offset degree:  {bg.get('signal_offset_degree', 'N/A')}",
            f"#   signal offset markers: {format_markers(bg.get('signal_offset_markers'))}",
            f"#   signal offset:         {bg.get('signal_offset', 'None')}",
            f"#   ref offset degree:     {bg.get('ref_offset_degree', 'N/A')}",
            f"#   ref offset markers:    {format_markers(bg.get('ref_offset_markers'))}",
            f"#   ref offset:            {bg.get('ref_offset', 'None')}",
        ]
    else:
        lines.append("# Background subtraction: not applied")

    norm = provenance.get("normalization", {})
    lines.append(
        f"# Normalization:        {'applied' if norm.get('applied') else 'not applied'}"
    )

    upconv = provenance.get("upconversion", {})
    if upconv.get("applied"):
        lines += [
            "# Upconversion:         applied",
            f"#   wavelength:         {upconv.get('wavelength_nm', 'N/A')} nm",
        ]
    else:
        lines.append("# Upconversion:         not applied")

    return lines


def format_heterodyne_provenance(provenance: dict) -> list[str]:
    d = provenance.get("despike", {})
    bg = provenance.get("background_subtraction", {})
    fft = provenance.get("fft_filter", {})
    norm = provenance.get("normalization", {})
    up = provenance.get("upconversion", {})

    def comp(key, label):
        c = d.get(key, {})
        return [
            f"# Despike {label} window:      {c.get('window', 'N/A')}",
            f"# Despike {label} threshold:   {c.get('threshold', 'N/A')}",
        ]

    excl = provenance.get("excluded_frames", {})

    def excl_line(key, label):
        ids = excl.get(key) or []
        return f"# Excluded frames {label}:      {','.join(map(str, ids)) if ids else 'none'}"

    lines = []
    lines += comp("signal", "signal")
    lines += comp("background", "background")
    lines += comp("reference", "reference")
    lines += comp("reference_background", "reference_background")
    lines.append(excl_line("signal", "signal"))
    lines.append(excl_line("background", "background"))
    lines.append(excl_line("reference", "reference"))
    lines.append(excl_line("reference_background", "reference_background"))
    lines += [
        f"# BG subtraction offset degree:       {bg.get('bg_offset_degree', 'N/A')}",
        f"# BG subtraction offset markers:      {format_markers(bg.get('bg_offset_markers'))}",
        f"# BG subtraction offset:              {bg.get('bg_offset', 'N/A')}",
        f"# BG subtraction edge_left_pts:       {bg.get('edge_left', 'N/A')}",
        f"# BG subtraction edge_right_pts:      {bg.get('edge_right', 'N/A')}",
        f"# BG smoothing window:                {bg.get('bg_smoothing_window', 'N/A')}",
        f"# BG smoothing order:                 {bg.get('bg_smoothing_order', 'N/A')}",
        f"# Signal smoothing window:            {bg.get('sig_smoothing_window', 'N/A')}",
        f"# Signal smoothing order:             {bg.get('sig_smoothing_order', 'N/A')}",
        f"# FFT window_type:                    {fft.get('window_type', 'N/A')}",
        f"# FFT start_pts:                      {fft.get('fft_start', 'N/A')}",
        f"# FFT end_pts:                        {fft.get('fft_end', 'N/A')}",
        f"# FFT hg_left_pts:                    {fft.get('hg_left', 'N/A')}",
        f"# FFT hg_right_pts:                   {fft.get('hg_right', 'N/A')}",
        f"# FFT mask_start_pts:                 {fft.get('mask_start', 'N/A')}",
        f"# FFT mask_end_pts:                   {fft.get('mask_end', 'N/A')}",
        f"# FFT mask_transition_pts:             {fft.get('mask_transition', 'N/A')}",
        f"# FFT mask_factor:                    {fft.get('mask_factor', 'N/A')}",
        f"# Normalization sample_exposure_s:     {norm.get('sample_exposure_s', 'N/A')}",
        f"# Normalization reference_exposure_s:  {norm.get('reference_exposure_s', 'N/A')}",
        f"# Normalization phase_correction_deg:  {norm.get('phase_correction_deg', 'N/A')}",
        f"# Upconversion wavelength_nm:          {up.get('wavelength_nm', 'N/A')}",
        f"# Frames processed:                    {provenance.get('n_frames', 'N/A')}",
    ]
    return lines


def format_fit_section(model_dict: dict, weighting: str, redchi: float,
                        r_squared: float, aic: float, bic: float, kind: str) -> list[str]:
    """A `# --- Fit ---` header block. The fit model itself is embedded as
    one compact JSON line (rather than a bespoke per-parameter line
    format) so it round-trips exactly via parse_fit_json() — colons
    inside the JSON are safe since header parsing only splits on the
    *first* colon in a line. `kind` ("homodyne"/"heterodyne") records
    which fit function produced this payload, since a restored
    FitModelSpec looks identical either way.
    """
    payload = {
        "model": model_dict, "weighting": weighting,
        "redchi": redchi, "r_squared": r_squared, "aic": aic, "bic": bic,
        "kind": kind,
    }
    return [
        "#",
        "# --- Fit ---",
        f"# Fit summary: redchi={redchi:.6g}, r_squared={r_squared:.6g}, "
        f"aic={aic:.6g}, bic={bic:.6g}, weighting={weighting}",
        f"# Fit json: {json.dumps(payload)}",
    ]


def parse_fit_json(provenance: dict) -> dict | None:
    """Decode the `fit_json` payload captured by parse_export_header(),
    if present. Returns the raw dict ({"model", "weighting", "redchi",
    "r_squared", "aic", "bic"}) — turning "model" back into a
    FitModelSpec is left to processing.fitting (keeps this module from
    needing to import it)."""
    raw = provenance.get("fit_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def write_csv_with_provenance(spectrum, kind: str, label: str, out_path: Path,
                               fit_section: list[str] | None = None):
    """Write a CSV with a commented provenance header, readable by pandas
    via pd.read_csv(path, comment='#'). `kind` is "homodyne" or
    "heterodyne". `fit_section` (from format_fit_section()) is appended
    after sample metadata, if given.
    """
    provenance = getattr(spectrum, "provenance", None) or \
        build_provenance_from_history(spectrum)

    header_lines = ["# SFG-App export"]
    if kind == "heterodyne":
        header_lines.append("# Type:        heterodyne")
    header_lines += [
        f"# Label:       {label}",
        f"# Exported:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# History:     {' → '.join(spectrum.history)}",
        "#",
        "# --- Source files ---",
        f"# Signal:               {provenance.get('signal', 'N/A')}",
        f"# Background:           {provenance.get('background', 'N/A')}",
        f"# Reference:            {provenance.get('reference', 'N/A')}",
        f"# Reference background: {provenance.get('reference_background', 'N/A')}",
        "#",
        "# --- Processing parameters ---",
    ]

    if kind == "heterodyne":
        header_lines += format_heterodyne_provenance(provenance)
    else:
        header_lines += format_homodyne_provenance(provenance)

    if spectrum.metadata:
        header_lines += ["#", "# --- Sample metadata ---"]
        for k, v in spectrum.metadata.items():
            if v is not None:
                header_lines.append(f"#   {k:<25} {v}")

    if fit_section:
        header_lines += fit_section

    header_lines.append("#")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        for line in header_lines:
            f.write(line + "\n")
        spectrum.data.to_csv(f, index=False)


def parse_export_header(path: Path) -> tuple[list[str], dict, dict]:
    """Parse the # comment header written by write_csv_with_provenance().
    Returns (raw_header_lines, provenance_dict, metadata_dict).
    Gracefully returns empty dicts if the file has no such header.
    """
    header_lines = []
    provenance: dict = {}
    metadata: dict = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            header_lines.append(line.rstrip())

    if not header_lines:
        metadata["source_filename"] = path.name
        return header_lines, provenance, metadata

    raw: dict[str, str] = {}
    for line in header_lines:
        content = line.lstrip("# ").strip()
        if not content or content.startswith("---"):
            continue
        if ":" in content:
            k, _, v = content.partition(":")
            raw[k.strip().lower()] = v.strip()

    provenance["signal"] = raw.get("signal", "N/A")
    provenance["background"] = raw.get("background", "N/A")
    provenance["reference"] = raw.get("reference", "N/A")
    provenance["reference_background"] = raw.get("reference background", "N/A")

    history_str = raw.get("history", "")
    provenance["history_list"] = (
        [s.strip() for s in history_str.split("→")]
        if history_str else ["loaded_from_file"]
    )

    is_heterodyne = raw.get("type", "").strip().lower() == "heterodyne"
    provenance["kind"] = "heterodyne" if is_heterodyne else "homodyne"

    def parse_excluded(key: str) -> list[int]:
        v = raw.get(key, "").strip().lower()
        if not v or v == "none":
            return []
        return [int(x) for x in v.split(",") if x.strip()]

    provenance["excluded_frames"] = {
        "signal": parse_excluded("excluded frames signal"),
        "background": parse_excluded("excluded frames background"),
        "reference": parse_excluded("excluded frames reference"),
        "reference_background": parse_excluded("excluded frames reference_background"),
    }

    if is_heterodyne:
        provenance["despike"] = {
            "signal": {"window": raw.get("despike signal window"),
                       "threshold": raw.get("despike signal threshold")},
            "background": {"window": raw.get("despike background window"),
                           "threshold": raw.get("despike background threshold")},
            "reference": {"window": raw.get("despike reference window"),
                          "threshold": raw.get("despike reference threshold")},
            "reference_background": {"window": raw.get("despike reference_background window"),
                                      "threshold": raw.get("despike reference_background threshold")},
        }
        provenance["background_subtraction"] = {
            "bg_offset_degree": raw.get("bg subtraction offset degree"),
            "bg_offset_markers": parse_markers(raw.get("bg subtraction offset markers")),
            "bg_offset": raw.get("bg subtraction offset"),
            "edge_left": raw.get("bg subtraction edge_left_pts"),
            "edge_right": raw.get("bg subtraction edge_right_pts"),
            "bg_smoothing_window": raw.get("bg smoothing window"),
            "bg_smoothing_order": raw.get("bg smoothing order"),
            "sig_smoothing_window": raw.get("signal smoothing window"),
            "sig_smoothing_order": raw.get("signal smoothing order"),
        }
        provenance["fft_filter"] = {
            "window_type": raw.get("fft window_type"),
            "fft_start": raw.get("fft start_pts"),
            "fft_end": raw.get("fft end_pts"),
            "hg_left": raw.get("fft hg_left_pts"),
            "hg_right": raw.get("fft hg_right_pts"),
            "mask_start": raw.get("fft mask_start_pts"),
            "mask_end": raw.get("fft mask_end_pts"),
            "mask_transition": raw.get("fft mask_transition_pts"),
            "mask_factor": raw.get("fft mask_factor"),
        }
        provenance["normalization"] = {
            "sample_exposure_s": raw.get("normalization sample_exposure_s"),
            "reference_exposure_s": raw.get("normalization reference_exposure_s"),
            "phase_correction_deg": raw.get("normalization phase_correction_deg"),
        }
        provenance["upconversion"] = {"wavelength_nm": raw.get("upconversion wavelength_nm")}
        provenance["n_frames"] = raw.get("frames processed")
    else:
        provenance["despike"] = {
            "signal": {"window": raw.get("despike signal window"),
                       "threshold": raw.get("despike signal threshold")},
            "background": {"window": raw.get("despike background window"),
                           "threshold": raw.get("despike background threshold")},
            "reference": {"window": raw.get("despike reference window"),
                          "threshold": raw.get("despike reference threshold")},
            "reference_background": {"window": raw.get("despike reference_background window"),
                                      "threshold": raw.get("despike reference_background threshold")},
        }
        provenance["background_subtraction"] = {
            "applied": raw.get("background subtraction", "").lower() == "applied",
            "signal_offset_degree": raw.get("signal offset degree"),
            "signal_offset_markers": parse_markers(raw.get("signal offset markers")),
            "signal_offset": raw.get("signal offset"),
            "ref_offset_degree": raw.get("ref offset degree"),
            "ref_offset_markers": parse_markers(raw.get("ref offset markers")),
            "ref_offset": raw.get("ref offset"),
        }
        provenance["normalization"] = {
            "applied": raw.get("normalization", "").lower() == "applied",
        }
        provenance["upconversion"] = {
            "applied": raw.get("upconversion", "").lower() == "applied",
            "wavelength_nm": raw.get("wavelength"),
        }

    provenance["fit_json"] = raw.get("fit json")

    metadata["source_filename"] = path.name
    metadata["label"] = raw.get("label", path.stem)
    metadata["exported"] = raw.get("exported")

    in_meta = False
    for line in header_lines:
        content = line.lstrip("#").strip()
        if "sample metadata" in content.lower():
            in_meta = True
            continue
        if in_meta and content.startswith("---"):
            in_meta = False
        if in_meta and ":" in content:
            k, _, v = content.partition(":")
            k = k.strip().lstrip("#").strip()
            if k and not k.startswith("---"):
                metadata[k] = v.strip()

    return header_lines, provenance, metadata
