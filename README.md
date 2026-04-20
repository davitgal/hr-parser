# hr-parser

AI HR-ассистент: слушает список Telegram-чатов через user-аккаунт (Telethon), гоняет каждое новое сообщение через Claude с твоим CV (`profile.md`), и репостит только релевантные вакансии в приватный канал.

## Как устроено

- **Telethon user account** (`StringSession`) — читает каналы/чаты, в которых ты состоишь.
- **`profile.md`** — твой CV в markdown, кэшируется в system-prompt'е Claude (prompt caching).
- **Claude Haiku 4.5** — один вызов на сообщение: классификация (вакансия ли) + извлечение полей + скоринг 0–100.
- **SQLite** на Railway volume `/data/state.db` — dedup по `(chat_id, msg_id)`.
- **Целевой канал** — тот же Telethon-клиент постит туда markdown-карточки.

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполни TG_API_ID, TG_API_HASH (с https://my.telegram.org), ANTHROPIC_API_KEY
```

Сгенерировать сессию Telegram (один раз, интерактивно — введёшь телефон и код из SMS):

```bash
python scripts/login.py
# скопируй выведенную строку в .env как TG_SESSION
```

Заполни `profile.md` реальным CV. Укажи нужные чаты в `sources.json`. Создай приватный канал, добавь туда себя (или используй "Избранное" — `me`), узнай `chat_id` (формат `-100...`) и положи в `TARGET_CHANNEL_ID`. Для локалки поставь `DB_PATH=./state.db`.

Запуск:

```bash
python -m src.main
```

Ожидаемые логи: `Connected as <you>`, `Monitoring N sources`, `Listening.`. Кинь тестовую вакансию в источник — через ~3 секунды она должна появиться в целевом канале.

## Деплой на Railway

1. Создать проект → Deploy from GitHub repo (ветка `claude/ai-hr-job-matcher-gJNUL`).
2. Добавить **volume**: mount path `/data`, размер 1 GB (имя `state`).
3. Env vars (всё из `.env.example`):
   - `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` (локально сгенерированный)
   - `ANTHROPIC_API_KEY`
   - `TARGET_CHANNEL_ID` (формат `-100...` или `@username`)
   - `MATCH_THRESHOLD=70`
   - `DB_PATH=/data/state.db`
4. Сервис поднимется как worker (см. `Procfile` / `railway.toml`). HTTP healthcheck не нужен.
5. Одна реплика — `StringSession` нельзя шарить.

## Настройка качества

- Сильно влияет содержимое `profile.md` — чем конкретнее секция `Preferences` (must/avoid stack, salary floor, remote policy, red flags), тем точнее фильтр.
- Поднять планку: `MATCH_THRESHOLD=80+`.
- Понизить шум дальше: добавить красных флагов в `profile.md` → Preferences → Red flags.

## Структура

```
src/
  main.py              # event loop
  config.py            # env + sources loader
  telegram_client.py   # Telethon + resolve sources
  profile.py           # profile.md loader
  matcher.py           # Claude call + JSON parse + retries
  publisher.py         # markdown format + send
  storage.py           # SQLite dedup
scripts/login.py       # StringSession generator
profile.md             # твой CV
sources.json           # мониторимые чаты
```
