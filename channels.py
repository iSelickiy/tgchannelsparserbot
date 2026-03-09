import json
import os
import time
import logging

logger = logging.getLogger(__name__)

CHANNELS_FILE = "channels.json"

_cache: list[str] | None = None


def load_channels() -> list[str]:
    """Загружает список каналов из JSON-файла. Результат кэшируется в памяти."""
    global _cache
    if _cache is not None:
        return _cache

    if not os.path.exists(CHANNELS_FILE):
        # Миграция: при первом запуске берём из .env
        env_channels = os.getenv('CHANNELS', '')
        channels = [ch.strip() for ch in env_channels.split(',') if ch.strip()]
        _save_and_cache(channels)
        logger.info(f"Мигрировано {len(channels)} каналов из .env в {CHANNELS_FILE}")
        return _cache

    with open(CHANNELS_FILE, 'r') as f:
        _cache = json.load(f)
    return _cache


def save_channels(channels: list[str]):
    _save_and_cache(channels)


def _save_and_cache(channels: list[str]):
    global _cache
    _cache = channels
    with open(CHANNELS_FILE, 'w') as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


def add_channel(channel_id: str) -> bool:
    channels = load_channels()
    if channel_id not in channels:
        _save_and_cache(channels + [channel_id])
        return True
    return False


def remove_channel(channel_id: str) -> bool:
    channels = load_channels()
    if channel_id in channels:
        _save_and_cache([ch for ch in channels if ch != channel_id])
        return True
    return False


_subs_cache: list[dict] | None = None
_subs_cache_ts: float = 0.0
_SUBS_TTL: float = 300.0  # 5 минут


async def get_subscribed_channels(user_client) -> list[dict]:
    """
    Получает список каналов, на которые подписан пользователь.
    Результат кэшируется на 5 минут — повторные вызовы мгновенны.
    Возвращает список словарей {id, title, username, unread_count}.
    """
    global _subs_cache, _subs_cache_ts

    if _subs_cache is not None and time.monotonic() - _subs_cache_ts < _SUBS_TTL:
        return _subs_cache

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
    _subs_cache = channels
    _subs_cache_ts = time.monotonic()
    logger.info(f"Подписки загружены: {len(channels)} каналов")
    return channels


def invalidate_subs_cache():
    """Сбрасывает кэш подписок (вызывать после добавления/удаления каналов)."""
    global _subs_cache, _subs_cache_ts
    _subs_cache = None
    _subs_cache_ts = 0.0
