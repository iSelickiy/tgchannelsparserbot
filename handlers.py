import logging
from telethon import events, Button
from clients import bot_client, user_client
from config import YOUR_USER_ID, WEB_PORT
from channels import load_channels, add_channel, remove_channel, get_subscribed_channels
from messages import get_unread_messages_from_channels, mark_messages_as_read
from summarizer import summarize_texts
from storage import save_summary

logger = logging.getLogger(__name__)

# Состояния диалога для каждого пользователя
user_states: dict[int, str] = {}


async def send_long_message(event, text: str, parse_mode='markdown'):
    """Отправляет длинный текст, разбивая на части по 4000 символов."""
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await event.respond(text, parse_mode=parse_mode)
        return

    while text:
        if len(text) <= MAX_LEN:
            await event.respond(text, parse_mode=parse_mode)
            break
        cut = text.rfind('\n', 0, MAX_LEN)
        if cut == -1:
            cut = MAX_LEN
        await event.respond(text[:cut], parse_mode=parse_mode)
        text = text[cut:].lstrip('\n')


# === Главное меню ===

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return
    buttons = [
        [Button.text("📰 Получить сводку", resize=True)],
        [Button.text("📋 Мои каналы", resize=True)],
        [Button.text("➕ Добавить канал", resize=True),
         Button.text("➖ Удалить канал", resize=True)],
    ]
    await event.respond("Привет! Выбери действие:", buttons=buttons)


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


# === Получить сводку ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "📰 Получить сводку"))
async def summary_request_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    await event.respond("⏳ Собираю непрочитанные сообщения из каналов...")

    try:
        unread_data, all_texts = await get_unread_messages_from_channels()

        if not all_texts:
            await event.respond("✅ Нет непрочитанных сообщений.")
            return

        async def progress(msg: str):
            await event.respond(msg)

        summary = await summarize_texts(all_texts, progress_callback=progress)
        summary_id = save_summary(summary, len(all_texts))

        await event.respond("📝 **Готовая сводка:**", parse_mode='markdown')
        await send_long_message(event, summary)
        await event.respond(
            f"✅ Готово! 🌐 http://103.228.169.198:{WEB_PORT}/summary/{summary_id}"
        )

        await mark_messages_as_read(unread_data)

    except Exception as e:
        logger.exception("Ошибка при получении сводки")
        await event.respond(f"❌ Произошла ошибка: {e}")


# === Добавить канал ===

@bot_client.on(events.NewMessage(func=lambda e: e.text == "➕ Добавить канал"))
async def add_channel_start(event):
    if event.sender_id != YOUR_USER_ID:
        return
    buttons = [
        [Button.inline("📋 Выбрать из моих подписок", data="pick_from_subs")],
        [Button.inline("✍️ Ввести вручную", data="add_manual")],
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

    buttons.append([Button.inline("🔙 Отмена", data="cancel")])
    await event.respond("Какой канал удалить?", buttons=buttons)


# === Inline-кнопки ===

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    data = event.data.decode('utf-8')

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
