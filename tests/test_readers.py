"""Reading instrument files of varying shape into the canonical frame.

The load-bearing assertion in most of these is the same one: whatever
the file looked like, what comes out has columns Frame/Wavelength/
Intensity. That normalisation at the boundary is what stops arbitrary
column names leaking into the ~14 modules downstream that treat those
three names as the data contract.

Run with:
    uv run pytest tests/test_readers.py -v
"""
import numpy as np
import pandas as pd
import pytest

from sfg_app2.processing.data_file import DataFile
from sfg_app2.processing.readers import (
    CANONICAL_COLUMNS, ReadOptions, UnrecognizedFormatError, peek_columns,
    read_spectrum, supported_extensions,
)

WAVELENGTHS = np.linspace(780.0, 800.0, 12)


@pytest.fixture
def write(tmp_path):
    """Write raw text to a file and hand back the path."""
    def _write(name: str, text: str, encoding: str = "utf-8"):
        path = tmp_path / name
        path.write_text(text, encoding=encoding)
        return path
    return _write


def _long_frame(sep: str = ",", decimal: str = ".") -> str:
    rows = [sep.join(["Frame", "Wavelength", "Intensity"])]
    for wl in WAVELENGTHS:
        values = ["1", f"{wl:.3f}", f"{wl * 2:.3f}"]
        if decimal != ".":
            values = [v.replace(".", decimal) for v in values]
        rows.append(sep.join(values))
    return "\n".join(rows) + "\n"


# ── The default path must not change ──────────────────────────────────────

def test_a_plain_comma_csv_still_loads(write):
    df = read_spectrum(write("plain.csv", _long_frame()))
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == len(WAVELENGTHS)


def test_wide_format_still_melts_to_long(write):
    header = "Wavelength,1,2\n"
    body = "".join(f"{wl:.3f},{wl:.1f},{wl * 2:.1f}\n" for wl in WAVELENGTHS)
    df = read_spectrum(write("wide.csv", header + body))
    assert set(df["Frame"]) == {1, 2}
    assert list(df.columns) == list(CANONICAL_COLUMNS)


# ── Wide format: frames as columns rather than a Frame column ─────────────

def _wide(headers, sep=","):
    rows = [sep.join(["Wavelength", *headers])]
    for wl in WAVELENGTHS:
        rows.append(sep.join([f"{wl:.3f}"]
                             + [f"{wl * (i + 2):.3f}" for i in range(len(headers))]))
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize("headers, expected", [
    (("1", "2"), {1, 2}),
    (("Frame 1", "Frame 2"), {1, 2}),       # the labels exports actually use
    (("scan1", "scan2"), {1, 2}),
    (("S1", "S2"), {1, 2}),
    (("3", "7"), {3, 7}),                   # numbering need not be 1..N
])
def test_frame_columns_are_identified_from_their_headers(write, headers, expected):
    df = read_spectrum(write("wide.csv", _wide(headers)))
    assert set(df["Frame"]) == expected
    assert len(df) == len(WAVELENGTHS) * len(headers)


def test_a_column_that_is_not_a_frame_is_refused_rather_than_guessed(write):
    """A wide file can carry a dark reference or a timestamp beside its
    frames. Numbering that by position would silently import it as real
    data, which is worse than refusing."""
    with pytest.raises(UnrecognizedFormatError, match="Dark"):
        read_spectrum(write("wide.csv", _wide(("1", "2", "Dark"))))


def test_naming_the_frame_columns_resolves_the_ambiguity(write):
    df = read_spectrum(write("wide.csv", _wide(("1", "2", "Dark"))),
                       ReadOptions(frame_columns=["1", "2"]))
    assert set(df["Frame"]) == {1, 2}


def test_a_mistyped_frame_column_says_what_is_actually_there(write):
    with pytest.raises(UnrecognizedFormatError, match="aren't in the file"):
        read_spectrum(write("wide.csv", _wide(("1", "2"))),
                      ReadOptions(frame_columns=["nope"]))


def test_wide_format_composes_with_the_other_options(write):
    """Frames-as-columns and a mapped wavelength column and a separator
    all at once -- each is handled in a different place, so their
    interaction is worth pinning."""
    text = _wide(("Frame 1", "Frame 2"), sep=";").replace("Wavelength", "lambda (nm)")
    df = read_spectrum(write("wide.csv", text), ReadOptions(
        delimiter=";", columns={"Wavelength": "lambda (nm)"}))
    assert set(df["Frame"]) == {1, 2}
    assert list(df.columns) == list(CANONICAL_COLUMNS)


