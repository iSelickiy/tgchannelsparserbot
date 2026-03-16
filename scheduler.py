import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import YOUR_USER_ID, SERVER_BASE_URL, SUMMARY_RETENTION_DAYS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def daily_summary_job():
    """Ежедневная задача: собрать новости за последние 25 часов и отправить сводку."""
    from messages import get_messages_by_time, mark_messages_as_read
    from summarizer import summarize_texts, update_news_context
    from storage import save_summary, get_news_context, save_news_context
    from clients import bot_client
    from telethon import Button
    import datetime

    logger.info("Запуск ежедневной сводки...")
    try:
        all_messages_data, all_texts = await get_messages_by_time(hours=25)

        if not all_texts:
            await bot_client.send_message(YOUR_USER_ID, "Доброе утро! Новых сообщений нет.")
            return

        # Получаем 30-дневный контекст
        context = get_news_context()

        summary = await summarize_texts(all_texts, context=context)
        summary_id = save_summary(summary, len(all_texts), summary_type='daily')
        url = f"{SERVER_BASE_URL}/summary/{summary_id}"

        await mark_messages_as_read(all_messages_data)

        # Обновляем контекст новостей
        try:
            new_context = await update_news_context(context, summary)
            save_news_context(new_context)
            logger.info(f"Контекст обновлён ({len(new_context)} символов)")
        except Exception as e:
            logger.error(f"Не удалось обновить контекст: {e}")

        date_str = datetime.date.today().strftime('%d.%m.%Y')
        await bot_client.send_message(
            YOUR_USER_ID,
            f"**Утренняя сводка за {date_str}** — {len(all_texts)} сообщ.",
            buttons=[Button.url("Читать сводку", url)],
            parse_mode='markdown',
        )

    except Exception as e:
        logger.exception("Ошибка в ежедневной сводке")
        from clients import bot_client as _bot
        await _bot.send_message(YOUR_USER_ID, f"Ошибка утренней сводки: {e}")


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
