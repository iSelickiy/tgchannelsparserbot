import json
import os
import logging

logger = logging.getLogger(__name__)

CHANNELS_FILE = "channels.json"


def load_channels() -> list[str]:
    """Загружает список каналов из JSON-файла."""
    if not os.path.exists(CHANNELS_FILE):
        # Миграция: при первом запуске берём из .env
        env_channels = os.getenv('CHANNELS', '')
        channels = [ch.strip() for ch in env_channels.split(',') if ch.strip()]
        save_channels(channels)
        logger.info(f"Мигрировано {len(channels)} каналов из .env в {CHANNELS_FILE}")
        return channels
    with open(CHANNELS_FILE, 'r') as f:
        return json.load(f)


def save_channels(channels: list[str]):
    with open(CHANNELS_FILE, 'w') as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


def add_channel(channel_id: str) -> bool:
    channels = load_channels()
    if channel_id not in channels:
        channels.append(channel_id)
        save_channels(channels)
        return True
    return False


def remove_channel(channel_id: str) -> bool:
    channels = load_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        save_channels(channels)
        return True
    return False


async def get_subscribed_channels(user_client) -> list[dict]:
    """
    Получает список каналов, на которые подписан пользователь.
    Возвращает список словарей {id, title, username, unread_count}.
    """
    from telethon.tl.types import Channel

    channels = []
    async for dialog in user_client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.broadcast:
            channels.append({
                'id': entity.id,
                'title': entity.title,
                'username': f"@{entity.username}" if entity.username else str(entity.id),
                'unread_count': dialog.unread_count
            })

    channels.sort(key=lambda x: x['unread_count'], reverse=True)
    return channels
