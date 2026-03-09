import sqlite3
import datetime
from contextlib import contextmanager

DB_FILE = "summaries.db"


@contextmanager
def _db():
    """Контекстный менеджер соединения: автокоммит и закрытие."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                content TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("PRAGMA journal_mode=WAL")


def save_summary(content: str, message_count: int = 0) -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO summaries (date, content, message_count) VALUES (?, ?, ?)",
            (datetime.date.today().isoformat(), content, message_count)
        )
        return cursor.lastrowid


def get_summary(summary_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE id = ?", (summary_id,)
        ).fetchone()
    return dict(row) if row else None


def get_recent_summaries(days: int = 30) -> list[dict]:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, date, message_count, created_at FROM summaries "
            "WHERE date >= ? ORDER BY date DESC",
            (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old_summaries(days: int = 30):
    """Удаляет сводки старше N дней."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _db() as conn:
        conn.execute("DELETE FROM summaries WHERE date < ?", (cutoff,))
