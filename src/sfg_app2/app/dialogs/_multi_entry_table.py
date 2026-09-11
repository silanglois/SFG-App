# src/sfg_app2/app/dialogs/_multi_entry_table.py
"""Shared helper for the "combine all selected into one table" mode on
the Spectra Library's read-only view dialogs (ProcessingParamsDialog,
FitParametersDialog) -- both show one entry's (label, *values) rows at
a time by default; this merges several entries' row-lists into one wide
table instead."""
from __future__ import annotations


def merge_entries_into_wide_rows(per_entry_rows: list[list[tuple]]) -> list[tuple]:
    """`per_entry_rows[i]` is entry i's list of `(label, *values)` tuples
    (every row across every entry must use the same number of value
    columns -- 1 for Field/Value, 2 for Parameter/Value/Error). Returns
    one row per distinct label -- the union across every entry, in
    first-appearance order -- shaped `(label, *entry0_values,
    *entry1_values, ...)`. An entry missing a given label gets "—"
    placeholders sized to its own value-column count, so entries with
    genuinely different fields/models still merge into one consistent
    table instead of raising or misaligning columns.
    """
    if not per_entry_rows:
        return []

    n_value_cols = 1
    for rows in per_entry_rows:
        if rows:
            n_value_cols = len(rows[0]) - 1
            break
    placeholder = ("—",) * n_value_cols

    order: list[str] = []
    seen: set[str] = set()
    per_entry_lookup: list[dict[str, tuple]] = []
    for rows in per_entry_rows:
        lookup = {}
        for row in rows:
            label, *values = row
            lookup[label] = tuple(values)
            if label not in seen:
                seen.add(label)
                order.append(label)
        per_entry_lookup.append(lookup)

    merged = []
    for label in order:
        row = [label]
        for lookup in per_entry_lookup:
            row.extend(lookup.get(label, placeholder))
        merged.append(tuple(row))
    return merged
