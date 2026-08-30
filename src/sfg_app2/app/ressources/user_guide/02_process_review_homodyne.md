# Process & Review — Homodyne

Once matched sets are ready, **Process / Review** lets you configure
and preview the processing pipeline before committing a result to
the **Spectra Library**. This page covers the **homodyne** panel; heterodyne
(HD-SFG) data uses a different panel — see **Process & Review —
Heterodyne**.

## Picking what to work on

The list on the left shows every matched set (✓ = complete, ✗ =
incomplete). Choose **Single** or **Compare** view above the list:

- **Single** — work on one set at a time.
- **Compare** — select multiple homodyne sets to preview their
  processing overlaid on the same plot, useful for checking
  consistency across a series before committing.

The shared **up-conversion wavelength** spinbox above the panel
applies to whichever set(s) you have selected.

## Before processing: calibration and reference review

- **▶ Calibrate with polystyrene...** opens a dialog that plots the
  measured polystyrene SFG ratio against its known reference optical
  properties so you can visually align them by adjusting the
  up-conversion wavelength spinbox; clicking OK writes the result back
  into the main up-conversion spinbox. The plot's own x-min/x-max
  controls set which wavenumber range is compared (defaulting to
  2750-3150 cm⁻¹, the usual CH-stretch region) — widen or shift it if
  your reference features fall elsewhere, or click Reset to see the
  whole measured spectrum. An **Auto-detect** button scans for the
  wavelength that best aligns the two curves over whatever range is
  currently shown, as a starting point you can still fine-tune by eye.
- **Review references** plots every reference and its background
  together, with per-curve visibility checkboxes, as a sanity check
  before you trust them in processing.

## Stepping through the pipeline

Use the step selector to move through **Raw → Despiked → Averaged →
BG Subtracted → Normalized**, checking the plot at each stage:

- **Despike parameters** — per component (Sample, Sample BG,
  Reference, Ref BG), set the moving-window size and outlier
  threshold used to detect and remove cosmic-ray spikes. Check **Show
  flagged spikes** to overlay the points currently being flagged (at
  their original raw values) on the Raw/Despiked plot, so you can
  judge the settings before committing to them.

- **Background offset** — sometimes the background trace itself sits
  slightly above or below zero where it shouldn't, and a plain
  subtraction isn't enough to correct that. Switch to a step where
  the background is visible, then click directly on the plot to drop
  a marker at that (x, y) position; click an existing marker again to
  remove it. Place as many markers as you need to trace the shape of
  the offset, or skip the plot entirely and edit the same points via
  the X/Y table below it, using **Add row / Remove selected / Clear
  all**. A polynomial-degree spinbox (0 = constant, 1 = linear, 2+ =
  higher order) fits a least-squares curve through whichever markers
  you've placed, and that curve becomes the offset subtracted from
  the background before the rest of the pipeline runs.

- **Frame exclusion** — per-component checkboxes let you exclude
  specific acquisition frames from averaging (e.g. a frame with a
  known glitch).

## Committing the result

- **▶ Process** runs the pipeline for the current step/parameters.
- **✓ Send to Spectra Library** pushes the final processed spectrum
  into the **Spectra Library** tab.

In **Compare** mode, parameter changes apply to every selected set at
once — except the background offset, which is always a single global
value shared across all sets.

Continue to **Spectra Library** once you've sent a spectrum through, or to
**Settings & Preferences** to adjust matching/plotting defaults.
