# Settings & Preferences

Everything global lives under the **Preferences** menu, organized into
four submenus: **Load / Match**, **Plotting**, **Fitting**, and
**Appearance**.

## Metadata patterns

Filenames often encode structured metadata (sample name, polarization,
center wavelength, acquisition time, timestamp, date, concentration,
potential, temperature). A **pattern** says how to pull those fields
back out. This dialog lets you define and manage named patterns,
organized into folders in a tree. Edits only take effect when you click
OK.

The **Match by** selector picks how a pattern reads a filename:

| Mode | How it works |
|---|---|
| **Split on a separator** | The filename is split on the **Separator** (`_` by default, but any character), and the parts map onto your ordered list of field names. A pattern claims a file when the number of parts matches the number of fields. |
| **Regular expression** | The **Expression** is matched against the filename, and its *named groups* become the fields — `(?P<sample>...)` fills a `sample` field. |

Splitting is simpler, but it can only tell layouts apart by counting
parts, so two layouts with the same number of parts are ambiguous — the
dialog warns when two such patterns are active at once. A regular
expression can look at the text itself, so it is the way to separate
those, and regex patterns are tried first.

Type a filename into **Preview filename** to see exactly which fields a
pattern would produce, including a warning when the pattern would not
be picked for that file at all. The preview runs the real parser, so it
cannot disagree with what loading actually does.

Filename metadata parsing can be turned off entirely from
**Preferences → Use metadata patterns**, independent of what patterns
exist.

## File import options

How raw data files are read. The defaults handle ordinary CSV exports,
so this is only needed when a file won't load — in which case the
dialog offers itself automatically, pointed at the file that failed,
with a live preview showing why.

| Option | Use it for |
|---|---|
| **Separator** | Files using semicolons, tabs or pipes instead of commas. "Detect automatically" tries the common ones. |
| **Decimal mark** | Instruments that write `1,23` rather than `1.23`. |
| **Encoding** | Files that aren't UTF-8 (`latin-1`, `cp1252`, …). |
| **Lines to skip** | Exports that begin with a block of instrument settings before the column headers. |
| **Frame / Wavelength / Intensity** | Which of the file's own columns hold those quantities, when its headers are named something else — `wavelength (nm)`, `counts`. Leave as *(detect)* when the headers already match. |
| **Frame columns** | Wide-format files only (see below). |

Besides `.csv`, the app reads `.txt`, `.dat`, `.asc` and `.tsv`; a file
with some other extension is still attempted rather than refused on its
name.

Some instruments write each frame as **its own column** instead of
using a Frame column. Those load as-is: the frame number is read from
the digits in each column header, so `1`, `Frame 1` and `S1` all work,
and the numbering need not start at 1. If such a file also carries a
column that *isn't* a frame — a dark reference, a timestamp — loading
stops and names it, rather than silently importing it as data; list the
real frame columns in **Frame columns** to resolve that.

## Auto-matching parameters

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

## Filename color-coding

Optionally colors filenames in the Load/Match file list and/or match
table, to make it easier to visually group related files. Modes:

- **Single field** — one metadata field's distinct values get
  distinct colors.
- **Multiple fields** — pick several fields via a checklist.
- **Role** — a fixed two-color split between signal and background
  files.

A separate **Apply to** control scopes coloring to the file list, the
match table, or both.

## Plotting settings

Pick a global matplotlib/aquarel plotting style — built-in aquarel
themes, any custom styles you've saved, or plain matplotlib defaults.
The dialog has its own preview canvas showing a small sample plot
(not your real data) that instantly re-renders in the newly selected
style as you click through the dropdown, so you can compare several
styles side by side before committing to one — no need to close the
dialog and check a real spectrum each time. Accepting immediately
restyles every plot in Process/Review, Spectra Library, and Fitting to match.

### Custom style editor

Opened from within Plotting Settings, this lets you build and save
your own named style: fonts (size/weight/family/style/variant), line
styles, tick/axis direction and alignment, legend location, and a
default color palette. You can start from an existing built-in theme
or from matplotlib's defaults, and the result is saved for reuse (and
shows up in the Plotting Settings dropdown alongside the built-in
styles).

## Fitting

- **Color parameter table by peak** — off by default. When enabled,
  every row belonging to the same peak in the Fitting tab's parameter
  and peak tables is tinted with that peak's color, making it easier
  to tell at a glance which rows belong together once a model has
  several peaks. The color matches whatever you've explicitly picked
  for that peak in the Display dock, if anything; otherwise it falls
  back to a stable, automatically-assigned color.

## Export / Import settings

**Export settings...** writes your whole configuration to a single
`.zip` you can hand to someone else — or keep as a backup before
changing a machine. You choose what goes in; only settings you've
actually saved are offered:

- filename metadata patterns
- auto-matching profiles
- fit templates
- plotting settings and any custom styles you've made
- filename color-coding
- file import options
- the calibration reference
- fitting display settings and appearance

**Import settings...** restores them. Two things to know: each part
you select is **replaced completely**, not merged with what you have
now; and several settings are read once at startup, so restart the app
afterwards for everything to take effect.

Window and dock layouts are deliberately *not* included — they're
geometry for one particular screen, so carrying them to another
machine does more harm than good.

## Appearance (Light / Dark / System)

A submenu with three mutually exclusive options controlling the
overall Qt theme: **Light**, **Dark**, or **System** (follow the OS
setting). Your choice is saved and restored on the next launch.
