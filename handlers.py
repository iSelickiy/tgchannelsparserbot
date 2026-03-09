import logging
import datetime
from telethon import events, Button
from clients import bot_client, user_client
from config import YOUR_USER_ID, SERVER_BASE_URL
from channels import load_channels, add_channel, remove_channel, get_subscribed_channels
from messages import get_unread_messages_from_channels, mark_messages_as_read
from summarizer import summarize_texts
from storage import save_summary, get_recent_summaries


logger = logging.getLogger(__name__)

# Состояния диалога для каждого пользователя
user_states: dict[int, str] = {}

# Хранение ID сообщений бота для последующего удаления
user_messages: dict[int, list[int]] = {}

MAIN_MENU_BUTTONS = [
    [Button.text("📰 Получить сводку", resize=True)],
    [Button.text("📋 Мои каналы", resize=True)],
    [Button.text("➕ Добавить канал", resize=True),
     Button.text("➖ Удалить канал", resize=True)],
    [Button.text("📚 История", resize=True)],
]


async def track(user_id: int, msg) -> None:
    """Запоминает ID сообщения бота."""
    user_messages.setdefault(user_id, []).append(msg.id)


async def delete_bot_messages(user_id: int, chat_id: int) -> None:
    """Удаляет все сохранённые сообщения бота для пользователя."""
    ids = user_messages.pop(user_id, [])
    if ids:
        try:
            await bot_client.delete_messages(chat_id, ids)
        except Exception:
            pass


# === Главное меню ===

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return
    await delete_bot_messages(event.sender_id, event.chat_id)
    msg = await event.respond("Привет! Выбери действие:", buttons=MAIN_MENU_BUTTONS)
    await track(event.sender_id, msg)


# === Список каналов ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "📋 Мои каналы"))
async def list_channels_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    channels = load_channels()
    if not channels:
        await event.respond("Список каналов пуст. Добавь каналы кнопкой ➕")
        return

    text = "**Твои каналы:**\n\n"
    for i, ch in enumerate(channels, 1):
        try:
            entity = await user_client.get_entity(ch)
            name = getattr(entity, 'title', ch)
            text += f"{i}. {name} (`{ch}`)\n"
        except Exception:
            text += f"{i}. {ch}\n"

    await event.respond(text, parse_mode='markdown')

@bot_client.on(events.NewMessage(func=lambda e: e.text == "📚 История"))
async def history_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    await delete_bot_messages(event.sender_id, event.chat_id)
    summaries = get_recent_summaries(30)

    if not summaries:
        msg = await event.respond("Сводок пока нет.")
        await track(event.sender_id, msg)
        return

    buttons = []
    for s in summaries:
        label = f"№{s['id']} — {s['date']} ({s['message_count']} сообщ.)"
        url = f"{SERVER_BASE_URL}/summary/{s['id']}"
        buttons.append([Button.url(label, url)])

    buttons.append([Button.inline("🏠 Главное меню", data="menu")])
    msg = await event.respond("📚 Сводки за последние 30 дней:", buttons=buttons)
    await track(event.sender_id, msg)

# === Получить сводку ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "📰 Получить сводку"))
async def summary_request_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    await delete_bot_messages(event.sender_id, event.chat_id)
    msg = await event.respond("⏳ Собираю непрочитанные сообщения из каналов...")
    await track(event.sender_id, msg)

    try:
        unread_data, all_texts = await get_unread_messages_from_channels()

        if not all_texts:
            await delete_bot_messages(event.sender_id, event.chat_id)
            msg = await event.respond("✅ Нет непрочитанных сообщений.")
            await track(event.sender_id, msg)
            return

        async def progress(text: str):
            m = await event.respond(text)
            await track(event.sender_id, m)

        summary = await summarize_texts(all_texts, progress_callback=progress)
        summary_id = save_summary(summary, len(all_texts))
        url = f"{SERVER_BASE_URL}/summary/{summary_id}"

        await delete_bot_messages(event.sender_id, event.chat_id)
        msg = await event.respond(
            f"✅ Сводка №{summary_id} за {datetime.date.today().strftime('%d.%m.%Y')}",
            buttons=[
                [Button.url("🌐 Читать", url)],
                [Button.inline("🏠 Главное меню", data="menu")],
            ]
        )
        await track(event.sender_id, msg)

        await mark_messages_as_read(unread_data)

    except Exception as e:
        logger.exception("Ошибка при получении сводки")
        await delete_bot_messages(event.sender_id, event.chat_id)
        msg = await event.respond(f"❌ Произошла ошибка: {e}")
        await track(event.sender_id, msg)


