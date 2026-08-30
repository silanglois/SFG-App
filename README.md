# SFG-App

A desktop application for processing and analyzing Sum-Frequency
Generation (SFG) spectroscopy data — homodyne and heterodyne — built
with PySide6.

This is the second-generation SFG-App, rewritten from the ground up
in Python — its MATLAB-based predecessor covered only a small
fraction of this app's functionality. The historical "2" lives on
internally as the Python package/distribution name (`sfg_app2` /
`sfg-app2`), but day-to-day the app is just called **SFG-App**.

## Features

- **Load/Match** — load raw data files individually or from a folder,
  automatically or manually match signal/background/reference files,
  and parse metadata from filenames using customizable patterns.
- **Process/Review** — homodyne (despike → background subtraction →
  normalize → upconvert) and heterodyne (despike → average →
  background subtraction → FFT filter → iFFT → normalize) processing
  pipelines with live preview.
- **Spectra Library** — view, compare, and normalize processed
  spectra, export to CSV, and save publication-ready plots.
- **Fitting** — fit peaks/lineshapes (homodyne intensity or
  heterodyne real/imaginary) to a processed spectrum, with batch and
  sequential (seeded-chain) multi-spectrum fitting.
- Customizable metadata patterns, auto-matching rules, plotting styles,
  and filename color-coding.

## Download

Grab the latest installer (or a portable ZIP, if you'd rather not
install anything) from the
[Releases page](https://github.com/silanglois/SFG-App/releases/latest) —
no Python or Git required. Run `SFG-App-Setup-*.exe` and follow the
wizard, or unzip the portable build and run `SFG-App.exe` directly.

Windows will likely show a "Windows protected your PC" SmartScreen
warning the first time you run either one, since the app isn't
code-signed — click **More info → Run anyway** to proceed; this is
expected and not a sign anything is wrong.

The rest of this section covers running the app **from source**
instead (for development, or on macOS/Linux) — most users should just
use the installer above.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/) (recommended — this repo is uv-managed:
  `uv.lock` + `uv_build` backend)

## Running from source

This app is managed with **[uv](https://docs.astral.sh/uv/)**, a tool that
automatically installs the right version of Python and all required
packages for you. You do **not** need to install Python yourself, and you
don't need any prior programming experience — just follow the steps below
for your operating system.

### Step 1: Install Git

Git is the tool used to download (and later update) the app's code.

- **Windows**: download and run the installer from
  [git-scm.com/download/win](https://git-scm.com/download/win) — the
  default options are fine.
- **macOS**: open the **Terminal** app and type `git --version`. If Git
  isn't installed, macOS will offer to install it for you automatically.
- **Linux**: open a terminal and run `sudo apt install git` (Debian/Ubuntu)
  or the equivalent for your distribution.

### Step 2: Install uv

Open a terminal — on Windows use **PowerShell** (search for it in the
Start menu), on macOS/Linux use **Terminal** — and run the command for
your system:

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux**:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

After it finishes, **close and reopen your terminal** so the `uv` command
becomes available.

### Step 3: Download the app

In your terminal, navigate to the folder where you'd like the project to
live (e.g. your Documents folder), then run:

```bash
git clone https://github.com/silanglois/SFG-App.git
cd SFG-App
```

The first command downloads the project into a new `SFG-App` folder; the
second moves your terminal into that folder. You'll need to be inside this
folder any time you run a command below.

### Step 4: Install dependencies

Still inside the `SFG-App` folder, run:

```bash
uv sync
```

This automatically downloads Python 3.14 (if you don't already have it)
and every package the app needs — nothing to configure.

### Step 5: Run the app

```bash
uv run sfg-app
```

The application window should open shortly. You'll run this same command
every time you want to launch the app — it doesn't need to be repeated,
just re-run from inside the `SFG-App` folder.

### Alternative: pip

If you're already comfortable with Python virtual environments and prefer
not to use uv:

```bash
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -e .
sfg-app
```

## Updating to the latest version

When a new version of the app is released, open a terminal inside the
`SFG-App` folder (from Step 3 above) and run:

```bash
git checkout main
git pull
uv sync
```

- `git checkout main` makes sure you're on the `main` branch, where
  released versions live (Git will tell you if you're already there —
  that's fine, nothing will change).
- `git pull` downloads the latest code.
- `uv sync` installs any new or updated dependencies.

> **If `git pull` fails or complains about diverged/unrelated
> history:** this repo's history was rewritten on 2026-08-25.
> Don't try to merge or rebase through the error. Instead, back up anything uncommitted, then either delete this folder and re-clone from scratch, or run:
> ```bash
> git fetch origin
> git reset --hard origin/main
> ```
> (use your actual branch name if not `main`).

Then launch the app as usual with `uv run sfg-app`.

## Building a standalone .exe

To build a distributable Windows executable (no Python/uv required to
run it):

```bash
uv sync --group dev
uv run pyinstaller packaging/sfg-app.spec
```

The built app appears in `dist/SFG-App/` — copy that whole folder to
distribute it; `SFG-App.exe` inside it depends on the rest of the
folder's contents. If `icon.svg` is ever changed,
`packaging/icon.ico` needs regenerating first: `uv run --group dev
python packaging/build_icon.py`.

To build the installer locally instead of waiting on CI, install
[Inno Setup 6](https://jrsoftware.org/isinfo.php), then run:

```bash
iscc /DMyAppVersion=X.Y.Z packaging\sfg-app.iss
```

The installer appears in `packaging/installer_output/`. In practice
this happens automatically: pushing a `vX.Y.Z` tag triggers
`.github/workflows/release.yml`, which builds the exe, packages both
the installer and a portable ZIP, and publishes them to a
[GitHub Release](https://github.com/silanglois/SFG-App/releases) —
see [ARCHITECTURE.md](ARCHITECTURE.md).

## Documentation

An in-depth user guide covering every tab and settings dialog is
built into the app — open it from **Help → User Guide**. For a
developer-facing overview of the codebase structure, see
[ARCHITECTURE.md](ARCHITECTURE.md).

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
