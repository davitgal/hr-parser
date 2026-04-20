from __future__ import annotations

from pathlib import Path


def load_profile(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Profile file is empty: {path}")
    return text