# === Добавить канал ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "➕ Добавить канал"))
async def add_channel_start(event):
    if event.sender_id != YOUR_USER_ID:
        return
    buttons = [
        [Button.inline("📋 Выбрать из моих подписок", data="pick_from_subs")],
        [Button.inline("✍️ Ввести вручную", data="add_manual")],
        [Button.inline("🏠 Главное меню", data="menu")],
    ]
    await event.respond("Как добавить канал?", buttons=buttons)


# === Удалить канал ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "➖ Удалить канал"))
async def remove_channel_start(event):
    if event.sender_id != YOUR_USER_ID:
        return

    channels = load_channels()
    if not channels:
        await event.respond("Список каналов пуст.")
        return

    buttons = []
    for ch in channels:
        try:
            entity = await user_client.get_entity(ch)
            name = getattr(entity, 'title', ch)
        except Exception:
            name = ch
        buttons.append([Button.inline(f"❌ {name}", data=f"del:{ch}")])

    buttons.append([Button.inline("🏠 Главное меню", data="menu")])
    await event.respond("Какой канал удалить?", buttons=buttons)


# === Inline-кнопки ===

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    data = event.data.decode('utf-8')

    if data == "menu":
        await event.answer()
        await event.delete()
        await delete_bot_messages(event.sender_id, event.chat_id)
        msg = await bot_client.send_message(event.chat_id, "Главное меню:", buttons=MAIN_MENU_BUTTONS)
        await track(event.sender_id, msg)
        return

    if data == "cancel":
        await event.answer("Отменено")
        await event.delete()
        return

    if data == "add_manual":
        await event.answer()
        user_states[event.sender_id] = 'adding_channel'
        await event.edit(
            "Отправь мне ссылку на канал или его @username.\n"
            "Например: `@durov` или `https://t.me/durov`\n\n"
            "Или нажми /cancel для отмены.",
        )
        return

    if data == "pick_from_subs":
        await event.answer("Загружаю подписки...")
        subscribed = await get_subscribed_channels(user_client)
        current = load_channels()

        available = [
            ch for ch in subscribed
            if ch['username'] not in current and str(ch['id']) not in current
        ]

        if not available:
            await event.edit("Все твои каналы уже добавлены!")
            return

        buttons = []
        for ch in available[:10]:
            label = f"{ch['title']} ({ch['unread_count']} непрочит.)"
            buttons.append([Button.inline(label, data=f"addsub:{ch['username']}")])

        if len(available) > 10:
            buttons.append([Button.inline(f"... и ещё {len(available) - 10}", data="noop")])
        buttons.append([Button.inline("🔙 Отмена", data="cancel")])
        await event.edit("Выбери канал для добавления:", buttons=buttons)
        return

    if data == "noop":
        await event.answer()
        return

    if data.startswith("addsub:"):
        channel_id = data[7:]
        try:
            entity = await user_client.get_entity(channel_id)
            name = getattr(entity, 'title', channel_id)
            if add_channel(channel_id):
                await event.answer(f"Канал добавлен!")
                await event.edit(f"✅ Канал **{name}** добавлен!", parse_mode='markdown')
            else:
                await event.answer("Уже в списке")
                await event.edit(f"Канал **{name}** уже в списке.", parse_mode='markdown')
        except Exception as e:
            await event.answer("Ошибка")
            await event.edit(f"❌ Не удалось добавить: {e}")
        return

    if data.startswith("del:"):
        channel_id = data[4:]
        if remove_channel(channel_id):
            await event.answer("Канал удалён!")
            await event.edit(f"✅ Канал `{channel_id}` удалён.", parse_mode='markdown')
        else:
            await event.answer("Канал не найден в списке")
        return
    


# === Текстовые сообщения (диалог добавления канала) ===

@bot_client.on(events.NewMessage())
async def text_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    state = user_states.get(event.sender_id)
    if state != 'adding_channel':
        return

    if event.text == '/cancel':
        user_states.pop(event.sender_id, None)
        await event.respond("Отменено.")
        return

    channel_input = event.text.strip()

    # Нормализуем ввод
    if channel_input.startswith('https://t.me/'):
        channel_input = '@' + channel_input.split('/')[-1]

    try:
        entity = await user_client.get_entity(channel_input)
        name = getattr(entity, 'title', channel_input)

        if add_channel(channel_input):
            await event.respond(f"✅ Канал **{name}** добавлен!", parse_mode='markdown')
        else:
            await event.respond(f"Канал **{name}** уже в списке.", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Не удалось найти канал: {channel_input}\nОшибка: {e}")

    user_states.pop(event.sender_id, None)
