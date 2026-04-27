"""ElkApp — Gtk.Application entry point."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

from elk.styles import install_static
from elk.window import ElkWindow


class ElkApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.elk.viewer")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        install_static(Gdk.Display.get_default())

    def do_activate(self) -> None:
        win = ElkWindow(self)
        win.present()
        win.push_scale()        # apply saved font sizes immediately
        win._start_fetch()      # auto-search on startup
