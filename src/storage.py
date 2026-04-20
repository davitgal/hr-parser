from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, isolation_level=None)
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

    def seen(self, chat_id: int, msg_id: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE chat_id=? AND msg_id=? LIMIT 1",
            (chat_id, msg_id),
        )
        return cur.fetchone() is not None

    def mark_seen(
        self,
        chat_id: int,
        msg_id: int,
        score: int | None = None,
        posted: bool = False,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO seen (chat_id, msg_id, score, posted)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, msg_id, score, 1 if posted else 0),
        )

    def close(self) -> None:
        self._conn.close()
