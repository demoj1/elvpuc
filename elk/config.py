"""Persistent configuration: load / save JSON from ~/.config/elk_config."""

import json
import os

CONFIG_FILE = os.path.expanduser("~/.config/elk_config")

DEFAULTS: dict = {
    "url":            "",
    "index":          "",
    "limit":          "250",
    "query":          "*",
    "t_from":         "now-15m",
    "t_to":           "now",
    "offline_filter": "",
    "query_history":  [],
    "highlighters":   {},
    "log_sz":         12,
    "ui_scale":       1.0,
}


def load() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        # Fill any missing keys with defaults
        return {**DEFAULTS, **data}
    except Exception:
        return dict(DEFAULTS)


def save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
