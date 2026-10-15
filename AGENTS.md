# elk-search — Agent Guide

## Quick start

```bash
python3 main.py
```

Requires: `python-gobject` (GTK4), `requests`.
Install textual (unused now): `pip install textual --break-system-packages`

---

## Project layout

```
elk-search/
├── main.py                  # Entry point. Sets GSK_RENDERER=gl, runs ElkApp.
└── elk/
    ├── app.py               # ElkApp(Gtk.Application). do_startup installs CSS,
    │                        # do_activate creates window, push_scale, _start_fetch.
    │                        # Single-instance: second launch raises existing window.
    ├── config.py            # load() / save() — JSON at ~/.config/elk_config.
    │                        # Keys: url, index, limit, query, t_from, t_to,
    │                        #       offline_filter, query_history, highlighters,
    │                        #       log_sz, ui_scale
    │                        # Saved on window close-request.
    ├── elastic.py           # fetch(url, index, q, t_from, t_to, limit) → (hits, buckets)
    │                        # Pure HTTP, no GTK. Module-level requests.Session
    │                        # (keep-alive between searches / auto-refresh).
    │                        # Uses auto_date_histogram agg (250 buckets).
    ├── styles.py            # Three CSS providers on Gdk.Display:
    │                        #   STATIC_CSS    — colours, borders (PRIORITY_APPLICATION)
    │                        #   OVERRIDE_CSS  — rules that must beat the user's
    │                        #                   ~/.config/gtk-4.0/gtk.css (PRIORITY_USER + 1)
    │                        #   _scale_provider — font sizes (+10 priority), rebuilt on
    │                        #                     every Log font / UI scale change.
    │                        # BASE_UI_PT = 10; effective = round(10 * ui_scale).
    │                        # Monospace applied to: .log-header, .log-body, textview.
    ├── utils.py             # Pure helpers:
    │                        #   utc_to_local_ms / utc_to_local_sec
    │                        #   heatmap_color(count, max) → (r,g,b)
    │                        #   rand_hl_color() → "#rrggbb"
    │                        #   apply_highlights(text, hl_dict) → Pango markup str
    │                        #   filter_matches(text_lower, tokens) → bool
    ├── window.py            # ElkWindow — all UI layout and business logic.
    └── widgets/
        ├── heatmap.py       # HeatmapWidget(Gtk.DrawingArea)
        │                    #   • Cairo bar chart, height=42px
        │                    #   • Popover tooltip: created LAZILY on "realize" signal
        │                    #     (set_parent requires the widget to be realized first)
        │                    #   • Scroll wheel → zoom_range ±1
        │                    #   • Click → on_zoom_cb(t_from, t_to)
        ├── log_row.py       # LogRow — legacy, kept but not used in main flow.
        └── log_view.py      # LogView(Gtk.TextView) — single widget for ALL logs.
```

---

## LogView — key design decisions

### Why one TextView instead of many Labels
Thousands of `Gtk.Label` with `wrap=True` each have their own Pango layout.
On window resize GTK recomputes every layout → severe lag.
One `Gtk.TextView` has one layout for the entire content → smooth resize.

### TextTag structure
| Tag name | Purpose |
|---|---|
| `hdr` | Header line: bold, `paragraph-background=#dde8f5` |
| `body` | Message body: left-margin=16, `paragraph-background=#ffffff` |
| `sep` | Blank separator line: `paragraph-background=#dddddd` |
| `hidden` | `invisible=True` — used by filter to hide non-matching entries |
| `hl:<word>` | Per-word highlight background colours |

No automatic `[error]/[warning]/…` colouring — removed for speed
(5 case-insensitive `forward_search` passes over the whole buffer per render).

### Render (`set_logs`)
Builds into a **detached** `Gtk.TextBuffer` that shares the view's tag table,
then swaps it in with `set_buffer()`. Inserting into an attached buffer
invalidates the layout on every insert (~3× slower). Cursor/selection reset
on every fetch (same as before).

Per entry it stores:
- `_log_marks[i] = (start_mark, end_mark)` — **both left gravity**
  (see pitfall 7)
