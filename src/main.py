from __future__ import annotations

import asyncio
import logging
import re

from telethon import events

from .config import load_settings
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

    # Validate target is reachable.
    try:
        target_entity = await client.get_entity(settings.target_channel)
        log.info("Target resolved: id=%s", getattr(target_entity, "id", "?"))
    except Exception as e:
        log.error("Could not resolve TARGET_CHANNEL_ID=%r: %s", settings.target_channel, e)
        raise

    @client.on(events.NewMessage(chats=source_entities))
    async def handler(event):
        chat_id = event.chat_id
        msg_id = event.id
        text = (event.message.message or "").strip()
        chat_title = _chat_title(event)

        if storage.seen(chat_id, msg_id):
            log.debug("dedup skip chat=%s msg=%s", chat_id, msg_id)
            return

        if len(text) < MIN_TEXT_LEN or not _HAS_LETTER.search(text):
            storage.mark_seen(chat_id, msg_id, score=None, posted=False)
            return

        try:
            result = await matcher.evaluate(chat_title, text)
        except TransientAIError as e:
            # Do NOT mark seen — retry on next restart / next message.
            log.error("AI transient failure, not marking seen: %s", e)
            return
        except Exception as e:
            log.exception("matcher crashed on chat=%s msg=%s: %s", chat_id, msg_id, e)
            storage.mark_seen(chat_id, msg_id, score=None, posted=False)
            return

        if not result.is_vacancy:
            log.info("not_vacancy chat=%s msg=%s", chat_id, msg_id)
            storage.mark_seen(chat_id, msg_id, score=result.match_score, posted=False)
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
        storage.mark_seen(chat_id, msg_id, score=result.match_score, posted=posted)

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
