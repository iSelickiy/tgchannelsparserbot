import asyncio
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

# ─── Состояния ──────────────────────────────────────────────────────────────
user_states: dict[int, str] = {}
user_messages: dict[int, list[int]] = {}   # ID сообщений бота для удаления
user_add_sel: dict[int, set[str]] = {}     # каналы, выбранные для добавления
user_del_sel: dict[int, set[str]] = {}     # каналы, выбранные для удаления
user_page: dict[int, int] = {}             # текущая страница списка подписок

PAGE_SIZE = 8  # каналов на страницу

MAIN_MENU_BUTTONS = [
    [Button.text("📰 Получить сводку", resize=True)],
    [Button.text("📋 Мои каналы", resize=True)],
    [Button.text("➕ Добавить канал", resize=True),
     Button.text("➖ Удалить канал", resize=True)],
    [Button.text("📚 История", resize=True)],
]


# ─── Вспомогательные функции ─────────────────────────────────────────────────

async def track(user_id: int, msg) -> None:
    user_messages.setdefault(user_id, []).append(msg.id)


async def delete_bot_messages(user_id: int, chat_id: int) -> None:
    ids = user_messages.pop(user_id, [])
    if ids:
        try:
            await bot_client.delete_messages(chat_id, ids)
        except Exception:
            pass


