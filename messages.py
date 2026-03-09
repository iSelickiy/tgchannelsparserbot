import logging
from clients import user_client
from channels import load_channels

logger = logging.getLogger(__name__)


async def get_unread_messages_from_channels() -> tuple[dict[int, list], list[str]]:
    """
    Собирает непрочитанные сообщения из каналов.

    Returns:
        unread_data: словарь {id_канала: [сообщения]}
        all_texts: список всех текстов с названием канала и ссылкой
    """
    unread_data: dict[int, list] = {}
    all_texts: list[str] = []

    # Загружаем диалоги один раз
    dialogs = await user_client.get_dialogs()
    dialog_map = {d.entity.id: d for d in dialogs}

    channels = load_channels()

    for channel_identifier in channels:
        try:
            entity = await user_client.get_entity(channel_identifier)
            dialog = dialog_map.get(entity.id)

            if not dialog:
                logger.warning(f"Диалог не найден для {channel_identifier}, пропускаем.")
                continue

            unread_count = dialog.dialog.unread_count
            if unread_count == 0:
                logger.info(f"В канале {channel_identifier} нет непрочитанных сообщений.")
                continue

            read_max_id = dialog.dialog.read_inbox_max_id
            messages = await user_client.get_messages(
                entity,
                min_id=read_max_id + 1,
                limit=None
            )

            if messages:
                unread_data[entity.id] = messages
                for msg in messages:
                    text = msg.text or msg.message or ''
                    if not text and msg.media:
                        text = "[Медиа без текста]"
                    if text:
                        # Формируем ссылку на оригинальный пост
                        if getattr(entity, 'username', None):
                            link = f"https://t.me/{entity.username}/{msg.id}"
                        else:
                            link = f"https://t.me/c/{entity.id}/{msg.id}"
                        all_texts.append(
                            f"Канал: {entity.title}\nСсылка: {link}\n{text}"
                        )

                logger.info(f"Загружено {len(messages)} сообщений из {channel_identifier}.")

        except Exception as e:
            logger.error(f"Ошибка при обработке канала {channel_identifier}: {e}")

    return unread_data, all_texts


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
