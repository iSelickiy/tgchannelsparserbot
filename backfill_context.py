#!/usr/bin/env python3
"""
Одноразовый скрипт: заполняет news_context из существующих сводок (от старых к новым).
Запуск: python backfill_context.py
"""
import asyncio
import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = "summaries.db"


async def main():
    from summarizer import update_news_context

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # Все сводки от старых к новым
    rows = conn.execute(
        "SELECT id, date, content FROM summaries ORDER BY id ASC"
    ).fetchall()

    if not rows:
        logger.info("Сводок нет — нечего обрабатывать")
        return

    logger.info(f"Найдено {len(rows)} сводок, начинаю заполнение контекста...")

    context = ""
    for i, row in enumerate(rows):
        logger.info(f"[{i+1}/{len(rows)}] Обрабатываю сводку #{row['id']} от {row['date']}...")
        try:
            context = await update_news_context(context, row['content'])
            logger.info(f"  Контекст обновлён ({len(context)} символов)")
        except Exception as e:
            logger.error(f"  Ошибка при обработке сводки #{row['id']}: {e}")
            continue

    # Сохраняем итоговый контекст
    conn.execute(
        "UPDATE news_context SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (context,)
    )
    conn.commit()
    conn.close()

    logger.info(f"Готово! Итоговый контекст: {len(context)} символов")
    logger.info(f"Контекст:\n{context}")


if __name__ == '__main__':
    asyncio.run(main())
