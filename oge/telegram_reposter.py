"""
Telegram Channel Auto-Reposter
Мониторит чужой канал и автоматически репостит посты в свой канал
с заменой рекламных ссылок
"""

import asyncio
import re
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
try:
    from config import (
        API_ID, API_HASH, SOURCE_CHANNEL, TARGET_CHANNEL,
        YOUR_CHANNEL_LINK, CHECK_INTERVAL, PROMO_MESSAGE
    )
except ImportError:
    print("❌ Ошибка: Файл config.py не найден!")
    print("Скопируйте config.example.py в config.py и заполните своими данными")
    exit(1)

# Проверка конфигурации
if API_ID == 'YOUR_API_ID' or API_HASH == 'YOUR_API_HASH':
    print("❌ Ошибка: Заполните config.py своими данными!")
    print("Получите API_ID и API_HASH на https://my.telegram.org/apps")
    exit(1)

if not isinstance(API_ID, int):
    try:
        API_ID = int(API_ID)
    except (ValueError, TypeError):
        print("❌ Ошибка: API_ID должен быть числом!")
        exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reposter.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Хранилище обработанных постов (ID последнего поста и текст для проверки дубликатов)
last_processed_id = None
processed_posts = set()  # Множество для проверки дубликатов

# Регулярные выражения для поиска ВСЕХ ссылок
# Удаляем все HTTP/HTTPS ссылки
HTTP_LINK_PATTERN = re.compile(
    r'https?://[^\s<>"\'\)]+',
    re.IGNORECASE
)

# Удаляем ссылки на telegram каналы/боты (t.me, telegram.me)
TELEGRAM_LINK_PATTERN = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/[^\s<>"\'\)]+',
    re.IGNORECASE
)

# HTML ссылки вида <a href="...">текст</a> - удаляем полностью
HTML_LINK_PATTERN = re.compile(
    r'<a\s+[^>]*href=["\']?[^"\'>]+["\']?[^>]*>[^<]*</a>',
    re.IGNORECASE
)

# Markdown ссылки вида [текст](ссылка) - оставляем только текст
MARKDOWN_LINK_PATTERN = re.compile(
    r'\[([^\]]+)\]\([^\)]+\)',
    re.IGNORECASE
)

# Удаляем упоминания каналов вида @channel
MENTION_PATTERN = re.compile(
    r'@[a-zA-Z0-9_]+',
    re.IGNORECASE
)

def clean_text(text):
    """
    Очищает текст от ВСЕХ ссылок и добавляет ссылку на свой канал с завлекающим сообщением
    """
    if not text:
        return ""
    
    cleaned = text
    
    # 1. Удаляем HTML ссылки полностью (<a href="...">текст</a>)
    cleaned = HTML_LINK_PATTERN.sub('', cleaned)
    
    # 2. Удаляем Markdown ссылки, оставляя только текст ([текст](ссылка) -> текст)
    cleaned = MARKDOWN_LINK_PATTERN.sub(r'\1', cleaned)
    
    # 3. Удаляем все HTTP/HTTPS ссылки
    cleaned = HTTP_LINK_PATTERN.sub('', cleaned)
    
    # 4. Удаляем ссылки на telegram каналы/боты (t.me, telegram.me)
    cleaned = TELEGRAM_LINK_PATTERN.sub('', cleaned)
    
    # 5. Удаляем упоминания каналов (@channel) - опционально, можно закомментировать если нужно оставить
    # cleaned = MENTION_PATTERN.sub('', cleaned)
    
    # 6. Очистка от лишних пробелов и переносов строк
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # Максимум 2 переноса подряд
    cleaned = re.sub(r' {2,}', ' ', cleaned)  # Убираем множественные пробелы
    cleaned = cleaned.strip()  # Убираем пробелы в начале и конце
    
    # 7. Добавляем завлекающее сообщение и ссылку на свой канал в конец
    if YOUR_CHANNEL_LINK:
        # Проверяем, нет ли уже нашей ссылки
        if YOUR_CHANNEL_LINK not in cleaned:
            footer = ""
            
            # Добавляем завлекающее сообщение, если оно указано
            if PROMO_MESSAGE and PROMO_MESSAGE.strip():
                footer = f"\n\n{PROMO_MESSAGE.strip()}"
            
            # Добавляем ссылку на канал
            footer += f"\n{YOUR_CHANNEL_LINK}"
            
            if cleaned:
                cleaned += footer
            else:
                # Если весь текст был удален, оставляем только промо и ссылку
                cleaned = (PROMO_MESSAGE.strip() + "\n" + YOUR_CHANNEL_LINK) if PROMO_MESSAGE and PROMO_MESSAGE.strip() else YOUR_CHANNEL_LINK
    
    return cleaned

