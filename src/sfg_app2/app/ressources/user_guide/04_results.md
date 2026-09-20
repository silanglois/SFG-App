# Spectra Library

**Spectra Library** is the working library of every processed spectrum —
whatever you've sent here from **Process / Review**, loaded directly
from a CSV, or exported from **Fitting**. From here you compare,
restyle, annotate, and export.

## Getting spectra in

- **Add spectra from file** loads already-processed spectra directly
  from a CSV, bypassing Load/Match/Process entirely — handy for
  revisiting old exports.
- Spectra sent from **Process / Review** or exported from **Fitting**
  appear here automatically.
- **Sort by metadata** reorders the entry list by a chosen metadata
  field.

## Display controls

- A **colormap** dropdown (a curated shortlist of perceptually
  reasonable colormaps first, then every other matplotlib colormap)
  drives automatic per-curve coloring.
- A **normalization** dropdown lets you rescale displayed curves for
  easier comparison.
- For heterodyne entries, the same component checkboxes as the
  processing panel — **Real, |χ⁽²⁾|² (Homodyne), Phase, Imaginary,
  Show error** — control which parts of each entry are plotted.
- **X axis label / Y axis label / Legend** fields customize plot
  labeling directly.

## Per-curve styling

Right-click an entry for a context menu including:

- **Trace Properties** — opens a per-curve style editor: color, line
  style, marker shape (circle, square, triangle up/down, diamond, X,
  plus, star, or none) and size, line width, opacity, which axis it
  plots against (Phase defaults to a secondary axis, since it's on a
  very different scale in degrees), and a custom label. Select
  multiple entries first and the dialog edits all of them together —
  handy for restyling a whole comparison series in one pass, e.g.
  giving every trace in a set the same marker while keeping each
  one's own color.
- **Review metadata** — same metadata editor as Load/Match.
- **View processing parameters** — a read-only summary of everything
  that went into producing this entry (source filenames, despike
  settings, background subtraction, normalization/up-conversion) —
  the full provenance.
- **Remove**.

## Annotations

The **Annotations...** button opens a dialog for adding free-form
overlays to the plot: vertical lines, horizontal lines, shaded
x-ranges, or text labels — useful for marking known peak positions or
regions of interest in a figure.

## Exporting

- **Export plotted** / **Export all** write CSV files with a
  `#`-comment provenance header — for fit-derived curves, this
  includes the model specification, weighting, and fit statistics as
  well. "Export plotted" covers the ticked spectra, and its label
  shows how many that is.
- Each panel's plot can be saved via a **WYSIWYG export dialog**
  (PNG/TIFF/SVG) with a live preview that matches exactly what will
  be written to disk.

## Export to a notebook

**Export notebook…** writes a Jupyter notebook that reproduces the
current figure, for when you want full control over a plot the app's
controls don't reach.

It is completely self-contained. The ticked spectra are embedded in the
notebook itself and it installs nothing, so it runs as-is on
[Google Colab](https://colab.research.google.com) with no files to
upload. It records which version of the app exported it, when, and
which spectra went into it.

The figure is built across several cells rather than one: a **setup**
cell that makes the axes, **one cell per trace**, and a **decorate**
cell for the axis labels, limits and legend. Each trace cell is a
single `plot()` call with its color, style and label already filled in,
so you can restyle one line, delete it, or copy it to add your own,
without unpicking the rest. Form fields control normalization, offsets,
the phase range and the output format; re-run the trace and decorate
cells after changing them.

Note that the figure uses plain matplotlib styling rather than the
app's current plotting style, and doesn't invert the wavenumber axis
unless you ask it to — the point of the export is a neutral starting
point you control, not a copy of the on-screen look. What each trace
looked like *individually* does travel: colors, line styles and markers
come across as you set them.

If a spectrum carries a fit, its curves are plotted alongside the data
and its parameters are printed with their uncertainties.

!!! tip "Processing notebooks"
    The Process / Review tab has a matching export: right-click a
    matched set and choose **Export processing notebook…** to get a
    step-by-step walkthrough of that set's homodyne or heterodyne
    pipeline, with your current parameters pre-filled. It embeds the
    four raw files *and* the processing code, and its final cell writes
    a CSV you can load straight back into this tab.

Continue to **Fitting** to fit peaks/lineshapes to a spectrum from
this list.
