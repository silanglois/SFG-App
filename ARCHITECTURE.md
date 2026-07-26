# ARCHITECTURE.md

## Project structure
- `src/sfg_app2/processing/` — pure Python processing pipeline (no Qt imports)
- `src/sfg_app2/app/` — PySide6 GUI application
- `src/sfg_app2/processing/hd_sfg/` — heterodyne SFG pipeline (steps.py, config.py, result.py)

## Key design decisions
- Processing and GUI are fully separated — processing modules never import Qt
- DataFile → SpectrumDataMixin → ProcessedSpectrum inheritance chain
- MatchedSet holds signal/background/reference/ref_background + spectrum_type
- HDSFGPanel uses step-by-step caching — each step stored independently
- soft_clear() vs full_clear() — soft preserves axes structure for same-step redraws
- Normalization uses in-place line updates for performance (self._norm_lines dict)
- Two timers: _redraw_timer (50ms) for view changes, _auto_process_timer (400ms) for param changes

## Current state
- Tabs: Load/Match, Process/Review, Results, Post Processing (placeholder)
- Homodyne pipeline: despike → bg subtract → normalize → upconvert
- Heterodyne pipeline: despike → average → bg subtract → FFT filter → iFFT → normalize
- HD-SFG panel lives in src/sfg_app2/app/widgets/hd_sfg_panel.py

## Known patterns
- All plots use SpectrumPlotWidget with x-range spinboxes
- Collapsible QGroupBox via make_collapsible() in widgets/collapsible_group_box.py
- PatternManager handles persistent metadata patterns via platformdirs
- export CSVs include # comment header with full provenance