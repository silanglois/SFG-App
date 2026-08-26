# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SFG-App.

Build with:   uv run --group dev pyinstaller packaging/sfg-app.spec
Output in:    dist/SFG-App/

This is a --onedir build (recommended for a desktop GUI app -- faster
startup than --onefile, which re-extracts itself into a temp dir on
every launch). To build a single-file exe instead, fold `a.binaries`/
`a.datas` directly into EXE(...) and drop the COLLECT(...) step -- see
PyInstaller's --onefile spec docs for the exact shape.
"""
from pathlib import Path

_REPO_ROOT = Path(SPECPATH).parent
_RESSOURCES = _REPO_ROOT / "src" / "sfg_app2" / "app" / "ressources"
_ICON = Path(SPECPATH) / "icon.ico"

a = Analysis(
    [str(Path(SPECPATH) / "entry_point.py")],
    pathex=[str(_REPO_ROOT / "src")],
    binaries=[],
    datas=[
        # main.py / about_dialog.py / user_guide_dialog.py all read this
        # directory at runtime via Path(__file__)-relative paths -- it
        # has to be bundled explicitly, PyInstaller can't infer it.
        (str(_RESSOURCES), "sfg_app2/app/ressources"),
    ],
    hiddenimports=[
        # Only ever imported lazily inside a function
        # (polystyrene_calibration_dialog.py::_check_refractiveindex),
        # so PyInstaller's static import analysis can miss it even
        # though it's a hard pyproject.toml dependency.
        "refractiveindex",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SFG-App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(_ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SFG-App",
)
