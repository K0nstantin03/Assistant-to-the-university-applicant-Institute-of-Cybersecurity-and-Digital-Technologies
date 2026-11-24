"""Сессионная память диалога в SQLite."""

import sqlite3
from contextlib import closing
from datetime import datetime

import config
from contracts import Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    role       TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Открыть файловую базу диалогов."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(config.DB_PATH)


def create_schema() -> None:
    """Создать таблицу при первом запуске."""
    with closing(connect()) as conn, conn:
        conn.execute(SCHEMA)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS messages_session_id_id "
            "ON messages(session_id, id)"
        )


def save(session_id: str, role: str, content: str) -> None:
    """Записать одну реплику и время её получения."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    with closing(connect()) as conn, conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, content, timestamp),
        )


def window(session_id: str, n: int = config.MEMORY_WINDOW) -> list[Message]:
    """Вернуть последние n сообщений сессии в порядке диалога."""
    if n <= 0:
        return []
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, n),
        ).fetchall()
    return [Message(*row) for row in reversed(rows)]


def clear(session_id: str) -> None:
    """Удалить все сообщения указанной сессии."""
    with closing(connect()) as conn, conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
