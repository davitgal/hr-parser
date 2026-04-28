from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                chat_id INTEGER NOT NULL,
                msg_id  INTEGER NOT NULL,
                score   INTEGER,
                posted  INTEGER NOT NULL DEFAULT 0,
                ts      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                PRIMARY KEY (chat_id, msg_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                chat_id     INTEGER PRIMARY KEY,
                username    TEXT,
                title       TEXT,
                last_msg_ts INTEGER
            )
            """
        )
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(seen)")}
        if "is_vacancy" not in existing:
            self._conn.execute("ALTER TABLE seen ADD COLUMN is_vacancy INTEGER")
        if "title" not in existing:
            self._conn.execute("ALTER TABLE seen ADD COLUMN title TEXT")

    def seen(self, chat_id: int, msg_id: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE chat_id=? AND msg_id=? LIMIT 1",
            (chat_id, msg_id),
        )
        return cur.fetchone() is not None

    def register_channel(self, chat_id: int, username: str | None, title: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO channels (chat_id, username, title)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              username = excluded.username,
              title    = excluded.title
            """,
            (chat_id, username, title),
        )

    def record_message(
        self,
        chat_id: int,
        msg_id: int,
        *,
        is_vacancy: bool | None = None,
        score: int | None = None,
        posted: bool = False,
        title: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO seen (chat_id, msg_id, is_vacancy, score, posted, title)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, msg_id, None if is_vacancy is None else (1 if is_vacancy else 0), score, 1 if posted else 0, title),
        )
        self._conn.execute(
            "UPDATE channels SET last_msg_ts = strftime('%s','now') WHERE chat_id=?",
            (chat_id,),
        )

    # Backwards-compat shim used elsewhere; keep simple semantics.
    def mark_seen(
        self,
        chat_id: int,
        msg_id: int,
        score: int | None = None,
        posted: bool = False,
    ) -> None:
        self.record_message(chat_id, msg_id, score=score, posted=posted)

    def overall_stats(self) -> dict:
        row = self._conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN is_vacancy=1 THEN 1 ELSE 0 END) AS vacancies,
              SUM(CASE WHEN is_vacancy=0 THEN 1 ELSE 0 END) AS not_vacancies,
              SUM(CASE WHEN posted=1 THEN 1 ELSE 0 END)    AS posted,
              MAX(ts)                                       AS last_ts
            FROM seen
            """
        ).fetchone()
        return {
            "total": row[0] or 0,
            "vacancies": row[1] or 0,
            "not_vacancies": row[2] or 0,
            "posted": row[3] or 0,
            "last_ts": row[4],
        }

    def channel_stats(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
              c.chat_id,
              c.username,
              c.title,
              c.last_msg_ts,
              COUNT(s.msg_id)                                            AS total,
              SUM(CASE WHEN s.is_vacancy=1 THEN 1 ELSE 0 END)             AS vacancies,
              SUM(CASE WHEN s.posted=1 THEN 1 ELSE 0 END)                 AS posted,
              AVG(CASE WHEN s.is_vacancy=1 THEN s.score END)              AS avg_vacancy_score,
              MAX(CASE WHEN s.is_vacancy=1 THEN s.score ELSE 0 END)       AS max_vacancy_score
            FROM channels c
            LEFT JOIN seen s ON s.chat_id = c.chat_id
            GROUP BY c.chat_id
            ORDER BY (c.title COLLATE NOCASE)
            """
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "chat_id": r[0],
                "username": r[1],
                "title": r[2],
                "last_msg_ts": r[3],
                "total": r[4] or 0,
                "vacancies": r[5] or 0,
                "posted": r[6] or 0,
                "avg_score": round(r[7], 1) if r[7] is not None else None,
                "max_score": r[8] or 0,
            })
        return out

    def list_messages(
        self,
        *,
        filter_type: str = "all",
        channel_id: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        where = ["1=1"]
        params: list = []
        if filter_type == "vacancies":
            where.append("s.is_vacancy = 1")
        elif filter_type == "not_vacancies":
            where.append("s.is_vacancy = 0")
        elif filter_type == "posted":
            where.append("s.posted = 1")
        if channel_id is not None:
            where.append("s.chat_id = ?")
            params.append(channel_id)
        params.append(limit)
        sql = f"""
            SELECT s.ts, s.chat_id, c.username, c.title, s.title, s.score, s.is_vacancy, s.posted, s.msg_id
            FROM seen s LEFT JOIN channels c ON c.chat_id = s.chat_id
            WHERE {" AND ".join(where)}
            ORDER BY s.ts DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            out.append({
                "ts": r[0],
                "chat_id": r[1],
                "channel_username": r[2],
                "channel_title": r[3],
                "title": r[4],
                "score": r[5],
                "is_vacancy": None if r[6] is None else bool(r[6]),
                "posted": bool(r[7]),
                "msg_id": r[8],
            })
        return out

    def recent_matches(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT s.ts, s.chat_id, c.username, c.title, s.title, s.score, s.msg_id
            FROM seen s
            LEFT JOIN channels c ON c.chat_id = s.chat_id
            WHERE s.posted = 1
            ORDER BY s.ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "ts": r[0],
                "chat_id": r[1],
                "channel_username": r[2],
                "channel_title": r[3],
                "title": r[4],
                "score": r[5],
                "msg_id": r[6],
            })
        return out

    def close(self) -> None:
        self._conn.close()
