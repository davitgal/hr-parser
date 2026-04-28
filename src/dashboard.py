from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone

from aiohttp import web

from .storage import Storage

log = logging.getLogger("hr-parser.dashboard")


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _channel_label(c: dict) -> str:
    title = c.get("title") or "?"
    username = c.get("username")
    if username:
        return f"{title} (@{username})"
    return title


def _source_link(chat_id: int | None, msg_id: int | None) -> str | None:
    if chat_id is None or msg_id is None:
        return None
    s = str(chat_id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{msg_id}"
    return None


def _render(overall: dict, channels: list[dict], matches: list[dict], threshold: int) -> str:
    rows_channels = []
    for c in channels:
        label = html.escape(_channel_label(c))
        avg = c["avg_score"] if c["avg_score"] is not None else "—"
        last = _fmt_ts(c["last_msg_ts"])
        rows_channels.append(
            f"<tr>"
            f"<td>{label}</td>"
            f"<td class='num'>{c['total']}</td>"
            f"<td class='num'>{c['vacancies']}</td>"
            f"<td class='num'>{c['posted']}</td>"
            f"<td class='num'>{avg}</td>"
            f"<td class='num'>{c['max_score']}</td>"
            f"<td>{last}</td>"
            f"</tr>"
        )
    channels_html = "\n".join(rows_channels) or "<tr><td colspan='7'>no data yet</td></tr>"

    rows_matches = []
    for m in matches:
        link = _source_link(m["chat_id"], m["msg_id"])
        title = html.escape(m["title"] or "—")
        chan = html.escape(m["channel_title"] or str(m["chat_id"]))
        ts = _fmt_ts(m["ts"])
        title_cell = f"<a href='{link}' target='_blank'>{title}</a>" if link else title
        rows_matches.append(
            f"<tr>"
            f"<td>{ts}</td>"
            f"<td>{chan}</td>"
            f"<td>{title_cell}</td>"
            f"<td class='num'>{m['score']}</td>"
            f"</tr>"
        )
    matches_html = "\n".join(rows_matches) or "<tr><td colspan='4'>no matches yet</td></tr>"

    last_overall = _fmt_ts(overall["last_ts"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Victoria — HR matcher dashboard</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #161a22; --border: #232936;
    --text: #e6e9ef; --muted: #9aa3b2; --accent: #7c5cff;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: var(--bg); color: var(--text); margin: 0; padding: 32px; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .sub {{ color: var(--muted); margin-bottom: 28px; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 32px; }}
  .stat {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .stat .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
  .stat .value {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
  h2 {{ font-size: 16px; margin: 28px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--panel);
           border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px; }}
  th, td {{ padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ background: #1c2230; color: var(--muted); font-weight: 500; font-size: 11px;
        text-transform: uppercase; letter-spacing: .04em; }}
  tr:last-child td {{ border-bottom: 0; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>
  <h1>Victoria — HR matcher</h1>
  <div class="sub">threshold = {threshold} · last activity {last_overall}</div>

  <div class="grid">
    <div class="stat"><div class="label">Total seen</div><div class="value">{overall['total']}</div></div>
    <div class="stat"><div class="label">Vacancies</div><div class="value">{overall['vacancies']}</div></div>
    <div class="stat"><div class="label">Not vacancies</div><div class="value">{overall['not_vacancies']}</div></div>
    <div class="stat"><div class="label">Posted (matched)</div><div class="value">{overall['posted']}</div></div>
    <div class="stat"><div class="label">Channels tracked</div><div class="value">{len(channels)}</div></div>
  </div>

  <h2>Per-channel stats</h2>
  <table>
    <thead><tr>
      <th>Channel</th><th class="num">Seen</th><th class="num">Vacancies</th>
      <th class="num">Posted</th><th class="num">Avg score</th><th class="num">Max score</th><th>Last activity</th>
    </tr></thead>
    <tbody>{channels_html}</tbody>
  </table>

  <h2>Recent matches</h2>
  <table>
    <thead><tr>
      <th>Time</th><th>Channel</th><th>Title</th><th class="num">Score</th>
    </tr></thead>
    <tbody>{matches_html}</tbody>
  </table>

  <div class="footer">Refresh the page to update.</div>
</body>
</html>"""


def make_app(storage: Storage, threshold: int, token: str) -> web.Application:
    async def index(request: web.Request) -> web.Response:
        if token and request.query.get("token") != token:
            return web.Response(text="unauthorized", status=401)
        overall = storage.overall_stats()
        channels = storage.channel_stats()
        matches = storage.recent_matches(limit=30)
        body = _render(overall, channels, matches, threshold)
        return web.Response(text=body, content_type="text/html")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    return app


async def start_dashboard(storage: Storage, threshold: int) -> None:
    port = int(os.environ.get("PORT", "0"))
    if not port:
        log.info("Dashboard disabled (PORT not set).")
        return
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token:
        log.warning("DASHBOARD_TOKEN not set — dashboard is publicly accessible. Set the env var to require ?token=...")
    app = make_app(storage, threshold, token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Dashboard listening on :%d (token_required=%s)", port, bool(token))
