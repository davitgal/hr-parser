from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

log = logging.getLogger(__name__)


STATIC_INSTRUCTIONS = """\
You are an AI HR assistant. You receive a single Telegram message that MAY be a job vacancy, \
and you evaluate it against the user's profile provided in <profile> in the system prompt.

Task:
1. First decide if the message is actually a job vacancy (not a reaction, question, news, \
repost intro, ad for a course, resume, etc.). If not, return a stub with is_vacancy=false and \
match_score=0 (other fields can be empty strings or empty arrays).
2. If it is a vacancy, extract the structured fields AND score how well it fits the user's \
profile (0-100). Score strictly: 100 = perfect fit on stack, grade, salary, remote, geo, \
language. Heavily penalise red flags and violations of the user's Preferences (avoided stack, \
below salary floor, wrong remote policy, wrong grade, listed red flags). A mismatch on a hard \
preference should drop the score below 40.

Output contract — ONLY valid JSON, no prose, no markdown fences, no explanations outside JSON:
{
  "is_vacancy": true|false,
  "title": "string",
  "company": "string",
  "stack": ["string", ...],
  "grade": "junior|middle|senior|staff|lead|unknown",
  "salary": "string",
  "remote": "full|hybrid|onsite|unknown",
  "match_score": 0-100,
  "reasoning": "max 2 short sentences, in the user's language",
  "red_flags": ["string", ...],
  "should_apply": true|false
}

Rules:
- reasoning: 2 sentences max, concrete (e.g., "Go + Kafka совпадают, senior, remote, зп выше floor" \
or "Требуют Java, твой основной — Go; remote нет").
- should_apply = (match_score >= 70 AND no hard red_flags).
- Never hallucinate salary/stack — if not mentioned, use empty string or empty array, grade/remote = "unknown".
- Keep extracted values short, don't copy the whole message.
"""


@dataclass
class MatchResult:
    is_vacancy: bool
    title: str
    company: str
    stack: list[str]
    grade: str
    salary: str
    remote: str
    match_score: int
    reasoning: str
    red_flags: list[str]
    should_apply: bool


class TransientAIError(Exception):
    """Raised on 429/5xx after retries so caller can skip mark_seen."""


def _clamp(n: Any) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, v))


def _parse(raw: str) -> MatchResult:
    data = json.loads(raw)
    return MatchResult(
        is_vacancy=bool(data.get("is_vacancy", False)),
        title=str(data.get("title", "") or ""),
        company=str(data.get("company", "") or ""),
        stack=[str(x) for x in (data.get("stack") or []) if x],
        grade=str(data.get("grade", "unknown") or "unknown"),
        salary=str(data.get("salary", "") or ""),
        remote=str(data.get("remote", "unknown") or "unknown"),
        match_score=_clamp(data.get("match_score", 0)),
        reasoning=str(data.get("reasoning", "") or "").strip(),
        red_flags=[str(x) for x in (data.get("red_flags") or []) if x],
        should_apply=bool(data.get("should_apply", False)),
    )


class Matcher:
    def __init__(self, api_key: str, model: str, profile_md: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._system = [
            {"type": "text", "text": STATIC_INSTRUCTIONS},
            {
                "type": "text",
                "text": f"<profile>\n{profile_md}\n</profile>",
                "cache_control": {"type": "ephemeral"},
            },
        ]

    async def evaluate(self, chat_title: str, text: str) -> MatchResult:
        user = (
            f"<source_chat>{chat_title}</source_chat>\n"
            f"<message>\n{text}\n</message>\n\n"
            "Return ONLY valid JSON matching the schema."
        )

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.messages.create(
                    model=self._model,
                    max_tokens=600,
                    system=self._system,
                    messages=[{"role": "user", "content": user}],
                )
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    log.debug(
                        "tokens in=%s out=%s cache_read=%s cache_create=%s",
                        getattr(usage, "input_tokens", "?"),
                        getattr(usage, "output_tokens", "?"),
                        getattr(usage, "cache_read_input_tokens", 0),
                        getattr(usage, "cache_creation_input_tokens", 0),
                    )
                raw = resp.content[0].text if resp.content else "{}"
                return _parse(raw)
            except (
                anthropic.RateLimitError,
                anthropic.APIStatusError,
                anthropic.APIConnectionError,
            ) as e:
                last_err = e
                status = getattr(e, "status_code", None)
                if isinstance(e, anthropic.APIStatusError) and status is not None and status < 500 and status != 429:
                    raise
                wait = 2 ** attempt
                log.warning("Anthropic transient error (attempt %d): %s; sleeping %ds", attempt + 1, e, wait)
                await asyncio.sleep(wait)
            except json.JSONDecodeError as e:
                log.error("Claude returned non-JSON, treating as not-a-vacancy: %s", e)
                return MatchResult(
                    is_vacancy=False, title="", company="", stack=[], grade="unknown",
                    salary="", remote="unknown", match_score=0,
                    reasoning="parse_error", red_flags=[], should_apply=False,
                )
        raise TransientAIError(f"Anthropic failed after retries: {last_err}")
