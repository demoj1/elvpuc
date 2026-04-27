"""HeatmapWidget — Cairo DrawingArea with a Popover tooltip."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from elk.utils import heatmap_color, utc_to_local_sec


class HeatmapWidget(Gtk.DrawingArea):
    """
    Colour-spectrum heatmap.

    The Popover is attached lazily on the first ``realize`` signal so that
    ``set_parent`` is called only after the widget has a native surface.
    """

    def __init__(self, on_zoom_cb):
        super().__init__()

        self._data:       list[dict] = []
        self._max_count:  int        = 1
        self._hover_x:    float      = -1.0
        self._hover_idx:  int        = -1
        self._zoom_range: int        = 1
        self._sel:        tuple      = (0, 0)
        self._on_zoom_cb             = on_zoom_cb
        self._popover:    Gtk.Popover | None = None   # created on realize

        self.set_content_height(42)
        self.set_draw_func(self._draw)

        # Lazy popover setup — must happen after the widget is realized
        self.connect("realize", self._on_realize)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave",  self._on_leave)
        self.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    # ── Lazy popover ──────────────────────────────────────────────────────────

    def _on_realize(self, _widget) -> None:
        if self._popover is not None:
            return

        tip = Gtk.Label()
        tip.add_css_class("heatmap-tip")
        tip.set_margin_start(8)
        tip.set_margin_end(8)
        tip.set_margin_top(3)
        tip.set_margin_bottom(3)

        pop = Gtk.Popover()
        pop.set_child(tip)
        pop.set_autohide(False)
        pop.set_has_arrow(True)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_parent(self)           # safe: widget is now realized
        pop.add_css_class("heatmap-popover")

        self._tip_lbl = tip
        self._popover = pop

    # ── Public ────────────────────────────────────────────────────────────────

    def update_data(self, data: list[dict]) -> None:
        self._data = data
        counts = [b.get("doc_count", 0) for b in data]
        self._max_count = max(counts) if counts and max(counts) > 0 else 1
        self._hover_idx = -1
        if self._popover:
            self._popover.popdown()
        self.queue_draw()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _idx_at(self, x: float) -> int:
        n, w = len(self._data), self.get_width()
        if n == 0 or w == 0:
            return 0
        return max(0, min(n - 1, int(x * n / w)))

    def _update_sel(self, x: float) -> None:
        self._hover_x   = x
        idx             = self._idx_at(x)
        self._hover_idx = idx
        n               = len(self._data)
        self._sel = (
            max(0,     idx - self._zoom_range),
            min(n - 1, idx + self._zoom_range),
        )
        self.queue_draw()
        self._show_popover(x)

    def _show_popover(self, x: float) -> None:
        if self._popover is None or self._hover_idx < 0 or not self._data:
            return

        s, e  = self._sel
        item  = self._data[self._hover_idx]
        total = sum(self._data[i]["doc_count"] for i in range(s, e + 1))
        ts    = utc_to_local_sec(item.get("key_as_string", ""))
        self._tip_lbl.set_label(
            f"{ts}   bucket: {item['doc_count']}   range: {total}")

        rect          = Gdk.Rectangle()
        rect.x        = max(0, int(x) - 1)
        rect.y        = 0
        rect.width    = 2
        rect.height   = self.get_height()
        self._popover.set_pointing_to(rect)

        if not self._popover.get_visible():
            self._popover.popup()
        # If already visible just update position (pointing_to already set)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_motion(self, _, x, y):
        if self._data:
            self._update_sel(x)

    def _on_leave(self, _):
        self._hover_idx = -1
        if self._popover:
            self._popover.popdown()
        self.queue_draw()

    def _on_click(self, _gesture, _n, _x, _y):
        if not self._data:
            return
        s, e = self._sel
        self._on_zoom_cb(
            self._data[s]["key_as_string"],
            self._data[e]["key_as_string"],
        )

    def _on_scroll(self, _, _dx, dy):
        self._zoom_range = max(1, self._zoom_range + int(dy))
        if self._hover_idx >= 0:
            self._update_sel(self._hover_x)
        return True

    # ── Draw ──────────────────────────────────────────────────────────────────

    def _draw(self, _area, cr, w, h):
        data, n = self._data, len(self._data)

        cr.set_source_rgb(0.07, 0.07, 0.07)
        cr.paint()
        if n == 0:
            return

        for i, item in enumerate(data):
            x0 = i * w / n
            x1 = (i + 1) * w / n
            cr.set_source_rgb(
                *heatmap_color(item.get("doc_count", 0), self._max_count))
            cr.rectangle(x0, 0, x1 - x0 + 0.5, h)
            cr.fill()

        if self._hover_idx >= 0:
            s, e = self._sel
            sx0  = s * w / n
            sx1  = (e + 1) * w / n

            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.rectangle(sx0, 0, sx1 - sx0, h)
            cr.fill()

            cr.set_source_rgb(1, 0.2, 0.2)
            cr.set_line_width(1.5)
            cr.rectangle(sx0, 0.75, sx1 - sx0, h - 1.5)
            cr.stroke()
