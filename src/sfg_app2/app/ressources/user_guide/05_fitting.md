# Fitting

The **Fitting** tab fits peaks/lineshapes to a single processed
spectrum. Homodyne data is fit as
`|χ_NR·e^(iφ) + Σ resonance_j(ω)|²` against measured intensity;
heterodyne data is fit as simultaneous real/imaginary fits of the
same complex χ⁽²⁾ against measured Real/Imaginary data. The fit mode
is chosen automatically from the kind of spectrum you load.

> ⚠️ **Experimental:** the Fitting tab is still under active
> development — results, especially from Batch/Sequential/global
> (shared-parameter) fits, should be independently sanity-checked
> rather than relied on as-is.

## The fitting equation

Every model — however many peaks it has — is built from two kinds of
term, summed *coherently* (as complex numbers, before anything is
squared):

- **Non-resonant term** — a single complex constant (flat across the
  whole spectrum):

  <span style="font-style: italic; font-size: 13pt;">χ<sub>NR</sub> = A<sub>NR</sub> e<sup>iφ<sub>NR</sub></sup></span>

- **Resonant term, one per peak *j*.** The only lineshape currently
  implemented is a Lorentzian:

  <span style="font-style: italic; font-size: 13pt;">χ<sub>j</sub>(ω) = A<sub>j</sub> / (ω − ω<sub>j</sub> + iΓ<sub>j</sub>)</span>

  where Γⱼ is the *half*-width-at-half-max. The Parameters table's
  **Width** column is the *full* width instead (the more usual quantity
  to eyeball on a plot), so internally Γⱼ = Width / 2.

These sum to one complex susceptibility:

<span style="font-style: italic; font-size: 13pt;">χ<sub>eff</sub>(ω) = χ<sub>NR</sub> + Σ<sub>j</sub> χ<sub>j</sub>(ω)</span>

which is where **homodyne** and **heterodyne** fitting diverge:

- **Homodyne** only ever measures intensity, so it fits against
  I(ω) = |χ_eff(ω)|² — the model curve you see is this squared
  magnitude, and the fit itself works on the intensity residual.
- **Heterodyne** measures Real(ω) and Imaginary(ω) directly, so it
  fits Re(χ_eff(ω)) and Im(χ_eff(ω)) simultaneously against them — one
  joint least-squares problem, both channels sharing the same
  parameters, rather than two separate fits.

Because the sum happens *before* squaring, cross-terms between peaks
(and between peaks and the non-resonant background) matter — |χ_a + χ_b|²
is not |χ_a|² + |χ_b|², which is why peaks can constructively or
destructively interfere in a homodyne spectrum. It's also why the
Display dock's per-peak "Individual features" curves (each peak's |χⱼ|²
in isolation) are a visual aid for locating a peak, not a literal
decomposition of the total — the real total includes interference terms
that no single curve captures alone.

| Symbol | Parameters-table name | Meaning |
|---|---|---|
| A_NR, φ_NR | Non-resonant → Amplitude, Phase | Non-resonant background amplitude/phase |
| Aⱼ | Peak *j* → Amplitude | Resonant amplitude (sign gives the peak's phase relative to the background) |
| ωⱼ | Peak *j* → Center | Resonance position (cm⁻¹) |
| Γⱼ | Peak *j* → Width, halved | Half-width-at-half-max (the table shows the full width) |

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
without adding one. The initial amplitude/width guess is estimated
from the data itself around the clicked point (not a fixed default),
so a fit is more likely to converge without manual adjustment first.
Hold **Ctrl** while clicking to seed a negative amplitude instead of
positive. Repeat for as many peaks as you need, switching
the lineshape dropdown between clicks if you want a mix of
lineshapes across peaks. An **Include non-resonant background**
checkbox is on by default. The peak table lists every current peak
with a **Remove** action per row.

> Which curves are actually *shown* on the plot is controlled by the
> **Display** dock below, not this table.

## 3. Parameters

An editable table with one row per parameter across the non-resonant
term and every peak — label, value, error, min/max bounds, a
**fixed** checkbox, an **expr** field for writing lmfit expression
constraints between parameters, and a **shared** checkbox (see
**Batch fit** below — it has no effect on a single-spectrum "Run fit").

Rows can optionally be tinted by which peak they belong to — enable
**Preferences → Fitting → Color parameter table by peak** (off by
default; see **Settings & Preferences**).

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
  zoom level. A **Set range to current view** button next to the
  spinboxes copies the plot's current zoomed x-axis into the fit range
  in one click, if you'd rather not type the bounds by hand.
- **Weighting** — for homodyne: None, Statistical (1/√intensity), or
  Measurement error (SEM). For heterodyne: None or Measurement error
  (95% CI, per channel) — there's no statistical option here, since
  shot-noise weighting doesn't apply to signed real/imaginary values.
  Despite the similar names, homodyne's "SEM" and heterodyne's "95% CI"
  are computed differently (one's a plain standard error, the other's
  1.96× that) — see the error/uncertainty glossary in
  **Reference & Tips** if you want the exact formulas.
- **Run fit** — runs the optimization; a quality readout summarizes
  the result (redchi/R²/AIC/BIC and a covariance-based "Value ± stderr"
  per parameter in the table above — the only uncertainty estimate this
  app computes; see **Reference & Tips** for what it is and isn't).
- **Fit templates** — save the current model (lineshapes, peaks,
  constraints, fit range, and weighting) as a named, reusable preset,
  and apply saved templates to new spectra later. **Manage templates...**
  opens a dedicated dialog to rename, delete, or export/import templates
  as a portable `.json` file (e.g. to share with a colleague or back up
  outside the app's own settings folder).
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

**Shared parameters:** check a parameter's **shared** box in the
Parameters table before running a batch fit, and that parameter is
optimized as one value held in common across every spectrum in the
batch — a true joint fit, not fit-then-average — while everything else
stays independent per spectrum as usual. Any shared parameter
automatically turns the next **Run batch fit** into this joint mode;
no separate button. The Multi-fit results table's per-row redchi is
then that spectrum's own diagnostic (shared parameters count as fixed,
not free, for that row), not the one combined redchi for the whole
joint fit shown in the status line above the table. Has no effect on
Sequential fit, whose seeded-chain design is a different thing
entirely.

**Export batch summary (CSV)** writes one summary CSV covering every
row (label, status, redchi/R²/AIC/BIC, and every parameter's
value/stderr), and — in the same export — one additional per-spectrum
CSV per row, in the same folder, with the exact same full
model/weighting/statistics provenance header as the single-spectrum
**Export fit (CSV with provenance)** button.

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