async def _show_subs_page(event, page: int, edit: bool = True) -> None:
    """
    Отображает страницу подписок для мультивыбора каналов на добавление.
    Первый вызов загружает подписки (~медленно), повторные — из кэша (мгновенно).
    """
    subscribed = await get_subscribed_channels(user_client)
    current = set(load_channels())
    available = [
        ch for ch in subscribed
        if ch['username'] not in current and str(ch['id']) not in current
    ]

    if not available:
        text = "Все твои каналы уже добавлены!"
        if edit:
            await event.edit(text)
        else:
            msg = await event.respond(text)
            await track(event.sender_id, msg)
        return

    total_pages = (len(available) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    user_page[event.sender_id] = page

    page_items = available[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    sel = user_add_sel.get(event.sender_id, set())

    buttons = []
    for ch in page_items:
        mark = "✅" if ch['username'] in sel else "⬜"
        label = f"{mark} {ch['title']} ({ch['unread_count']} непрочит.)"
        buttons.append([Button.inline(label, data=f"sadd:{ch['username']}")])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(Button.inline("◀️", data=f"subs:{page - 1}"))
        nav.append(Button.inline(f"{page + 1} / {total_pages}", data="noop"))
        if page < total_pages - 1:
            nav.append(Button.inline("▶️", data=f"subs:{page + 1}"))
        buttons.append(nav)

    if sel:
        buttons.append([Button.inline(f"✅ Добавить выбранные ({len(sel)})", data="addok")])

    buttons.append([Button.inline("🏠 Главное меню", data="menu")])

    text = f"Выбери каналы для добавления (стр. {page + 1}/{total_pages}):"
    if edit:
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            msg = await bot_client.send_message(event.chat_id, text, buttons=buttons)
            await track(event.sender_id, msg)
    else:
        msg = await event.respond(text, buttons=buttons)
        await track(event.sender_id, msg)


async def _show_del_menu(event, edit: bool = False) -> None:
    """
    Отображает список отслеживаемых каналов для мультивыбора удаления.
    Имена каналов разрешаются параллельно.
    """
    channels = load_channels()
    if not channels:
        text = "Список каналов пуст."
        if edit:
            await event.edit(text)
        else:
            await event.respond(text)
        return

    async def resolve(ch_id: str) -> tuple[str, str]:
        try:
            entity = await user_client.get_entity(ch_id)
            return ch_id, getattr(entity, 'title', ch_id)
        except Exception:
            return ch_id, ch_id

    resolved = await asyncio.gather(*[resolve(ch) for ch in channels])
    sel = user_del_sel.get(event.sender_id, set())

    buttons = []
    for ch_id, name in resolved:
        mark = "✅" if ch_id in sel else "⬜"
        buttons.append([Button.inline(f"{mark} {name}", data=f"dtog:{ch_id}")])

    if sel:
        buttons.append([Button.inline(f"🗑 Удалить выбранные ({len(sel)})", data="delok")])

    buttons.append([Button.inline("🏠 Главное меню", data="menu")])

    text = "Выбери каналы для удаления:"
    if edit:
        try:
            await event.edit(text, buttons=buttons)
        except Exception:
            msg = await bot_client.send_message(event.chat_id, text, buttons=buttons)
            await track(event.sender_id, msg)
    else:
        msg = await event.respond(text, buttons=buttons)
        await track(event.sender_id, msg)


# ─── Главное меню ─────────────────────────────────────────────────────────────

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return
    await delete_bot_messages(event.sender_id, event.chat_id)
    msg = await event.respond("Привет! Выбери действие:", buttons=MAIN_MENU_BUTTONS)
    await track(event.sender_id, msg)


# ─── Список каналов ───────────────────────────────────────────────────────────

@bot_client.on(events.NewMessage(func=lambda e: e.text == "📋 Мои каналы"))
async def list_channels_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    channels = load_channels()
    if not channels:
        await event.respond("Список каналов пуст. Добавь каналы кнопкой ➕")
        return

    async def resolve(ch):
        try:
            entity = await user_client.get_entity(ch)
            return getattr(entity, 'title', ch), ch
        except Exception:
            return ch, ch

    resolved = await asyncio.gather(*[resolve(ch) for ch in channels])
    text = "**Твои каналы:**\n\n" + "".join(
        f"{i}. {name} (`{ch}`)\n" for i, (name, ch) in enumerate(resolved, 1)
    )
    await event.respond(text, parse_mode='markdown')


# ─── История ──────────────────────────────────────────────────────────────────

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
        buttons.append([Button.url(label, f"{SERVER_BASE_URL}/summary/{s['id']}")])

    buttons.append([Button.inline("🏠 Главное меню", data="menu")])
    msg = await event.respond("📚 Сводки за последние 30 дней:", buttons=buttons)
    await track(event.sender_id, msg)


# ─── Получить сводку ──────────────────────────────────────────────────────────

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

        await delete_bot_messages(event.sender_id, event.chat_id)
        msg = await event.respond(
            f"✅ Сводка №{summary_id} за {datetime.date.today().strftime('%d.%m.%Y')}",
            buttons=[
                [Button.url("🌐 Читать", f"{SERVER_BASE_URL}/summary/{summary_id}")],
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


# ─── Добавить канал ───────────────────────────────────────────────────────────

@bot_client.on(events.NewMessage(func=lambda e: e.text == "➕ Добавить канал"))
async def add_channel_start(event):
    if event.sender_id != YOUR_USER_ID:
        return
    msg = await event.respond(
        "Как добавить канал?",
        buttons=[
            [Button.inline("📋 Выбрать из моих подписок", data="pick_from_subs")],
            [Button.inline("✍️ Ввести вручную", data="add_manual")],
            [Button.inline("🏠 Главное меню", data="menu")],
        ]
    )
    await track(event.sender_id, msg)


# ─── Удалить канал ────────────────────────────────────────────────────────────

@bot_client.on(events.NewMessage(func=lambda e: e.text == "➖ Удалить канал"))
async def remove_channel_start(event):
    if event.sender_id != YOUR_USER_ID:
        return
    await _show_del_menu(event, edit=False)


# ─── Inline-кнопки ────────────────────────────────────────────────────────────

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    data = event.data.decode('utf-8')

    # ── Главное меню ──
    if data == "menu":
        await event.answer()
        await event.delete()
        await delete_bot_messages(event.sender_id, event.chat_id)
        user_add_sel.pop(event.sender_id, None)
        user_del_sel.pop(event.sender_id, None)
        user_page.pop(event.sender_id, None)
        msg = await bot_client.send_message(
            event.chat_id, "Главное меню:", buttons=MAIN_MENU_BUTTONS
        )
        await track(event.sender_id, msg)
        return

    if data == "noop":
        await event.answer()
        return

    if data == "cancel":
        await event.answer("Отменено")
        await event.delete()
        return

    # ── Добавление: ручной ввод ──
    if data == "add_manual":
        await event.answer()
        user_states[event.sender_id] = 'adding_channel'
        await event.edit(
            "Отправь мне ссылку на канал или его @username.\n"
            "Например: `@durov` или `https://t.me/durov`\n\n"
            "Или нажми /cancel для отмены."
        )
        return

    # ── Добавление: список подписок (открыть / перейти на страницу) ──
    if data == "pick_from_subs":
        await event.answer("Загружаю подписки...")
        user_add_sel.pop(event.sender_id, None)
        await _show_subs_page(event, 0, edit=True)
        return

    if data.startswith("subs:"):
        await event.answer()
        await _show_subs_page(event, int(data[5:]), edit=True)
        return

    # ── Добавление: тогл канала ──
    if data.startswith("sadd:"):
        username = data[5:]
        sel = user_add_sel.setdefault(event.sender_id, set())
        sel.discard(username) if username in sel else sel.add(username)
        await event.answer()
        await _show_subs_page(event, user_page.get(event.sender_id, 0), edit=True)
        return

    # ── Добавление: подтверждение ──
    if data == "addok":
        sel = user_add_sel.pop(event.sender_id, set())
        if not sel:
            await event.answer("Ничего не выбрано")
            return
        added = [ch for ch in sel if add_channel(ch)]
        logger.info(f"Добавлено каналов: {added}")
        await event.answer(f"Добавлено: {len(added)}")
        await event.edit(
            f"✅ Добавлено {len(added)} канал(ов):\n" +
            "\n".join(f"• `{ch}`" for ch in added),
            parse_mode='markdown'
        )
        return

    # ── Удаление: тогл канала ──
    if data.startswith("dtog:"):
        ch_id = data[5:]
        sel = user_del_sel.setdefault(event.sender_id, set())
        sel.discard(ch_id) if ch_id in sel else sel.add(ch_id)
        await event.answer()
        await _show_del_menu(event, edit=True)
        return

    # ── Удаление: подтверждение ──
    if data == "delok":
        sel = user_del_sel.pop(event.sender_id, set())
        if not sel:
            await event.answer("Ничего не выбрано")
            return
        removed = [ch for ch in sel if remove_channel(ch)]
        logger.info(f"Удалено каналов: {removed}")
        await event.answer(f"Удалено: {len(removed)}")
        await event.edit(
            f"✅ Удалено {len(removed)} канал(ов):\n" +
            "\n".join(f"• `{ch}`" for ch in removed),
            parse_mode='markdown'
        )
        return


# ─── Текстовые сообщения (ручной ввод канала) ────────────────────────────────

@bot_client.on(events.NewMessage())
async def text_handler(event):
    if event.sender_id != YOUR_USER_ID:
        return

    if user_states.get(event.sender_id) != 'adding_channel':
        return

    if event.text == '/cancel':
        user_states.pop(event.sender_id, None)
        await event.respond("Отменено.")
        return

    channel_input = event.text.strip()
    if channel_input.startswith('https://t.me/'):
        channel_input = '@' + channel_input.split('/')[-1]

    try:
        entity = await user_client.get_entity(channel_input)
        name = getattr(entity, 'title', channel_input)
        if add_channel(channel_input):
            logger.info(f"Канал добавлен вручную: {channel_input}")
            await event.respond(f"✅ Канал **{name}** добавлен!", parse_mode='markdown')
        else:
            await event.respond(f"Канал **{name}** уже в списке.", parse_mode='markdown')
    except Exception as e:
        await event.respond(f"❌ Не удалось найти канал: {channel_input}\nОшибка: {e}")

    user_states.pop(event.sender_id, None)
