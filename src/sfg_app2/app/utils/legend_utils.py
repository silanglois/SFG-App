"""Legend construction that stays rebuildable.

A matplotlib Legend does not keep the handles it was given -- only the
proxy artists it drew, and for a tuple handle (a combined data+fit
entry, drawn by HandlerTuple) only the *first* of those. Anything that
needs to rebuild a legend with some rows dropped (SavePlotDialog) can't
recover the originals from the Legend itself, so build_legend() records
them alongside, and legend_source() reads them back -- falling back to
what the live legend exposes for legends built some other way.
"""
from __future__ import annotations

_SOURCE_ATTR = "_sfg_source"


def build_legend(ax, handles, labels, **kwargs):
    """``ax.legend(handles, labels, **kwargs)``, remembering its inputs."""
    handles, labels = list(handles), list(labels)
    legend = ax.legend(handles, labels, **kwargs)
    setattr(legend, _SOURCE_ATTR, (handles, labels, dict(kwargs)))
    return legend


def legend_source(legend) -> tuple[list, list, dict]:
    """(handles, labels, kwargs) to rebuild ``legend`` with."""
    source = getattr(legend, _SOURCE_ATTR, None)
    if source is not None:
        handles, labels, kwargs = source
        return list(handles), list(labels), dict(kwargs)

    texts = legend.get_texts()
    kwargs = {
        "loc": legend._loc,
        "ncols": getattr(legend, "_ncols", 1),
        "frameon": legend.get_frame_on(),
    }
    if texts:
        kwargs["fontsize"] = texts[0].get_fontsize()
    title = legend.get_title().get_text()
    if title:
        kwargs["title"] = title
    if getattr(legend, "_bbox_to_anchor", None) is not None:
        kwargs["bbox_to_anchor"] = legend._bbox_to_anchor
    custom = getattr(legend, "_custom_handler_map", None)
    if custom:
        kwargs["handler_map"] = custom
    return list(legend.legend_handles), [t.get_text() for t in texts], kwargs
