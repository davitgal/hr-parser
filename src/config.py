from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    tg_api_id: int
    tg_api_hash: str
    tg_session: str
    anthropic_api_key: str
    target_channel: str | int
    threshold: int
    db_path: str
    sources_path: str
    profile_path: str
    model: str
    log_level: str
    sources: tuple[str | int, ...]


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _parse_channel(raw: str) -> str | int:
    raw = raw.strip()
    if raw.startswith("-") or raw.isdigit():
        return int(raw)
    return raw


def _load_sources(path: str) -> tuple[str | int, ...]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chats = data.get("chats", [])
    if not isinstance(chats, list) or not chats:
        raise RuntimeError(f"{path} must contain a non-empty 'chats' array")
    out: list[str | int] = []
    for item in chats:
        if isinstance(item, int):
            out.append(item)
        elif isinstance(item, str) and item.strip():
            out.append(item.strip())
        else:
            raise RuntimeError(f"Invalid source entry in {path}: {item!r}")
    return tuple(out)


def load_settings() -> Settings:
    load_dotenv()

    sources_path = os.environ.get("SOURCES_PATH", "sources.json")
    profile_path = os.environ.get("PROFILE_PATH", "profile.md")

    if not Path(profile_path).is_file():
        raise RuntimeError(f"Profile file not found: {profile_path}")
    if not Path(sources_path).is_file():
        raise RuntimeError(f"Sources file not found: {sources_path}")

    return Settings(
        tg_api_id=int(_require("TG_API_ID")),
        tg_api_hash=_require("TG_API_HASH"),
        tg_session=_require("TG_SESSION"),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        target_channel=_parse_channel(_require("TARGET_CHANNEL_ID")),
        threshold=int(os.environ.get("MATCH_THRESHOLD", "70")),
        db_path=os.environ.get("DB_PATH", "state.db"),
        sources_path=sources_path,
        profile_path=profile_path,
        model=os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        sources=_load_sources(sources_path),
    )
