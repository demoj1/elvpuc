"""ElkApp — Gtk.Application entry point."""

import logging

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

from elk.styles import install_static
from elk.window import ElkWindow

log = logging.getLogger("elk")


class ElkApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.elk.viewer")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        install_static(Gdk.Display.get_default())

    def do_activate(self) -> None:
        # Single-instance: a second launch re-activates the primary process.
        # Raise the existing window instead of doing nothing.
        existing = self.get_active_window()
        if existing is not None:
            log.debug("do_activate: raising existing window")
            existing.present()
            return

        log.debug("do_activate: building window")
        win = ElkWindow(self)
        log.debug("do_activate: window built, presenting")
        win.present()
        log.debug("do_activate: presented")
        win.push_scale()        # apply saved font sizes immediately
        win._start_fetch()      # auto-search on startup
        log.debug("do_activate: done")
