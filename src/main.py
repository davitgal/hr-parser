from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from telethon import events, utils

from .config import load_settings
from .dashboard import start_dashboard
from .matcher import Matcher, TransientAIError
from .profile import load_profile
from .publisher import post_match
from .storage import Storage
from .telegram_client import build_client, resolve_sources

log = logging.getLogger("hr-parser")

MIN_TEXT_LEN = 40
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _chat_title(event) -> str:
    chat = event.chat
    if chat is None:
        return "unknown"
    for attr in ("title", "username", "first_name"):
        v = getattr(chat, attr, None)
        if v:
            return str(v)
    return str(getattr(chat, "id", "unknown"))


async def _run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    profile_md = load_profile(settings.profile_path)
    log.info("Profile loaded (%d chars)", len(profile_md))

    storage = Storage(settings.db_path)
    matcher = Matcher(settings.anthropic_api_key, settings.model, profile_md)
    client = build_client(settings.tg_api_id, settings.tg_api_hash, settings.tg_session)

    await client.start()
    me = await client.get_me()
    log.info("Connected as %s (id=%s)", getattr(me, "username", None) or getattr(me, "first_name", "?"), me.id)

    source_entities = await resolve_sources(client, settings.sources)
    log.info("Monitoring %d sources; target=%s; threshold=%d", len(source_entities), settings.target_channel, settings.threshold)

    for entity in source_entities:
        chat_id = utils.get_peer_id(entity)
        username = getattr(entity, "username", None)
        title = getattr(entity, "title", None) or username or str(chat_id)
        storage.register_channel(chat_id, username, title)

    await start_dashboard(storage, settings.threshold)

    # Validate target is reachable.
    try:
        target_entity = await client.get_entity(settings.target_channel)
        log.info("Target resolved: id=%s", getattr(target_entity, "id", "?"))
    except Exception as e:
        log.error("Could not resolve TARGET_CHANNEL_ID=%r: %s", settings.target_channel, e)
        raise

    async def process_message(chat_id, msg_id, text, chat_title, *, source: str):
        log.info("incoming src=%s chat=%s msg=%s len=%d title=%r", source, chat_id, msg_id, len(text), chat_title)

        if storage.seen(chat_id, msg_id):
            log.info("dedup_skip chat=%s msg=%s", chat_id, msg_id)
            return

        if len(text) < MIN_TEXT_LEN or not _HAS_LETTER.search(text):
            log.info("too_short_skip chat=%s msg=%s len=%d", chat_id, msg_id, len(text))
            storage.record_message(chat_id, msg_id, is_vacancy=False, score=None, posted=False)
            return

        try:
            result = await matcher.evaluate(chat_title, text)
        except TransientAIError as e:
            log.error("AI transient failure, not marking seen: %s", e)
            return
        except Exception as e:
            log.exception("matcher crashed on chat=%s msg=%s: %s", chat_id, msg_id, e)
            storage.record_message(chat_id, msg_id, score=None, posted=False)
            return

        if not result.is_vacancy:
            log.info("not_vacancy chat=%s msg=%s", chat_id, msg_id)
            storage.record_message(chat_id, msg_id, is_vacancy=False, score=result.match_score, posted=False)
            return

        posted = False
        if result.match_score >= settings.threshold:
            try:
                await post_match(client, settings.target_channel, result, chat_title, chat_id, msg_id)
                posted = True
            except Exception as e:
                log.exception("publish failed: %s", e)

        log.info(
            "evaluated chat=%s msg=%s score=%d posted=%s title=%r",
            chat_id, msg_id, result.match_score, posted, result.title,
        )
        storage.record_message(
            chat_id, msg_id, is_vacancy=True, score=result.match_score, posted=posted, title=result.title,
        )

    @client.on(events.NewMessage(chats=source_entities))
    async def handler(event):
        text = (event.message.message or "").strip()
        await process_message(event.chat_id, event.id, text, _chat_title(event), source="live")

    backfill_hours = int(os.environ.get("BACKFILL_HOURS", "0"))
    if backfill_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=backfill_hours)
        log.info("Backfill: scanning last %d hours from each source", backfill_hours)
        for entity in source_entities:
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(getattr(entity, "id", "?"))
            chat_id = utils.get_peer_id(entity)
            count = 0
            async for msg in client.iter_messages(entity, limit=200):
                if msg.date and msg.date < cutoff:
                    break
                text = (msg.message or "").strip()
                await process_message(chat_id, msg.id, text, title, source="backfill")
                count += 1
            log.info("Backfill done for %s (id=%s): %d messages scanned", title, chat_id, count)
        log.info("Backfill complete.")

    log.info("Listening. Ctrl+C to stop.")
    try:
        await client.run_until_disconnected()
    finally:
        storage.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
