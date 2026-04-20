from __future__ import annotations

import logging
from typing import Iterable

from telethon import TelegramClient
from telethon.sessions import StringSession

log = logging.getLogger(__name__)


def build_client(api_id: int, api_hash: str, session: str) -> TelegramClient:
    return TelegramClient(StringSession(session), api_id, api_hash)


async def resolve_sources(
    client: TelegramClient, sources: Iterable[str | int]
) -> list:
    resolved = []
    for src in sources:
        try:
            entity = await client.get_entity(src)
            resolved.append(entity)
            log.info("Resolved source %r -> id=%s", src, getattr(entity, "id", "?"))
        except Exception as e:
            log.error("Failed to resolve source %r: %s", src, e)
    if not resolved:
        raise RuntimeError("No sources could be resolved")
    return resolved
