# Settings & Preferences

Everything global lives under the **Preferences** menu, plus an
**Appearance** submenu for light/dark/system theme.

## Metadata patterns

![Metadata patterns dialog](images/settings_metadata_patterns.png)

Filenames often encode structured metadata (sample name, polarization,
center wavelength, acquisition time, timestamp, date, concentration,
potential, temperature) as underscore-separated tokens. A **pattern**
is an ordered list of field names that maps onto those tokens for
filenames with a given number of tokens. This dialog lets you define
and manage named patterns, organized into folders in a tree, with a
conflict warning if two patterns of the same token-length would be
ambiguous. Edits only take effect when you click OK.

Filename metadata parsing can be turned off entirely from
**Preferences → Use metadata patterns**, independent of what patterns
exist.

## Auto-matching parameters

![Auto-matching settings dialog](images/settings_auto_matching.png)

Manages named, tree-organized **matching profiles** (only one active
at a time — this is what Load/Match's **Auto-match Files** button
actually uses). Each profile configures:

- How backgrounds are identified (filename suffix, filename prefix,
  or a metadata field, with a customizable list of matching tokens).
- How references are recognized.
- Per-field matching rules: Ignore / Optional / Required / Closest /
  Highest.
- Rules that force homodyne vs. heterodyne classification based on
  filename or metadata.

## Plotting settings

![Plotting settings dialog with live preview](images/settings_plotting.png)

Pick a global matplotlib/aquarel plotting style — built-in aquarel
themes, any custom styles you've saved, or plain matplotlib defaults
— with a live preview canvas that updates as you change the
selection. Accepting immediately restyles every plot in Process/
Review, Results, and Fitting.

### Custom style editor

![Custom style editor](images/settings_custom_style_editor.png)

Opened from within Plotting Settings, this lets you build and save
your own named style: fonts (size/weight/family/style/variant), line
styles, tick/axis direction and alignment, legend location, and a
default color palette. You can start from an existing built-in theme
or from matplotlib's defaults, and the result is saved for reuse (and
shows up in the Plotting Settings dropdown alongside the built-in
styles).

## Filename color-coding

![Color-coding settings dialog](images/settings_color_coding.png)

Optionally colors filenames in the Load/Match file list and/or match
table, to make it easier to visually group related files. Modes:

- **Single field** — one metadata field's distinct values get
  distinct colors.
- **Multiple fields** — pick several fields via a checklist.
- **Role** — a fixed two-color split between signal and background
  files.

A separate **Apply to** control scopes coloring to the file list, the
match table, or both.

## Appearance (Light / Dark / System)

A submenu with three mutually exclusive options controlling the
overall Qt theme: **Light**, **Dark**, or **System** (follow the OS
setting). Your choice is saved and restored on the next launch.
