"""ElkWindow — the main GTK4 ApplicationWindow."""

import queue
import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio

import elk.config  as cfg
import elk.elastic as elastic
from elk.styles            import apply_scale, BASE_UI_PT
from elk.utils             import rand_hl_color
from elk.widgets.heatmap   import HeatmapWidget
from elk.widgets.log_view  import LogView

# Debounce delay for the offline filter (ms)
_FILTER_DEBOUNCE_MS = 120

# Auto-refresh interval (s)
_AUTO_REFRESH_S = 10


class ElkWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Elastic Log Viewer")
        self.set_default_size(1400, 900)

        self._conf:          dict           = cfg.load()
        self._all_logs:      list[dict]     = []
        self._hist_agg:      list[dict]     = []
        self._hist_agg_sum:  int            = 0
        self._query_history: list[str]      = self._conf["query_history"]
        self._highlighters:  dict[str, str] = self._conf["highlighters"]
        self._hist_idx:      int            = -1
        self._is_loading:    bool           = False
        self._data_queue:    queue.Queue    = queue.Queue()
        self._filter_timer:  int            = 0   # GLib source id
        self._auto_timer:    int            = 0   # GLib source id

        self._build_ui()
        self._setup_shortcuts()
        self.connect("close-request", self._on_close)

    # ── Config ────────────────────────────────────────────────────────────────

    def _on_close(self, *_):
        if self._auto_timer:
            GLib.source_remove(self._auto_timer)
            self._auto_timer = 0
        cfg.save({
            "url":            self._url_ent.get_text(),
            "index":          self._idx_ent.get_text(),
            "limit":          self._lim_ent.get_text(),
            "query":          self._get_query(),
            "t_from":         self._from_ent.get_text(),
            "t_to":           self._to_ent.get_text(),
            "offline_filter": self._filter_ent.get_text(),
            "query_history":  self._query_history,
            "highlighters":   self._highlighters,
            "log_sz":         int(self._log_spin.get_value()),
            "ui_scale":       round(self._scale_slider.get_value(), 2),
        })
        return False

    # ── Scale ─────────────────────────────────────────────────────────────────

    def push_scale(self) -> None:
        ui_pt  = max(7, round(BASE_UI_PT * self._scale_slider.get_value()))
        log_pt = int(self._log_spin.get_value())
        apply_scale(self.get_display(), ui_pt, log_pt)

    def _on_scale_changed(self, _):    self.push_scale()
    def _on_log_font_changed(self, _): self.push_scale()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        c    = self._conf
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        root.append(self._build_toolbar(c))

        self._heatmap = HeatmapWidget(self._handle_zoom)
        root.append(self._heatmap)

        root.append(self._build_query_area(c))
        root.append(self._build_hl_bar())
        root.append(self._build_log_area())
        root.append(self._build_statusbar(c))

    def _build_toolbar(self, c: dict) -> Gtk.Box:
        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        toolbar.add_css_class("toolbar")
        toolbar.append(self._build_toolbar_row1(c))
        toolbar.append(self._build_toolbar_row2(c))
        return toolbar

    def _build_toolbar_row1(self, c: dict) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("toolbar-row")
        row.set_valign(Gtk.Align.CENTER)

        # Alt+U → URL
        url_lbl = Gtk.Label(label="_URL:", use_underline=True)
        url_lbl.set_margin_end(2)
        self._url_ent = self._entry(c["url"])
        self._url_ent.add_css_class("entry-url")
        self._url_ent.set_hexpand(True)
        self._url_ent.set_valign(Gtk.Align.CENTER)
        url_lbl.set_mnemonic_widget(self._url_ent)
        row.append(url_lbl); row.append(self._url_ent)

        # Alt+I → Index
        idx_lbl = Gtk.Label(label="_Index:", use_underline=True)
        idx_lbl.set_margin_end(2)
        self._idx_ent = self._entry(c["index"])
        self._idx_ent.add_css_class("entry-index")
        self._idx_ent.set_valign(Gtk.Align.CENTER)
        idx_lbl.set_mnemonic_widget(self._idx_ent)
        row.append(idx_lbl); row.append(self._idx_ent)

        row.append(self._lbl("Log font:"))
        self._log_spin = Gtk.SpinButton.new_with_range(7, 40, 1)
        self._log_spin.set_value(c["log_sz"])
        self._log_spin.set_valign(Gtk.Align.CENTER)
        self._log_spin.connect("value-changed", self._on_log_font_changed)
        row.append(self._log_spin)

        row.append(self._lbl("UI scale:"))
        self._scale_slider = Gtk.SpinButton.new_with_range(0.75, 3.0, 0.05)
        self._scale_slider.set_value(c["ui_scale"])
        self._scale_slider.set_digits(2)
        self._scale_slider.set_valign(Gtk.Align.CENTER)
        self._scale_slider.connect("value-changed", self._on_scale_changed)
        row.append(self._scale_slider)

        return row

    def _build_toolbar_row2(self, c: dict) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.add_css_class("toolbar-row")
        row.set_valign(Gtk.Align.CENTER)

        # Alt+S → Search
        self._search_btn = Gtk.Button(label="_Search", use_underline=True)
        self._search_btn.add_css_class("btn-search")
        self._search_btn.set_valign(Gtk.Align.CENTER)
        self._search_btn.connect("clicked", lambda *_: self._start_fetch())
        row.append(self._search_btn)

        # Auto-refresh toggle — re-runs the search every _AUTO_REFRESH_S seconds
        self._auto_btn = Gtk.ToggleButton(label=f"Auto ⟳ {_AUTO_REFRESH_S}s")
        self._auto_btn.add_css_class("btn-auto")
        self._auto_btn.set_valign(Gtk.Align.CENTER)
        self._auto_btn.set_tooltip_text(
            f"Auto-refresh every {_AUTO_REFRESH_S} seconds")
        self._auto_btn.connect("toggled", self._on_auto_toggled)
        row.append(self._auto_btn)

        # Alt+L → Limit
        lim_lbl = Gtk.Label(label="_Limit:", use_underline=True)
        lim_lbl.set_margin_end(2)
        self._lim_ent = self._entry(c["limit"])
        self._lim_ent.add_css_class("entry-limit")
        self._lim_ent.set_valign(Gtk.Align.CENTER)
        lim_lbl.set_mnemonic_widget(self._lim_ent)
        # mouse wheel changes limit ±10
        lim_scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        lim_scroll.connect("scroll", self._on_limit_scroll)
        self._lim_ent.add_controller(lim_scroll)
        row.append(lim_lbl); row.append(self._lim_ent)

        # Alt+F → From
        from_lbl = Gtk.Label(label="_From:", use_underline=True)
        from_lbl.set_margin_end(2)
        self._from_ent = self._entry(c["t_from"])
        self._from_ent.add_css_class("entry-time")
        self._from_ent.set_valign(Gtk.Align.CENTER)
        from_lbl.set_mnemonic_widget(self._from_ent)
        row.append(from_lbl); row.append(self._from_ent)

        # Alt+T → To
        to_lbl = Gtk.Label(label="_To:", use_underline=True)
        to_lbl.set_margin_end(2)
        self._to_ent = self._entry(c["t_to"])
        self._to_ent.add_css_class("entry-time")
        self._to_ent.set_valign(Gtk.Align.CENTER)
        to_lbl.set_mnemonic_widget(self._to_ent)
        row.append(to_lbl); row.append(self._to_ent)

        # Time presets — Alt+digit mnemonics: 5m=Alt+5, 1h=Alt+1, etc.
        presets = [
            ("_5m",  "now-5m"),
            ("1_5m", "now-15m"),
            ("_3m",  "now-30m"),   # 30m
            ("_1h",  "now-1h"),
            ("_3h",  "now-3h"),
            ("1_2h", "now-12h"),
            ("_2h",  "now-24h"),   # 24h
        ]
        # Simpler: just use the label as-is and Tab/click to activate
        for display, val in [
            ("5m","now-5m"),("15m","now-15m"),("30m","now-30m"),
            ("1h","now-1h"),("3h","now-3h"),("12h","now-12h"),("24h","now-24h"),
        ]:
            btn = Gtk.Button(label=display)
            btn.set_valign(Gtk.Align.CENTER)
            btn.set_can_focus(True)   # Tab-reachable
            btn.connect("clicked", lambda _, v=val: self._set_time(v))
            row.append(btn)

        sp = Gtk.Box(); sp.set_hexpand(True)
        row.append(sp)

        return row

    def _build_query_area(self, c: dict) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("toolbar")

        self._hist_ent = Gtk.Entry()
        self._hist_ent.set_placeholder_text("Query history  (↑↓ to navigate)")
        self._hist_ent.connect("activate", self._on_hist_activate)
        hk = Gtk.EventControllerKey()
        hk.connect("key-pressed", self._on_hist_key)
        self._hist_ent.add_controller(hk)
        box.append(self._hist_ent)

        self._query_buf  = Gtk.TextBuffer()
        self._query_buf.set_text(c["query"])
        self._query_view = Gtk.TextView(buffer=self._query_buf)
        self._query_view.set_monospace(True)
        self._query_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._query_view.set_size_request(-1, 120)
        qk = Gtk.EventControllerKey()
        qk.connect("key-pressed", self._on_query_key)
        self._query_view.add_controller(qk)

        qscroll = Gtk.ScrolledWindow()
        qscroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        qscroll.set_child(self._query_view)
        qscroll.set_size_request(-1, 120)
        box.append(qscroll)

        return box

    def _build_hl_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.add_css_class("toolbar")
        self._hl_label = Gtk.Label(xalign=0)
        self._hl_label.add_css_class("hl-info")
        bar.append(self._hl_label)
        self._update_hl_label()
        return bar

    def _build_log_area(self) -> Gtk.ScrolledWindow:
        self._log_view = LogView()
        self._build_context_menu()

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)
        scroll.set_child(self._log_view)
        scroll.set_vexpand(True)
        return scroll

    def _build_context_menu(self) -> None:
        """
        Right-click menu — rebuilt on a Gio.Menu model + Gtk.PopoverMenu.

        The model/action approach avoids the manual button wiring and the
        autohide-grab races of the old hand-rolled popover (which could lock
        up the TextView).  Actions live in a 'ctx' group on the window, so the
        menu items resolve them through the normal widget action muxer.
        """
        actions = Gio.SimpleActionGroup()
        specs = [
            ("filter-inc", lambda: self._try_add_filter(True)),
            ("filter-exc", lambda: self._try_add_filter(False)),
            ("query-inc",  lambda: self._try_add_query(True)),
            ("query-exc",  lambda: self._try_add_query(False)),
            ("highlight",  lambda: self._try_add_highlight()),
        ]
        for name, cb in specs:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda _a, _p, f=cb: f())
            actions.add_action(act)
        self.insert_action_group("ctx", actions)

        menu = Gio.Menu()

        sec_f = Gio.Menu()
        sec_f.append("+ filter (include)   [A]", "ctx.filter-inc")
        sec_f.append("− filter (exclude)   [D]", "ctx.filter-exc")
        menu.append_section("Offline filter", sec_f)

        sec_q = Gio.Menu()
        sec_q.append("+ query (include)   [Shift+A]", "ctx.query-inc")
        sec_q.append("− query (exclude)   [Shift+D]", "ctx.query-exc")
        menu.append_section("Lucene query", sec_q)

        sec_h = Gio.Menu()
        sec_h.append("Toggle highlight   [Space]", "ctx.highlight")
        menu.append_section("Highlight", sec_h)

        self._ctx_popover = Gtk.PopoverMenu.new_from_model(menu)
        self._ctx_popover.set_parent(self._log_view)
        self._ctx_popover.set_has_arrow(False)

        # Suppress the default TextView right-click menu entirely
        self._log_view.set_extra_menu(None)

        rc = Gtk.GestureClick()
        rc.set_button(3)
        # CAPTURE = run before the TextView's own button-3 handler so it can't
        # steal the press / reset the selection we act on.
        rc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        rc.connect("pressed", self._on_log_right_click)
        self._log_view.add_controller(rc)

    def _build_statusbar(self, c: dict) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("statusbar")

        # Alt+W → filter (F conflicts with From)
        flt_lbl = Gtk.Label(label="Filter:", use_underline=True)
        flt_lbl.set_margin_end(2)
        self._filter_ent = self._entry(c["offline_filter"])
        self._filter_ent.set_hexpand(True)
        # debounced: schedule _render_logs 120ms after last keystroke
        self._filter_ent.connect("changed", self._on_filter_changed)
        flt_lbl.set_mnemonic_widget(self._filter_ent)
        bar.append(flt_lbl)
        bar.append(self._filter_ent)

        hints = Gtk.Label(
            label="[Ctrl+R] Search  [Ctrl+F] Filter  [Ctrl+S] Query"
                  "  [Space] HL  [Ctrl+Space] Clear HL"
                  "  [A/D] ±filter  [Shift+A/D] ±query")
        hints.add_css_class("dim")
        bar.append(hints)

        self._status_lbl = Gtk.Label(label="Ready")
        self._status_lbl.add_css_class("status-label")
        self._status_lbl.set_margin_start(12)
        bar.append(self._status_lbl)

        return bar

    # ── Widget helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_margin_end(2)
        return lbl

    @staticmethod
    def _entry(value: str) -> Gtk.Entry:
        e = Gtk.Entry()
        e.set_text(value)
        e.set_width_chars(-1)
        return e

    def _get_query(self) -> str:
        buf = self._query_buf
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

    def _set_status(self, text: str) -> None:
        GLib.idle_add(self._status_lbl.set_label, text)

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_log_right_click(self, gesture, n_press, x, y) -> None:
        # Claim the event so GTK's built-in TextView menu doesn't appear
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._ctx_popover.set_pointing_to(rect)
        self._ctx_popover.popup()

    # ── Shortcuts ─────────────────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        ctrl = Gtk.EventControllerKey()
        # CAPTURE phase = intercept before child widgets consume the key
        ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctrl.connect("key-pressed", self._on_global_key)
        self.add_controller(ctrl)

    def _latin_keyval(self, keycode: int) -> int:
        """
        Map a hardware *keycode* to its Latin (a–z) keyval, scanning every
        keyboard group.  This makes letter shortcuts work regardless of the
        active layout — e.g. physical 'A' on a Russian ЙЦУКЕН layout reports
        the keyval for 'ф', but the same key still carries 'a' in the Latin
        group, which is what we match against.
        """
        ok, _keys, keyvals = self.get_display().map_keycode(keycode)
        if not ok:
            return 0
        for kv in keyvals:
            if Gdk.KEY_a <= kv <= Gdk.KEY_z:
                return kv
        return 0

    def _on_global_key(self, _ctrl, keyval, keycode, state):
        ctrl  = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        # Layout-independent keyval for letter shortcuts
        lk = self._latin_keyval(keycode) or keyval

        if ctrl:
            if lk == Gdk.KEY_r:
                self._start_fetch();           return True
            if lk == Gdk.KEY_f:
                self._filter_ent.grab_focus(); return True
            if lk == Gdk.KEY_s:
                self._query_view.grab_focus(); return True
            if keyval == Gdk.KEY_space:
                self._clear_highlights();      return True
            return False

        if keyval == Gdk.KEY_F5:
            self._start_fetch(); return True
        if keyval == Gdk.KEY_space:
            return self._try_add_highlight()
        if lk in (Gdk.KEY_a, Gdk.KEY_d):
            include = lk == Gdk.KEY_a
            if shift:
                return self._try_add_query(include=include)
            return self._try_add_filter(include=include)
        return False

    def _on_query_key(self, _ctrl, keyval, _kc, state):
        if (state & Gdk.ModifierType.CONTROL_MASK) and \
                keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._start_fetch()
            return True
        return False

    # ── Filter debounce ───────────────────────────────────────────────────────

    def _on_filter_changed(self, _entry) -> None:
        if self._filter_timer:
            GLib.source_remove(self._filter_timer)
        self._filter_timer = GLib.timeout_add(_FILTER_DEBOUNCE_MS,
                                               self._filter_fire)

    def _filter_fire(self) -> bool:
        self._filter_timer = 0
        self._apply_filter()
        return False  # don't repeat

    # ── Highlights ────────────────────────────────────────────────────────────

    def _update_hl_label(self) -> None:
        if not self._highlighters:
            self._hl_label.set_label(
                "No highlights  [Space] add selection  [Ctrl+Space] clear")
        else:
            parts = [
                f'<span background="{color}"> {GLib.markup_escape_text(w)} </span>'
                for w, color in self._highlighters.items()
            ]
            self._hl_label.set_markup("Highlights: " + "  ".join(parts))

    def _try_add_highlight(self) -> bool:
        # Try from the log TextView first, then any focused Label
        text = self._log_view.get_selected_text()
        if not text:
            focused = self.get_focus()
            text = self._get_label_selection(focused)
        if not text:
            return False
        if text in self._highlighters:
            # Second Space on same word → remove it
            del self._highlighters[text]
        else:
            self._highlighters[text] = rand_hl_color()
        self._log_view.refresh_highlights(self._highlighters)
        self._update_hl_label()
        return True

    @staticmethod
    def _get_label_selection(widget) -> str | None:
        """Extract selected text from a Gtk.Label (byte-offset aware)."""
        if not (isinstance(widget, Gtk.Label) and widget.get_selectable()):
            return None
        has_sel, start_b, end_b = widget.get_selection_bounds()
        if not has_sel or start_b == end_b:
            return None
        plain_utf8 = widget.get_layout().get_text().encode("utf-8")
        text = plain_utf8[start_b : end_b + 1].decode("utf-8").strip()
        return text or None

    def _clear_highlights(self) -> None:
        self._highlighters.clear()
        self._log_view.refresh_highlights(self._highlighters)
        self._update_hl_label()

    # ── Quick filter via A / D ────────────────────────────────────────────────

    def _try_add_query(self, include: bool) -> bool:
        """Shift+A / Shift+D — append +"text" or -"text" to the Lucene query."""
        text = self._log_view.get_selected_text()
        if not text:
            focused = self.get_focus()
            text = self._get_label_selection(focused)
        if not text:
            return False

        prefix = "+" if include else "-"
        token  = f'{prefix}"{text}"'

        buf     = self._query_buf
        current = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        new_val = (current + " " + token).strip() if current else token
        buf.set_text(new_val)

        # Move cursor to end
        buf.place_cursor(buf.get_end_iter())
        self._query_view.grab_focus()
        return True

    def _try_add_filter(self, include: bool) -> bool:
        """A = append +word, D = append -word to the filter entry."""
        text = self._log_view.get_selected_text()
        if not text:
            focused = self.get_focus()
            text = self._get_label_selection(focused)
        if not text:
            return False

        prefix   = "+" if include else "-"
        token    = f"{prefix}{text}"
        current  = self._filter_ent.get_text().strip()
        # Avoid duplicates
        tokens   = current.split()
        if token in tokens:
            return True
        new_val  = (current + " " + token).strip() if current else token
        self._filter_ent.set_text(new_val)
        # Trigger debounced filter immediately
        self._filter_ent.set_position(-1)
        self._filter_fire()
        return True

    # ── Query history ─────────────────────────────────────────────────────────

    def _add_to_history(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        if query in self._query_history:
            self._query_history.remove(query)
        self._query_history.insert(0, query)
        self._query_history = self._query_history[:50]
        self._hist_idx = -1

    def _on_hist_activate(self, entry) -> None:
        val = entry.get_text().strip()
        if val:
            self._query_buf.set_text(val)
            self._add_to_history(val)

    def _on_hist_key(self, _ctrl, keyval, _kc, _state) -> bool:
        if keyval == Gdk.KEY_Up:   self._cycle_history(-1); return True
        if keyval == Gdk.KEY_Down: self._cycle_history(1);  return True
        return False

    def _cycle_history(self, direction: int) -> None:
        if not self._query_history:
            return
        self._hist_idx = (self._hist_idx + direction) % len(self._query_history)
        val = self._query_history[self._hist_idx]
        self._hist_ent.set_text(val)
        self._query_buf.set_text(val)

    # ── Limit scroll ─────────────────────────────────────────────────────────

    def _on_limit_scroll(self, _ctrl, _dx, dy) -> bool:
        try:
            current = int(self._lim_ent.get_text() or 0)
        except ValueError:
            current = 250
        delta = -10 if dy < 0 else 10          # scroll up = more, down = less
        new_val = max(10, current + delta)
        self._lim_ent.set_text(str(new_val))
        return True

    # ── Time presets ──────────────────────────────────────────────────────────

    def _set_time(self, val: str) -> None:
        self._from_ent.set_text(val)
        self._to_ent.set_text("now")
        self._start_fetch()

    def _handle_zoom(self, t_from: str, t_to: str) -> None:
        self._from_ent.set_text(t_from)
        self._to_ent.set_text(t_to)
        self._start_fetch()

    # ── Auto-refresh ───────────────────────────────────────────────────────────

    def _on_auto_toggled(self, btn: Gtk.ToggleButton) -> None:
        if btn.get_active():
            self._start_fetch()
            self._auto_timer = GLib.timeout_add_seconds(
                _AUTO_REFRESH_S, self._auto_tick)
        elif self._auto_timer:
            GLib.source_remove(self._auto_timer)
            self._auto_timer = 0

    def _auto_tick(self) -> bool:
        if not self._auto_btn.get_active():
            self._auto_timer = 0
            return False               # stop the timer
        self._start_fetch()            # no-op if a fetch is already running
        return True                    # keep ticking

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _start_fetch(self) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self._search_btn.set_sensitive(False)
        self._set_status("Fetching…")

        params = dict(
            url    = self._url_ent.get_text().strip().rstrip("/"),
            index  = self._idx_ent.get_text().strip(),
            limit  = int(self._lim_ent.get_text().strip() or 250),
            q      = self._get_query(),
            t_from = self._from_ent.get_text().strip(),
            t_to   = self._to_ent.get_text().strip(),
        )
        self._add_to_history(params["q"])
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()
        GLib.timeout_add(100, self._poll_queue)

    def _worker(self, p: dict) -> None:
        try:
            hits, buckets = elastic.fetch(
                p["url"], p["index"], p["q"],
                p["t_from"], p["t_to"], p["limit"],
            )
            self._data_queue.put(("OK", hits, buckets))
        except Exception as e:
            self._data_queue.put(("ERR", str(e), []))

    def _poll_queue(self) -> bool:
        try:
            status, payload, agg = self._data_queue.get_nowait()
        except queue.Empty:
            return True

        self._is_loading = False
        self._search_btn.set_sensitive(True)

        if status == "OK":
            self._hist_agg     = agg
            self._hist_agg_sum = sum(x.get("doc_count", 0) for x in agg)
            self._all_logs = [{"time": x["t"], "msg": x["m"]} for x in payload]
            self._render_logs()
        else:
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error", secondary_text=payload,
            )
            dlg.connect("response", lambda d, _: d.destroy())
            dlg.present()
            self._set_status("Error")

        return False

    # ── Render / filter logs ──────────────────────────────────────────────────

    def _render_logs(self) -> None:
        """Full rebuild — called only after a fresh fetch."""
        self._log_view.set_logs(self._all_logs, self._highlighters)
        self._apply_filter()
        self._heatmap.update_data(self._hist_agg)
        self._update_hl_label()

    def _apply_filter(self) -> None:
        tokens = self._filter_ent.get_text().lower().split()
        count  = self._log_view.apply_filter(tokens)
        self._set_status(f"Showing: {count} / {self._hist_agg_sum}")
