"""Tests for the generic plotting-notebook export (any SpectrumPlotWidget).

`build_payload()`/`build()` take plain matplotlib objects and dicts, so
most of this needs no Qt at all -- only the "handler" tests at the
bottom drive the real button through a live SpectrumPlotWidget.
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from sfg_app2.app.utils import notebook_export, notebook_plotting


# ── build_payload() ──────────────────────────────────────────────────────

@pytest.fixture
def two_line_axes():
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [4, 5, 6], label="alpha", color="tab:blue")
    ax.axhline(1.0)   # overlay placeholder -- must not become a trace
    ax2 = ax.twinx()
    ax2.plot([1, 2, 3], [7, 8, 9], label="beta", color="tab:orange")
    yield ax, ax2
    plt.close(fig)


def test_build_payload_recovers_both_real_lines(two_line_axes):
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)

    assert len(payload["traces"]) == 2
    by_label = {t["label"]: t for t in payload["traces"]}
    assert set(by_label) == {"alpha", "beta"}
    assert by_label["alpha"]["secondary"] is False
    assert by_label["beta"]["secondary"] is True


def test_build_payload_excludes_axhline_overlay(two_line_axes):
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)
    # Only "alpha"/"beta" -- the axhline never shows up as a third trace.
    assert len(payload["traces"]) == 2


def test_build_payload_csv_round_trips(two_line_axes):
    import base64, gzip, io
    import pandas as pd

    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)
    alpha = next(t for t in payload["traces"] if t["label"] == "alpha")

    df = pd.read_csv(io.StringIO(alpha["csv"]))
    assert list(df["x"]) == [1.0, 2.0, 3.0]
    assert list(df["y"]) == [4.0, 5.0, 6.0]

    # Also round-trips through the same gzip+base64 encoding build() uses.
    blob = notebook_export.encode_text(alpha["csv"])
    decoded = gzip.decompress(base64.b64decode(blob)).decode("utf-8")
    assert decoded == alpha["csv"]


def test_build_payload_unlabeled_line_has_empty_label():
    fig, ax = plt.subplots()
    ax.plot([1, 2], [3, 4])   # no label -> matplotlib's auto "_child0"
    payload = notebook_plotting.build_payload(ax)
    plt.close(fig)

    assert len(payload["traces"]) == 1
    assert payload["traces"][0]["label"] == ""


def test_build_payload_without_a_twin_axis():
    fig, ax = plt.subplots()
    ax.plot([1, 2], [3, 4], label="solo")
    payload = notebook_plotting.build_payload(ax)
    plt.close(fig)

    assert len(payload["traces"]) == 1
    assert payload["y_label2"] is None


# ── build() ───────────────────────────────────────────────────────────────

def test_built_notebook_is_valid_json_with_colab_metadata(two_line_axes, tmp_path):
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2, output_name="demo")
    nb = notebook_plotting.build(payload)

    path = tmp_path / "demo.ipynb"
    notebook_export.write_notebook(nb, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["nbformat"] == 4
    assert loaded["metadata"]["kernelspec"]["name"] == "python3"


def test_built_notebook_installs_nothing(two_line_axes):
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)
    nb = notebook_plotting.build(payload)
    code = "".join("".join(c["source"]) for c in nb["cells"]
                   if c["cell_type"] == "code")
    assert "pip install" not in code


def test_built_notebook_never_has_a_fit_section(two_line_axes):
    """The generic exporter is fully uniform -- no Spectra-Library-only
    fit-parameters concept survives here, unlike the old exporter."""
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)
    sources = "".join("".join(c["source"]) for c in notebook_plotting.build(payload)["cells"])
    assert "Fit parameters" not in sources


def test_built_notebook_has_one_editable_cell_per_line(two_line_axes):
    ax, ax2 = two_line_axes
    payload = notebook_plotting.build_payload(ax, ax2)
    cells = notebook_plotting.build(payload)["cells"]
    trace_cells = [c for c in cells if c["cell_type"] == "code"
                   and "".join(c["source"]).startswith("# TRACE")]
    assert len(trace_cells) == 2


# ── The export handler ───────────────────────────────────────────────────

@pytest.fixture
def silent_dialogs(monkeypatch, tmp_path):
    """Stub the file picker and the confirmation/warning popups."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    target = tmp_path / "exported.ipynb"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "Jupyter Notebook (*.ipynb)")),
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    return target


@pytest.fixture
def plot_widget(qtbot):
    from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget

    widget = SpectrumPlotWidget()
    qtbot.addWidget(widget)
    return widget


def test_export_notebook_handler_writes_a_notebook(plot_widget, silent_dialogs):
    plot_widget.plot([1, 2, 3], [4, 5, 6], label="alpha")

    plot_widget._on_export_notebook()

    assert silent_dialogs.exists(), "handler ran but wrote nothing"
    nb = json.loads(silent_dialogs.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4


def test_export_notebook_handler_refuses_an_empty_plot(plot_widget, silent_dialogs):
    plot_widget._on_export_notebook()
    assert not silent_dialogs.exists()


# ── End to end ────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_generated_notebook_runs_end_to_end(plot_widget, tmp_path):
    """Generate a notebook from a live two-line, twin-axis plot and
    execute it -- a notebook that merely parses proves nothing."""
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")

    plot_widget.plot([1, 2, 3, 4], [1, 4, 9, 16], label="data", color="tab:blue")
    ax2 = plot_widget.secondary_axis()
    ax2.plot([1, 2, 3, 4], [4, 3, 2, 1], label="phase", color="tab:red")
    plot_widget.set_labels(xlabel="x", ylabel="y", ylabel2="y2", title="demo")

    payload = notebook_plotting.build_payload(
        plot_widget.ax, plot_widget.ax2, output_name=str(tmp_path / "figure"),
    )
    path = tmp_path / "exported.ipynb"
    notebook_export.write_notebook(notebook_plotting.build(payload), path)

    nb = nbformat.read(path, as_version=4)
    nbclient.NotebookClient(
        nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(tmp_path)}},
    ).execute()

    errors = [o for cell in nb.cells for o in cell.get("outputs", [])
              if o.get("output_type") == "error"]
    assert not errors, errors[0].get("evalue")

    figures = [o for cell in nb.cells for o in cell.get("outputs", [])
               if "image/png" in o.get("data", {})]
    assert figures, "notebook ran but rendered no figure"
    assert (tmp_path / "figure.png").exists(), "save cell wrote nothing"
