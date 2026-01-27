"""Модуль для генерации случайных параметров устройства (антидетект)"""
import random
import hashlib


# База данных устройств для антидетекта
DEVICES = {
    'ios': [
        {'model': 'iPhone 13 Pro', 'system': 'iOS 15.0', 'app': '9.0'},
        {'model': 'iPhone 13', 'system': 'iOS 15.1', 'app': '9.1'},
        {'model': 'iPhone 14 Pro', 'system': 'iOS 16.0', 'app': '9.2'},
        {'model': 'iPhone 14', 'system': 'iOS 16.1', 'app': '9.3'},
        {'model': 'iPhone 15 Pro', 'system': 'iOS 17.0', 'app': '9.4'},
        {'model': 'iPhone 15', 'system': 'iOS 17.1', 'app': '9.5'},
        {'model': 'iPhone 12 Pro', 'system': 'iOS 14.8', 'app': '8.9'},
        {'model': 'iPhone 12', 'system': 'iOS 14.7', 'app': '8.8'},
        {'model': 'iPhone 11 Pro', 'system': 'iOS 13.7', 'app': '8.7'},
        {'model': 'iPhone 11', 'system': 'iOS 13.6', 'app': '8.6'},
    ],
    'android': [
        {'model': 'Samsung Galaxy S21', 'system': 'Android 11', 'app': '9.0'},
        {'model': 'Samsung Galaxy S22', 'system': 'Android 12', 'app': '9.1'},
        {'model': 'Samsung Galaxy S23', 'system': 'Android 13', 'app': '9.2'},
        {'model': 'Xiaomi Mi 11', 'system': 'Android 11', 'app': '9.0'},
        {'model': 'Xiaomi Mi 12', 'system': 'Android 12', 'app': '9.1'},
        {'model': 'Huawei P50', 'system': 'Android 11', 'app': '9.0'},
        {'model': 'OnePlus 9', 'system': 'Android 11', 'app': '9.0'},
        {'model': 'Google Pixel 6', 'system': 'Android 12', 'app': '9.1'},
        {'model': 'Sony Xperia 1 III', 'system': 'Android 11', 'app': '9.0'},
        {'model': 'OPPO Find X3', 'system': 'Android 11', 'app': '9.0'},
    ]
}

LANG_CODES = ['en', 'ru', 'uk', 'de', 'fr', 'es', 'it', 'pt']
SYSTEM_LANG_CODES = {
    'en': 'en-US',
    'ru': 'ru-RU',
    'uk': 'uk-UA',
    'de': 'de-DE',
    'fr': 'fr-FR',
    'es': 'es-ES',
    'it': 'it-IT',
    'pt': 'pt-BR'
}


def generate_device_params(user_id: int, phone: str, prefer_ios: bool = True):
    """
    Генерация уникальных параметров устройства для пользователя
    
    Args:
        user_id: ID пользователя
        phone: Номер телефона
        prefer_ios: Предпочитать iOS устройства (по умолчанию True)
    
    Returns:
        dict с параметрами устройства
    """
    # Создаем детерминированный seed на основе user_id и phone
    # Это гарантирует, что для одного пользователя всегда будет одно устройство
    seed_string = f"{user_id}_{phone}"
    seed = int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)
    random.seed(seed)
    
    # Выбираем тип устройства (70% iOS, 30% Android если prefer_ios=True)
    if prefer_ios:
        device_type = 'ios' if random.random() < 0.7 else 'android'
    else:
        device_type = 'android' if random.random() < 0.7 else 'ios'
    
    # Выбираем случайное устройство из базы
    device = random.choice(DEVICES[device_type])
    
    # Выбираем язык
    lang_code = random.choice(LANG_CODES)
    system_lang_code = SYSTEM_LANG_CODES.get(lang_code, 'en-US')
    
    # Добавляем небольшую вариацию в версию приложения
    app_version = device['app']
    if random.random() < 0.3:  # 30% шанс на минорную версию
        app_version = f"{app_version}.{random.randint(1, 9)}"
    
    return {
        'device_model': device['model'],
        'system_version': device['system'],
        'app_version': app_version,
        'lang_code': lang_code,
        'system_lang_code': system_lang_code
    }


def get_device_for_session(session_file: str, user_id: int, phone: str):
    """
    Получение параметров устройства для сессии
    Если параметры уже сохранены - возвращаем их, иначе генерируем новые
    """
    # Пока просто генерируем на основе user_id и phone
    # В будущем можно сохранять в БД для каждой сессии
    return generate_device_params(user_id, phone, prefer_ios=True)
