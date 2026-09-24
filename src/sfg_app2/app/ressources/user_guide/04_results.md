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
  be written to disk. Its legend section lists every entry currently
  in the legend, each with its own checkbox and an editable label —
  untick a row to leave it out of the saved/copied image, or rename it,
  without touching the on-screen plot. This dialog is shared across the
  app, so the same controls are available from any plot that has its
  own "💾 Save plot" button (the Spectra Library, the Fitting tab, ...).

In the Fit components panel, **Hide fit traces from legend** keeps
fit-derived curves on screen but drops them from the legend — handy
once a fit's curves start crowding out the data traces. It's
session-only and resets on restart.

!!! tip "Processing notebooks"
    The Process / Review tab has a matching export: right-click a
    matched set and choose **Export processing notebook…** to get a
    step-by-step walkthrough of that set's homodyne or heterodyne
    pipeline, with your current parameters pre-filled. It embeds the
    four raw files *and* the processing code, and its final cell writes
    a CSV you can load straight back into this tab.

Continue to **Fitting** to fit peaks/lineshapes to a spectrum from
this list.
