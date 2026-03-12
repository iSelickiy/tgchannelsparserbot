import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import YOUR_USER_ID, SERVER_BASE_URL, SUMMARY_RETENTION_DAYS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def daily_summary_job():
    """Ежедневная задача: собрать новости за последние 25 часов и отправить сводку."""
    from messages import get_messages_by_time, mark_messages_as_read
    from summarizer import summarize_texts
    from storage import save_summary
    from clients import bot_client
    from telethon import Button
    import datetime

    logger.info("Запуск ежедневной сводки...")
    try:
        all_messages_data, all_texts = await get_messages_by_time(hours=25)

        if not all_texts:
            await bot_client.send_message(YOUR_USER_ID, "☀️ Доброе утро! Новых сообщений нет.")
            return

        summary = await summarize_texts(all_texts)
        summary_id = save_summary(summary, len(all_texts))
        url = f"{SERVER_BASE_URL}/summary/{summary_id}"

        await mark_messages_as_read(all_messages_data)

        date_str = datetime.date.today().strftime('%d.%m.%Y')
        await bot_client.send_message(
            YOUR_USER_ID,
            f"☀️ **Утренняя сводка за {date_str}** — {len(all_texts)} сообщ.",
            buttons=[Button.url("🌐 Читать сводку", url)],
            parse_mode='markdown',
        )

    except Exception as e:
        logger.exception("Ошибка в ежедневной сводке")
        from clients import bot_client as _bot
        await _bot.send_message(YOUR_USER_ID, f"❌ Ошибка утренней сводки: {e}")


def setup_scheduler():
    """Настраивает ежедневный запуск в 7:00 МСК (4:00 UTC)."""
    scheduler.add_job(
        daily_summary_job,
        trigger=CronTrigger(hour=4, minute=0),  # 4:00 UTC = 7:00 МСК
        id='daily_summary',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Планировщик запущен: ежедневная сводка в 7:00 МСК")
