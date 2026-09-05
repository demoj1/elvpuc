"""LogView — single TextView that renders all log entries efficiently."""

import re

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from elk.utils import utc_to_local_ms

_TAG_HEADER  = "hdr"
_TAG_BODY    = "body"
_TAG_SEP     = "sep"
_TAG_HIDDEN  = "hidden"
_HL_PREFIX   = "hl:"

# Log-level accent colors (matched in the first line of message)
_LEVEL_TAGS = {
    "error":   ("lvl:error",   "#c0392b"),
    "warning": ("lvl:warning", "#e67e22"),
    "warn":    ("lvl:warn",    "#e67e22"),
    "info":    ("lvl:info",    "#27ae60"),
    "debug":   ("lvl:debug",   "#2980b9"),
}


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

        # Log-level accent tags
        for tag_name, color in _LEVEL_TAGS.values():
            add(tag_name, foreground=color, weight=Pango.Weight.BOLD)

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

        # Freeze notifications to avoid incremental redraws during insert
        self._buf.set_text("")
        self._remove_all_hl_tags()

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

            end_mark = self._buf.create_mark(None, end, False)
            self._log_marks.append((start_mark, end_mark))

        self._apply_level_colors()
        self._apply_highlights_internal()

    def apply_filter(self, tokens: list[str]) -> int:
        """Show/hide entries via the 'hidden' tag.  Returns visible count."""
        if not self._log_marks:
            return 0
        visible = 0
        for i, log in enumerate(self._logs):
            sm, em = self._log_marks[i]
            s = self._buf.get_iter_at_mark(sm)
            e = self._buf.get_iter_at_mark(em)
            if _filter_match(log, tokens):
                self._buf.remove_tag_by_name(_TAG_HIDDEN, s, e)
                visible += 1
            else:
                self._buf.apply_tag_by_name(_TAG_HIDDEN, s, e)
        return visible

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
        off = it.get_offset()
        for i, (sm, em) in enumerate(self._log_marks):
            s = self._buf.get_iter_at_mark(sm).get_offset()
            e = self._buf.get_iter_at_mark(em).get_offset()
            if s <= off < e:
                return self._logs[i]
        return None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_level_colors(self) -> None:
        """Color [error]/[info]/[warn] tokens using TextIter search."""
        for keyword, (tag_name, _) in _LEVEL_TAGS.items():
            needle = f"[{keyword}]"
            self._apply_tag_for_word(needle, tag_name, case_sensitive=False)

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


# ── Filter helper ─────────────────────────────────────────────────────────────

def _filter_match(log: dict, tokens: list[str]) -> bool:
    if not tokens:
        return True
    full = (log["time"] + " " + log["msg"]).lower()
    return all(
        (t[1:] in full     if t.startswith("+") else
         t[1:] not in full if t.startswith("-") else
         t in full)
        for t in tokens
    )
