#!/usr/bin/env python3
import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler

from clients import user_client, bot_client
from config import BOT_TOKEN, SUMMARY_RETENTION_DAYS
from scheduler import setup_scheduler
from web_server import start_web_server
from storage import cleanup_old_summaries, init_db

import handlers  # noqa: F401 — регистрирует все обработчики команд


def _setup_logging() -> None:
    """Логи выводятся в консоль и в файл bot.log с ротацией по дням (10 дней истории)."""
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    fh = TimedRotatingFileHandler(
        'bot.log', when='midnight', backupCount=10, encoding='utf-8'
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


_setup_logging()
logger = logging.getLogger(__name__)


async def main():
    # Инициализация БД и очистка старых сводок
    init_db()
    cleanup_old_summaries(SUMMARY_RETENTION_DAYS)

    # Запуск Telethon клиентов
    await user_client.start()
    logger.info("User client started")

    await bot_client.start(bot_token=BOT_TOKEN)
    logger.info("Bot client started")

    # Планировщик ежедневной сводки
    setup_scheduler()

    # Веб-сервер для просмотра архива сводок
    await start_web_server()

    # Основной цикл бота
    await bot_client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено")
