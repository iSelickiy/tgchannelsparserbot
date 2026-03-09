import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
YOUR_USER_ID = int(os.getenv('YOUR_USER_ID'))

# Настройки суммаризации
MAX_CHARS_PER_REQUEST = 30_000
MAX_CONCURRENT_REQUESTS = 5
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# Веб-сервер
WEB_PORT = int(os.getenv('WEB_PORT', 8080))
SUMMARY_RETENTION_DAYS = 30

# Приоритеты тем для суммаризации
TOPIC_PRIORITIES = {
    "политика/геополитика": "кратко, 1-2 предложения на новость",
    "технологии/ИИ": "подробно, сохраняй все детали и цифры",
    "экономика/финансы": "средне, основные факты и цифры",
    "наука": "подробно",
    "бизнес": "средне, основные факты",
}
