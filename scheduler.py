import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import YOUR_USER_ID, WEB_PORT, SUMMARY_RETENTION_DAYS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def daily_summary_job():
    """Ежедневная задача: собрать новости и отправить сводку."""
    from messages import get_unread_messages_from_channels, mark_messages_as_read
    from summarizer import summarize_texts
    from storage import save_summary
    from clients import bot_client

    logger.info("Запуск ежедневной сводки...")
    try:
        unread_data, all_texts = await get_unread_messages_from_channels()

        if not all_texts:
            await bot_client.send_message(YOUR_USER_ID, "☀️ Доброе утро! Новых сообщений нет.")
            return

        summary = await summarize_texts(all_texts)
        summary_id = save_summary(summary, len(all_texts))

        # Отправляем сводку (разбиваем на части если длинная)
        header = f"☀️ **Утренняя сводка**\n\n"
        footer = f"\n\n🌐 http://103.228.169.198:{WEB_PORT}/summary/{summary_id}"
        full_text = header + summary + footer

        await _send_long_message_direct(bot_client, YOUR_USER_ID, full_text)
        await mark_messages_as_read(unread_data)

    except Exception as e:
        logger.exception("Ошибка в ежедневной сводке")
        from clients import bot_client as _bot
        await _bot.send_message(YOUR_USER_ID, f"❌ Ошибка утренней сводки: {e}")


async def _send_long_message_direct(bot_client, user_id: int, text: str):
    """Отправляет длинный текст, разбивая на части по 4000 символов."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await bot_client.send_message(user_id, text, parse_mode='markdown')
        return

    while text:
        if len(text) <= MAX_LEN:
            await bot_client.send_message(user_id, text, parse_mode='markdown')
            break
        cut = text.rfind('\n', 0, MAX_LEN)
        if cut == -1:
            cut = MAX_LEN
        await bot_client.send_message(user_id, text[:cut], parse_mode='markdown')
        text = text[cut:].lstrip('\n')


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
