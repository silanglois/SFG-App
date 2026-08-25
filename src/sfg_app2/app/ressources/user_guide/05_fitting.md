# Fitting

The **Fitting** tab fits peaks/lineshapes to a single processed
spectrum. Homodyne data is fit as
`|χ_NR·e^(iφ) + Σ resonance_j(ω)|²` against measured intensity;
heterodyne data is fit as simultaneous real/imaginary fits of the
same complex χ⁽²⁾ against measured Real/Imaginary data. The fit mode
is chosen automatically from the kind of spectrum you load.

Panels are dockable and rearrangeable; the natural order to work
through them is:

## 1. Data source

Load a spectrum either **from the Spectra Library tab** (pick from a
dropdown, Refresh, then **Load selected**) or **directly from a
file**. A status label always shows what's currently loaded.

## 2. Model

Pick a **lineshape** from the dropdown *before* adding a peak — that
choice is what the next placed peak will use. Then click **Add
peak**: it's a checkable button, so clicking it "arms" placement mode
(the button stays visibly pressed while armed) rather than adding a
peak immediately. With it armed, click anywhere on the plot to drop a
new peak centered at that x-position; right-click cancels placement
without adding one. Repeat for as many peaks as you need, switching
the lineshape dropdown between clicks if you want a mix of
lineshapes across peaks. An **Include non-resonant background**
checkbox is on by default. The peak table lists every current peak
with a **Remove** action per row.

> Which curves are actually *shown* on the plot is controlled by the
> **Display** dock below, not this table.

## 3. Parameters

An editable table with one row per parameter across the non-resonant
term and every peak — label, value, error, min/max bounds, a
**fixed** checkbox, and an **expr** field for writing lmfit
expression constraints between parameters.

## 4. Display

Controls which computed series — Data, Fit total/real/imaginary,
Residual, and per-peak curves (the exact set differs for homodyne vs.
heterodyne) — appear on Plot 1 vs. Plot 2, each with its own color
and line style.

## 5. Fit

- **Fit range** — two spinboxes defining the lower/upper bound of
  what actually gets fit. The app shades that x-range on Plot 1 so
  you can see it at a glance, but that shading is purely a display
  aid — it has nothing to do with the plot's own zoom/pan state.
  Zooming in or out never changes what gets fit, and moving the Fit
  range spinboxes never moves the view; if a fit looks like it's
  ignoring part of your data, check these spinboxes rather than the
  zoom level.
- **Weighting** — for homodyne: None, Statistical (1/√intensity), or
  Measurement error (SEM). For heterodyne: None or Measurement error
  (95% CI, per channel) — there's no statistical option here, since
  shot-noise weighting doesn't apply to signed real/imaginary values.
- **Run fit** — runs the optimization; a quality readout summarizes
  the result.
- **Compute confidence intervals** — a separate, more expensive step
  for rigorous parameter uncertainty.
- **Fit templates** — save the current model (lineshapes, peaks,
  constraints) as a named, reusable preset, and apply saved templates
  to new spectra later.
- **Export fit (CSV with provenance)** — writes the fit result back
  out, including full model/weighting/statistics metadata.

## 6. Batch fit

Fits every spectrum in a list **independently**, using whatever
model/parameters are currently configured in the Model/Parameters/Fit
docks (list order doesn't matter). Pull spectra in from the Spectra
Library and/or load files directly; right-click a row to remove it. All
spectra in a batch must be the same kind (homodyne or heterodyne) —
mixed kinds are rejected with a warning. Progress is shown in a
cancelable dialog.

## 7. Sequential fit

A **seeded chain**: each spectrum in list order is fit starting from
the *previous* spectrum's converged parameters — useful for a series
where peaks drift gradually and a fresh fit might not converge
reliably on its own. Drag rows to reorder the chain.

Mark any row as a **checkpoint** if you want to inspect that spectrum
before the chain continues past it. Concretely: running the chain
fits row 1, feeds its converged result into row 2 as the starting
point, and so on; when it reaches a checkpointed row, it pauses
immediately after that spectrum finishes, loads it into the normal
single-spectrum workspace above (Model / Parameters / Fit docks) so
you can check the fit quality or manually re-run it with different
settings, and waits there — it does **not** resume on its own.
Continuing the run seeds the next row from whatever is currently in
the workspace, including any manual edits you made during the pause.

## 8. Multi-fit results & plots

Both Batch and Sequential runs populate a shared results table with
per-row drill-down, plus dedicated multi-fit, primary, and secondary
plot panels.

Fitted curves can be exported and reloaded into the **Spectra
Library**, where
they appear as additional plottable columns alongside the original
spectrum.
