# Process & Review — Heterodyne (HD-SFG)

Matched sets classified as **heterodyne** use a different panel from
homodyne data, laid out as a central plot surrounded by several
dockable parameter panels. See **Process & Review — Homodyne** for
the homodyne equivalent.

## Step selector

Move through **Raw → Despiked → Averaged → BG Subtraction → FFT +
Filter → iFFT → Normalization** to inspect the effect of each stage:

## Despike & frame exclusion

Same idea as the homodyne panel: per-component despike window/
threshold, a **Show flagged spikes** checkbox to preview which points
the current settings would flag, and per-component frame exclusion,
each in their own dock. The starting values differ by channel for the
same reason as in homodyne — Sample and Reference at window 50 /
threshold 20, their backgrounds at window 300 / threshold 10.

## Background subtraction + edge window

This dock combines two things:

- **Edge low / Edge high (points)** — an edge-taper window applied to
  the background-subtracted delta before it goes into the FFT step.
- **BG offset degree** and the same **click-to-place-marker** /
  editable X/Y table mechanism as the homodyne panel's background
  offset — click on the plot in "Signal + Background" view to add a
  marker, click an existing marker to remove it, or edit the table
  directly (the same interaction shown in **Process & Review —
  Homodyne**'s background-offset section).

## FFT filter window parameters

This is the heart of the HD-SFG pipeline: it isolates the
signal-of-interest in frequency space before inverse-transforming
back. The **Type** dropdown controls the filter's shape:

| Type | Name | Behavior |
|---|---|---|
| 1 | Box-Car | Hard cutoff at the start/end points — no tapering. |
| 2 | Box-Car + Happ-Genzel | A soft taper on the left edge only. |
| 3 | Double Happ-Genzel (**default**) | A soft taper on both edges. |
| 4 | Masking Happ-Genzel | Type 2's taper, plus an attenuated notch region inside the passband. |

A hard cutoff (type 1) is the simplest to reason about, but can
introduce ringing artifacts if the cutoff lands where the signal
isn't actually zero. Tapering the edges (types 2-4) trades a little
frequency resolution for a cleaner, ringing-free result, which is why
type 3 is the default. Reach for type 4 specifically when there's an
unwanted feature *inside* the passband you want to suppress without
discarding everything around it.

Depending on the selected type, additional spinboxes appear:
**Start / End** (points) set where the passband begins and ends;
**HG L / HG R** (points) control how many points the Happ-Genzel
taper ramps over on the left/right edge respectively (a larger value
means a gentler roll-off); and for type 4 only, **Mask start / end /
transition** (points) define where the notch sits and how sharply it
transitions in and out, while **Mask factor** (0–1) sets how strongly
that region is attenuated (0 = removed entirely, 1 = no attenuation
at all).

## Normalization parameters

- **Sample exposure** / **Reference exposure** (seconds) — used to
  correctly scale sample vs. reference when their acquisition times
  differ.
- **Phase correction** (degrees, −360 to 360) — an additional
  rotation applied to the computed phase.
- Plot-component checkboxes — **Im(χ⁽²⁾)**, **Re(χ⁽²⁾)**, **|χ⁽²⁾|²**,
  **Phase**, and **Show errors** — the last one shades a 95% confidence
  band around each shown curve, estimated from how much the individual
  acquisition frames disagree with each other (nothing to show with
  only one frame). See **Reference & Tips** for exactly how that
  estimate is computed and its caveats.
- **Phase range** — choose how phase is displayed: **[−180°, 180°]**
  or **[0°, 360°)**. This isn't just a relabeling: switching it
  recomputes exactly where the plotted phase line should show a gap,
  so wrapped phase data always looks continuous and correct in
  either convention. See **Reference & Tips** for more on this.

## Committing the result

**▶ Process** and **✓ Send to Spectra Library** work exactly as in the
homodyne panel. Note that parameter edits trigger an automatic
reprocess after a brief pause (~400ms) — you generally don't need to
click Process yourself after every small tweak. Purely visual toggles
(checkboxes, the step selector) redraw almost immediately (~50ms)
without reprocessing.

## Export to a notebook

Right-click a matched set and choose **Export processing notebook…** to
write a Jupyter notebook that walks the HD-SFG pipeline one stage at a
time — despike, average and interpolate, background subtraction and
edge taper, FFT filter, normalization — with your current parameters
pre-filled as editable form fields. It is the clearest way to see what
the FFT window or the edge taper is actually doing: the filter plot
shows the mask drawn over the signal it's cutting, and sample and
reference are plotted separately at every stage that changes them.

Each stage is two cells: a **compute** cell that does the work, and a
**plot** cell that draws it, so you can replace either without
disturbing the other. The embedded data, the processing package and the
setup are collapsed behind named cells you can expand if you want to.

The notebook is completely self-contained: the four raw files *and* the
processing code are embedded, so it runs on
[Google Colab](https://colab.research.google.com) with nothing to upload
and nothing to install. It records which version of the app exported
it, when, and from which files. The final cell writes a CSV with the
usual provenance header, which loads straight back into the **Spectra
Library** via *Add spectra from file*.

!!! note "Background offset"
    The offset is fitted from the markers you place against *this* set's
    averaged background, so the notebook receives the resolved number
    rather than the marker positions — the markers alone wouldn't
    reproduce it elsewhere.

Continue to **Spectra Library** to view, compare, and export what you've
processed.
