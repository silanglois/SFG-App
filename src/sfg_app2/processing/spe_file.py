from __future__ import annotations
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from sfg_app2.processing.image_file import CCDImage, UnrecognizedImageFormatError

# Princeton Instruments LightField ".spe" files (SPE format version 3.x)
# keep a fixed 4100-byte binary header (for WinSpec/SPE-2.x backward
# compatibility) in front of the raw frame data, followed by an XML
# footer whose byte offset is itself stored in that header. Confirmed
# against real LightField-exported files (header/version/offsets below).
_HEADER_SIZE = 4100
_SPE_NS = "{http://www.princetoninstruments.com/spe/2009}"

# offsets within the legacy 4100-byte header, little-endian
_OFF_XDIM = 42                  # int16
_OFF_DATATYPE = 108              # int16: 0=float32, 1=int32, 2=int16, 3=uint16
_OFF_YDIM = 656                  # int16
_OFF_XML_FOOTER_OFFSET = 678     # int64 -- byte offset of the XML footer
_OFF_NUM_FRAMES = 1446           # int32

_DATATYPE_DTYPES = {
    0: np.dtype("<f4"),
    1: np.dtype("<i4"),
    2: np.dtype("<i2"),
    3: np.dtype("<u2"),
}


def _read(buf: bytes, offset: int, fmt: str):
    return struct.unpack_from(fmt, buf, offset)[0]


def load_spe(path: str | Path) -> CCDImage:
    """Parses a Princeton Instruments LightField .spe (SPE 3.x) file
    into the app's existing CCDImage shape (rows=ydim, cols=xdim). The
    column axis is the file's own per-pixel wavelength calibration
    (<Calibrations><WavelengthMapping><Wavelength>, in the XML footer)
    when present, falling back to plain pixel indices otherwise.

    Only the first frame is used when the file has multiple frames --
    combining frames (averaging/summing) is a physically meaningful
    choice that shouldn't be assumed silently; multi-frame .spe support
    is a possible future extension.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise UnrecognizedImageFormatError(f"{path.name}: could not read file ({e})") from e

    if len(raw) < _HEADER_SIZE:
        raise UnrecognizedImageFormatError(f"{path.name}: too small to be an SPE file")

    header = raw[:_HEADER_SIZE]
    try:
        xdim = _read(header, _OFF_XDIM, "<h")
        ydim = _read(header, _OFF_YDIM, "<h")
        datatype = _read(header, _OFF_DATATYPE, "<h")
        num_frames = _read(header, _OFF_NUM_FRAMES, "<i")
        xml_offset = _read(header, _OFF_XML_FOOTER_OFFSET, "<q")
    except struct.error as e:
        raise UnrecognizedImageFormatError(f"{path.name}: malformed SPE header ({e})") from e

    dtype = _DATATYPE_DTYPES.get(datatype)
    if dtype is None or xdim <= 0 or ydim <= 0 or num_frames <= 0:
        raise UnrecognizedImageFormatError(
            f"{path.name}: unrecognized SPE header fields "
            f"(xdim={xdim}, ydim={ydim}, datatype={datatype}, num_frames={num_frames})"
        )

    frame_bytes = xdim * ydim * dtype.itemsize
    frame0_end = _HEADER_SIZE + frame_bytes
    if len(raw) < frame0_end:
        raise UnrecognizedImageFormatError(
            f"{path.name}: file too short for its declared frame size "
            f"(need {frame0_end} bytes, have {len(raw)})"
        )

    data = np.frombuffer(raw, dtype=dtype, count=xdim * ydim, offset=_HEADER_SIZE)
    data = data.reshape(ydim, xdim).astype(float)

    cols = _wavelength_axis_from_xml(raw, xml_offset, xdim)
    if cols is None:
        cols = np.arange(xdim, dtype=float)
    rows = np.arange(ydim, dtype=float)

    return CCDImage(path, data, rows, cols)


def _wavelength_axis_from_xml(raw: bytes, xml_offset: int, xdim: int):
    """Pulls the per-pixel wavelength calibration array out of the SPE
    3.x XML footer, if present and well-formed. Returns None (falling
    back to plain pixel indices) rather than raising -- the image is
    still perfectly usable without it."""
    if xml_offset <= 0 or xml_offset >= len(raw):
        return None
    try:
        footer = raw[xml_offset:]
        end_marker = b"</SpeFormat>"
        end_idx = footer.find(end_marker)
        if end_idx != -1:
            footer = footer[:end_idx + len(end_marker)]
        root = ET.fromstring(footer.decode("utf-8", errors="ignore"))
        wavelength_el = root.find(f".//{_SPE_NS}WavelengthMapping/{_SPE_NS}Wavelength")
        if wavelength_el is None or not wavelength_el.text:
            return None
        values = np.array(
            [float(v) for v in wavelength_el.text.strip().split(",")], dtype=float,
        )
        if len(values) != xdim:
            return None
        return values
    except Exception:
        return None
