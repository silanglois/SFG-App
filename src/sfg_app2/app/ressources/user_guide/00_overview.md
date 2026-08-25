# Getting Started

SFG-App2 processes and analyzes Sum-Frequency Generation (SFG)
spectroscopy data, for both **homodyne** and **heterodyne** (HD-SFG)
measurements. It takes you from raw acquisition files all the way to
publication-ready plots and fitted peak parameters.

## The four-tab workflow

Work moves left to right across four tabs at the top of the window:

1. **Load / Match** — bring raw files into the app and organize them
   into matched sets (signal, background, reference, reference
   background).
2. **Process / Review** — configure and preview the processing
   pipeline (despike, background subtraction, normalization, and
   more) for each matched set, then send the results onward.
3. **Results** — the working library of every processed spectrum:
   compare, restyle, annotate, and export.
4. **Fitting** — fit peaks/lineshapes to a processed spectrum, with
   batch and sequential (multi-spectrum) fitting support.

You don't strictly have to go in order. **Results** and **Fitting**
are always reachable — for example, you can jump straight to
**Fitting** and load a previously exported CSV without touching
**Load / Match** at all. Only **Process / Review** stays locked until
you've matched at least one set of files.

## General UI patterns

A few things behave the same way across the whole app, so it's worth
knowing them up front:

- **Dockable panels.** Most tabs are built from several panels
  (parameter docks, plots, tables) that you can drag, resize, float,
  or close. If you accidentally close one, reopen it from the
  **View** menu — it lists every dockable panel for the currently
  active tab, grouped by section.
- **The Window menu** tracks every floating preview window you've
  opened (raw-file previews from Load/Match, CCD image viewers) so
  you can jump back to one instead of hunting for it, or close them
  all at once.
- **The Preferences menu** is where all of the app's global settings
  live — metadata patterns, auto-matching rules, plotting style,
  filename color-coding, and light/dark/system appearance. See
  **Settings & Preferences** in this guide for details on each.
- **Debounced auto-updates.** In the processing panels, editing a
  parameter doesn't require an explicit "apply" click for most
  things — the plot updates automatically a short moment after you
  stop typing/dragging.

Continue to **Load & Match** for the first real step of a typical
session.