- `_search_text[i]` — lowercased `"time msg"`, computed once per fetch
- `_visible[i]` — current filter state

### Filter implementation
`apply_filter(tokens)` matches `_search_text` with `utils.filter_matches`,
and only touches entries whose visibility **flipped**. Consecutive flips in
the same direction are merged into one `apply_tag`/`remove_tag` over the
range (entries are contiguous). No widget rebuild.

Showing many hidden entries at once is still ~270ms / 2000 entries — that's
GTK relayout of the newly visible text, not fixable from Python.

### Highlight / search implementation
**Always use `TextIter.forward_search()`**, never `re.finditer()` + `get_iter_at_offset()`.

Reason: `TextBuffer.get_text()` skips invisible (hidden) characters, so byte/char offsets
from `re.finditer` don't match buffer positions when a filter is active.
`forward_search` returns `(match_start, match_end)` as `TextIter` objects that are always
correct regardless of visibility.

```python
cursor = buf.get_start_iter()
while result := cursor.forward_search(word, flags, end):
    match_s, match_e = result
    buf.apply_tag(tag, match_s, match_e)
    cursor = match_e
```

### Record lookup
`log_at_location(x, y)` (right click) and `log_at_cursor()` (V key) map a
buffer offset to an entry via `_log_at_offset()` over `_log_marks`.

---

## Window architecture (elk/window.py)

### Render pipeline
```
fetch() [thread] → queue → _poll_queue() [GLib timer]
  → _render_logs()          # full rebuild: log_view.set_logs()
    → _apply_filter()       # show/hide via hidden tag
    → heatmap.update_data()
```

Filter changes (debounced 120ms) call only `_apply_filter()` — no rebuild.
Auto ⟳ toggle re-runs `_start_fetch()` every `_AUTO_REFRESH_S` (10s);
no-op while a fetch is in flight.

### Highlight pipeline
```
[Ctrl+Space] → _try_add_highlight()
  → _focused_selection()
  → toggle: add or remove from self._highlighters
  → log_view.refresh_highlights()
    → _remove_all_hl_tags()
    → _apply_tag_for_word() for each word  # uses forward_search
```

### Selection source — `_focused_selection(from_menu=False)`
Used by highlight / quick filter / quick query. Returns the selection from
the **focused** widget only: the log view, or a selectable `Gtk.Label`.

The log keeps its selection after focus moves to an entry, so without the
focus check typing `a`/`d` in Filter/URL would add filter tokens.
Context menu actions pass `from_menu=True` and skip the check — the popover
takes focus.

### Label selection (byte offset caveat)
`Gtk.Label.get_selection_bounds()` returns `(has_sel, start_b, end_b)` where
`start_b` and `end_b` are **byte offsets** into the UTF-8 Pango layout text,
and `end_b` is **inclusive** (last selected byte, not past-end).

Correct extraction:
```python
plain_utf8 = label.get_layout().get_text().encode("utf-8")
text = plain_utf8[start_b : end_b + 1].decode("utf-8").strip()
```

### Quick filter (A / D keys)
`_try_add_filter(include=True/False)`:
- Gets selection via `_focused_selection()`
- Appends `+word` (A) or `-word` (D) to filter entry
- Calls `_filter_fire()` immediately (bypasses debounce)

### Quick query (Shift+A / Shift+D keys)
`_try_add_query(include=True/False)`:
- Gets selection via `_focused_selection()`
- Appends `+"word"` (Shift+A) or `-"word"` (Shift+D) to the Lucene query TextBuffer
- Quotes are required for Lucene phrase matching
- Moves focus to query view after insert

### Full record (V / right click → Show all fields)
`_show_record_details(log)` opens a non-modal "Full record" window with the
whole `_source` as pretty JSON. Esc closes it. V works only while the log
view has focus (record under the text cursor).

