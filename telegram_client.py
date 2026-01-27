"""Модуль для работы с Telegram Client API через Telethon"""
import asyncio
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneNumberBannedError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    PhoneNumberFloodError,
    PhoneNumberUnoccupiedError
)
from telethon.tl.types import User, Channel, Chat
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon import events
from config import API_ID, API_HASH, SESSIONS_DIR
from device_generator import generate_device_params, get_device_for_session
import os


class UserTelegramClient:
    """Обертка над Telethon для работы с Telegram API от имени пользователя"""
    
    def __init__(self, session_file: str, api_id: str, api_hash: str, phone: str, proxy: dict = None, user_id: int = None, device_params: dict = None):
        self.session_file = os.path.join(SESSIONS_DIR, session_file)
        self.session_file_name = session_file  # Имя файла без пути для БД
        self.api_id = int(api_id) if api_id else None
        self.api_hash = api_hash
        self.phone = phone
        self.proxy = proxy
        self.user_id = user_id
        self.phone_code_hash = None  # Сохраняем hash кода для sign_in
        
        # Генерируем или используем переданные параметры устройства
        if device_params:
            self.device_params = device_params
        elif user_id:
            self.device_params = get_device_for_session(session_file, user_id, phone)
        else:
            # Fallback на случай, если user_id не передан
            self.device_params = generate_device_params(
                hash(phone) % 1000000,  # Простой hash для генерации
                phone,
                prefer_ios=True
            )
        
        # Настройки для антидетекта (уникальные для каждого пользователя)
        self.client = TelegramClient(
            self.session_file, 
            self.api_id, 
            self.api_hash,
            proxy=self.proxy,
            device_model=self.device_params['device_model'],
            system_version=self.device_params['system_version'],
            app_version=self.device_params['app_version'],
            lang_code=self.device_params['lang_code'],
            system_lang_code=self.device_params['system_lang_code']
        )
        self.is_connected = False
    
    async def connect(self):
        """Подключение к Telegram с проверкой прокси"""
        if not self.is_connected:
            try:
                if self.proxy:
                    print(f"[CLIENT] Подключение через прокси {self.proxy.get('proxy_type', 'unknown')}://{self.proxy.get('addr', 'unknown')}:{self.proxy.get('port', 'unknown')}")
                else:
                    print("[CLIENT] Подключение без прокси (прямое соединение)")
                
                await self.client.connect()
                self.is_connected = True
                print(f"[CLIENT] Успешно подключен. Устройство: {self.device_params['device_model']} {self.device_params['system_version']}")
            except Exception as e:
                print(f"[CLIENT] Ошибка подключения: {e}")
                if self.proxy:
                    print(f"[CLIENT] Проверьте настройки прокси: {self.proxy}")
                raise
    
    async def disconnect(self):
        """Отключение от Telegram"""
        if self.is_connected:
            await self.client.disconnect()
            self.is_connected = False
    
    async def send_code(self):
        """Отправка кода верификации с улучшенной обработкой ошибок"""
        try:
            # Подключаемся только если не подключены
            if not self.is_connected:
                await self.connect()
            
            print(f"[SEND_CODE] Отправка кода для номера: {self.phone}")
            print(f"[SEND_CODE] API_ID: {self.api_id}, API_HASH: {self.api_hash[:10]}...")
            print(f"[SEND_CODE] Устройство: {self.device_params['device_model']} {self.device_params['system_version']}")
            
            # Нормализуем номер телефона (убираем пробелы, дефисы)
            normalized_phone = self.phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            
            # Проверяем формат номера
            if not normalized_phone.startswith('+'):
                if normalized_phone.startswith('7') or normalized_phone.startswith('8'):
                    normalized_phone = '+7' + normalized_phone.lstrip('78')
                else:
                    normalized_phone = '+' + normalized_phone
            
            print(f"[SEND_CODE] Нормализованный номер: {normalized_phone}")
            
            # Отправляем запрос на код
            result = await self.client.send_code_request(normalized_phone)
            
            # Сохраняем phone_code_hash для использования в sign_in
            if result and hasattr(result, 'phone_code_hash'):
                self.phone_code_hash = result.phone_code_hash
                print(f"[SEND_CODE] ✅ Код успешно отправлен!")
                print(f"[SEND_CODE] phone_code_hash: {self.phone_code_hash[:20]}...")
                print(f"[SEND_CODE] Тип результата: {type(result).__name__}")
            else:
                print(f"[SEND_CODE] ⚠️ Результат не содержит phone_code_hash: {result}")
                raise ValueError("Не удалось получить phone_code_hash от Telegram")
            
            return result
        except PhoneNumberInvalidError:
            print(f"[SEND_CODE] ❌ Неверный номер телефона: {self.phone}")
            self.phone_code_hash = None
            raise ValueError("Неверный номер телефона. Проверьте формат: +79991234567")
        except PhoneNumberFloodError:
            print(f"[SEND_CODE] ❌ Превышен лимит запросов для номера: {self.phone}")
            self.phone_code_hash = None
            raise FloodWaitError("Превышен лимит запросов кода для этого номера. Подождите несколько часов.")
        except PhoneNumberUnoccupiedError:
            print(f"[SEND_CODE] ❌ Номер не зарегистрирован в Telegram: {self.phone}")
            self.phone_code_hash = None
            raise ValueError("Этот номер телефона не зарегистрирован в Telegram")
        except PhoneNumberBannedError:
            print(f"[SEND_CODE] ❌ Номер заблокирован: {self.phone}")
            self.phone_code_hash = None
            raise
        except FloodWaitError as e:
            print(f"[SEND_CODE] ⏰ FloodWait: {e.seconds} секунд")
            self.phone_code_hash = None
            raise
        except Exception as e:
            error_msg = str(e).lower()
            error_str = str(e)
            print(f"[SEND_CODE] ❌ КРИТИЧЕСКАЯ ОШИБКА при отправке кода: {e}")
            print(f"[SEND_CODE] Тип ошибки: {type(e).__name__}")
            print(f"[SEND_CODE] Полный текст ошибки: {error_str}")
            self.phone_code_hash = None
            
            # Пытаемся переподключиться при ошибке
            try:
                if self.is_connected:
                    await self.disconnect()
                    self.is_connected = False
            except Exception as disconnect_error:
                print(f"[SEND_CODE] Ошибка при отключении: {disconnect_error}")
            
            raise
    
    async def sign_in(self, code: str = None, password: str = None, phone_code_hash: str = None):
        """Вход в аккаунт с кодом и опциональным паролем 2FA"""
        await self.connect()
        try:
            if password:
                # Для 2FA - правильный способ: передаем только пароль после успешного sign_in с кодом
                # Telethon автоматически использует текущую сессию
                result = await self.client.sign_in(password=password)
                return result
            else:
                # Используем phone_code_hash из send_code_request или переданный
                hash_to_use = phone_code_hash or self.phone_code_hash
                if not hash_to_use:
                    raise ValueError("phone_code_hash не найден. Запросите код заново через /start")
                if not code:
                    raise ValueError("Код не указан")
                result = await self.client.sign_in(self.phone, code, phone_code_hash=hash_to_use)
                return result
        except SessionPasswordNeededError:
            raise
        except Exception as e:
            raise
    
    async def get_dialogs(self, limit: int = 200):
        """Получение списка диалогов"""
        await self.connect()
        dialogs = []
        async for dialog in self.client.iter_dialogs(limit=limit):
            dialogs.append(dialog)
        return dialogs
    
    async def get_private_chats(self):
        """Получение только личных чатов (не боты)"""
        dialogs = await self.get_dialogs()
        private_chats = []
        for dialog in dialogs:
            entity = dialog.entity
            if isinstance(entity, User) and not entity.bot and not entity.deleted:
                private_chats.append(entity)
        return private_chats
    
    async def get_folder_chats(self, folder_name: str):
        """Получение чатов из папки (заглушка - возвращает все диалоги)"""
        # TODO: Реализовать реальную фильтрацию по папкам
        dialogs = await self.get_dialogs()
        chats = []
        for dialog in dialogs:
            entity = dialog.entity
            if isinstance(entity, (Channel, Chat)):
                chats.append(entity)
        return chats
    
    async def send_message(self, entity, text: str, delay: int, auto_subscribe: bool = False):
        """Отправка сообщения с обработкой ошибок"""
        try:
            # Проверка и присоединение к каналу/группе при необходимости
            if auto_subscribe:
                await self.check_and_join(entity, auto_subscribe)
            
            await self.client.send_message(entity, text)
            # Минимальная задержка для скорости, но не меньше указанной пользователем
            await asyncio.sleep(max(1, delay))
            return True
        except FloodWaitError as e:
            # Автоматическое ожидание при FloodWait
            wait_time = e.seconds
            print(f"[SEND_MESSAGE] FloodWait: ожидание {wait_time} секунд")
            await asyncio.sleep(wait_time)
            # Повторная попытка
            await self.client.send_message(entity, text)
            await asyncio.sleep(max(1, delay))
            return True
        except Exception as e:
            error_msg = str(e).lower()
            error_str = str(e)
            
            # Обработка "Too many requests"
            if "too many requests" in error_msg or "too many" in error_msg:
                print(f"[SEND_MESSAGE] Too many requests, увеличиваем задержку до {delay * 2} секунд")
                await asyncio.sleep(delay * 2)  # Увеличиваем задержку в 2 раза
                return False  # Возвращаем False, чтобы не считать как успех
            
            # Игнорируем ошибки доступа
            if "privacy" in error_msg or "restricted" in error_msg:
                return False
            
            # Для других ошибок - логируем и возвращаем False
            print(f"[SEND_MESSAGE] Ошибка отправки: {e}")
            return False
    
    async def join_channel_or_group(self, entity):
        """Присоединение к каналу/группе"""
        try:
            if isinstance(entity, Channel):
                from telethon.tl.functions.channels import JoinChannelRequest
                await self.client(JoinChannelRequest(entity))
            elif isinstance(entity, Chat):
                from telethon.tl.functions.messages import ImportChatInviteRequest
                # Для обычных чатов нужен invite hash, поэтому просто возвращаем True
                pass
            return True
        except Exception:
            return False
    
    async def check_and_join(self, entity, auto_subscribe: bool):
        """Проверка и присоединение к каналу/группе"""
        if auto_subscribe and isinstance(entity, (Channel, Chat)):
            await self.join_channel_or_group(entity)
