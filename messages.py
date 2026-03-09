import re
import asyncio
import datetime
import logging

from clients import user_client
from channels import load_channels

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 3  # Максимум одновременных запросов к Telegram


def is_ad_message(text: str) -> bool:
    """Возвращает True если сообщение помечено как реклама (маркировка erid)."""
    return bool(re.search(r'\berid\b', text, re.IGNORECASE))


def _format_text(entity, msg) -> str | None:
    """
    Формирует строку с заголовком канала, ссылкой и текстом.
    Возвращает None если сообщение пустое или рекламное.
    """
    text = msg.text or getattr(msg, 'message', '') or ''
    if not text and msg.media:
        text = '[Медиа без текста]'
    if not text or is_ad_message(text):
        return None
    link = (
        f"https://t.me/{entity.username}/{msg.id}"
        if getattr(entity, 'username', None)
        else f"https://t.me/c/{entity.id}/{msg.id}"
    )
    return f"Канал: {entity.title}\nСсылка: {link}\n{text}"


async def get_unread_messages_from_channels() -> tuple[dict[int, list], list[str]]:
    """
    Собирает непрочитанные сообщения из каналов.
    Каналы обрабатываются параллельно (до _MAX_PARALLEL одновременно).
    """
    dialogs = await user_client.get_dialogs()
    dialog_map = {d.entity.id: d for d in dialogs}
    channels = load_channels()
    semaphore = asyncio.Semaphore(_MAX_PARALLEL)

    async def fetch(ch_id: str):
        async with semaphore:
            try:
                entity = await user_client.get_entity(ch_id)
                dialog = dialog_map.get(entity.id)
                if not dialog or dialog.dialog.unread_count == 0:
                    return None, [], []
                read_max_id = dialog.dialog.read_inbox_max_id
                messages = await user_client.get_messages(
                    entity, min_id=read_max_id + 1, limit=None
                )
                if not messages:
                    return None, [], []
                texts = list(filter(None, (_format_text(entity, msg) for msg in messages)))
                logger.info(f"Загружено {len(messages)} сообщений из {ch_id}")
                return entity.id, list(messages), texts
            except Exception as e:
                logger.error(f"Ошибка канала {ch_id}: {e}")
                return None, [], []

    results = await asyncio.gather(*[fetch(ch) for ch in channels])

    unread_data: dict[int, list] = {}
    all_texts: list[str] = []
    for ch_id, messages, texts in results:
        if ch_id is not None and messages:
            unread_data[ch_id] = messages
            all_texts.extend(texts)

    return unread_data, all_texts


async def get_messages_by_time(hours: int = 25) -> tuple[dict[int, list], list[str]]:
    """
    Собирает все сообщения из каналов за последние N часов.
    Используется для регулярной (ежедневной) выгрузки.
    Каналы обрабатываются параллельно (до _MAX_PARALLEL одновременно).
    """
    from_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    channels = load_channels()
    semaphore = asyncio.Semaphore(_MAX_PARALLEL)

    async def fetch(ch_id: str):
        async with semaphore:
            try:
                entity = await user_client.get_entity(ch_id)
                messages = []
                async for msg in user_client.iter_messages(entity, limit=None):
                    if msg.date < from_date:
                        break
                    messages.append(msg)
                if not messages:
                    return None, [], []
                texts = list(filter(None, (_format_text(entity, msg) for msg in messages)))
                logger.info(f"Загружено {len(messages)} сообщений за {hours}ч из {ch_id}")
                return entity.id, messages, texts
            except Exception as e:
                logger.error(f"Ошибка канала {ch_id}: {e}")
                return None, [], []

    results = await asyncio.gather(*[fetch(ch) for ch in channels])

    all_messages_data: dict[int, list] = {}
    all_texts: list[str] = []
    for ch_id, messages, texts in results:
        if ch_id is not None and messages:
            all_messages_data[ch_id] = messages
            all_texts.extend(texts)

    return all_messages_data, all_texts


async def mark_messages_as_read(unread_data: dict[int, list]):
    """Помечает все сообщения из unread_data как прочитанные."""
    for channel_id, messages in unread_data.items():
        if messages:
            try:
                entity = await user_client.get_entity(channel_id)
                max_id = max(msg.id for msg in messages)
                await user_client.send_read_acknowledge(entity, max_id=max_id)
                logger.info(f"Прочитано в {entity.title} до ID {max_id}")
            except Exception as e:
                logger.error(f"Не удалось пометить прочитанными для канала {channel_id}: {e}")
