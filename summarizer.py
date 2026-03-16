import asyncio
import math
import logging
from clients import deepseek_client
from config import DEEPSEEK_MODEL, MAX_CHARS_PER_REQUEST, MAX_CONCURRENT_REQUESTS, TOPIC_PRIORITIES

_SECS_PER_API_CALL = 140  # эмпирически: ~2 мин 20 сек на один вызов DeepSeek


def _estimate_minutes(chunks: int) -> int:
    """Грубая оценка времени ожидания в минутах."""
    if chunks == 1:
        api_calls = 1
    else:
        parallel_rounds = math.ceil(chunks / MAX_CONCURRENT_REQUESTS)
        api_calls = parallel_rounds + 1  # параллельные чанки + итоговый вызов
    return max(1, round(api_calls * _SECS_PER_API_CALL / 60))

logger = logging.getLogger(__name__)

# === ПРОМПТЫ ===

_priorities_text = "\n".join(f"- {k}: {v}" for k, v in TOPIC_PRIORITIES.items())

SYSTEM_PROMPT = f"""Ты — профессиональный редактор ежедневного дайджеста. Твоя задача — создавать
информативные, структурированные сводки из сырых сообщений Telegram-каналов.

Каналы содержат разнообразный контент: новости, анонсы мероприятий, афишу событий,
рекомендации (места, книги, сервисы, фильмы), спортивные результаты, локальные события.
Все типы контента одинаково важны — ничего не отбрасывай.

Правила:
- Пиши на русском языке
- Группируй информацию по темам, не по каналам
- Сохраняй все ключевые факты: цифры, имена, даты, ссылки, адреса, время проведения
- Для каждого пункта указывай источник (название канала) в скобках
- Если информация упоминается в нескольких каналах — объединяй, отмечая все источники
- Не добавляй своих оценок и комментариев
- Используй Markdown-форматирование
- Сохраняй ссылки на оригинальные посты, если они есть в тексте
- Анонсы мероприятий и афиши обязательно выноси в отдельный раздел с датами и местами
- Рекомендации (что посетить, посмотреть, попробовать) — тоже в отдельный раздел

Уровни подробности по темам:
{_priorities_text}"""

CHUNK_PROMPT = """Обработай следующие сообщения из Telegram-каналов.
Для каждого тематического блока:
1. Выдели заголовок темы
2. Перечисли ключевые факты
3. Укажи источники и ссылки на оригиналы

Важно: сообщения могут содержать не только новости, но и анонсы мероприятий,
афишу событий, рекомендации мест и сервисов. Сохраняй всё — ничего не отбрасывай.

Сообщения:
{text}"""

FINAL_PROMPT = """Ниже — обработанные блоки сообщений из Telegram-каналов за день.
Создай итоговую сводку-дайджест. Контент разнообразный: новости, события, афиша,
рекомендации, спорт, локальные новости. Включи ВСЁ — ничего не выбрасывай.

## Обязательная структура ответа:

### 🔥 Главное (3-5 самых важных новостей/событий дня — по 2-3 предложения каждая)

### 📂 Новости по темам:
Сгруппируй новости по категориям. Примеры категорий:
- Технологии и ИИ
- Бизнес и экономика
- Политика
- Кино, игры и развлечения
- Спорт
- Происшествия
- Другое

Для каждой новости:
- Заголовок жирным
- 1-3 предложения с фактами
- (источник) в конце, ссылка на оригинальный пост если есть

### 🎭 Афиша и мероприятия
Все анонсы событий, выставок, концертов, фестивалей, мастер-классов, открытий.
Для каждого события укажи:
- Название события жирным
- Дата и время (если указаны)
- Место проведения (если указано)
- Краткое описание (1-2 предложения)
- (источник)
Если таких событий нет в исходных данных — напиши "Сегодня без анонсов".

### 💡 Рекомендации
Советы, подборки, рекомендации из каналов: что посетить, посмотреть, попробовать,
куда сходить, полезные сервисы, книги, фильмы, места.
Если рекомендаций нет — напиши "Сегодня без рекомендаций".

### 📊 Цифра дня (одна интересная цифра или факт из сводки, если есть)

---
Обработанные блоки:
{text}"""


def split_texts_into_chunks(texts: list[str]) -> list[str]:
    """Разбивает тексты на части, не превышающие MAX_CHARS_PER_REQUEST."""
    chunks = []
    current = ""
    for text in texts:
        if len(current) + len(text) + 2 <= MAX_CHARS_PER_REQUEST:
            current = f"{current}\n\n{text}" if current else text
        else:
            if current:
                chunks.append(current)
            current = text
    if current:
        chunks.append(current)
    return chunks


async def call_deepseek(prompt: str, system: str = SYSTEM_PROMPT,
                        max_retries: int = 3) -> str:
    """Вызов DeepSeek API с retry и экспоненциальной задержкой."""
    for attempt in range(max_retries):
        try:
            response = await deepseek_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=3000
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"DeepSeek retry {attempt + 1}/{max_retries} через {wait}с: {e}")
                await asyncio.sleep(wait)
            else:
                raise


async def summarize_texts(all_texts: list[str], progress_callback=None) -> str:
    """
    Полный пайплайн суммаризации.

    Args:
        all_texts: список текстов сообщений
        progress_callback: async функция для отправки статуса пользователю
    """
    chunks = split_texts_into_chunks(all_texts)

    if progress_callback:
        est = _estimate_minutes(len(chunks))
        await progress_callback(
            f"📊 {len(all_texts)} сообщений → {len(chunks)} запросов к AI\n"
            f"⏱ Примерное время ожидания: ~{est} мин."
        )

    # Один чанк — обрабатываем за один API-вызов
    if len(chunks) == 1:
        if progress_callback:
            await progress_callback("⏳ Формирую сводку...")
        return await call_deepseek(FINAL_PROMPT.format(text=chunks[0]))

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def process_chunk(chunk: str, index: int) -> str:
        async with semaphore:
            if progress_callback:
                await progress_callback(f"⏳ Обрабатываю часть {index + 1}/{len(chunks)}...")
            return await call_deepseek(CHUNK_PROMPT.format(text=chunk))

    partial = await asyncio.gather(*[process_chunk(c, i) for i, c in enumerate(chunks)])

    if progress_callback:
        await progress_callback("🔗 Собираю итоговую сводку...")

    combined = "\n\n---\n\n".join(partial)
    return await call_deepseek(FINAL_PROMPT.format(text=combined))
