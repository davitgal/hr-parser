from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from aiohttp import web

from .storage import Storage

log = logging.getLogger("hr-parser.dashboard")

FILTER_LABELS = {
    "all": "All messages",
    "vacancies": "Vacancies",
    "not_vacancies": "Not vacancies",
    "posted": "Posted matches",
}


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _channel_label(c: dict) -> str:
    title = c.get("title") or c.get("channel_title") or "?"
    username = c.get("username") or c.get("channel_username")
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


def _qs(token: str, **params) -> str:
    q = {k: v for k, v in params.items() if v is not None and v != ""}
    if token:
        q["token"] = token
    return ("?" + urlencode(q)) if q else ""


_BASE_CSS = """
:root {
  --bg: #0f1115; --panel: #161a22; --border: #232936;
  --text: #e6e9ef; --muted: #9aa3b2; --accent: #7c5cff;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
       background: var(--bg); color: var(--text); margin: 0; padding: 32px; }
h1 { margin: 0 0 4px; font-size: 22px; }
h2 { font-size: 16px; margin: 28px 0 12px; }
.sub { color: var(--muted); margin-bottom: 28px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 32px; }
.stat { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
        padding: 14px 16px; text-decoration: none; color: inherit; display: block;
        transition: border-color .15s, transform .15s; }
.stat:hover { border-color: var(--accent); transform: translateY(-1px); }
.stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
.stat .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; background: var(--panel);
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: #1c2230; color: var(--muted); font-weight: 500; font-size: 11px;
     text-transform: uppercase; letter-spacing: .04em; }
tr:last-child td { border-bottom: 0; }
tr.clickable { cursor: pointer; }
tr.clickable:hover td { background: #1c2230; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
       border: 1px solid var(--border); color: var(--muted); }
.tag.posted { color: #7eecbb; border-color: #2c6748; }
.tag.vac { color: #ffd07e; border-color: #6f5022; }
.tag.notvac { color: #9aa3b2; }
.footer { color: var(--muted); font-size: 12px; margin-top: 24px; }
.back { color: var(--muted); font-size: 13px; margin-bottom: 16px; display: inline-block; }

.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.55);
            opacity: 0; pointer-events: none; transition: opacity .18s; z-index: 100; }
.backdrop.open { opacity: 1; pointer-events: auto; }
.drawer { position: fixed; top: 0; right: 0; height: 100vh;
          width: min(960px, 92vw); background: var(--bg);
          border-left: 1px solid var(--border); transform: translateX(100%);
          transition: transform .22s ease-out; z-index: 101;
          overflow-y: auto; box-shadow: -8px 0 24px rgba(0,0,0,0.4); }
.drawer.open { transform: translateX(0); }
.drawer-header { position: sticky; top: 0; background: var(--bg);
                 padding: 16px 24px; border-bottom: 1px solid var(--border);
                 display: flex; justify-content: space-between; align-items: center;
                 z-index: 1; }
.drawer-header h2 { margin: 0; font-size: 14px; color: var(--muted); font-weight: 500;
                    text-transform: uppercase; letter-spacing: .04em; }
.drawer-close { background: transparent; border: 1px solid var(--border); color: var(--text);
                padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.drawer-close:hover { border-color: var(--accent); }
.drawer-body { padding: 20px 24px; }
.drawer-body h1 { font-size: 18px; margin-bottom: 4px; }"""


