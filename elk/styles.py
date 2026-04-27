"""GTK4 CSS: static theme + dynamic font/scale provider."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

BASE_UI_PT  = 10   # base UI font size (pt), scaled by ui_scale
BASE_LOG_PT = 12   # default log font size (pt)

# ── Static CSS (colours, borders, padding) ────────────────────────────────────
# Applied once at startup with PRIORITY_APPLICATION.

STATIC_CSS = """
window { background: #f5f5f5; }

.toolbar {
    background: #ececec;
    border-bottom: 1px solid #cccccc;
    padding: 2px 6px;
}

/* every toolbar row is exactly one line tall */
.toolbar-row {
    min-height: 28px;
    max-height: 28px;
}

entry {
    background: #ffffff;
    color: #1a1a1a;
    border: 1px solid #cccccc;
    border-radius: 3px;
    padding: 0 4px;
    min-height: 22px;
    max-height: 22px;
}
entry:focus { border-color: #4a90d9; }

/* spinbutton wraps an entry + two arrow buttons */
spinbutton {
    min-height: 22px;
    max-height: 22px;
}
spinbutton entry {
    min-width: 32px;
    min-height: 22px;
    max-height: 22px;
    padding: 0 2px;
}
spinbutton button {
    min-height: 22px;
    max-height: 22px;
    padding: 0 2px;
    min-width: 20px;
}

/* scale slider — keep it thin */
scale {
    min-height: 22px;
    max-height: 22px;
}
scale trough {
    min-height: 4px;
    max-height: 4px;
    margin: 9px 0;
}
scale slider {
    min-height: 16px;
    min-width:  16px;
    max-height: 16px;
    max-width:  16px;
}

/* field widths — in px, independent of font size */
.entry-url   { max-width: 180px; }
.entry-index { min-width: 140px; }
.entry-limit { min-width:  44px; max-width:  50px; }
.entry-time  { min-width: 190px; max-width: 190px; }

button {
    background: #dde4ee;
    color: #1a1a1a;
    border: 1px solid #bbbbbb;
    border-radius: 3px;
    padding: 0 8px;
    min-height: 22px;
    max-height: 22px;
}
button:hover  { background: #c5d0e2; }
button:active { background: #4a90d9; color: #ffffff; }

.btn-search { background: #4a90d9; color: #ffffff; font-weight: bold; }
.btn-search:hover { background: #357abd; }

label.dim     { color: #777777; }
label.hl-info { color: #555555; font-style: italic; }


/* log TextView */
textview {
    background: #ffffff;
    border: none;
}
textview text {
    background: #ffffff;
}

.log-header {
    background: #dde8f5;
    color: #1a1a2e;
    font-weight: bold;
    padding: 3px 6px;
    border-bottom: 1px solid #c5d0e2;
}
.log-body {
    background: #f9f9f9;
    color: #1a1a1a;
    padding: 4px 16px;
    border-bottom: 1px solid #eeeeee;
}

.statusbar {
    background: #e0e0e0;
    border-top: 1px solid #cccccc;
    padding: 1px 6px;
    min-height: 24px;
    max-height: 24px;
}
.status-label { color: #1a6bbf; font-weight: bold; }

/* right-click context menu */
.ctx-menu {
    padding: 2px;
    background: #ffffff;
}
.ctx-section {
    color: #888888;
    font-size: 0.85em;
    padding: 6px 8px 2px 8px;
}
.ctx-item {
    padding: 4px 16px;
    border-radius: 4px;
    color: #1a1a1a;
}
.ctx-item:hover {
    background: #e8f0fe;
    color: #1a1a1a;
}

/* heatmap tooltip popover */
.heatmap-popover contents {
    background: #1e1e1e;
    border-radius: 3px;
    padding: 0;
}
.heatmap-tip {
    color: #000;
    font-family: Monospace;
}
""".encode()

# ── Dynamic scale provider ────────────────────────────────────────────────────
# Replaced on every font/scale change with PRIORITY_APPLICATION + 10.

_scale_provider = Gtk.CssProvider()


def _build_scale_css(ui_pt: int, log_pt: int) -> bytes:
    return f"""
* {{
    font-family: Sans;
    font-size: {ui_pt}pt;
}}
.log-header, .log-body, textview text, textview {{
    font-family: Monospace;
    font-size: {log_pt}pt;
}}
""".encode()


def apply_scale(display: Gdk.Display, ui_pt: int, log_pt: int) -> None:
    """Push updated font sizes to the global display CSS."""
    _scale_provider.load_from_data(_build_scale_css(ui_pt, log_pt))
    Gtk.StyleContext.add_provider_for_display(
        display, _scale_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10,
    )


def install_static(display: Gdk.Display) -> None:
    """Install the static theme CSS once at application startup."""
    provider = Gtk.CssProvider()
    provider.load_from_data(STATIC_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
