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

- **▶ Calibrate...** opens a dialog that plots your measured SFG ratio
  against a known reference so you can align the two by adjusting the
  up-conversion wavelength spinbox; clicking OK writes the result back
  into the main up-conversion spinbox. The plot's own x-min/x-max
  controls set which wavenumber range is compared (defaulting to
  2750-3150 cm⁻¹, the usual CH-stretch region) — widen or shift it if
  your reference features fall elsewhere, or click Reset to see the
  whole measured spectrum. An **Auto-detect** button scans for the
  wavelength that best matches, as a starting point you can still
  fine-tune by eye.

    The **Reference** row picks what to calibrate against:

    | Reference | Use it when |
    |---|---|
    | **Tabulated material** (default: polystyrene) | The material's optical constants are in the refractiveindex.info database. To use a different one, enter its shelf / book / page — the three identifiers that database uses to address an entry. |
    | **Curve from file** | You have the reference absorption as data — a two-column CSV of wavenumber and value. |
    | **Known line positions** | You only know where the peaks *should* be. Type the literature wavenumbers, and the scan lines your measured peaks up with them. |

    The last two need no reference database at all, so calibration
    still works in a build without the `refractiveindex` package.
    Whichever you choose is remembered, so a list of line positions or
    a reference file only has to be entered once.
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

    The two kinds of channel start from different values, because they
    look different: Sample and Reference are real spectra and begin at
    window 50 / threshold 20, while their backgrounds — flatter,
    noisier traces with no spectral features to preserve — begin at
    window 300 / threshold 10. The spin arrows step the window by 10
    and the threshold by 1. These are only starting points; the
    **Show flagged spikes** preview is the thing to judge them by.

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

## Export to a notebook

Right-click a matched set and choose **Export processing notebook…** to
write a Jupyter notebook that walks its pipeline one stage at a time —
despike, average, background subtraction, normalization, upconversion —
plotting every component at each, with your current parameters
pre-filled as editable form fields.

Each stage is two cells: a **compute** cell that does the work, and a
**plot** cell that draws it. That split is what makes the notebook
worth having — swap in your own processing for one stage without
touching how it's plotted, or restyle a figure without going near the
maths. Each cell says which variables the next one needs, so an edit
stays contained. The machinery you don't need to read — the embedded
data, the processing package, the setup — is collapsed behind named
cells you can expand if you want to.

The notebook is completely self-contained: the four raw files *and* the
processing code are embedded, so it runs on
[Google Colab](https://colab.research.google.com) with nothing to upload
and nothing to install. It records which version of the app exported
it, when, and from which files. The final cell writes a CSV with the
usual provenance header, which loads straight back into the **Spectra
Library** via *Add spectra from file*.

This is the way to see exactly what a parameter does, or to hand someone
a complete, runnable record of how a spectrum was processed.

Continue to **Spectra Library** once you've sent a spectrum through, or to
**Settings & Preferences** to adjust matching/plotting defaults.