async def process_and_repost(client, message):
    """
    Обрабатывает сообщение и репостит в целевой канал
    """
    global last_processed_id, processed_posts
    
    try:
        # Проверка на дубликат (по ID сообщения)
        if message.id in processed_posts:
            logger.debug(f"⏭️ Пропущен дубликат: {message.id}")
            return
        
        # Получаем текст сообщения
        text = message.message or ""
        
        # Очищаем текст
        cleaned_text = clean_text(text)
        
        # Если текст пустой после очистки, используем оригинал
        if not cleaned_text and text:
            cleaned_text = text
        
        # Подготовка медиа
        media = None
        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                media = message.media
            elif isinstance(message.media, MessageMediaDocument):
                media = message.media
        
        # Отправляем в целевой канал
        if media:
            await client.send_file(
                TARGET_CHANNEL,
                file=message.media,
                caption=cleaned_text if cleaned_text else None,
                parse_mode=None  # Без форматирования для безопасности
            )
            logger.info(f"✅ Репост с медиа: {message.id}")
        else:
            if cleaned_text:
                await client.send_message(
                    TARGET_CHANNEL,
                    cleaned_text,
                    parse_mode=None  # Без форматирования для безопасности
                )
                logger.info(f"✅ Репост текста: {message.id}")
            else:
                logger.warning(f"⚠️ Пропущен пустой пост: {message.id}")
                return
        
        # Сохраняем информацию о обработанном посте
        last_processed_id = message.id
        processed_posts.add(message.id)
        
        # Ограничиваем размер множества (храним последние 1000 постов)
        if len(processed_posts) > 1000:
            processed_posts = set(list(processed_posts)[-500:])
        
        logger.info(f"📝 Обработан пост ID: {message.id} в {datetime.now().strftime('%H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке поста {message.id}: {str(e)}")

async def check_new_posts(client):
    """
    Проверяет новые посты в исходном канале
    """
    global last_processed_id
    
    try:
        # Получаем последние сообщения из канала
        messages = await client.get_messages(SOURCE_CHANNEL, limit=5)
        
        if not messages:
            return
        
        # Находим самый новый пост
        latest_message = None
        for msg in messages:
            if msg.message or msg.media:  # Пропускаем служебные сообщения
                if latest_message is None or msg.id > latest_message.id:
                    latest_message = msg
        
        if not latest_message:
            return
        
        # Если это новый пост
        if last_processed_id is None or latest_message.id > last_processed_id:
            logger.info(f"🆕 Найден новый пост ID: {latest_message.id}")
            await process_and_repost(client, latest_message)
        else:
            logger.debug(f"⏳ Новых постов нет (последний: {last_processed_id})")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке постов: {str(e)}")

async def main():
    """
    Основная функция
    """
    client = TelegramClient('reposter_session', API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("🚀 Бот запущен!")
        
        # Проверяем доступ к каналам
        try:
            source_entity = await client.get_entity(SOURCE_CHANNEL)
            target_entity = await client.get_entity(TARGET_CHANNEL)
            logger.info(f"📡 Мониторинг канала: {source_entity.title}")
            logger.info(f"📤 Публикация в канал: {target_entity.title}")
        except Exception as e:
            logger.error(f"❌ Ошибка доступа к каналам: {str(e)}")
            logger.error("Проверьте правильность username каналов и права доступа")
            return
        
        # Первичная проверка для получения последнего поста
        await check_new_posts(client)
        
        # Настраиваем обработчик новых сообщений в реальном времени
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
        async def handler(event):
            message = event.message
            # Пропускаем служебные сообщения
            if message.message or message.media:
                logger.info(f"🔔 Получено новое сообщение ID: {message.id}")
                await process_and_repost(client, message)
        
        logger.info("👂 Ожидание новых постов...")
        
        # Дополнительная периодическая проверка на случай пропуска событий
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            await check_new_posts(client)
            
    except KeyboardInterrupt:
        logger.info("⏹️ Остановка бота...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {str(e)}")
    finally:
        await client.disconnect()
        logger.info("👋 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())