# ── New: separators, decimals, preambles, encodings ───────────────────────

@pytest.mark.parametrize("sep", [";", "\t", "|"])
def test_other_separators_are_picked_up_without_being_configured(write, sep):
    """Falling back to sniffing means a semicolon export just works,
    rather than failing for a reason the user can't see."""
    df = read_spectrum(write("other.csv", _long_frame(sep=sep)))
    assert len(df) == len(WAVELENGTHS)


def test_an_explicit_separator_is_used_verbatim(write):
    df = read_spectrum(write("semi.txt", _long_frame(sep=";")),
                       ReadOptions(delimiter=";"))
    assert len(df) == len(WAVELENGTHS)


def test_decimal_commas_are_read_as_numbers(write):
    """European instrument exports. Read as text these become object
    dtype and every downstream numeric operation breaks."""
    path = write("euro.csv", _long_frame(sep=";", decimal=","))
    df = read_spectrum(path, ReadOptions(delimiter=";", decimal=","))
    assert pd.api.types.is_numeric_dtype(df["Wavelength"])
    assert df["Wavelength"].iloc[0] == pytest.approx(WAVELENGTHS[0], abs=1e-3)


def test_an_instrument_preamble_can_be_skipped(write):
    preamble = "# Spectrometer v2.1\nAcquired: 2024-01-01\nOperator: nobody\n"
    path = write("preamble.txt", preamble + _long_frame())
    with pytest.raises(UnrecognizedFormatError):
        read_spectrum(path)
    df = read_spectrum(path, ReadOptions(skiprows=3))
    assert len(df) == len(WAVELENGTHS)


def test_a_non_utf8_encoding_can_be_named(write):
    path = write("latin.csv", _long_frame(), encoding="latin-1")
    assert len(read_spectrum(path, ReadOptions(encoding="latin-1"))) == len(WAVELENGTHS)


def test_txt_and_dat_extensions_are_supported(write):
    for ext in (".txt", ".dat", ".asc", ".tsv"):
        assert ext in supported_extensions()
    assert len(read_spectrum(write("data.dat", _long_frame()))) == len(WAVELENGTHS)


def test_an_unknown_extension_is_still_attempted(write):
    """Instruments label plain text with all sorts of suffixes; refusing
    on the name alone would be worse than trying the parse."""
    assert len(read_spectrum(write("data.spectrum", _long_frame()))) == len(WAVELENGTHS)


# ── Column mapping: the alternative to a column-agnostic pipeline ─────────

def test_arbitrary_column_names_map_onto_the_canonical_ones(write):
    text = "frame no;wavelength (nm);counts\n" + "".join(
        f"1;{wl:.3f};{wl * 2:.3f}\n" for wl in WAVELENGTHS)
    path = write("named.csv", text)

    with pytest.raises(UnrecognizedFormatError):
        read_spectrum(path)

    df = read_spectrum(path, ReadOptions(delimiter=";", columns={
        "Frame": "frame no", "Wavelength": "wavelength (nm)", "Intensity": "counts",
    }))
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert df["Intensity"].iloc[0] == pytest.approx(WAVELENGTHS[0] * 2, abs=1e-3)


def test_a_file_with_no_frame_column_becomes_a_single_frame(write):
    """Wavelength + Intensity and nothing else is a single spectrum, and
    is what mapping columns by hand usually produces. It must not fall
    into the wide-format branch, which would try to melt an "Intensity"
    column into a column of the same name."""
    text = "Wavelength,Intensity\n" + "".join(
        f"{wl:.3f},{wl * 2:.3f}\n" for wl in WAVELENGTHS)
    df = read_spectrum(write("single.csv", text))
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert set(df["Frame"]) == {1}
    assert len(df) == len(WAVELENGTHS)


def test_mapping_a_column_that_is_not_there_says_so(write):
    path = write("named.csv", _long_frame())
    with pytest.raises(UnrecognizedFormatError, match="isn't in the file"):
        read_spectrum(path, ReadOptions(columns={"Intensity": "nope"}))


def test_peek_columns_reports_the_files_own_headers(write):
    """What a mapping dialog shows after a file fails to load."""
    text = "frame no;wavelength (nm);counts\n1;780.0;2.0\n"
    assert peek_columns(write("named.csv", text)) == [
        "frame no", "wavelength (nm)", "counts"]


def test_peek_columns_is_empty_for_something_unreadable(write):
    assert peek_columns(write("junk.csv", "")) == []