### Context menu
`Gio.Menu` + `Gtk.PopoverMenu`, actions in a `ctx` action group on the window.
Right click is caught by a `GestureClick` (button 3) in CAPTURE phase, so the
TextView's own menu never appears (`set_extra_menu(None)`).

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+R` / `F5` | Search |
| `Ctrl+F` | Focus Filter |
| `Ctrl+S` | Focus Query |
| `Ctrl+Enter` | Search (from Query field) |
| `Ctrl+Space` | Toggle highlight on selection |
| `A` | Append `+selection` to offline filter |
| `D` | Append `-selection` to offline filter |
| `Shift+A` | Append `+"selection"` to Lucene query |
| `Shift+D` | Append `-"selection"` to Lucene query |
| `V` | Full record under text cursor (log focused) |
| `Esc` | Close full record window |
| `Alt+U/I/S/L/F/T` | Mnemonic focus: URL/Index/Search/Limit/From/To |

All handled via `EventControllerKey` with `PropagationPhase.CAPTURE` on the window,
so they fire before child widgets process the key. Letter keys are matched
layout-independently (`_latin_keyval` scans all keyboard groups → works on ЙЦУКЕН).
A/D/V/Ctrl+Space return `False` (key passes through) when there's nothing to act on.

---

## Filter token syntax

| Token | Meaning |
|---|---|
| `word` | message must contain word |
| `+word` | must contain (explicit) |
| `-word` | must NOT contain |

Multiple tokens are ANDed. Case-insensitive.

---

## CSS / styling notes

- `.toolbar-row`: `min-height: 28px; max-height: 28px`
- `entry`, `button`, `spinbutton`: `max-height: 22px`
- Field width via CSS classes (not `set_width_chars`):
  `.entry-url` (max 180px, hexpand), `.entry-index` (140px),
  `.entry-limit` (44–50px), `.entry-time` (120–190px), `.entry-filter` (min 450px)
- `.entry-url:not(:focus-within) > text { filter: blur(5px) }` — hides credentials
  in screenshots; visual only, copy still gets the real text
- Statusbar hotkey hints label is ellipsized → shrinks first, filter keeps its room
- Time presets `.btn-preset` are tightened in `OVERRIDE_CSS` (see pitfall 8).
  Window min width at UI scale 1.45 is ~1010px, bound by toolbar row 2.
- `textview { background: #ffffff }` — overrides GTK default grey
- `.heatmap-popover contents { background: #1e1e1e }` + `.heatmap-tip { color: #f0f0f0 }`
- `paragraph-background` on TextTag fills full line width; `background` only covers glyphs

---

## Common pitfalls

1. **Popover `set_parent` before realize** — always create Popover inside a `"realize"` signal handler, not in `__init__`.

2. **`get_text()` + `re.finditer` + `get_iter_at_offset`** — broken when `hidden` tag is active. Use `forward_search` instead.

3. **`Gtk.Label.get_selection_bounds` end offset** — is inclusive (last byte), not exclusive. Use `[start:end+1]`.

4. **`set_width_chars` with large UI scale** — makes fields huge. Use CSS `min-width`/`max-width` in px instead.

5. **`Gtk.Scale` in toolbar row** — tall by default, use `Gtk.SpinButton` for compact numeric input.

6. **`paragraph-background` vs `background` on TextTag** — `background` only covers text glyphs; `paragraph-background` fills the full line width.

7. **Mark gravity when appending** — a right-gravity mark (`create_mark(..., False)`) at the
   insert point moves with every later insert, so it ends up at buffer end. Per-entry
   end marks must be left gravity, otherwise every entry spans to the end of the log
   (record lookup returns the first entry, hiding one entry hides everything after it).

8. **User `~/.config/gtk-4.0/gtk.css` beats app CSS** — it's loaded at `PRIORITY_USER` (800)
   > `PRIORITY_APPLICATION` (600), regardless of selector specificity. E.g. Materia sets
   `.toolbar button.text-button { min-width: 48px }`. Put such overrides in
   `OVERRIDE_CSS` (`PRIORITY_USER + 1`), keep the rest in `STATIC_CSS`.

9. **Removing a tag that was never applied is a no-op** — GTK doesn't even invalidate
   layout for it, so it can't be used as a "force relayout" trick.

10. **Sending keys with `wtype` / clicking for UI tests** — Hyprland may not move focus
    to the app window, and the keys land in the user's active window. Test UI with an
    isolated script (own window, programmatic `grab_focus`, `grim` screenshot) instead.