def _render_index(overall: dict, channels: list[dict], matches: list[dict], threshold: int, token: str) -> str:
    rows_channels = []
    for c in channels:
        label = html.escape(_channel_label(c))
        avg = c["avg_score"] if c["avg_score"] is not None else "—"
        last = _fmt_ts(c["last_msg_ts"])
        href = "/list" + _qs(token, channel=c["chat_id"])
        rows_channels.append(
            f"<tr class='clickable' data-drawer='{href}' onclick=\"location.href='{href}'\">"
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
            f"<tr><td>{ts}</td><td>{chan}</td><td>{title_cell}</td><td class='num'>{m['score']}</td></tr>"
        )
    matches_html = "\n".join(rows_matches) or "<tr><td colspan='4'>no matches yet</td></tr>"

    last_overall = _fmt_ts(overall["last_ts"])

    def card(label: str, value: int, ftype: str | None) -> str:
        if ftype:
            href = "/list" + _qs(token, type=ftype)
            return (
                f"<a class='stat' href='{href}' data-drawer='{href}'>"
                f"<div class='label'>{label}</div><div class='value'>{value}</div></a>"
            )
        return (
            f"<div class='stat'>"
            f"<div class='label'>{label}</div><div class='value'>{value}</div></div>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Victoria — HR matcher</title><style>{_BASE_CSS}</style></head>
<body>
  <h1>Victoria — HR matcher</h1>
  <div class="sub">threshold = {threshold} · last activity {last_overall}</div>

  <div class="grid">
    {card("Total seen", overall['total'], "all")}
    {card("Vacancies", overall['vacancies'], "vacancies")}
    {card("Not vacancies", overall['not_vacancies'], "not_vacancies")}
    {card("Posted (matched)", overall['posted'], "posted")}
    {card("Channels tracked", len(channels), None)}
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

  <div class="footer">Click any card or channel row to drill down.</div>

  <div class="backdrop" id="backdrop"></div>
  <aside class="drawer" id="drawer" aria-hidden="true">
    <div class="drawer-header">
      <h2 id="drawer-title">Details</h2>
      <button class="drawer-close" id="drawer-close">close · esc</button>
    </div>
    <div class="drawer-body" id="drawer-body"></div>
  </aside>

  <script>
    (function() {{
      const drawer = document.getElementById('drawer');
      const backdrop = document.getElementById('backdrop');
      const body = document.getElementById('drawer-body');
      const closeBtn = document.getElementById('drawer-close');

      function open(href) {{
        const url = href + (href.includes('?') ? '&' : '?') + 'fragment=1';
        body.innerHTML = '<div style="color:#9aa3b2">Loading…</div>';
        drawer.classList.add('open');
        backdrop.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        fetch(url, {{credentials: 'same-origin'}}).then(r => {{
          if (!r.ok) throw new Error('http ' + r.status);
          return r.text();
        }}).then(html => {{ body.innerHTML = html; }})
          .catch(e => {{ body.innerHTML = '<div style="color:#ff8888">Error: ' + e.message + '</div>'; }});
      }}
      function close() {{
        drawer.classList.remove('open');
        backdrop.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
      }}
      document.querySelectorAll('[data-drawer]').forEach(el => {{
        el.addEventListener('click', e => {{
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
          e.preventDefault();
          e.stopPropagation();
          open(el.dataset.drawer);
        }});
      }});
      backdrop.addEventListener('click', close);
      closeBtn.addEventListener('click', close);
      document.addEventListener('keydown', e => {{ if (e.key === 'Escape') close(); }});
    }})();
  </script>
</body></html>"""


def _render_list_inner(rows: list[dict], title_str: str) -> str:
    body_rows = []
    for r in rows:
        ts = _fmt_ts(r["ts"])
        chan = html.escape(_channel_label(r))
        link = _source_link(r["chat_id"], r["msg_id"])
        post_link = f"<a href='{link}' target='_blank' rel='noopener'>open ↗</a>" if link else "—"
        title = html.escape(r["title"] or "—")
        score = r["score"] if r["score"] is not None else "—"
        tags = []
        if r["posted"]:
            tags.append("<span class='tag posted'>posted</span>")
        if r["is_vacancy"] is True:
            tags.append("<span class='tag vac'>vacancy</span>")
        elif r["is_vacancy"] is False:
            tags.append("<span class='tag notvac'>not vacancy</span>")
        tags_html = " ".join(tags) or "—"
        body_rows.append(
            f"<tr><td>{ts}</td><td>{chan}</td><td>{title}</td>"
            f"<td class='num'>{score}</td><td>{tags_html}</td><td>{post_link}</td></tr>"
        )
    body_html = "\n".join(body_rows) or "<tr><td colspan='6'>no data</td></tr>"

    return f"""
  <h1>{html.escape(title_str)}</h1>
  <div class="sub">{len(rows)} rows · click "open ↗" to view the original Telegram post</div>
  <table>
    <thead><tr>
      <th>Time</th><th>Channel</th><th>Title</th>
      <th class="num">Score</th><th>Tags</th><th>Source</th>
    </tr></thead>
    <tbody>{body_html}</tbody>
  </table>"""


def _list_title(filter_type: str, channel_label: str | None) -> str:
    parts = []
    if channel_label:
        parts.append(channel_label)
    parts.append(FILTER_LABELS.get(filter_type, "All messages"))
    return " · ".join(parts)


def _render_list_page(rows: list[dict], filter_type: str, channel_label: str | None, token: str) -> str:
    title_str = _list_title(filter_type, channel_label)
    inner = _render_list_inner(rows, title_str)
    back_href = "/" + _qs(token)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title_str)} — Victoria</title><style>{_BASE_CSS}</style></head>
<body>
  <a href="{back_href}" class="back">← back to dashboard</a>
  {inner}
</body></html>"""


def make_app(storage: Storage, threshold: int, token: str) -> web.Application:
    def _check(request: web.Request) -> web.Response | None:
        if token and request.query.get("token") != token:
            return web.Response(text="unauthorized", status=401)
        return None

    async def index(request: web.Request) -> web.Response:
        if (resp := _check(request)) is not None:
            return resp
        body = _render_index(
            storage.overall_stats(),
            storage.channel_stats(),
            storage.recent_matches(limit=30),
            threshold,
            token,
        )
        return web.Response(text=body, content_type="text/html")

    async def list_view(request: web.Request) -> web.Response:
        if (resp := _check(request)) is not None:
            return resp
        ftype = request.query.get("type", "all")
        if ftype not in FILTER_LABELS:
            ftype = "all"
        channel_id_raw = request.query.get("channel")
        channel_id = int(channel_id_raw) if channel_id_raw and channel_id_raw.lstrip("-").isdigit() else None
        channel_label = None
        if channel_id is not None:
            for c in storage.channel_stats():
                if c["chat_id"] == channel_id:
                    channel_label = _channel_label(c)
                    break
        rows = storage.list_messages(filter_type=ftype, channel_id=channel_id, limit=300)
        if request.query.get("fragment"):
            body = _render_list_inner(rows, _list_title(ftype, channel_label))
        else:
            body = _render_list_page(rows, ftype, channel_label, token)
        return web.Response(text=body, content_type="text/html")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/list", list_view)
    app.router.add_get("/health", health)
    return app


async def start_dashboard(storage: Storage, threshold: int) -> None:
    port = int(os.environ.get("PORT", "0"))
    if not port:
        log.info("Dashboard disabled (PORT not set).")
        return
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token:
        log.warning("DASHBOARD_TOKEN not set — dashboard is publicly accessible.")
    app = make_app(storage, threshold, token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Dashboard listening on :%d (token_required=%s)", port, bool(token))
