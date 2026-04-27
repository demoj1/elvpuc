"""Pure-Python helpers: time conversion, colours, markup."""

import colorsys
import random
import re
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib


def utc_to_local_ms(utc_str: str) -> str:
    """'2026-04-27T06:30:39.256Z'  →  '09:30:39.256'  (local, ms precision)."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return utc_str


def utc_to_local_sec(utc_str: str) -> str:
    """'2026-04-27T06:30:39.256Z'  →  '09:30:39'  (local, second precision)."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return utc_str


def heatmap_color(count: int, max_count: int) -> tuple[float, float, float]:
    """Return an (r, g, b) triple in [0..1] for a heatmap bar segment."""
    if count == 0:
        return (0.07, 0.07, 0.07)
    ratio = count / max_count
    hue   = 0.7 * (1 - ratio * 0.8)
    value = 0.3 + 0.7 * ratio
    return colorsys.hsv_to_rgb(hue, 0.9, value)


def rand_hl_color() -> str:
    """Return a random pastel hex colour string for text highlighting."""
    r = random.randint(180, 255)
    g = random.randint(180, 255)
    b = random.randint(120, 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def apply_highlights(text: str, highlighters: dict[str, str]) -> str:
    """
    Escape *text* for Pango markup, then wrap each highlighted word in
    a ``<span background="…">`` tag.  Returns a Pango markup string.
    """
    if not highlighters:
        return GLib.markup_escape_text(text)

    escaped = GLib.markup_escape_text(text)
    for word, color in highlighters.items():
        esc_word = GLib.markup_escape_text(word)
        pattern  = re.compile(re.escape(esc_word), re.IGNORECASE)
        escaped  = pattern.sub(
            lambda m: f'<span background="{color}">{m.group(0)}</span>',
            escaped,
        )
    return escaped


def filter_matches(log: dict, tokens: list[str]) -> bool:
    """
    Return True if *log* passes the offline filter.

    Token syntax:
      ``+word``  — must contain *word*
      ``-word``  — must NOT contain *word*
      ``word``   — must contain *word*
    """
    if not tokens:
        return True
    full = (log["time"] + " " + log["msg"]).lower()
    return all(
        (t[1:] in full     if t.startswith("+") else
         t[1:] not in full if t.startswith("-") else
         t in full)
        for t in tokens
    )
