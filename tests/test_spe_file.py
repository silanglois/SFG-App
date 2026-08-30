import struct

import numpy as np
import pytest

from sfg_app2.processing.spe_file import load_spe
from sfg_app2.processing.image_file import UnrecognizedImageFormatError

HEADER_SIZE = 4100
OFF_XDIM = 42
OFF_DATATYPE = 108
OFF_YDIM = 656
OFF_XML_FOOTER_OFFSET = 678
OFF_NUM_FRAMES = 1446


def _build_spe_bytes(xdim: int, ydim: int, datatype: int, dtype: np.dtype,
                      wavelengths: np.ndarray | None = None) -> bytes:
    """Builds a minimal, synthetic (but structurally valid) SPE 3.x file
    in-memory: a 4100-byte header with just the fields load_spe() reads,
    one frame of data, and (optionally) an XML footer carrying a
    per-pixel wavelength calibration -- matching the real format
    confirmed against actual LightField-exported files."""
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<h", header, OFF_XDIM, xdim)
    struct.pack_into("<h", header, OFF_YDIM, ydim)
    struct.pack_into("<h", header, OFF_DATATYPE, datatype)
    struct.pack_into("<i", header, OFF_NUM_FRAMES, 1)

    data = (np.arange(xdim * ydim, dtype=np.float64) + 1).reshape(ydim, xdim)
    frame_bytes = data.astype(dtype).tobytes()

    xml_offset = HEADER_SIZE + len(frame_bytes)
    struct.pack_into("<q", header, OFF_XML_FOOTER_OFFSET, xml_offset if wavelengths is not None else 0)

    footer = b""
    if wavelengths is not None:
        wl_csv = ",".join(repr(float(v)) for v in wavelengths)
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<SpeFormat version="3.0" xmlns="http://www.princetoninstruments.com/spe/2009">'
            '<Calibrations>'
            '<WavelengthMapping id="1">'
            f'<Wavelength xml:space="preserve">{wl_csv}</Wavelength>'
            '</WavelengthMapping>'
            '</Calibrations>'
            '</SpeFormat>'
        )
        footer = xml.encode("utf-8")

    return bytes(header) + frame_bytes + footer, data


def test_load_spe_2d_frame_with_wavelength_calibration(tmp_path):
    xdim, ydim = 10, 4
    wavelengths = np.linspace(585.0, 673.0, xdim)
    raw, expected_data = _build_spe_bytes(xdim, ydim, datatype=3, dtype=np.uint16,
                                           wavelengths=wavelengths)
    path = tmp_path / "sample.spe"
    path.write_bytes(raw)

    image = load_spe(path)

    assert image.data.shape == (ydim, xdim)
    np.testing.assert_allclose(image.data, expected_data)
    np.testing.assert_allclose(image.cols, wavelengths)
    np.testing.assert_allclose(image.rows, np.arange(ydim, dtype=float))


def test_load_spe_height_one_frame(tmp_path):
    """Already vertically-binned files (ydim=1) -- e.g. calibration
    spectra -- should still load fine, just as a 1-row image."""
    xdim, ydim = 20, 1
    raw, expected_data = _build_spe_bytes(xdim, ydim, datatype=3, dtype=np.uint16,
                                           wavelengths=None)
    path = tmp_path / "binned.spe"
    path.write_bytes(raw)

    image = load_spe(path)

    assert image.data.shape == (1, xdim)
    np.testing.assert_allclose(image.data, expected_data)
    # no XML footer written -- falls back to plain pixel indices
    np.testing.assert_allclose(image.cols, np.arange(xdim, dtype=float))


def test_load_spe_without_xml_footer_falls_back_to_pixel_indices(tmp_path):
    xdim, ydim = 8, 3
    raw, _ = _build_spe_bytes(xdim, ydim, datatype=2, dtype=np.int16, wavelengths=None)
    path = tmp_path / "no_footer.spe"
    path.write_bytes(raw)

    image = load_spe(path)
    np.testing.assert_allclose(image.cols, np.arange(xdim, dtype=float))


def test_load_spe_float32_datatype(tmp_path):
    xdim, ydim = 6, 2
    raw, expected_data = _build_spe_bytes(xdim, ydim, datatype=0, dtype=np.float32, wavelengths=None)
    path = tmp_path / "float32.spe"
    path.write_bytes(raw)

    image = load_spe(path)
    np.testing.assert_allclose(image.data, expected_data, rtol=1e-6)


def test_load_spe_rejects_truncated_file(tmp_path):
    path = tmp_path / "truncated.spe"
    path.write_bytes(b"\x00" * 100)   # far shorter than the 4100-byte header
    with pytest.raises(UnrecognizedImageFormatError):
        load_spe(path)


def test_load_spe_rejects_bad_datatype(tmp_path):
    xdim, ydim = 5, 5
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<h", header, OFF_XDIM, xdim)
    struct.pack_into("<h", header, OFF_YDIM, ydim)
    struct.pack_into("<h", header, OFF_DATATYPE, 99)   # not a recognized datatype code
    struct.pack_into("<i", header, OFF_NUM_FRAMES, 1)
    path = tmp_path / "bad_datatype.spe"
    path.write_bytes(bytes(header) + b"\x00" * (xdim * ydim * 2))
    with pytest.raises(UnrecognizedImageFormatError):
        load_spe(path)
