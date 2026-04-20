from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError

from .matcher import MatchResult

log = logging.getLogger(__name__)


def _escape_md(s: str) -> str:
    # Telethon "md" mode uses standard Markdown; escape chars that could break formatting.
    return s.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")


def _format(match: MatchResult, chat_title: str, source_link: str | None) -> str:
    title = _escape_md(match.title or "Vacancy")
    company = _escape_md(match.company) if match.company else ""
    header = f"*{title}*"
    if company:
        header += f" — {company}"

    stack = ", ".join(match.stack) if match.stack else "—"
    red = ", ".join(match.red_flags) if match.red_flags else "—"
    salary = match.salary or "—"
    remote = match.remote or "unknown"
    grade = match.grade or "unknown"
    reasoning = _escape_md(match.reasoning or "")

    lines = [
        header,
        f"Score: {match.match_score}/100 · grade: {_escape_md(grade)} · remote: {_escape_md(remote)}",
        f"Stack: {_escape_md(stack)}",
        f"Salary: {_escape_md(salary)}",
        f"Red flags: {_escape_md(red)}",
        "",
        reasoning,
    ]
    src_line = f"Source: {_escape_md(chat_title)}"
    if source_link:
        src_line += f" · {source_link}"
    lines.extend(["", src_line])
    return "\n".join(lines)


def _source_link(chat_id: int, msg_id: int) -> str | None:
    # For channels/supergroups chat_id has the -100 prefix in Telethon raw form.
    s = str(chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{msg_id}"
    return None


async def post_match(
    client: TelegramClient,
    target: str | int,
    match: MatchResult,
    chat_title: str,
    chat_id: int,
    msg_id: int,
) -> None:
    text = _format(match, chat_title, _source_link(chat_id, msg_id))
    for attempt in range(3):
        try:
            await client.send_message(target, text, parse_mode="md", link_preview=False)
            return
        except FloodWaitError as e:
            log.warning("FloodWait on publish: sleeping %ds", e.seconds)
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            log.error("send_message failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    log.error("Giving up publishing match for chat=%s msg=%s", chat_id, msg_id)
