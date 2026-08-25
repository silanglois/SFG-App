# Reference & Tips

Miscellaneous behavior that's useful to understand but doesn't belong
to any one tab.

## The phase-display toggle, in depth

Anywhere you see a **Phase range** dropdown (Process/Review's HD-SFG
panel, and Results when plotting a heterodyne entry's Phase
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

**File → Load image...** opens a CCD image CSV in its own floating
image window, entirely independent of the spectral matching/
processing pipeline — useful for a quick look at a raw camera frame
without it needing to be part of a matched set.

## CSV export & provenance

Every CSV this app writes (from Results' export buttons, or Fitting's
export) includes a `#`-comment header recording exactly how that data
was produced — source filenames, per-component despike settings,
background subtraction and normalization/up-conversion parameters,
and for fit-derived curves, the full model specification, weighting,
and fit statistics. You can always trace an exported file back to
exactly what produced it, and Results' **View processing parameters**
context-menu action shows the same information without needing to
open the file.
