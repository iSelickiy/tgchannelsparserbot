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
        # Миграция: добавляем summary_type если нет
        cols = [r[1] for r in conn.execute("PRAGMA table_info(summaries)").fetchall()]
        if 'summary_type' not in cols:
            conn.execute("ALTER TABLE summaries ADD COLUMN summary_type TEXT DEFAULT 'manual'")
            # Существующие сводки, созданные в 04:00 UTC (±30 мин) — ежедневные
            conn.execute("""
                UPDATE summaries
                SET summary_type = 'daily'
                WHERE strftime('%H', created_at) IN ('03', '04')
            """)

        # Таблица контекста за 30 дней (одна строка)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_context (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                content TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Убедимся что строка существует
        if not conn.execute("SELECT 1 FROM news_context WHERE id = 1").fetchone():
            conn.execute("INSERT INTO news_context (id, content) VALUES (1, '')")

        conn.execute("PRAGMA journal_mode=WAL")


def save_summary(content: str, message_count: int = 0,
                 summary_type: str = 'manual') -> int:
    with _db() as conn:
        cursor = conn.execute(
            "INSERT INTO summaries (date, content, message_count, summary_type) "
            "VALUES (?, ?, ?, ?)",
            (datetime.date.today().isoformat(), content, message_count, summary_type)
        )
        return cursor.lastrowid


def get_summary(summary_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE id = ?", (summary_id,)
        ).fetchone()
    return dict(row) if row else None


def get_recent_summaries(days: int = 30) -> list[dict]:
    """Возвращает ежедневные за N дней + последние 5 ручных."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _db() as conn:
        daily = conn.execute(
            "SELECT id, date, message_count, created_at, summary_type FROM summaries "
            "WHERE summary_type = 'daily' AND date >= ? "
            "ORDER BY date DESC",
            (cutoff,)
        ).fetchall()
        manual = conn.execute(
            "SELECT id, date, message_count, created_at, summary_type FROM summaries "
            "WHERE summary_type = 'manual' "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()
    # Объединяем и сортируем по дате убывания
    combined = [dict(r) for r in daily] + [dict(r) for r in manual]
    combined.sort(key=lambda x: x['id'], reverse=True)
    return combined


def cleanup_old_summaries(days: int = 30):
    """Удаляет ежедневные сводки старше N дней, ручные — все кроме последних 5."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _db() as conn:
        conn.execute(
            "DELETE FROM summaries WHERE summary_type = 'daily' AND date < ?",
            (cutoff,)
        )
        # Ручные: оставляем последние 5
        conn.execute("""
            DELETE FROM summaries
            WHERE summary_type = 'manual'
              AND id NOT IN (
                  SELECT id FROM summaries
                  WHERE summary_type = 'manual'
                  ORDER BY id DESC LIMIT 5
              )
        """)


# ─── Контекст за 30 дней ────────────────────────────────────────────────────

def get_news_context() -> str:
    with _db() as conn:
        row = conn.execute("SELECT content FROM news_context WHERE id = 1").fetchone()
    return row['content'] if row else ''


def save_news_context(content: str):
    with _db() as conn:
        conn.execute(
            "UPDATE news_context SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (content,)
        )
