from telethon import TelegramClient
from openai import AsyncOpenAI
from config import API_ID, API_HASH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

user_client = TelegramClient(
    'user_session', API_ID, API_HASH,
    device_model="Desktop",
    system_version="Windows 10",
    app_version="4.16.31"
)

bot_client = TelegramClient('bot_session', API_ID, API_HASH)

deepseek_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)
