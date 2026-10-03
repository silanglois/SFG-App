"""The two spectrum kinds, and how their names are read back.

The phase-resolved technique was called "heterodyne" (HD-SFG) in earlier
versions of this app, and that name is still in exported CSV headers
("# Type: heterodyne"), saved fits ("kind"), matching profiles and dock
layouts written before the rename. Everything that reads a kind from
outside the running app passes it through normalize_kind(), so old files
and settings keep loading; everything written uses the new name.
"""
from __future__ import annotations

HOMODYNE = "homodyne"
PHASE_RESOLVED = "phase_resolved"

# Names a phase-resolved kind has been (or may be) written as.
_PHASE_RESOLVED_ALIASES = {
    "phase_resolved", "phase-resolved", "phase resolved", "pr-sfg", "pr_sfg", "pr",
    # legacy (pre-rename) spellings
    "heterodyne", "hd-sfg", "hd_sfg", "hd",
}

_LABELS = {HOMODYNE: "Homodyne", PHASE_RESOLVED: "Phase-resolved"}


def normalize_kind(value) -> str:
    """PHASE_RESOLVED for any current or legacy phase-resolved name
    (any case), HOMODYNE for anything else."""
    text = str(value or "").strip().lower()
    return PHASE_RESOLVED if text in _PHASE_RESOLVED_ALIASES else HOMODYNE


def kind_label(kind) -> str:
    """Display name: "Homodyne" / "Phase-resolved"."""
    return _LABELS[normalize_kind(kind)]


def header_token(kind) -> str:
    """How a kind is spelled on an exported CSV's "# Type:" line."""
    return "phase-resolved" if normalize_kind(kind) == PHASE_RESOLVED else HOMODYNE