# ── DataFile goes through the registry ────────────────────────────────────

def test_datafile_accepts_read_options(write):
    text = "wl;counts\n" + "".join(f"{wl:.3f};{wl * 2:.3f}\n" for wl in WAVELENGTHS)
    path = write("mapped.csv", text)
    data_file = DataFile(path, read_options=ReadOptions(
        delimiter=";", columns={"Wavelength": "wl", "Intensity": "counts"}))
    # No Frame column in the file: it's wide format, one frame per column,
    # so "counts" becomes frame 1 once Wavelength is identified.
    assert set(data_file.data.columns) >= {"Frame", "Wavelength", "Intensity"}
    assert data_file.n_frames >= 1


# ── Persisted options ─────────────────────────────────────────────────────

def test_settings_default_to_reading_an_ordinary_csv():
    """The premise of the whole feature: a user who never opens the
    dialog gets exactly the behaviour the app always had."""
    from sfg_app2.app.utils.file_format_settings import FileFormatSettings

    settings = FileFormatSettings()
    assert settings.is_default()
    assert settings.options.to_dict() == ReadOptions().to_dict()


def test_settings_round_trip_through_disk():
    from sfg_app2.app.utils.file_format_settings import FileFormatSettings

    saved = FileFormatSettings()
    assert saved.set_options(ReadOptions(
        delimiter=";", decimal=",", encoding="latin-1", skiprows=3,
        columns={"Wavelength": "wl"}))

    reloaded = FileFormatSettings()
    assert reloaded.options.delimiter == ";"
    assert reloaded.options.decimal == ","
    assert reloaded.options.encoding == "latin-1"
    assert reloaded.options.skiprows == 3
    assert reloaded.options.columns == {"Wavelength": "wl"}
    assert not reloaded.is_default()


def test_a_realistic_awkward_instrument_export(write):
    """Everything at once: a settings preamble, semicolons, decimal
    commas, latin-1, and the instrument's own column names."""
    text = ("Spectrometer XYZ v3\nOperator: nobody\n\n"
            "wavelength (nm);counts\n"
            + "".join(f"{wl:.3f};{wl * 2:.3f}\n".replace(".", ",")
                      for wl in WAVELENGTHS))
    path = write("instrument.csv", text, encoding="latin-1")

    with pytest.raises(UnrecognizedFormatError):
        read_spectrum(path)

    df = read_spectrum(path, ReadOptions(
        delimiter=";", decimal=",", encoding="latin-1", skiprows=3,
        columns={"Wavelength": "wavelength (nm)", "Intensity": "counts"}))
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert df["Wavelength"].iloc[0] == pytest.approx(WAVELENGTHS[0], abs=1e-3)


# ── The dialog ────────────────────────────────────────────────────────────
# Constructing it at all is most of the value: a NameError in a dialog
# nobody instantiates in tests is invisible until a user opens it, which
# is exactly how a crash shipped here once before.

def test_the_import_dialog_builds_and_round_trips_its_options(qtbot, write):
    from sfg_app2.app.dialogs.file_format_dialog import FileFormatDialog

    options = ReadOptions(delimiter=";", decimal=",", encoding="latin-1",
                          skiprows=2, columns={"Wavelength": "wl"},
                          frame_columns=["a", "b"])
    dialog = FileFormatDialog(options, sample_path=write("s.csv", _long_frame()))
    qtbot.addWidget(dialog)
    assert dialog.options().to_dict() == options.to_dict()


def test_the_dialog_preview_explains_a_file_it_cannot_read(qtbot, write):
    from sfg_app2.app.dialogs.file_format_dialog import FileFormatDialog

    path = write("wide.csv", _wide(("1", "2", "Dark")))
    dialog = FileFormatDialog(ReadOptions(), sample_path=path)
    qtbot.addWidget(dialog)
    assert "Dark" in dialog._preview.toPlainText()

    dialog._frame_columns.setText("1, 2")
    assert "2 frame(s)" in dialog._preview.toPlainText()


def test_unreadable_files_still_raise_the_error_callers_catch(write):
    """UnrecognizedFormatError moved to readers.py but is caught by name
    throughout the app -- importing it from data_file must keep working."""
    from sfg_app2.processing.data_file import UnrecognizedFormatError as FromDataFile
    from sfg_app2.processing.readers import UnrecognizedFormatError as FromReaders
    assert FromDataFile is FromReaders

    with pytest.raises(FromDataFile):
        DataFile(write("bad.csv", "nothing,useful\n1,2\n"))
