"""Конфигурация проекта WrauX / RuWEEX"""
import os
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла (опционально)
load_dotenv()

# === ДАННЫЕ ВАШЕГО БОТА / АККАУНТА ===
# Если хотите, можете вынести их в .env,
# но сейчас они захардкожены по вашим данным.

# Токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8596718407:AAHPJuta1DiE1150PzIam0nExvNGIg-wsZ8"

# API credentials из my.telegram.org
API_ID = int(os.getenv("API_ID") or 31889511)
API_HASH = os.getenv("API_HASH") or "e2760abf213126f085fe9683d78f2db7"

# Директория для хранения сессий
SESSIONS_DIR = "sessions"

# Путь к базе данных
DATABASE_PATH = "wraux_bot.db"

# Настройки прокси (опционально)
# Формат: {'proxy_type': 'socks5', 'addr': '127.0.0.1', 'port': 1080, 'username': None, 'password': None}
# Или можно использовать из переменных окружения:
# PROXY_TYPE=socks5 PROXY_ADDR=127.0.0.1 PROXY_PORT=1080 PROXY_USER=user PROXY_PASS=pass
# 
# ВАЖНО: Для лучшей защиты от блокировок рекомендуется использовать прокси!
# Прокси должен быть SOCKS5 и соответствовать стране номера телефона

# Список доступных прокси для ротации (если нужно использовать разные прокси)
PROXY_LIST = [
    {
        'proxy_type': 'socks5',
        'addr': '192.109.91.157',
        'port': 8000,
        'username': 'YdpUBS',
        'password': 'B6XH5x'
    },
    {
        'proxy_type': 'socks5',
        'addr': '192.109.100.174',
        'port': 8000,
        'username': 'YdpUBS',
        'password': 'B6XH5x'
    },
    {
        'proxy_type': 'socks5',
        'addr': '192.109.100.19',
        'port': 8000,
        'username': 'YdpUBS',
        'password': 'B6XH5x'
    }
]

# Основной прокси (используется по умолчанию - первый из списка)
PROXY = PROXY_LIST[0] if PROXY_LIST else None

# Если прокси заданы через переменные окружения, они имеют приоритет
proxy_type = os.getenv("PROXY_TYPE")
if proxy_type:
    try:
        PROXY = {
            'proxy_type': proxy_type.lower(),  # 'socks5', 'http', 'socks4'
            'addr': os.getenv("PROXY_ADDR", "127.0.0.1"),
            'port': int(os.getenv("PROXY_PORT", 1080)),
            'username': os.getenv("PROXY_USER"),
            'password': os.getenv("PROXY_PASS")
        }
        # Проверка корректности типа прокси
        if PROXY['proxy_type'] not in ['socks5', 'socks4', 'http']:
            print(f"[WARNING] Неподдерживаемый тип прокси: {PROXY['proxy_type']}, используем socks5")
            PROXY['proxy_type'] = 'socks5'
        print(f"[PROXY] Прокси настроен из переменных окружения: {PROXY['proxy_type']}://{PROXY['addr']}:{PROXY['port']}")
    except Exception as e:
        print(f"[ERROR] Ошибка настройки прокси из переменных окружения: {e}")
        # Используем прокси из списка, если настройка из env не удалась
        PROXY = PROXY_LIST[0] if PROXY_LIST else None

# Вывод информации о прокси
if PROXY:
    proxy_info = f"{PROXY['proxy_type']}://{PROXY['addr']}:{PROXY['port']}"
    if PROXY.get('username'):
        proxy_info += f" (user: {PROXY['username']})"
    print(f"[PROXY] ✅ Прокси настроен: {proxy_info}")
    print(f"[PROXY] Доступно прокси для ротации: {len(PROXY_LIST)}")
else:
    print("[PROXY] ⚠️ Прокси не настроен. Рекомендуется использовать прокси для защиты от блокировок.")

# === RuWEEX / управление доступом ===

# ID администратора (панель управления)
ADMIN_ID = int(os.getenv("ADMIN_ID") or 8496337858)

# Канал, на который пользователь обязан подписаться,
# чтобы получить 1 день бесплатного доступа
# ВАЖНО: сюда нужно вручную поставить реальный chat_id канала RuWEEX
# после того, как бот будет добавлен в канал.
# Временное значение-заглушка, чтобы код не падал.
REQUIRED_CHANNEL_ID = int(os.getenv("REQUIRED_CHANNEL_ID") or -1003627900148)

# Ссылка-приглашение на канал RuWEEX (для сообщений бота)
REQUIRED_CHANNEL_LINK = os.getenv("REQUIRED_CHANNEL_LINK") or "https://t.me/+YyPx-IwvUEdhMTFl"

# Название проекта
PROJECT_NAME = os.getenv("PROJECT_NAME") or "RuWEEX"

# Создаем директорию для сессий, если её нет
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)
