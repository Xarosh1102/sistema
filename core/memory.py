import sqlite3
from datetime import datetime
from typing import Dict, List

from config.settings import DB_PATH


class MemoryManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Таблица истории сообщений
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            # Таблица долгосрочных фактов (ключ-значение)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_message(self, role: str, content: str):
        """Сохраняет реплику ('user' или 'model') в историю."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()

    def get_recent_messages(self, limit: int = 10) -> List[Dict[str, str]]:
        """Возвращает последние N сообщений в хронологическом порядке."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def clear_short_term(self):
        """Очищает историю текущей сессии."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages")
            conn.commit()

    def save_fact(self, key: str, value: str) -> str:
        """Сохраняет или обновляет долгосрочный факт."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key.strip().lower(), value.strip(), datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
        return f"Факт '{key}' сохранен в память."

    def get_all_facts(self) -> Dict[str, str]:
        """Возвращает все сохраненные долгосрочные факты."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM facts ORDER BY updated_at DESC")
            return {row[0]: row[1] for row in cursor.fetchall()}