# Load & Match

This tab gets raw data files into the app and organizes them into
matched **signal / background / reference / reference-background**
sets, ready for processing.

## 1. Load files

Use the **File** menu:

- **Load file(s)** — pick one or more raw files individually.
- **Load files from folder** — load every recognized file in a
  folder at once.
- **Load files from multiple folders** (checkable) — when off,
  loading a new folder replaces the files from any previously loaded
  folder. Turn it on to accumulate files from several folders at
  once.
- **Load image...** — loads a CCD image CSV independently of the
  spectral pipeline, opened in its own floating image window (see
  **Reference & Tips**).
- **Ignore selected files** — permanently excludes specific file
  paths from loading, and removes any already-loaded matches that
  used them.

Loaded files appear in the file list on the left.

## 2. Review metadata and preview files (optional)

Right-click a file in the list to:

- **Review metadata** — step through the file's parsed metadata
  fields one at a time (previous/next navigation), and correct
  anything the automatic filename parsing got wrong.
- **Plot** — open a raw-spectrum preview in its own floating window.
  These preview windows are tracked in the **Window** menu, so you
  can get back to one later without reopening it.

Metadata is parsed automatically from filenames using **patterns**
(see **Settings & Preferences → Metadata patterns**). If you'd rather
not use filename-based metadata at all, turn it off from
**Preferences → Use metadata patterns**.

## 3. Auto-match

Click **Auto-match Files** to run the matcher using the currently
active auto-matching profile (**Preferences → Auto-matching
parameters**). Matched sets populate the table on the right, with one
column each for **Signal, Sample BG, Reference, Ref BG,** and
**Type** (homodyne/heterodyne).

If the matcher finds ambiguous matches, a warning dialog lists them
(up to 10 at a time; the rest are logged).

## 4. Adjust matches manually

The match table is editable directly:

- **Drag a file** from the file list into any cell to assign it
  manually — click and hold on a filename in the list, drag it over
  the target cell (any of the Signal / Sample BG / Reference / Ref BG
  columns, on any row), and release to drop it in. This works even if
  the auto-matcher got that one cell wrong, or left it empty.
- Click the **Type** cell to change homodyne/heterodyne via a
  dropdown.

## 5. Update and start processing

- **Update** re-loads/refreshes files from any loaded folders
  (reapplying the current metadata-pattern and ignore-list settings)
  without needing to re-browse for them — useful if new files have
  landed in a folder you already loaded.
- **Start Processing** converts the match table into a list of
  matched sets and unlocks the **Process / Review** tab. If any set
  is missing a required file (e.g. no reference), you'll be warned
  and offered the option to skip it rather than block the whole
  batch.

Continue to **Process & Review — Homodyne** or **Process & Review —
Heterodyne**, depending on which kind of data you're working with.
