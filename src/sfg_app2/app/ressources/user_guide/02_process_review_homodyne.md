# Process & Review — Homodyne

Once matched sets are ready, **Process / Review** lets you configure
and preview the processing pipeline before committing a result to
**Results**. This page covers the **homodyne** panel; heterodyne
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

- **▶ Calibrate with polystyrene...** fits a measured polystyrene SFG
  spectrum against its known reference optical properties to derive
  a corrected up-conversion wavelength, and writes the result back
  into the up-conversion spinbox for you.
- **Review references** plots every reference and its background
  together, with per-curve visibility checkboxes, as a sanity check
  before you trust them in processing.

## Stepping through the pipeline

Use the step selector to move through **Raw → Despiked → Averaged →
BG Subtracted → Normalized**, checking the plot at each stage:

- **Despike parameters** — per component (Sample, Sample BG,
  Reference, Ref BG), set the moving-window size and outlier
  threshold used to detect and remove cosmic-ray spikes.

- **Background offset** — click directly on the plot (while viewing
  an appropriate step) to place markers, or edit an X/Y table
  directly with **Add row / Remove selected / Clear all**. A
  polynomial-degree spinbox (0 = constant, 1 = linear, 2+ = higher
  order) controls the least-squares fit through your markers, which
  becomes the offset applied before background subtraction.

  ![Placing background-offset markers on the plot](images/homodyne_bg_offset.png)

- **Frame exclusion** — per-component checkboxes let you exclude
  specific acquisition frames from averaging (e.g. a frame with a
  known glitch).

## Committing the result

- **▶ Process** runs the pipeline for the current step/parameters.
- **✓ Send to Results** pushes the final processed spectrum into the
  **Results** tab.

In **Compare** mode, parameter changes apply to every selected set at
once — except the background offset, which is always a single global
value shared across all sets.

Continue to **Results** once you've sent a spectrum through, or to
**Settings & Preferences** to adjust matching/plotting defaults.
