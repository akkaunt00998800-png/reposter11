"""
Тестовый скрипт для проверки функции очистки текста
Запустите этот файл, чтобы проверить, как работает удаление ссылок
"""

import re
import sys
sys.path.insert(0, '.')

from config import YOUR_CHANNEL_LINK, PROMO_MESSAGE

# Регулярные выражения (скопированы из telegram_reposter.py)
HTTP_LINK_PATTERN = re.compile(r'https?://[^\s<>"\'\)]+', re.IGNORECASE)
TELEGRAM_LINK_PATTERN = re.compile(r'(?:https?://)?(?:t\.me|telegram\.me)/[^\s<>"\'\)]+', re.IGNORECASE)
HTML_LINK_PATTERN = re.compile(r'<a\s+[^>]*href=["\']?[^"\'>]+["\']?[^>]*>[^<]*</a>', re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\([^\)]+\)', re.IGNORECASE)

def clean_text(text):
    """Функция очистки текста (копия из telegram_reposter.py)"""
    if not text:
        return ""
    
    cleaned = text
    
    # 1. Удаляем HTML ссылки полностью
    cleaned = HTML_LINK_PATTERN.sub('', cleaned)
    
    # 2. Удаляем Markdown ссылки, оставляя только текст
    cleaned = MARKDOWN_LINK_PATTERN.sub(r'\1', cleaned)
    
    # 3. Удаляем все HTTP/HTTPS ссылки
    cleaned = HTTP_LINK_PATTERN.sub('', cleaned)
    
    # 4. Удаляем ссылки на telegram каналы/боты
    cleaned = TELEGRAM_LINK_PATTERN.sub('', cleaned)
    
    # 5. Очистка от лишних пробелов
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = cleaned.strip()
    
    # 6. Добавляем завлекающее сообщение и ссылку
    if YOUR_CHANNEL_LINK:
        if YOUR_CHANNEL_LINK not in cleaned:
            footer = ""
            if PROMO_MESSAGE and PROMO_MESSAGE.strip():
                footer = f"\n\n{PROMO_MESSAGE.strip()}"
            footer += f"\n{YOUR_CHANNEL_LINK}"
            
            if cleaned:
                cleaned += footer
            else:
                cleaned = (PROMO_MESSAGE.strip() + "\n" + YOUR_CHANNEL_LINK) if PROMO_MESSAGE and PROMO_MESSAGE.strip() else YOUR_CHANNEL_LINK
    
    return cleaned

# Тестовые примеры
test_cases = [
    {
        "name": "Пост с обычной ссылкой",
        "input": "Ответы на контрольную работу:\n\n1. Вариант А\n2. Вариант Б\n\nБольше здесь: https://t.me/other_channel"
    },
    {
        "name": "Пост с несколькими ссылками",
        "input": "Материалы для подготовки:\n\nhttps://example.com/file.pdf\nhttps://t.me/other_channel\n\nПодписывайтесь!"
    },
    {
        "name": "Пост с HTML ссылкой",
        "input": "Проверьте ответы <a href='https://t.me/other_channel'>здесь</a> и готовьтесь к экзамену"
    },
    {
        "name": "Пост с Markdown ссылкой",
        "input": "Все ответы [в этом канале](https://t.me/other_channel) и еще [здесь](https://example.com)"
    },
    {
        "name": "Пост только со ссылками",
        "input": "https://t.me/other_channel\nhttps://example.com/test"
    },
    {
        "name": "Пост без ссылок",
        "input": "Ответы на вопросы:\n\n1. Первый ответ\n2. Второй ответ"
    }
]

print("=" * 60)
print("ТЕСТИРОВАНИЕ ФУНКЦИИ ОЧИСТКИ ТЕКСТА")
print("=" * 60)
print(f"\nВаша ссылка: {YOUR_CHANNEL_LINK}")
print(f"Завлекающее сообщение: {PROMO_MESSAGE if PROMO_MESSAGE else '(не указано)'}")
print("\n" + "=" * 60 + "\n")

for i, test in enumerate(test_cases, 1):
    print(f"Тест {i}: {test['name']}")
    print("-" * 60)
    print("ВХОДНОЙ ТЕКСТ:")
    print(test['input'])
    print("\nРЕЗУЛЬТАТ ПОСЛЕ ОЧИСТКИ:")
    result = clean_text(test['input'])
    print(result)
    print("\n" + "=" * 60 + "\n")

print("\n✅ Тестирование завершено!")
print("\nПроверьте результаты выше. Все ссылки должны быть удалены,")
print("а в конце должен быть ваш канал с завлекающим сообщением.")


