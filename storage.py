import sqlite3
import datetime

DB_FILE = "summaries.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            content TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_summary(content: str, message_count: int = 0) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "INSERT INTO summaries (date, content, message_count) VALUES (?, ?, ?)",
        (datetime.date.today().isoformat(), content, message_count)
    )
    summary_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return summary_id


def get_summary(summary_id: int) -> dict | None:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_summaries(days: int = 30) -> list[dict]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, date, message_count, created_at FROM summaries "
        "WHERE date >= ? ORDER BY date DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_old_summaries(days: int = 30):
    """Удаляет сводки старше N дней."""
    conn = sqlite3.connect(DB_FILE)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM summaries WHERE date < ?", (cutoff,))
    conn.commit()
    conn.close()


# При импорте создаём таблицу
init_db()
