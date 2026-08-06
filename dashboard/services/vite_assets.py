"""Resolve locally built Vite entry assets without exposing build internals."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


@lru_cache(maxsize=8)
def vite_entry_assets(bundle: str, entry: str = "src/main.tsx") -> dict[str, object]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", bundle):
        return {"available": False, "js": "", "css": []}
    manifest_path = STATIC_ROOT / bundle / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        item = manifest[entry]
        js_file = str(item["file"])
        css_files = [str(value) for value in item.get("css", [])]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"available": False, "js": "", "css": []}
    safe_prefix = f"{bundle}/"
    if any(".." in Path(value).parts for value in [js_file, *css_files]):
        return {"available": False, "js": "", "css": []}
    return {
        "available": True,
        "js": safe_prefix + js_file,
        "css": [safe_prefix + value for value in css_files],
    }
