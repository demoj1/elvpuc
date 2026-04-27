"""LogRow — a GTK widget for a single log entry (header + body)."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

from elk.utils import utc_to_local_ms, apply_highlights


class LogRow(Gtk.Box):
    """
    Log entry: bold header + selectable body.
    Always fully expanded (no collapse).
    """

    def __init__(self, entry_id: int, log: dict, highlighters: dict[str, str]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.log           = log          # exposed so _apply_filter can read it
        self._highlighters = highlighters

        self._hdr_lbl  = self._make_header()
        self._body_lbl = self._make_body()
        self.append(self._hdr_lbl)
        self.append(self._body_lbl)

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh_highlights(self, highlighters: dict[str, str]) -> None:
        """Re-apply markup with new highlighter dict without rebuilding widget."""
        self._highlighters = highlighters
        self._body_lbl.set_markup(apply_highlights(self.log["msg"], highlighters))

    # ── Private ───────────────────────────────────────────────────────────────

    def _make_header(self) -> Gtk.Label:
        local_time = utc_to_local_ms(self.log["time"])
        text = f" {local_time}  {self.log['time']}"
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class("log-header")
        lbl.set_selectable(True)
        return lbl

    def _make_body(self) -> Gtk.Label:
        lbl = Gtk.Label(xalign=0)
        lbl.add_css_class("log-body")
        lbl.set_selectable(True)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.CHAR)
        lbl.set_markup(apply_highlights(self.log["msg"], self._highlighters))
        return lbl
