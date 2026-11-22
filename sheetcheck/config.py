"""Loads config.yaml (settings a non-programmer may want to change)."""
from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import yaml

from .verification import Settings

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"

DEFAULTS = {
    "verification": {
        "tax_rate": "0.05",
        "rounding_unit": "10000",
        "tax_tolerance": "0",
    },
    "extraction": {
        "model": "qwen3-vl:4b-instruct",
        "max_image_side": 2400,
        "num_ctx": 4096,
        "strip_ratio": 1.5,
        "summary_strip_ratio": 1.5,
        "sheet_hint": "",
        "summary_hint": "",
    },
    "form": {
        "template": "templates/form_template.xlsx",
        "sheet": None,
        "cells": {
            "name": "C3",
            "serial_from": "C4",
            "serial_to": "E4",
            "date": "C5",
            "month": "E5",
            "total": "C7",
            "tax": "C8",
            "rounding": "C9",
            "stamp": "C10",
            "notes": "B12",
        },
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    user = {}
    if path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = _merge(DEFAULTS, user)
    # The cell map is replaced, not merged, so a key removed from the file stays removed.
    if isinstance(user.get("form", {}).get("cells"), dict):
        cfg["form"]["cells"] = dict(user["form"]["cells"])
    return cfg


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def verification_settings(cfg: dict) -> Settings:
    v = cfg["verification"]
    return Settings(
        tax_rate=Decimal(str(v["tax_rate"])),
        rounding_unit=Decimal(str(v["rounding_unit"])),
        tax_tolerance=Decimal(str(v["tax_tolerance"])),
    )
