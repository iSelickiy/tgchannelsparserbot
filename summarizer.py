import asyncio
import logging
from clients import deepseek_client
from config import DEEPSEEK_MODEL, MAX_CHARS_PER_REQUEST, MAX_CONCURRENT_REQUESTS, TOPIC_PRIORITIES

logger = logging.getLogger(__name__)

# === ПРОМПТЫ ===

_priorities_text = "\n".join(f"- {k}: {v}" for k, v in TOPIC_PRIORITIES.items())

SYSTEM_PROMPT = f"""Ты — профессиональный новостной редактор. Твоя задача — создавать
информативные, структурированные сводки из сырых сообщений Telegram-каналов.

Правила:
- Пиши на русском языке
- Группируй новости по темам, не по каналам
- Сохраняй все ключевые факты: цифры, имена, даты, ссылки
- Для каждой новости указывай источник (название канала) в скобках
- Если новость упоминается в нескольких каналах — объединяй, отмечая все источники
- Не добавляй своих оценок и комментариев
- Используй Markdown-форматирование
- Сохраняй ссылки на оригинальные посты, если они есть в тексте

Уровни подробности по темам:
{_priorities_text}"""

CHUNK_PROMPT = """Обработай следующие сообщения из Telegram-каналов.
Для каждого тематического блока:
1. Выдели заголовок темы
2. Перечисли ключевые факты
3. Укажи источники и ссылки на оригиналы

Сообщения:
{text}"""

FINAL_PROMPT = """Ниже — обработанные блоки новостей за день. Создай итоговую сводку:

## Структура ответа:

### 🔥 Главное (3-5 самых важных новостей дня — по 2-3 предложения каждая)

### 📂 По темам:
Сгруппируй остальные новости по категориям. Примеры категорий:
- Технологии и ИИ
- Бизнес и экономика
- Политика
- Наука
- Другое

Для каждой новости:
- Заголовок жирным
- 1-3 предложения с фактами
- (источник) в конце, ссылка на оригинальный пост если есть

### 📊 Цифра дня (одна интересная цифра или факт из новостей, если есть)

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
        await progress_callback(f"📊 {len(all_texts)} сообщений → {len(chunks)} запросов к AI")

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
