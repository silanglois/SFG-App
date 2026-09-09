# CLAUDE.md

Guidance for developing this project — a PySide6 desktop app for
processing/analyzing SFG (Sum-Frequency Generation) spectroscopy data.
`src/sfg_app2/processing/` is a pure Python, Qt-free processing/fitting
pipeline; `src/sfg_app2/app/` is the PySide6 GUI on top of it (tabs,
widgets, dialogs; settings persistence lives in `app/utils/`; Designer
`.ui` files + generated `ui_*.py` live in `app/ui/`). This split is
enforced by convention, not tooling — processing modules should never
import Qt.

## Invariants and gotchas worth knowing before changing things

- `DataFile → SpectrumDataMixin → ProcessedSpectrum` is the inheritance
  chain for spectrum objects; `MatchedSet` bundles a
  signal/background/reference/reference_background quartet plus
  `spectrum_type`.
- Homodyne pipeline order: despike → background subtract → normalize →
  upconvert. Heterodyne: despike → average → background subtract → FFT
  filter → iFFT → normalize. Each step assumes the previous ones already
  ran — don't reorder without re-checking those assumptions.
- `SpectrumPlotWidget.soft_clear()` (same-step redraw, preserves axes
  structure) vs `full_clear()` (recreates axes from scratch): always use
  `full_clear()` after creating/tearing down a `twinx()` overlay, or
  after a style change — otherwise orphaned twin axes accumulate, or
  stale chrome is left behind.
- `DockablePlotPanel` mixin gives each tab (`ProcessedResultsTab`,
  `FittingTab`, `HomodynePanel`, `HDSFGPanel`) its own nested
  `QMainWindow` of `QDockWidget`s. This exists because `QDockWidget`
  needs a `QMainWindow` to dock into, and docking against the app's one
  real `MainWindow` would snap panels to the whole app window instead of
  staying scoped to their own tab.
- Rapid-input coalescing pattern: a single-shot `QTimer` per panel that
  needs to debounce (spinbox edits, view changes) into one recompute,
  rather than reacting to every signal immediately.
- Fitting (`processing/fitting.py`): marking any `FitParam.shared = True`
  (the Parameters table's "Shared" checkbox) is the *only* thing that
  routes a batch run through `fit_global_batch` (one jointly-optimized
  `lmfit.Parameters` shared across every dataset) instead of independent
  per-dataset fits. Sequential (seeded-chain) fitting is a wholly
  separate mode that ignores the Shared flag entirely.
- A fit's results only reach the Spectra Library by export-to-CSV and
  reload — there is no in-memory link from `FittingTab` back to a
  `SpectrumEntry`. The `# Fit json: {...}` comment header
  (`processing/provenance.py`'s `format_fit_section`/`parse_fit_json`)
  is the sole channel; anything that re-exports a Library entry must
  re-embed that section itself or the fit data silently disappears
  (this bit `ProcessedResultsTab._write_csv_with_provenance`, which for
  a while dropped it on every re-export).
- Settings persistence (dock layouts, plotting style, matching profiles,
  color coding, metadata patterns, fit templates, fitting display
  settings) all independently follow the same load/save-to-JSON-via-
  `platformdirs` pattern (`app/utils/*_settings.py`) — a new persisted
  setting should follow suit rather than inventing a new mechanism.
- Exported CSVs carry a `#`-commented provenance header (readable via
  `pd.read_csv(path, comment='#')`) with the full processing-parameter
  trail, plus a `# Fit json:` section when a fit is attached — this is
  what makes export → reload a lossless round trip.
- `TraceStyle` (per-curve color/linestyle/marker/etc., shared by the
  Spectra Library and Fitting tabs via `TraceStyleDialog`) uses `None`
  fields to mean "use the active plotting style's automatic default",
  not "unset" — don't treat `None` as a missing value to backfill.
- `.ui` files under `app/ui/` are Qt Designer sources; their `ui_*.py`
  counterparts are regenerated **by hand**, not by an automated build
  step. Editing one without the other leaves them silently out of sync.

## Working conventions

- Python 3.14, uv-managed (`uv.lock` + `uv_build`).
- Commands: `uv sync` (install deps), `uv run sfg-app` (launch),
  `uv run pytest -q` (tests), `uv run pyinstaller
  packaging/sfg-app.spec` (build a standalone exe).
- Branch `dev` is the active working branch; `main` is where releases
  live — pushing a `vX.Y.Z` tag there triggers `.github/workflows/release.yml`
  (builds the exe, packages an installer + portable ZIP, publishes a
  GitHub Release).
- Never commit or push without an explicit instruction to do so.
