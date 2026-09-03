# Reference & Tips

Miscellaneous behavior that's useful to understand but doesn't belong
to any one tab.

## The phase-display toggle, in depth

Anywhere you see a **Phase range** dropdown (Process/Review's HD-SFG
panel, and Spectra Library when plotting a heterodyne entry's Phase
component), you're choosing between two display windows:
**[−180°, 180°]** or **[0°, 360°)**.

This is not just a relabeling of the y-axis. Phase data naturally
wraps — a continuously-varying phase that drifts past the edge of
whichever window you're displaying has to "jump" back in. Naively
just folding the numbers into the chosen window (with a plain modulo)
creates a spurious near-vertical line at the wrap point, because the
plot doesn't know that jump isn't real data.

Concretely: suppose the real, physical phase drifts smoothly from
170° up to 190° as you scan across a resonance. In the
**[−180°, 180°]** window, 190° doesn't exist — it has to be displayed
as −170° instead (190 − 360). Naively connecting the dots would make
the curve appear to plunge from +170° straight down to −170° at that
point, even though nothing physically unusual happens there — so a
correct plot has to insert a break there instead of a connecting
line. In the **[0°, 360°)** window, that same 170°→190° drift needs
no correction or break at all — it draws as one smooth, continuous
rise, because that window's seam is nowhere nearby. The reverse can
just as easily happen: a drift from 10° down through 0° into −10°
(i.e. 350°) needs a break in the **[0°, 360°)** window, but draws
through cleanly in **[−180°, 180°]**. Which window needs the break
depends entirely on where the data happens to sit, not on the data
itself.

SFG-App handles this correctly in both directions: it reconstructs
the true continuous phase first, then folds it into whichever window
you've selected, and inserts a break in the plotted line **only**
exactly where the continuous phase crosses *that window's own* seam
— never elsewhere, and never missing one where it's genuinely needed.
In other words, switching this dropdown recomputes exactly where the
line should show a gap, so the data reads correctly no matter which
convention you display it in. There's no global setting for this;
it's chosen per open panel.

## Where the heterodyne error bars ("95% CI") actually come from

The HD-SFG Normalization step's **Show errors** checkbox (and the
Spectra Library's error bands for heterodyne entries) come from a
per-frame re-analysis, not an analytic noise-propagation formula: each
raw acquisition frame is pushed independently through the exact same
background subtraction, edge window, FFT filter, and reference used to
produce the main result, and at every wavenumber point, how much those
frames *disagree* with each other becomes the error estimate. No
assumptions about shot noise or detector characteristics are needed —
it's a direct empirical measure of how reproducible the measurement
actually was.

Concretely, the half-width shown is `1.96 × std(across frames) / √n` —
a 95% confidence interval on the mean, under the normal approximation.
Two caveats worth knowing:
- It uses a **fixed z = 1.96** rather than a proper small-sample
  Student-t critical value. That's only exactly right as the frame
  count grows large; with only a handful of frames (common in SFG —
  say 3–10), the true 95% critical value is meaningfully bigger (e.g.
  ≈4.30 for 3 frames, ≈2.78 for 5), so the displayed band is somewhat
  **narrower than a rigorous 95% CI** would be at low frame counts.
- It measures spread using NumPy's default (`ddof=0`, dividing by N)
  rather than the Bessel-corrected sample standard deviation
  (`ddof=1`, dividing by N−1) — a small further underestimate,
  more noticeable at low N.
- It only captures **signal**-frame-to-frame variability — the
  reference, background, and reference background are never tracked
  per-frame (only ever averaged once), so the true total uncertainty
  is understated to whatever extent those also fluctuate frame to
  frame.

**Why Real/Imaginary have one unambiguous value, but Phase and
|χ⁽²⁾|² needed a deliberate choice:** every step of the pipeline up to
normalization (interpolation, smoothing, background subtraction,
windowing, FFT/mask/iFFT, dividing by the reference) is linear, so
"average the raw frames, then run the pipeline once" and "run the
pipeline on each frame, then average the results" arrive at exactly
the same complex χ⁽²⁾ — not just approximately, mathematically
identical. Phase and homodyne intensity (|χ|²), though, are *nonlinear*
functions of χ, so those two orders of operation genuinely disagree —
and one of them is measurably wrong: averaging each frame's own
|χ|² **systematically overestimates** the true intensity (a basic
statistical fact — for any noisy quantity, the average of the
squared-magnitudes is always ≥ the squared-magnitude of the average,
with equality only when there's zero frame-to-frame noise). Averaging
each frame's own phase angle directly is also risky, independent of
that bias — it can distort badly if frames scatter across the ±180°
seam. SFG-App avoids both problems by always deriving phase and
homodyne intensity from the single, coherently-averaged χ⁽²⁾ (never
by averaging per-frame phase/intensity values separately) — the error
bars still come from the per-frame spread, they just don't change
which central value is displayed.

**A quick glossary**, since "error"/"CI"/"uncertainty" mean genuinely
different things in different corners of this app:

| Where | What it actually is |
|---|---|
| Heterodyne "Show errors" (this section) | Empirical 95% CI from per-frame spread, pre-fit — describes measurement reproducibility. |
| Homodyne's "Measurement error (SEM)" fit weighting | A plain standard error of the mean (`std/√n`, **no** 1.96 factor, despite the similar name) from `average_spectrum()`'s per-wavelength frame statistics — and that std uses the *opposite* convention (`ddof=1`) from the heterodyne CI above. |
| Fitting tab's parameter-table "Value ± stderr" | Always shown after **Run fit** — `lmfit`'s asymptotic covariance-matrix estimate. Post-fit: describes how uncertain a *fitted parameter* is, unrelated to either measurement-spread quantity above. This is the only per-parameter uncertainty this app computes -- there is no separate profile-likelihood/confidence-interval step. |
| Multi-fit results' trend-plot error bars | The same parameter `stderr` as above, just plotted across a batch of independent fits. |

## Dockable panels & the View menu

Most tabs are built from several independent dock panels (parameter
panels, tables, plots) that can be dragged, resized, floated
out of the main window, or closed. If a panel goes missing, open the
**View** menu — it lists a show/hide toggle for every dock belonging
to the currently active tab, grouped into submenus that mirror the
tab's own layout.

## The Window menu

Every floating window you've opened — raw-file previews from
Load/Match, CCD image viewers — is tracked here. Use it to jump back
to (raise) a specific window instead of hunting for it among other
application windows, or use **Close all windows** to clean them all
up at once.

## Loading a CCD image directly

**File → Load image...** opens a CCD image — a CSV grid, or a
Princeton Instruments LightField `.spe` file (its own per-pixel
wavelength calibration is used for the column axis when present) — in
its own floating image window, entirely independent of the spectral
matching/processing pipeline — useful for a quick look at a raw camera
frame without it needing to be part of a matched set.

## CSV export & provenance

Every CSV this app writes (from the Spectra Library's export buttons,
or Fitting's export) includes a `#`-comment header recording exactly
how that data was produced — source filenames, per-component despike
settings, background subtraction and normalization/up-conversion
parameters, and for fit-derived curves, the full model specification,
weighting, and fit statistics. You can always trace an exported file
back to exactly what produced it, and the Spectra Library's **View
processing parameters** context-menu action shows the same
information without needing to open the file.
