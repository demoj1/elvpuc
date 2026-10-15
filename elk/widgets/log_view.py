"""LogView — single TextView that renders all log entries efficiently."""

import re

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from elk.utils import utc_to_local_ms, filter_matches

_TAG_HEADER  = "hdr"
_TAG_BODY    = "body"
_TAG_SEP     = "sep"
_TAG_HIDDEN  = "hidden"
_HL_PREFIX   = "hl:"


class LogView(Gtk.TextView):
    """
    Read-only TextView for all log entries.
    One Pango layout → smooth resize, no per-label overhead.
    """

    def __init__(self):
        super().__init__()
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_monospace(True)
        self.set_left_margin(6)
        self.set_right_margin(6)
        self.set_top_margin(4)
        self.set_bottom_margin(4)

        self._buf           = self.get_buffer()
        self._logs:         list[dict]     = []
        self._highlighters: dict[str, str] = {}
        self._log_marks:    list[tuple]    = []   # (start_mark, end_mark) per log
        self._search_text:  list[str]      = []   # lowercased "time msg" per log
        self._visible:      list[bool]     = []   # current filter state per log

        self._setup_tags()

    # ── Tags ──────────────────────────────────────────────────────────────────

    def _setup_tags(self) -> None:
        tt = self._buf.get_tag_table()

        def add(name, **props):
            tag = Gtk.TextTag(name=name)
            for k, v in props.items():
                tag.set_property(k.replace("_", "-"), v)
            tt.add(tag)
            return tag

        # Header: bold, blue-tinted background spanning full line width
        add(_TAG_HEADER,
            weight=Pango.Weight.BOLD,
            paragraph_background="#dde8f5",
            foreground="#1a1a2e",
            pixels_above_lines=8,
            pixels_below_lines=2,
            left_margin=6)

        # Body: slightly indented, normal weight
        add(_TAG_BODY,
            foreground="#1a1a1a",
            paragraph_background="#ffffff",
            left_margin=16,
            pixels_below_lines=2)

        # Separator: thin blank line between entries
        add(_TAG_SEP,
            paragraph_background="#dddddd",
            pixels_above_lines=0,
            pixels_below_lines=0)

        # Hidden (filtered out)
        add(_TAG_HIDDEN, invisible=True)

    # ── Highlight tag management ───────────────────────────────────────────────

    def _get_or_create_hl_tag(self, word: str, color: str) -> Gtk.TextTag:
        name = _HL_PREFIX + word
        tt   = self._buf.get_tag_table()
        tag  = tt.lookup(name)
        if tag is None:
            tag = Gtk.TextTag(name=name)
            tag.set_property("background", color)
            tt.add(tag)
        else:
            tag.set_property("background", color)
        return tag

    def _remove_all_hl_tags(self) -> None:
        tt      = self._buf.get_tag_table()
        to_kill: list[Gtk.TextTag] = []
        tt.foreach(lambda t: to_kill.append(t)
                   if t.get_property("name").startswith(_HL_PREFIX) else None)
        if not to_kill:
            return
        s, e = self._buf.get_bounds()
        for tag in to_kill:
            self._buf.remove_tag(tag, s, e)
            tt.remove(tag)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_logs(self, logs: list[dict], highlighters: dict[str, str]) -> None:
        """Replace buffer content with *logs*.  Single O(n) pass."""
        self._logs         = logs
        self._highlighters = highlighters
        self._log_marks    = []
        self._search_text  = [(l["time"] + " " + l["msg"]).lower() for l in logs]
        self._visible      = [True] * len(logs)

        # Build into a detached buffer (shared tag table) and swap it in at
        # the end: no layout invalidation per insert while the view watches.
        self._remove_all_hl_tags()
        self._buf = Gtk.TextBuffer(tag_table=self._buf.get_tag_table())

        end = self._buf.get_end_iter()

        for log in logs:
            start_mark = self._buf.create_mark(None, end, True)

            # ── Header ───────────────────────────────────────────────────────
            local_t  = utc_to_local_ms(log["time"])
            hdr_text = f" {local_t} {log['time']}\n"
            self._buf.insert_with_tags_by_name(end, hdr_text, _TAG_HEADER)

            # ── Body ─────────────────────────────────────────────────────────
            body_text = log["msg"].rstrip("\n") + "\n"
            self._buf.insert_with_tags_by_name(end, body_text, _TAG_BODY)

            # ── Separator line ────────────────────────────────────────────────
            self._buf.insert_with_tags_by_name(end, "\n", _TAG_SEP)

            # Left gravity: stays put when the next entry is inserted at `end`
            end_mark = self._buf.create_mark(None, end, True)
            self._log_marks.append((start_mark, end_mark))

        self._apply_highlights_internal()
        self.set_buffer(self._buf)

    def apply_filter(self, tokens: list[str]) -> int:
        """
        Show/hide entries via the 'hidden' tag.  Returns visible count.
        Only entries whose visibility flipped get a tag op.
        """
        if not self._log_marks:
            return 0
        visible = 0
        run_start, run_show = -1, False   # pending run of same-direction flips
        for i, text in enumerate(self._search_text + [None]):
            show = text is not None and filter_matches(text, tokens)
            visible += show
            flip = text is not None and show != self._visible[i]
            # Entries are contiguous, so a run of flips is one tag op
            if run_start >= 0 and (not flip or show != run_show):
                self._set_hidden(run_start, i - 1, not run_show)
                run_start = -1
            if flip:
                self._visible[i] = show
                if run_start < 0:
                    run_start, run_show = i, show
        return visible

    def _set_hidden(self, first: int, last: int, hidden: bool) -> None:
        s = self._buf.get_iter_at_mark(self._log_marks[first][0])
        e = self._buf.get_iter_at_mark(self._log_marks[last][1])
        if hidden:
            self._buf.apply_tag_by_name(_TAG_HIDDEN, s, e)
        else:
            self._buf.remove_tag_by_name(_TAG_HIDDEN, s, e)

    def refresh_highlights(self, highlighters: dict[str, str]) -> None:
        """Re-apply highlight tags without rebuilding buffer."""
        self._highlighters = highlighters
        self._remove_all_hl_tags()
        self._apply_highlights_internal()

    def get_selected_text(self) -> str | None:
        """Return currently selected text, or None."""
        if not self._buf.get_has_selection():
            return None
        s, e = self._buf.get_selection_bounds()
        return self._buf.get_text(s, e, False).strip() or None

    def log_at_location(self, wx: float, wy: float) -> dict | None:
        """Return the log entry under widget-space coords (wx, wy), or None."""
        bx, by = self.window_to_buffer_coords(
            Gtk.TextWindowType.WIDGET, int(wx), int(wy)
        )
        ok, it = self.get_iter_at_location(bx, by)
        if not ok:
            return None
        return self._log_at_offset(it.get_offset())

    def log_at_cursor(self) -> dict | None:
        """Return the log entry under the text cursor (insert mark), or None."""
        it = self._buf.get_iter_at_mark(self._buf.get_insert())
        return self._log_at_offset(it.get_offset())

    def _log_at_offset(self, off: int) -> dict | None:
        for i, (sm, em) in enumerate(self._log_marks):
            s = self._buf.get_iter_at_mark(sm).get_offset()
            e = self._buf.get_iter_at_mark(em).get_offset()
            if s <= off < e:
                return self._logs[i]
        return None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_highlights_internal(self) -> None:
        if not self._highlighters:
            return
        for word, color in self._highlighters.items():
            tag = self._get_or_create_hl_tag(word, color)
            self._apply_tag_for_word(word, tag.get_property("name"),
                                     case_sensitive=False)

    def _apply_tag_for_word(self, word: str, tag_name: str,
                            case_sensitive: bool = True) -> None:
        """
        Walk the buffer with forward_search and apply *tag_name* at every
        occurrence of *word*.  This uses buffer character offsets directly
        so it is immune to the invisible-tag / get_text offset mismatch.
        """
        flags = Gtk.TextSearchFlags.VISIBLE_ONLY
        if not case_sensitive:
            flags |= Gtk.TextSearchFlags.CASE_INSENSITIVE

        s_all, e_all = self._buf.get_bounds()
        cursor = s_all
        while True:
            result = cursor.forward_search(word, flags, e_all)
            if result is None:
                break
            match_s, match_e = result
            self._buf.apply_tag_by_name(tag_name, match_s, match_e)
            cursor = match_e

