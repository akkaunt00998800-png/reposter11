"""Основной модуль Telegram-бота WrauX / RuWEEX"""
import asyncio
import os
import re
import time
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ErrorEvent
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneNumberBannedError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError
)

from config import (
    BOT_TOKEN,
    API_ID,
    API_HASH,
    SESSIONS_DIR,
    PROXY,
    ADMIN_ID,
    REQUIRED_CHANNEL_ID,
    REQUIRED_CHANNEL_LINK,
    PROJECT_NAME,
)
from database import Database
from telegram_client import UserTelegramClient
from campaign_manager import CampaignManager
from payment import create_invoice, check_invoice, get_user_pending_invoices, update_invoice_status, SUBSCRIPTION_PRICES
from device_generator import generate_device_params
import aiohttp

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация компонентов
db = Database()
campaign_manager = CampaignManager(db)

# Словари для хранения данных
user_clients = {}  # {user_id: UserTelegramClient (активная сессия)}
user_auth_data = {}  # {user_id: {phone, attempts}}
auth_attempts = {}  # {user_id: {last_attempt, code_requests}}
auto_response_tasks = {}  # {user_id: asyncio.Task} - задачи мониторинга входящих сообщений


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором RuWEEX"""
    return user_id == ADMIN_ID


# Вспомогательные проверки доступа
def is_subscription_active(user: dict) -> bool:
    """Активна ли платная подписка RuWEEX"""
    sub_until = user.get("subscription_until")
    if not sub_until:
        return False
    try:
        dt = datetime.fromisoformat(sub_until)
    except Exception:
        return False
    return dt > datetime.now()


def is_trial_active(user: dict) -> bool:
    """Активен ли бесплатный период (по умолчанию 1 день)"""
    free_days = user.get("free_days") or 0
    created_at = user.get("created_at")
    if not created_at or free_days <= 0:
        return False
    try:
        created_dt = datetime.fromisoformat(created_at)
    except Exception:
        return False
    return created_dt + timedelta(days=free_days) > datetime.now()


def get_user_accounts(user: dict):
    """Список аккаунтов пользователя RuWEEX из used_phones + fallback"""
    raw = user.get("used_phones")
    accounts = []

    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = []

        for item in data:
            if isinstance(item, str):
                accounts.append(
                    {
                        "phone": item,
                        "session": None,
                        "created_at": None,
                    }
                )
            elif isinstance(item, dict):
                phone = item.get("phone")
                if not phone:
                    continue
                accounts.append(
                    {
                        "phone": phone,
                        "session": item.get("session"),
                        "created_at": item.get("created_at"),
                    }
                )

    # Фолбэк: хотя бы текущий активный аккаунт
    if not accounts and user.get("phone_number"):
        accounts.append(
            {
                "phone": user["phone_number"],
                "session": user.get("session_file"),
                "created_at": user.get("created_at"),
            }
        )

    return accounts


async def check_channel_subscription(user_id: int) -> bool:
    """Проверка обязательной подписки на канал RuWEEX"""
    if not REQUIRED_CHANNEL_ID:
        # Если админ не настроил ID канала — считаем проверку выключенной
        return True
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        status = getattr(member, "status", None)
        return status in ("member", "administrator", "creator")
    except Exception as e:
        # Если бот не может получить статус (не добавлен в канал или неверный ID),
        # не даём бесплатный день, чтобы не обходили подписку
        print(f"Ошибка проверки подписки на канал RuWEEX: {e}")
        return False


async def check_user_access(message: Message) -> bool:
    """
    Общая проверка доступа к функционалу рассылок.
    Без подписки — только 1 день триала.
    """
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await safe_answer(message,
            "______ RuWEEX ACCESS ______\n\n"
            "Доступ к рассылкам не инициализирован.\n"
            "Сначала выполните /start и пройдите авторизацию."
        )
        return False

    if is_subscription_active(user):
        return True

    if is_trial_active(user):
        return True

    await safe_answer(message,
        "______ RuWEEX ACCESS ______\n\n"
        "Бесплатный период (1 день) завершён.\n"
        "Подписка: 5$ за 30 дней.\n"
        "Покупка: используйте команду `.саб` для оплаты."
    )
    return False


# FSM состояния
class AuthStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()
    waiting_retry = State()


class CampaignStates(StatesGroup):
    waiting_flood_params = State()
    waiting_pflood_params = State()
    waiting_folder_name = State()


# Вспомогательные функции
async def safe_answer(message: Message, text: str, max_retries: int = 3, reply_markup=None):
    """Безопасная отправка сообщения с обработкой сетевых ошибок"""
    for attempt in range(max_retries):
        try:
            await message.answer(text, reply_markup=reply_markup)
            return True
        except (TelegramNetworkError, TelegramRetryAfter, Exception) as e:
            error_msg = str(e).lower()
            error_str = str(e)
            
            # Проверяем тип ошибки
            is_timeout = ("timeout" in error_msg or 
                        "семафора" in error_str.lower() or 
                        "semaphore" in error_msg or
                        "connection" in error_msg)
            
            if attempt < max_retries - 1 and is_timeout:
                wait_time = getattr(e, 'retry_after', 3 * (attempt + 1))
                await asyncio.sleep(wait_time)
                continue
            elif attempt < max_retries - 1 and "retry" in error_msg:
                wait_time = getattr(e, 'retry_after', 5)
                await asyncio.sleep(wait_time)
                continue
            
            # Если все попытки исчерпаны, логируем ошибку
            if attempt == max_retries - 1:
                print(f"Не удалось отправить сообщение после {max_retries} попыток: {e}")
            return False
    return False


async def clear_user_session(user_id: int):
    """Очистка сессии пользователя"""
    # Сначала отключаем клиент, чтобы освободить файл
    if user_id in user_clients:
        try:
            client = user_clients[user_id]
            await client.disconnect()
            # Даем время на закрытие файла
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Ошибка при отключении клиента: {e}")
        finally:
            del user_clients[user_id]
    
    # Теперь удаляем файлы сессии
    session_file = os.path.join(SESSIONS_DIR, f"{user_id}.session")
    journal_file = session_file + ".journal"
    
    # Функция для безопасного удаления файла
    async def safe_remove_file(file_path: str):
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    return True
            except PermissionError:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1)  # Ждем и пробуем снова
                else:
                    print(f"Не удалось удалить файл {file_path} после {max_attempts} попыток")
            except Exception as e:
                print(f"Ошибка при удалении файла {file_path}: {e}")
                break
        return False
    
    await safe_remove_file(session_file)
    await safe_remove_file(journal_file)
    
    # Очистка данных авторизации
    if user_id in user_auth_data:
        del user_auth_data[user_id]
    if user_id in auth_attempts:
        del auth_attempts[user_id]


# Команды бота
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Команда /start - начало работы"""
    user_id = message.from_user.id
    
    # Проверяем наличие пользователя в БД
    user = await db.get_user(user_id)
    
    if user:
        # Проверяем существование файла сессии
        session_file = user.get("session_file")
        has_session = bool(session_file and os.path.exists(os.path.join(SESSIONS_DIR, session_file)))
        if has_session:
            # Проверяем подписку
            has_sub = is_subscription_active(user)
            has_trial = is_trial_active(user)
            
            if has_sub:
                sub_until = user.get("subscription_until")
                if sub_until:
                    try:
                        until_dt = datetime.fromisoformat(sub_until)
                        days_left = (until_dt - datetime.now()).days
                        sub_text = f"✅ Активна ({days_left} дн.)"
                    except:
                        sub_text = "✅ Активна"
                else:
                    sub_text = "✅ Активна"
            elif has_trial:
                sub_text = "⏳ Триал активен"
            else:
                sub_text = "❌ Отсутствует"
            
            await safe_answer(
                message,
                "🤖 Меню RUWEEX\n"
                f"├  ID: {user_id}\n"
                f"├  Подписка: {sub_text}\n"
                f"├  Прокси: {'стандартный' if not PROXY else PROXY.get('proxy_type', 'socks5')}\n"
                f"└  Префикс: .\n\n"
                f"💡 Получить бесплатную подписку\n"
                f"└ 1 день: Отправьте /checksub\n\n"
                f"🤝 Полезно\n"
                f"├  Как избегать блокировок (см. /help)\n"
                f"├  Получить помощь от админов @ruweex\n"
                f"└  Бот не работает @ruweex"
            )
            return
    
    # Если нет авторизации - запрашиваем номер
    print(f"[START] Пользователь {user_id} начал авторизацию")
    await state.set_state(AuthStates.waiting_phone)
    print(f"[START] Состояние установлено: waiting_phone для {user_id}")
    await safe_answer(
        message,
        "______ RuWEEX CORE ______\n\n"
        "Для запуска рассылки требуется авторизация.\n"
        "Отправьте номер телефона в формате: +79991234567"
    )
    print(f"[START] Сообщение отправлено пользователю {user_id}")


@dp.message(Command("reauth"))
async def cmd_reauth(message: Message, state: FSMContext):
    """Команда /reauth - повторная авторизация"""
    user_id = message.from_user.id
    
    # Очищаем старую сессию (с обработкой ошибок)
    try:
        await clear_user_session(user_id)
    except Exception as e:
        print(f"Ошибка при очистке сессии: {e}")
        # Продолжаем работу, даже если не удалось очистить
    
    await state.set_state(AuthStates.waiting_phone)
    await safe_answer(message,
        "______ RuWEEX REAUTH ______\n\n"
        "Отправьте номер телефона в формате: +79991234567"
    )


@dp.message(F.text.startswith(".флуд"))
async def cmd_flood(message: Message):
    """Команда .флуд - рассылка по личным сообщениям"""
    user_id = message.from_user.id
    
    # Проверяем доступ (триал / подписка)
    if not await check_user_access(message):
        return
    
    # Проверяем авторизацию
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сначала авторизуйтесь через /start"
        )
        return
    
    # Парсим параметры: .флуд (круги) (задержка) (текст)
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await safe_answer(message,
            "______ RuWEEX FORMAT ______\n\n"
            "Ожидается: `.флуд (круги) (задержка) (текст)`\n"
            "Пример: `.флуд 2 5 Привет! Это тестовое сообщение`"
        )
        return
    
    try:
        rounds = int(parts[1])
        delay = int(parts[2])
        text = parts[3]
        
        if rounds <= 0 or delay < 0:
            raise ValueError()
    except:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Круги и задержка должны быть числами."
        )
        return
    
    # Создаем или используем существующий клиент
    if user_id not in user_clients:
        session_file = user.get("session_file") or f"{user_id}.session"
        
        # Получаем или генерируем параметры устройства
        device_params = await db.get_device_params(session_file)
        if not device_params:
            from device_generator import generate_device_params
            device_params = generate_device_params(user_id, user['phone_number'], prefer_ios=True)
            await db.save_device_params(session_file, user_id, device_params)
        
        client = UserTelegramClient(
            session_file,
            API_ID,
            API_HASH,
            user['phone_number'],
            proxy=PROXY,
            user_id=user_id,
            device_params=device_params
        )
        await client.connect()
        user_clients[user_id] = client
    else:
        client = user_clients[user_id]
    
    # Добавляем рассылку в БД
    campaign_id = await db.add_campaign(
        user_id=user_id,
        campaign_type='dm',
        text=text,
        rounds=rounds,
        delay=delay
    )
    
    # Запускаем рассылку в отдельной задаче
    task = asyncio.create_task(
        campaign_manager.start_dm_campaign(
            user_id, campaign_id, client, text, rounds, delay
        )
    )
    campaign_manager.active_campaigns[campaign_id] = task
    
    await safe_answer(message,
        "______ RuWEEX CAMPAIGN STARTED ______\n\n"
        f"id: {campaign_id}\n"
        f"круги: {rounds}\n"
        f"задержка: {delay} c\n"
        f"текст: {text[:50]}..."
    )


@dp.message(F.text.startswith(".сфлуд"))
async def cmd_stop_flood(message: Message):
    """Команда .сфлуд - остановка рассылки по ЛС"""
    user_id = message.from_user.id
    
    # Получаем активные рассылки типа 'dm'
    campaigns = await db.get_active_campaigns(user_id)
    dm_campaigns = [c for c in campaigns if c['campaign_type'] == 'dm']
    
    if not dm_campaigns:
        await safe_answer(message,
            "______ RuWEEX ______\n"
            "Нет активных рассылок по личным сообщениям."
        )
        return
    
    # Останавливаем все рассылки
    stopped_count = 0
    for campaign in dm_campaigns:
        if await campaign_manager.stop_campaign(campaign['id']):
            stopped_count += 1
    
    await safe_answer(message,
        "______ RuWEEX STOP ______\n"
        f"Остановлено рассылок по ЛС: {stopped_count}"
    )


@dp.message(F.text.startswith(".пфлуд"))
async def cmd_pflood(message: Message, state: FSMContext):
    """Команда .пфлуд - рассылка по папкам"""
    user_id = message.from_user.id
    
    # Проверяем доступ (триал / подписка)
    if not await check_user_access(message):
        return
    
    # Проверяем авторизацию
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сначала авторизуйтесь через /start"
        )
        return
    
    # Парсим параметры: .пфлуд (круги) (задержка) (текст)
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await safe_answer(message,
            "______ RuWEEX FORMAT ______\n\n"
            "Ожидается: `.пфлуд (круги) (задержка) (текст)`\n"
            "Пример: `.пфлуд 2 5 Привет! Это тестовое сообщение`"
        )
        return
    
    try:
        rounds = int(parts[1])
        delay = int(parts[2])
        text = parts[3]
        
        if rounds <= 0 or delay < 0:
            raise ValueError()
    except:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Круги и задержка должны быть числами."
        )
        return
    
    # Сохраняем параметры в FSM и запрашиваем название папки
    await state.update_data(rounds=rounds, delay=delay, text=text)
    await state.set_state(CampaignStates.waiting_folder_name)
    await safe_answer(message,
        "---- ВВЕДИТЕ НАЗВАНИЕ ПАПКИ ----"
    )


@dp.message(CampaignStates.waiting_folder_name)
async def process_folder_name(message: Message, state: FSMContext):
    """Обработка названия папки"""
    user_id = message.from_user.id
    folder_name = message.text.strip()
    
    # Получаем сохраненные параметры
    data = await state.get_data()
    rounds = data.get('rounds')
    delay = data.get('delay')
    text = data.get('text')
    
    await state.clear()
    
    # Проверяем авторизацию
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Начните заново через /start"
        )
        return
    
    # Создаем или используем существующий клиент
    if user_id not in user_clients:
        session_file = user.get("session_file") or f"{user_id}.session"
        
        # Получаем или генерируем параметры устройства
        device_params = await db.get_device_params(session_file)
        if not device_params:
            from device_generator import generate_device_params
            device_params = generate_device_params(user_id, user['phone_number'], prefer_ios=True)
            await db.save_device_params(session_file, user_id, device_params)
        
        client = UserTelegramClient(
            session_file,
            API_ID,
            API_HASH,
            user['phone_number'],
            proxy=PROXY,
            user_id=user_id,
            device_params=device_params
        )
        await client.connect()
        user_clients[user_id] = client
    else:
        client = user_clients[user_id]
    
    # Добавляем рассылку в БД
    campaign_id = await db.add_campaign(
        user_id=user_id,
        campaign_type='folder',
        text=text,
        rounds=rounds,
        delay=delay,
        folder_name=folder_name
    )
    
    # Запускаем рассылку в отдельной задаче
    task = asyncio.create_task(
        campaign_manager.start_folder_campaign(
            user_id, campaign_id, client, folder_name, rounds, delay
        )
    )
    campaign_manager.active_campaigns[campaign_id] = task
    
    await safe_answer(message,
        "______ RuWEEX FOLDER CAMPAIGN STARTED ______\n\n"
        f"id: {campaign_id}\n"
        f"папка: {folder_name}\n"
        f"круги: {rounds}\n"
        f"задержка: {delay} c\n"
        f"текст: {text[:50]}..."
    )


@dp.message(F.text.startswith(".спфлуд"))
async def cmd_stop_pflood(message: Message):
    """Команда .спфлуд - остановка рассылки по папкам"""
    user_id = message.from_user.id
    
    # Получаем активные рассылки типа 'folder'
    campaigns = await db.get_active_campaigns(user_id)
    folder_campaigns = [c for c in campaigns if c['campaign_type'] == 'folder']
    
    if not folder_campaigns:
        await safe_answer(message,
            "______ RuWEEX ______\n"
            "Нет активных рассылок по папкам."
        )
        return
    
    # Создаем инлайн-клавиатуру с кнопками
    builder = InlineKeyboardBuilder()
    for campaign in folder_campaigns:
        builder.add(InlineKeyboardButton(
            text=f"Остановить #{campaign['id']}",
            callback_data=f"stop_folder_{campaign['id']}"
        ))
    builder.adjust(1)
    
    await safe_answer(message,
        "______ RuWEEX ______\n"
        "Выберите рассылку для остановки:",
        reply_markup=builder.as_markup()
    )


@dp.message(F.text.startswith(".инфо"))
async def cmd_info(message: Message):
    """Команда .инфо - информация о рассылках"""
    user_id = message.from_user.id
    
    campaigns = await db.get_campaigns(user_id)
    
    if not campaigns:
        await safe_answer(message,
            "______ RuWEEX ______\n"
            "Данных о рассылках нет."
        )
        return
    
    # Группируем по статусам
    active = [c for c in campaigns if c['status'] == 'active']
    completed = [c for c in campaigns if c['status'] == 'completed']
    stopped = [c for c in campaigns if c['status'] == 'stopped']
    errors = [c for c in campaigns if c['status'] == 'error']
    
    # Подсчитываем общую статистику
    total_sent = sum(c.get('sent_count', 0) for c in campaigns)
    total_success = sum(c.get('success_count', 0) for c in campaigns)
    total_errors = sum(c.get('error_count', 0) for c in campaigns)
    
    text = (
        "______ RuWEEX STATS ______\n\n"
        f"активных:   {len(active)}\n"
        f"завершено:  {len(completed)}\n"
        f"остановлено:{len(stopped)}\n"
        f"с ошибкой:  {len(errors)}\n"
        f"всего:      {len(campaigns)}\n\n"
        f"📊 ОБЩАЯ СТАТИСТИКА:\n"
        f"отправлено: {total_sent}\n"
        f"успешно: {total_success}\n"
        f"ошибок: {total_errors}\n"
        f"успешность: {(total_success/total_sent*100 if total_sent > 0 else 0):.1f}%"
    )
    
    # Создаем кнопки для активных рассылок
    if active:
        builder = InlineKeyboardBuilder()
        for campaign in active:
            builder.add(InlineKeyboardButton(
                text=f"#{campaign['id']} - {campaign['campaign_type']}",
                callback_data=f"info_{campaign['id']}"
            ))
        builder.adjust(1)
        await safe_answer(message, text, reply_markup=builder.as_markup())
    else:
        await safe_answer(message, text)


@dp.message(F.text.startswith(".статус") | F.text.startswith(".status"))
async def cmd_status(message: Message):
    """Команда .статус - проверка статуса бота и подключения"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await safe_answer(message,
            "🤖 Меню RUWEEX\n\n"
            "❌ Вы не авторизованы.\n"
            "Используйте /start для авторизации."
        )
        return
    
    # Проверяем подключение клиента
    client_status = "❌ Не подключен"
    if user_id in user_clients:
        try:
            client = user_clients[user_id]
            if client.is_connected:
                client_status = "✅ Подключен"
            else:
                client_status = "⚠️ Создан, но не подключен"
        except:
            client_status = "❌ Ошибка"
    
    # Проверяем сессию
    session_file = user.get("session_file")
    session_exists = "✅" if (session_file and os.path.exists(os.path.join(SESSIONS_DIR, session_file))) else "❌"
    
    # Проверяем доступ
    has_sub = is_subscription_active(user)
    has_trial = is_trial_active(user)
    
    # Определяем статус подписки
    if has_sub:
        sub_until = user.get("subscription_until")
        if sub_until:
            try:
                until_dt = datetime.fromisoformat(sub_until)
                days_left = (until_dt - datetime.now()).days
                access_status = f"✅ Активна ({days_left} дн.)"
            except:
                access_status = "✅ Активна"
        else:
            access_status = "✅ Активна"
    elif has_trial:
        access_status = "⏳ Триал активен"
    else:
        access_status = "❌ Отсутствует"
    
    # Получаем статистику рассылок
    campaigns = await db.get_campaigns(user_id)
    active_campaigns = len([c for c in campaigns if c['status'] == 'active'])
    
    # Проверяем автоответчик
    auto_response = await db.get_auto_response(user_id)
    auto_response_status = "❌ Выключен"
    if auto_response and auto_response.get('enabled'):
        auto_response_status = "✅ Включен"
    
    # Проверяем прокси
    proxy_status = "стандартный"
    if PROXY:
        proxy_status = f"{PROXY.get('proxy_type', 'socks5')}"
    
    await safe_answer(message,
        "🤖 Меню RUWEEX\n"
        f"├  ID: {user_id}\n"
        f"├  Подписка: {access_status}\n"
        f"├  Прокси: {proxy_status}\n"
        f"└  Префикс: .\n\n"
        f"💡 Получить бесплатную подписку\n"
        f"└ 1 день: Отправьте /checksub\n\n"
        f"🤝 Полезно\n"
        f"├  Как избегать блокировок (см. /help)\n"
        f"├  Получить помощь от админов @ruweex\n"
        f"└  Бот не работает @ruweex"
    )


@dp.message(F.text.startswith(".саб"))
async def cmd_subscribe(message: Message):
    """Команда .саб - покупка подписки"""
    user_id = message.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "❌ Сначала авторизуйтесь через /start"
        )
        return
    
    # Создаем клавиатуру с вариантами подписки
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="30 дней - 5 USDT",
        callback_data="sub_30"
    ))
    builder.add(InlineKeyboardButton(
        text="90 дней - 12 USDT",
        callback_data="sub_90"
    ))
    builder.add(InlineKeyboardButton(
        text="180 дней - 20 USDT",
        callback_data="sub_180"
    ))
    builder.add(InlineKeyboardButton(
        text="365 дней - 35 USDT",
        callback_data="sub_365"
    ))
    builder.adjust(1)
    
    await safe_answer(message,
        "💳 Покупка подписки RuWEEX\n\n"
        "Выберите срок подписки:",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("sub_"))
async def process_subscribe(callback: CallbackQuery):
    """Обработка выбора подписки"""
    user_id = callback.from_user.id
    days = int(callback.data.split("_")[1])
    amount = SUBSCRIPTION_PRICES.get(days, 5.0)
    
    # Создаем инвойс
    invoice = await create_invoice(user_id, days, amount)
    
    if not invoice:
        await callback.answer("❌ Ошибка создания платежа. Попробуйте позже.", show_alert=True)
        return
    
    invoice_url = invoice.get("pay_url", "")
    invoice_id = invoice.get("invoice_id")
    
    await callback.message.edit_text(
        f"💳 Оплата подписки на {days} дней\n\n"
        f"💰 Сумма: {amount} USDT\n"
        f"📅 Срок: {days} дней\n\n"
        f"Нажмите на кнопку ниже для оплаты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_pay_{invoice_id}")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("check_pay_"))
async def process_check_payment(callback: CallbackQuery):
    """Проверка оплаты"""
    user_id = callback.from_user.id
    invoice_id = int(callback.data.split("_")[2])
    
    invoice_data = await check_invoice(invoice_id)
    
    if not invoice_data:
        await callback.answer("❌ Инвойс не найден", show_alert=True)
        return
    
    status = invoice_data.get("status", "pending")
    
    if status == "paid":
        # Обновляем статус в БД
        await update_invoice_status(invoice_id, "paid")
        
        # Получаем данные инвойса из БД
        from config import DATABASE_PATH
        import aiosqlite
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT days FROM payments WHERE invoice_id = ?", (invoice_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    days = row["days"]
                    # Выдаем подписку через метод БД
                    from database import Database
                    db_instance = Database()
                    await db_instance.update_subscription(user_id, days)
                    
                    # Получаем информацию о подписке
                    user_data = await db.get_user(user_id)
                    sub_until = user_data.get("subscription_until") if user_data else None
                    
                    # Форматируем дату
                    if sub_until:
                        try:
                            until_dt = datetime.fromisoformat(sub_until)
                            sub_until_formatted = until_dt.strftime('%d.%m.%Y %H:%M')
                        except:
                            sub_until_formatted = sub_until
                    else:
                        sub_until_formatted = "N/A"
                    
                    await callback.message.edit_text(
                        f"✅ Оплата успешна!\n\n"
                        f"📅 Подписка активирована на {days} дней\n"
                        f"🆔 Ваш ID: {user_id}\n"
                        f"📆 Действует до: {sub_until_formatted}\n\n"
                        f"Спасибо за покупку! 🎉"
                    )
                    await callback.answer("✅ Подписка активирована!")
    elif status == "expired":
        await callback.answer("⏰ Время оплаты истекло. Создайте новый платеж.", show_alert=True)
    else:
        await callback.answer("⏳ Оплата еще не получена. Попробуйте позже.", show_alert=True)


@dp.message(F.text.startswith(".чексаб"))
async def cmd_check_sub(message: Message):
    """Команда .чексаб - проверка подписки и активных платежей"""
    user_id = message.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "❌ Сначала авторизуйтесь через /start"
        )
        return
    
    # Проверяем подписку
    has_sub = is_subscription_active(user)
    has_trial = is_trial_active(user)
    
    if has_sub:
        sub_until = user.get("subscription_until")
        if sub_until:
            try:
                until_dt = datetime.fromisoformat(sub_until)
                days_left = (until_dt - datetime.now()).days
                sub_text = f"✅ Активна\n📅 Осталось дней: {days_left}\n📆 Действует до: {until_dt.strftime('%d.%m.%Y %H:%M')}"
            except:
                sub_text = "✅ Активна"
        else:
            sub_text = "✅ Активна"
    elif has_trial:
        sub_text = "⏳ Триал активен (1 день)"
    else:
        sub_text = "❌ Отсутствует"
    
    # Проверяем активные платежи
    pending_invoices = await get_user_pending_invoices(user_id)
    
    text = f"📊 Статус подписки\n\n{sub_text}\n\n"
    
    if pending_invoices:
        text += "💳 Активные платежи:\n"
        for inv in pending_invoices:
            text += f"├  ID: {inv['invoice_id']}\n"
            text += f"├  Сумма: {inv['amount']} USDT\n"
            text += f"├  Дней: {inv['days']}\n"
            text += f"└  Статус: {inv['status']}\n\n"
        text += "Используйте кнопку 'Проверить оплату' в сообщении с платежом."
    else:
        text += "💳 Активных платежей нет"
    
    await safe_answer(message, text)


@dp.message(F.text.startswith(".автоп"))
async def cmd_autop(message: Message):
    """Команда .автоп - переключение авто-подписки"""
    user_id = message.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сначала авторизуйтесь через /start"
        )
        return
    
    current_state = user.get('auto_subscribe', 0) == 1
    new_state = not current_state
    
    await db.update_auto_subscribe(user_id, new_state)
    
    status = "АКТИВНА" if new_state else "ВЫКЛЮЧЕНА"
    await safe_answer(message,
        "______ RuWEEX AUTO-SUB ______\n"
        f"Состояние: {status}"
    )


@dp.message(F.text.startswith(".автоответ"))
async def cmd_auto_response(message: Message):
    """Команда .автоответ (текст) - включение автоответчика"""
    user_id = message.from_user.id
    
    # Проверяем авторизацию
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сначала авторизуйтесь через /start"
        )
        return
    
    # Парсим текст ответа
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_answer(message,
            "______ RuWEEX AUTO-RESPONSE ______\n\n"
            "Использование: `.автоответ (текст ответа)`\n\n"
            "Пример: `.автоответ Спасибо за сообщение! Я отвечу позже.`\n\n"
            "Для выключения: `.савтоответ`"
        )
        return
    
    response_text = parts[1].strip()
    
    if not response_text:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Текст ответа не может быть пустым."
        )
        return
    
    # Сохраняем настройки автоответчика
    await db.set_auto_response(user_id, True, response_text)
    
    # Запускаем мониторинг входящих сообщений, если еще не запущен
    if user_id not in auto_response_tasks or auto_response_tasks[user_id].done():
        # Получаем клиент
        if user_id not in user_clients:
            session_file = user.get("session_file") or f"{user_id}.session"
            client = UserTelegramClient(
                session_file,
                API_ID,
                API_HASH,
                user['phone_number'],
                proxy=PROXY
            )
            await client.connect()
            user_clients[user_id] = client
        else:
            client = user_clients[user_id]
        
        # Запускаем задачу мониторинга
        task = asyncio.create_task(monitor_incoming_messages(user_id, client))
        auto_response_tasks[user_id] = task
    
    await safe_answer(message,
        "______ RuWEEX AUTO-RESPONSE ______\n\n"
        "✅ Автоответчик включен!\n\n"
        f"Текст ответа: {response_text}\n\n"
        "Для выключения используйте: `.савтоответ`"
    )


@dp.message(F.text.startswith(".савтоответ"))
async def cmd_stop_auto_response(message: Message):
    """Команда .савтоответ - выключение автоответчика"""
    user_id = message.from_user.id
    
    # Проверяем авторизацию
    user = await db.get_user(user_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сначала авторизуйтесь через /start"
        )
        return
    
    # Выключаем автоответчик
    await db.set_auto_response(user_id, False)
    
    # Останавливаем задачу мониторинга
    if user_id in auto_response_tasks:
        task = auto_response_tasks[user_id]
        if not task.done():
            task.cancel()
        del auto_response_tasks[user_id]
    
    await safe_answer(message,
        "______ RuWEEX AUTO-RESPONSE ______\n\n"
        "❌ Автоответчик выключен."
    )


async def monitor_incoming_messages(user_id: int, client: UserTelegramClient):
    """Мониторинг входящих сообщений и отправка автоответов"""
    from telethon import events
    
    try:
        print(f"[AUTO-RESPONSE] Запущен мониторинг для пользователя {user_id}")
        
        # Получаем настройки автоответчика
        auto_response = await db.get_auto_response(user_id)
        if not auto_response or not auto_response.get('enabled'):
            print(f"[AUTO-RESPONSE] Автоответчик выключен для {user_id}")
            return
        
        response_text = auto_response.get('response_text', '')
        if not response_text:
            return
        
        # Словарь для отслеживания уже отвеченных сообщений (храним последние 1000)
        # Используем список для сохранения порядка и возможности среза
        answered_messages = []
        answered_messages_set = set()  # Для быстрой проверки
        
        # Обработчик новых сообщений
        @client.client.on(events.NewMessage(incoming=True))
        async def auto_response_handler(event):
            nonlocal answered_messages, answered_messages_set  # Объявляем nonlocal для доступа к внешним переменным
            try:
                # Проверяем, что автоответчик еще включен
                auto_response_check = await db.get_auto_response(user_id)
                if not auto_response_check or not auto_response_check.get('enabled'):
                    print(f"[AUTO-RESPONSE] Автоответчик выключен, останавливаем обработчик для {user_id}")
                    try:
                        client.client.remove_event_handler(auto_response_handler)
                    except:
                        pass
                    return
                
                # Проверяем, что это личное сообщение (не группа/канал)
                if not event.is_private:
                    return
                
                # Проверяем, что это не бот
                if event.message.sender and hasattr(event.message.sender, 'bot') and event.message.sender.bot:
                    return
                
                # Проверяем, не отвечали ли уже на это сообщение
                message_id = f"{event.chat_id}_{event.message.id}"
                if message_id in answered_messages_set:
                    return
                
                # Отправляем автоответ
                await event.reply(response_text)
                answered_messages.append(message_id)
                answered_messages_set.add(message_id)
                print(f"[AUTO-RESPONSE] Отправлен автоответ пользователю {event.chat_id} от {user_id}")
                
                # Ограничиваем размер списка (оставляем последние 500)
                if len(answered_messages) > 1000:
                    removed = answered_messages[:-500]
                    answered_messages[:] = answered_messages[-500:]
                    answered_messages_set -= set(removed)
                
            except Exception as e:
                print(f"[AUTO-RESPONSE] Ошибка при обработке сообщения: {e}")
                import traceback
                traceback.print_exc()
        
        # Ждем, пока задача не будет отменена
        try:
            while True:
                # Проверяем, что автоответчик еще включен
                auto_response_check = await db.get_auto_response(user_id)
                if not auto_response_check or not auto_response_check.get('enabled'):
                    print(f"[AUTO-RESPONSE] Автоответчик выключен, останавливаем мониторинг для {user_id}")
                    client.client.remove_event_handler(auto_response_handler)
                    break
                
                await asyncio.sleep(10)  # Проверяем каждые 10 секунд
                
        except asyncio.CancelledError:
            print(f"[AUTO-RESPONSE] Мониторинг отменен для {user_id}")
            try:
                client.client.remove_event_handler(auto_response_handler)
            except:
                pass
                
    except Exception as e:
        print(f"[AUTO-RESPONSE] Критическая ошибка в мониторинге для {user_id}: {e}")
        import traceback
        traceback.print_exc()


@dp.message(Command("checksub"))
async def cmd_checksub(message: Message):
    """Команда /checksub - получение бесплатной подписки (1 день)"""
    user_id = message.from_user.id
    
    # Проверяем подписку на канал
    is_subscribed = await check_channel_subscription(user_id)
    
    if not is_subscribed:
        await safe_answer(message,
            "🤖 Меню RUWEEX\n\n"
            "❌ Для получения бесплатной подписки необходимо подписаться на канал.\n\n"
            f"📢 Подпишитесь: {REQUIRED_CHANNEL_LINK}\n\n"
            "После подписки отправьте /checksub снова."
        )
        return
    
    # Проверяем, не получал ли уже пользователь триал
    user = await db.get_user(user_id)
    if user:
        # Проверяем, активен ли уже триал или подписка
        has_sub = is_subscription_active(user)
        has_trial = is_trial_active(user)
        
        if has_sub:
            await safe_answer(message,
                "✅ У вас уже есть активная подписка!"
            )
            return
        
        if has_trial:
            await safe_answer(message,
                "⏳ У вас уже активен бесплатный период (1 день)!"
            )
            return
    
    # Выдаем триал на 1 день
    if not user:
        # Создаем пользователя, если его нет
        await db.add_user(user_id, f"+{user_id}", f"{user_id}.session")
    
    # Обновляем free_days
    from config import DATABASE_PATH
    import aiosqlite
    async with aiosqlite.connect(DATABASE_PATH) as db_conn:
        await db_conn.execute("""
            UPDATE users SET free_days = 1, created_at = CURRENT_TIMESTAMP 
            WHERE user_id = ?
        """, (user_id,))
        await db_conn.commit()
    
    await safe_answer(message,
        "✅ Бесплатная подписка активирована!\n\n"
        "📅 Срок: 1 день\n\n"
        "Теперь вы можете использовать все функции бота."
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help - помощь и инструкции"""
    await safe_answer(message,
        "📚 Руководство RuWEEX\n\n"
        "🔐 Как избегать блокировок:\n\n"
        "1. API ID + HASH\n"
        "├  Используйте свои API ID + HASH из my.telegram.org\n"
        "├  Не используйте чужие или 'официальные' API ID\n"
        "└  Грязные API ID могут привести к моментальному слету сессии\n\n"
        "2. Прокси\n"
        "├  Используйте качественный SOCKS5 прокси\n"
        "├  IP должен совпадать со страной номера телефона\n"
        "├  Избегайте дешевых shared прокси\n"
        "└  Настройка: см. PROXY_SETUP.md\n\n"
        "3. Поведение аккаунта\n"
        "├  Telegram не должен думать, что вы занимаетесь автоматической рассылкой\n"
        "├  Делайте все, чтобы телеграмм думал, что с аккаунта общается живой человек\n"
        "├  Не рассылайте слишком часто\n"
        "└  Рассылайте только по тематическим чатам, где это разрешено\n\n"
        "4. Важные правила\n"
        "├  Рассылка по личным сообщениям крайне рискованна\n"
        "├  Используйте рассылку только по группам/каналам\n"
        "├  Соблюдайте задержки между сообщениями\n"
        "└  Не рассылайте каждые 10 секунд\n\n"
        "📋 Все команды:\n"
        "`.флуд` — рассылка по ЛС\n"
        "`.сфлуд` — остановка рассылки по ЛС\n"
        "`.пфлуд` — рассылка по папкам\n"
        "`.спфлуд` — остановка рассылки по папкам\n"
        "`.инфо` — информация о рассылках\n"
        "`.статус` — статус бота и подключения\n"
        "`.автоп` — авто-подписка\n"
        "`.автоответ` — автоответчик на входящие\n"
        "`.савтоответ` — выключить автоответчик\n"
        "`.саб` — купить подписку\n"
        "`.чексаб` — проверить оплату\n"
        "`/reauth` — новая авторизация\n"
        "`.аккаунты` — переключение между аккаунтами\n"
        "`/checksub` — получить бесплатную подписку (1 день)\n\n"
        "💡 Помощь: @ruweex"
    )


@dp.message(Command("accounts"))
@dp.message(F.text.startswith(".аккаунты"))
async def cmd_accounts(message: Message):
    """Просмотр и управление аккаунтами RuWEEX"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await safe_answer(message,
            "🤖 Меню RUWEEX\n\n"
            "❌ Аккаунты не найдены.\n"
            "Сначала выполните /start и пройдите авторизацию."
        )
        return

    # Проверяем подписку для расширенных функций
    has_sub = is_subscription_active(user)
    
    accounts = get_user_accounts(user)
    active_phone = user.get("phone_number")

    if not accounts:
        text = "📱 Управление аккаунтами\n\n"
        text += "❌ Подключённых аккаунтов нет.\n\n"
        if has_sub:
            text += "💡 Используйте /start для добавления нового аккаунта."
        else:
            text += "💡 Для управления несколькими аккаунтами нужна подписка.\n"
            text += "Используйте `.саб` для покупки подписки."
        
        builder = InlineKeyboardBuilder()
        if has_sub:
            builder.add(InlineKeyboardButton(
                text="➕ Добавить аккаунт",
                callback_data="acc_add_new"
            ))
        await safe_answer(message, text, reply_markup=builder.as_markup() if has_sub else None)
        return

    # Формируем список аккаунтов с информацией
    text = "📱 Управление аккаунтами\n\n"
    
    builder = InlineKeyboardBuilder()
    for idx, acc in enumerate(accounts):
        phone = acc.get("phone") or "неизвестно"
        session_file = acc.get("session")
        created_at = acc.get("created_at")
        
        # Форматируем дату
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                created_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                created_str = created_at[:10] if len(created_at) > 10 else created_at
        else:
            created_str = "дата не указана"
        
        # Проверяем статус сессии
        session_exists = "✅" if (session_file and os.path.exists(os.path.join(SESSIONS_DIR, session_file))) else "❌"
        is_active = "🟢" if phone == active_phone else "⚪"
        
        # Формируем текст кнопки
        label = f"{is_active} {phone}\n   📅 {created_str} | {session_exists} сессия"
        if phone == active_phone:
            label = f"🟢 {phone} [АКТИВЕН]\n   📅 {created_str} | {session_exists} сессия"
        
        builder.add(
            InlineKeyboardButton(
                text=label,
                callback_data=f"acc_ruweex:{user_id}:{idx}",
            )
        )
        
        # Добавляем кнопку удаления для подписчиков
        if has_sub and phone != active_phone:  # Нельзя удалить активный аккаунт
            builder.add(
                InlineKeyboardButton(
                    text=f"🗑️ Удалить {phone}",
                    callback_data=f"acc_delete:{user_id}:{idx}"
                )
            )

    builder.adjust(1)
    
    # Добавляем кнопку добавления нового аккаунта для подписчиков
    if has_sub:
        builder.add(InlineKeyboardButton(
            text="➕ Добавить новый аккаунт",
            callback_data="acc_add_new"
        ))
    
    text += f"📊 Всего аккаунтов: {len(accounts)}\n"
    text += f"🟢 Активный: {active_phone}\n\n"
    if has_sub:
        text += "💡 Вы можете переключаться между аккаунтами, удалять и добавлять новые."
    else:
        text += "💡 Для управления несколькими аккаунтами нужна подписка."

    await safe_answer(message, text, reply_markup=builder.as_markup())


@dp.callback_query(F.data == "acc_add_new")
async def process_add_account(callback: CallbackQuery, state: FSMContext):
    """Обработка добавления нового аккаунта"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    
    if not user:
        await callback.answer("❌ Сначала авторизуйтесь через /start", show_alert=True)
        return
    
    # Проверяем подписку
    has_sub = is_subscription_active(user)
    if not has_sub:
        await callback.answer("❌ Для добавления аккаунтов нужна подписка. Используйте `.саб`", show_alert=True)
        return
    
    # Проверяем лимит аккаунтов
    accounts = get_user_accounts(user)
    if len(accounts) >= 5:
        await callback.answer("❌ Достигнут лимит аккаунтов (5)", show_alert=True)
        return
    
    await callback.answer()
    await state.set_state(AuthStates.waiting_phone)
    await callback.message.edit_text(
        "📱 Добавление нового аккаунта\n\n"
        "Отправьте номер телефона в формате: +79991234567"
    )


@dp.callback_query(F.data.startswith("acc_delete:"))
async def process_delete_account(callback: CallbackQuery):
    """Обработка удаления аккаунта"""
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    target_user_id = int(parts[1])
    acc_idx = int(parts[2])
    
    if user_id != target_user_id:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    # Проверяем подписку
    has_sub = is_subscription_active(user)
    if not has_sub:
        await callback.answer("❌ Для удаления аккаунтов нужна подписка", show_alert=True)
        return
    
    accounts = get_user_accounts(user)
    if acc_idx >= len(accounts):
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    account_to_delete = accounts[acc_idx]
    phone_to_delete = account_to_delete.get("phone")
    active_phone = user.get("phone_number")
    
    if phone_to_delete == active_phone:
        await callback.answer("❌ Нельзя удалить активный аккаунт. Сначала переключитесь на другой.", show_alert=True)
        return
    
    # Удаляем аккаунт из списка
    used_phones_raw = user.get("used_phones")
    phones = []
    if used_phones_raw:
        try:
            phones = json.loads(used_phones_raw)
        except Exception:
            phones = []
    
    if phone_to_delete in phones:
        phones.remove(phone_to_delete)
        
        # Обновляем БД
        from config import DATABASE_PATH
        import aiosqlite
        async with aiosqlite.connect(DATABASE_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE users SET used_phones = ? WHERE user_id = ?",
                (json.dumps(phones), user_id)
            )
            await db_conn.commit()
        
        # Удаляем файл сессии, если существует
        session_file = account_to_delete.get("session")
        if session_file:
            session_path = os.path.join(SESSIONS_DIR, session_file)
            if os.path.exists(session_path):
                try:
                    os.remove(session_path)
                    # Также удаляем journal файл
                    journal_path = session_path + ".journal"
                    if os.path.exists(journal_path):
                        os.remove(journal_path)
                except Exception as e:
                    print(f"[ACCOUNTS] Ошибка удаления сессии: {e}")
        
        await callback.answer("✅ Аккаунт удален")
        # Обновляем список аккаунтов через edit_text
        user = await db.get_user(user_id)
        has_sub = is_subscription_active(user) if user else False
        accounts = get_user_accounts(user)
        active_phone = user.get("phone_number") if user else None
        
        if not accounts:
            await callback.message.edit_text(
                "📱 Управление аккаунтами\n\n"
                "❌ Подключённых аккаунтов нет.\n\n"
                "💡 Используйте /start для добавления нового аккаунта."
            )
            return
        
        text = "📱 Управление аккаунтами\n\n"
        builder = InlineKeyboardBuilder()
        for idx, acc in enumerate(accounts):
            phone = acc.get("phone") or "неизвестно"
            session_file = acc.get("session")
            created_at = acc.get("created_at")
            
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_str = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    created_str = created_at[:10] if len(created_at) > 10 else created_at
            else:
                created_str = "дата не указана"
            
            session_exists = "✅" if (session_file and os.path.exists(os.path.join(SESSIONS_DIR, session_file))) else "❌"
            is_active = "🟢" if phone == active_phone else "⚪"
            
            label = f"{is_active} {phone}\n   📅 {created_str} | {session_exists} сессия"
            if phone == active_phone:
                label = f"🟢 {phone} [АКТИВЕН]\n   📅 {created_str} | {session_exists} сессия"
            
            builder.add(InlineKeyboardButton(
                text=label,
                callback_data=f"acc_ruweex:{user_id}:{idx}",
            ))
            
            if has_sub and phone != active_phone:
                builder.add(InlineKeyboardButton(
                    text=f"🗑️ Удалить {phone}",
                    callback_data=f"acc_delete:{user_id}:{idx}"
                ))
        
        builder.adjust(1)
        if has_sub:
            builder.add(InlineKeyboardButton(
                text="➕ Добавить новый аккаунт",
                callback_data="acc_add_new"
            ))
        
        text += f"📊 Всего аккаунтов: {len(accounts)}\n"
        text += f"🟢 Активный: {active_phone}\n\n"
        if has_sub:
            text += "💡 Вы можете переключаться между аккаунтами, удалять и добавлять новые."
        else:
            text += "💡 Для управления несколькими аккаунтами нужна подписка."
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)


# Админ-панель RuWEEX
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора RuWEEX"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    stats = await db.get_users_stats()

    text = (
        "______ RuWEEX ADMIN ______\n\n"
        f"пользователей:        {stats['total_users']}\n"
        f"активные подписки:    {stats['active_subscriptions']}\n"
        f"активные триалы:      {stats['active_trials']}\n"
        f"зарегистрированные сессии: {stats['sessions']}\n\n"
        "управление:\n"
        "/ruweex_sub <user_id> <дней>   — выдать / продлить подписку\n"
        "/ruweex_unsub <user_id>        — снять подписку\n"
        "/ruweex_user <user_id>         — информация по пользователю"
    )

    await safe_answer(message, text)


@dp.message(Command("ruweex_sub"))
async def cmd_ruweex_sub(message: Message):
    """Выдача / продление подписки пользователю (только ADMIN_ID)"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "Формат:\n"
            "/ruweex_sub <user_id> <дней>"
        )
        return

    try:
        target_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "user_id и дни должны быть числами."
        )
        return

    user = await db.get_user(target_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            f"Пользователь {target_id} в базе не найден."
        )
        return

    await db.update_subscription(target_id, days)
    await safe_answer(message,
        "______ RuWEEX ADMIN ______\n\n"
        f"Подписка пользователю {target_id} продлена на {days} дней."
    )


@dp.message(Command("ruweex_unsub"))
async def cmd_ruweex_unsub(message: Message):
    """Сброс подписки пользователя (только ADMIN_ID)"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "Формат:\n"
            "/ruweex_unsub <user_id>"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "user_id должен быть числом."
        )
        return

    user = await db.get_user(target_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            f"Пользователь {target_id} в базе не найден."
        )
        return

    await db.clear_subscription(target_id)
    await safe_answer(message,
        "______ RuWEEX ADMIN ______\n\n"
        f"Подписка пользователя {target_id} сброшена."
    )


@dp.message(Command("ruweex_user"))
async def cmd_ruweex_user(message: Message):
    """Информация по пользователю для админа"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 2:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "Формат:\n"
            "/ruweex_user <user_id>"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            "user_id должен быть числом."
        )
        return

    user = await db.get_user(target_id)
    if not user:
        await safe_answer(message,
            "______ RuWEEX ADMIN ______\n\n"
            f"Пользователь {target_id} не найден."
        )
        return

    now = datetime.now()
    sub_active = is_subscription_active(user)
    trial_active = is_trial_active(user)

    used_phones_raw = user.get("used_phones")
    phones = []
    if used_phones_raw:
        try:
            import json
            phones = json.loads(used_phones_raw)
        except Exception:
            phones = []

    text = (
        "______ RuWEEX USER ______\n\n"
        f"user_id: {user['user_id']}\n"
        f"phone: {user['phone_number']}\n"
        f"session_file: {user['session_file']}\n"
        f"created_at: {user.get('created_at', 'N/A')}\n"
        f"free_days: {user.get('free_days', 0)}\n"
        f"subscription_until: {user.get('subscription_until') or 'нет'}\n"
        f"подписка активна: {'да' if sub_active else 'нет'}\n"
        f"триал активен: {'да' if trial_active else 'нет'}\n"
        f"телефоны (лимиты аккаунтов): {', '.join(phones) if phones else 'пусто'}"
    )

    await safe_answer(message, text)


@dp.callback_query(F.data.startswith("acc_ruweex:"))
async def process_account_select(callback: CallbackQuery):
    """Переключение активного аккаунта RuWEEX через инлайн-клавиатуру"""
    try:
        _, user_id_str, idx_str = callback.data.split(":")
        user_id = int(user_id_str)
        idx = int(idx_str)
    except Exception:
        await callback.answer("Ошибка данных выбора аккаунта.")
        return

    # Защита от чужих нажатий
    if callback.from_user.id != user_id:
        await callback.answer("Недоступно.")
        return

    user = await db.get_user(user_id)
    if not user:
        await callback.message.edit_text(
            "______ RuWEEX ACCOUNTS ______\n\n"
            "Пользователь не найден. Выполните /start."
        )
        await callback.answer()
        return

    accounts = get_user_accounts(user)
    if not accounts or idx < 0 or idx >= len(accounts):
        await callback.answer("Аккаунт не найден.")
        return

    acc = accounts[idx]
    phone = acc.get("phone")
    session = acc.get("session") or user.get("session_file")

    if not phone:
        await callback.answer("Ошибка: номер аккаунта не задан.")
        return

    # Пытаемся угадать имя сессии, если оно не сохранено
    if not session:
        clean_phone = re.sub(r"[^0-9]", "", phone)
        guessed = f"{user_id}_{clean_phone}.session"
        guessed_path = os.path.join(SESSIONS_DIR, guessed)
        if os.path.exists(guessed_path):
            session = guessed
        else:
            # Фолбэк — текущее значение из БД или шаблон
            session = user.get("session_file") or guessed

    # Обновляем активный аккаунт в БД
    await db.add_user(user_id, phone, session)

    # Отключаем активного клиента, чтобы следующая команда пересоздала сессию
    client = user_clients.get(user_id)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
        user_clients.pop(user_id, None)

    await callback.answer("✅ Аккаунт выбран.")
    # Обновляем список аккаунтов
    user = await db.get_user(user_id)
    has_sub = is_subscription_active(user) if user else False
    accounts = get_user_accounts(user)
    active_phone = user.get("phone_number") if user else None
    
    if not accounts:
        await callback.message.edit_text(
            "📱 Управление аккаунтами\n\n"
            "❌ Подключённых аккаунтов нет."
        )
        return
    
    text = "📱 Управление аккаунтами\n\n"
    builder = InlineKeyboardBuilder()
    for idx_new, acc in enumerate(accounts):
        phone_new = acc.get("phone") or "неизвестно"
        session_file = acc.get("session")
        created_at = acc.get("created_at")
        
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                created_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                created_str = created_at[:10] if len(created_at) > 10 else created_at
        else:
            created_str = "дата не указана"
        
        session_exists = "✅" if (session_file and os.path.exists(os.path.join(SESSIONS_DIR, session_file))) else "❌"
        is_active = "🟢" if phone_new == active_phone else "⚪"
        
        label = f"{is_active} {phone_new}\n   📅 {created_str} | {session_exists} сессия"
        if phone_new == active_phone:
            label = f"🟢 {phone_new} [АКТИВЕН]\n   📅 {created_str} | {session_exists} сессия"
        
        builder.add(InlineKeyboardButton(
            text=label,
            callback_data=f"acc_ruweex:{user_id}:{idx_new}",
        ))
        
        if has_sub and phone_new != active_phone:
            builder.add(InlineKeyboardButton(
                text=f"🗑️ Удалить {phone_new}",
                callback_data=f"acc_delete:{user_id}:{idx_new}"
            ))
    
    builder.adjust(1)
    if has_sub:
        builder.add(InlineKeyboardButton(
            text="➕ Добавить новый аккаунт",
            callback_data="acc_add_new"
        ))
    
    text += f"📊 Всего аккаунтов: {len(accounts)}\n"
    text += f"🟢 Активный: {active_phone}\n\n"
    if has_sub:
        text += "💡 Вы можете переключаться между аккаунтами, удалять и добавлять новые."
    else:
        text += "💡 Для управления несколькими аккаунтами нужна подписка."
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


# Обработчики авторизации
@dp.message(AuthStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    """Обработка номера телефона"""
    user_id = message.from_user.id
    phone = message.text.strip()
    
    print(f"[AUTH] Получен номер телефона от пользователя {user_id}: {phone}")
    
    # Нормализация и проверка формата номера
    phone = phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    # Если номер начинается с 7 или 8 без +, добавляем +7
    if phone.startswith('7') and not phone.startswith('+7'):
        phone = '+7' + phone[1:]
    elif phone.startswith('8') and not phone.startswith('+8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone
    
    # Проверка формата номера
    if not re.match(r'^\+\d{10,15}$', phone):
        print(f"[AUTH] Неверный формат номера: {phone}")
        await safe_answer(message,
            "______ RuWEEX PHONE ______\n\n"
            "❌ Неверный формат номера.\n\n"
            "Используйте формат: +79991234567\n"
            "Или: 79991234567 (бот автоматически добавит +)"
        )
        return
    
    print(f"[AUTH] Нормализованный номер: {phone}")
    
    # Проверка частоты запросов
    if user_id not in auth_attempts:
        auth_attempts[user_id] = {'last_attempt': 0, 'code_requests': 0}
    
    last_attempt = auth_attempts[user_id].get('last_attempt', 0)
    code_requests = auth_attempts[user_id].get('code_requests', 0)
    
    # Уменьшаем задержку до 30 секунд для удобства пользователей
    if time.time() - last_attempt < 30:
        wait_time = int(30 - (time.time() - last_attempt)) + 1
        print(f"[AUTH] Слишком частый запрос от {user_id}, нужно подождать {wait_time} сек")
        await safe_answer(message,
            "______ RuWEEX LIMIT ______\n"
            f"Подождите {wait_time} секунд перед повторным запросом кода."
        )
        return
    
    # Увеличиваем лимит до 10 запросов для удобства
    if code_requests >= 10:
        print(f"[AUTH] Превышен лимит запросов кода для {user_id}")
        await safe_answer(message,
            "______ RuWEEX LIMIT ______\n"
            "Превышен лимит запросов кода (10). Подождите 15–20 минут и попробуйте снова."
        )
        return

    # Проверяем состояние пользователя и лимиты аккаунтов
    user = await db.get_user(user_id)

    # Новый пользователь: даём триал только при подписке на канал
    if not user:
        print(f"[AUTH] Новый пользователь {user_id}, проверка подписки на канал")
        is_member = await check_channel_subscription(user_id)
        if not is_member:
            print(f"[AUTH] Пользователь {user_id} не подписан на канал")
            await safe_answer(message,
                "______ RuWEEX TRIAL ______\n\n"
                "1 день бесплатного доступа доступен только при подписке на канал RuWEEX.\n"
                f"Канал: {REQUIRED_CHANNEL_LINK}\n\n"
                "Подпишитесь и снова выполните /start."
            )
            return
        print(f"[AUTH] Пользователь {user_id} подписан на канал, продолжаем")
    else:
        # Существующий пользователь: проверяем триал / подписку
        has_sub = is_subscription_active(user)
        trial_ok = is_trial_active(user)

        if not has_sub and not trial_ok:
            print(f"[AUTH] У пользователя {user_id} нет доступа (подписка и триал истекли)")
            await safe_answer(message,
                "______ RuWEEX ACCESS ______\n\n"
                "Бесплатный период (1 день) завершён.\n"
                "Подписка: 5$ за 30 дней.\n"
                "Покупка: у @svbboss.\n"
                "После оплаты администратор активирует доступ."
            )
            return

        # Контроль количества аккаунтов по телефонам
        used_phones_raw = user.get("used_phones")
        phones = []
        if used_phones_raw:
            try:
                import json
                phones = json.loads(used_phones_raw)
            except Exception:
                phones = []

        if phone not in phones:
            limit = 5 if has_sub else 1
            if len(phones) >= limit:
                print(f"[AUTH] Лимит аккаунтов исчерпан для {user_id}: {len(phones)}/{limit}")
                await safe_answer(message,
                    "______ RuWEEX ACCOUNTS ______\n\n"
                    f"Лимит подключённых аккаунтов исчерпан ({limit}).\n"
                    "Без подписки доступен только 1 аккаунт.\n"
                    "С подпиской можно подключить до 5 аккаунтов.\n"
                    "Подписка: 5$ / месяц у @svbboss."
                )
                return
    
    # Очистка старой сессии
    print(f"[AUTH] Очистка старой сессии для {user_id}")
    try:
        await clear_user_session(user_id)
    except Exception as e:
        print(f"[AUTH] Ошибка при очистке сессии: {e}")
    
    # Создание клиента с прокси (если настроен)
    # Привязываем имя сессии к user_id и номеру телефона
    session_name = f"{user_id}_{re.sub(r'[^0-9]', '', phone)}.session"
    print(f"[AUTH] Создание клиента для {phone}, сессия: {session_name}")
    
    # Получаем или генерируем параметры устройства
    from device_generator import generate_device_params
    device_params = await db.get_device_params(session_name)
    if not device_params:
        device_params = generate_device_params(user_id, phone, prefer_ios=True)
        # Сохраняем параметры устройства в БД
        await db.save_device_params(session_name, user_id, device_params)
        print(f"[AUTH] Сгенерированы параметры устройства: {device_params['device_model']} {device_params['system_version']}")
    else:
        print(f"[AUTH] Используются сохраненные параметры устройства: {device_params['device_model']} {device_params['system_version']}")
    
    print(f"[AUTH] Создание клиента для {phone}...")
    print(f"[AUTH] Session: {session_name}")
    print(f"[AUTH] Device: {device_params['device_model']} {device_params['system_version']}")
    
    try:
        client = UserTelegramClient(
            session_name,
            str(API_ID),  # Убеждаемся, что это строка
            API_HASH,
            phone,
            proxy=PROXY,
            user_id=user_id,
            device_params=device_params
        )
        user_clients[user_id] = client
        # Сохраняем время отправки кода для проверки истечения
        user_auth_data[user_id] = {'phone': phone, 'attempts': 0, 'code_sent_time': None}
        print(f"[AUTH] ✅ Клиент успешно создан")
    except Exception as client_error:
        print(f"[AUTH] ❌ Ошибка создания клиента: {client_error}")
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n\n"
            f"❌ Ошибка инициализации: {str(client_error)}\n\n"
            "Попробуйте начать заново через /start."
        )
        await state.clear()
        return
    
    try:
        print(f"[AUTH] ========== НАЧАЛО ОТПРАВКИ КОДА ==========")
        print(f"[AUTH] Пользователь: {user_id}")
        print(f"[AUTH] Номер телефона: {phone}")
        print(f"[AUTH] API_ID: {API_ID}")
        print(f"[AUTH] API_HASH: {API_HASH[:10]}...")
        print(f"[AUTH] Прокси: {PROXY if PROXY else 'не настроен'}")
        
        # Небольшая задержка перед запросом для стабильности
        await asyncio.sleep(2)
        
        # Отправка кода с повторными попытками при сетевых ошибках
        max_retries = 5  # Увеличиваем количество попыток
        code_sent = False
        last_error = None
        
        for attempt in range(max_retries):
            try:
                print(f"[AUTH] ========== ПОПЫТКА {attempt + 1}/{max_retries} ==========")
                print(f"[AUTH] Вызов client.send_code()...")
                
                result = await client.send_code()
                
                if result and client.phone_code_hash:
                    code_sent = True
                    print(f"[AUTH] ✅✅✅ КОД УСПЕШНО ОТПРАВЛЕН! ✅✅✅")
                    print(f"[AUTH] phone_code_hash: {client.phone_code_hash[:30]}...")
                    print(f"[AUTH] Тип результата: {type(result).__name__}")
                    break
                else:
                    print(f"[AUTH] ⚠️ Результат получен, но phone_code_hash отсутствует")
                    raise ValueError("phone_code_hash не получен от Telegram")
                    
            except FloodWaitError as e:
                # Если FloodWait - ждем указанное время
                wait_time = e.seconds
                print(f"[AUTH] ⏰ FloodWait: нужно подождать {wait_time} секунд")
                if attempt < max_retries - 1:
                    await safe_answer(message,
                        f"______ RuWEEX LIMIT ______\n"
                        f"Telegram ограничил запросы. Подождите {wait_time} секунд..."
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise
            except ValueError as ve:
                # Ошибки валидации - не повторяем
                error_str = str(ve)
                print(f"[AUTH] ❌ Ошибка валидации: {error_str}")
                last_error = ve
                raise
            except Exception as retry_error:
                error_msg = str(retry_error).lower()
                error_str = str(retry_error)
                last_error = retry_error
                print(f"[AUTH] ❌ Ошибка при отправке кода (попытка {attempt + 1}): {retry_error}")
                print(f"[AUTH] Тип ошибки: {type(retry_error).__name__}")
                print(f"[AUTH] Полный текст: {error_str}")
                
                # Повторяем только при сетевых ошибках
                if ("timeout" in error_msg or "connection" in error_msg or "network" in error_msg or "семафора" in error_str.lower() or "connection reset" in error_msg) and attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # Увеличиваем задержку с каждой попыткой
                    print(f"[AUTH] 🔄 Повторная попытка через {wait_time} секунд...")
                    await asyncio.sleep(wait_time)
                    # Пытаемся переподключиться
                    try:
                        if user_id in user_clients:
                            await user_clients[user_id].disconnect()
                            await asyncio.sleep(1)
                    except:
                        pass
                    continue
                else:
                    raise
        
        if not code_sent:
            print(f"[AUTH] ❌❌❌ НЕ УДАЛОСЬ ОТПРАВИТЬ КОД ПОСЛЕ {max_retries} ПОПЫТОК ❌❌❌")
            if last_error:
                raise last_error
            raise Exception("Не удалось отправить код после всех попыток")
        
        # Обновление счетчиков (гарантируем, что ключ существует)
        if user_id not in auth_attempts:
            auth_attempts[user_id] = {'last_attempt': 0, 'code_requests': 0}
        auth_attempts[user_id]['last_attempt'] = time.time()
        auth_attempts[user_id]['code_requests'] = auth_attempts[user_id].get('code_requests', 0) + 1
        
        # Сохраняем время отправки кода
        if user_id in user_auth_data:
            user_auth_data[user_id]['code_sent_time'] = time.time()
        
        await state.set_state(AuthStates.waiting_code)
        await safe_answer(message,
            "______ RuWEEX CODE ______\n\n"
            "✅ Код отправлен в Telegram!\n\n"
            "📱 Введите код из Telegram (5 цифр):\n\n"
            "⏰ Код действителен ~2-3 минуты.\n"
            "⚠️ Введите код как можно быстрее!\n\n"
            "Если код истек, просто введите его - бот автоматически запросит новый."
        )
    except FloodWaitError as e:
        wait_time = e.seconds
        await safe_answer(
            message,
            "______ RuWEEX LIMIT ______\n"
            f"Telegram ограничил запросы. Подождите {wait_time} секунд перед следующей попыткой."
        )
        await state.clear()
    except PhoneNumberBannedError:
        await safe_answer(
            message,
            "______ RuWEEX ERROR ______\n\n"
            "❌ Этот номер телефона заблокирован в Telegram.\n\n"
            "Используйте другой номер телефона."
        )
        await state.clear()
    except ValueError as ve:
        error_str = str(ve)
        print(f"[AUTH] Ошибка валидации: {ve}")
        await safe_answer(
            message,
            f"______ RuWEEX ERROR ______\n\n"
            f"❌ {error_str}\n\n"
            "Проверьте правильность номера телефона.\n"
            "Формат: +79991234567"
        )
        await state.clear()
    except Exception as e:
        error_msg = str(e).lower()
        error_str = str(e)
        error_type = type(e).__name__
        print(f"[AUTH] ❌❌❌ КРИТИЧЕСКАЯ ОШИБКА при отправке кода для {phone} ❌❌❌")
        print(f"[AUTH] Тип ошибки: {error_type}")
        print(f"[AUTH] Сообщение: {error_str}")
        
        # Детальная обработка различных типов ошибок
        if "flood" in error_msg or "FloodWaitError" in error_type:
            await safe_answer(
                message,
                "______ RuWEEX LIMIT ______\n\n"
                "⏰ Telegram ограничил запросы кода.\n\n"
                "Подождите несколько минут и попробуйте снова."
            )
        elif "invalid" in error_msg or "неверн" in error_str.lower():
            await safe_answer(
                message,
                "______ RuWEEX ERROR ______\n\n"
                "❌ Неверный номер телефона.\n\n"
                "Проверьте формат: +79991234567"
            )
        elif "timeout" in error_msg or "connection" in error_msg or "network" in error_msg or "семафора" in error_str.lower():
            await safe_answer(
                message,
                "______ RuWEEX NETWORK ______\n\n"
                "🌐 Проблема с подключением к Telegram.\n\n"
                "Проверьте:\n"
                "• Интернет-соединение\n"
                "• Настройки прокси (если используется)\n"
                "• Попробуйте позже"
            )
        elif "unoccupied" in error_msg or "не зарегистрирован" in error_str.lower():
            await safe_answer(
                message,
                "______ RuWEEX ERROR ______\n\n"
                "❌ Этот номер не зарегистрирован в Telegram.\n\n"
                "Сначала зарегистрируйте номер в официальном приложении Telegram."
            )
        else:
            await safe_answer(
                message,
                f"______ RuWEEX ERROR ______\n\n"
                f"❌ Ошибка: {error_str}\n\n"
                "Попробуйте:\n"
                "• Проверить номер телефона\n"
                "• Подождать несколько минут\n"
                "• Начать заново через /start"
            )
        await state.clear()


@dp.message(AuthStates.waiting_code)
async def process_code(message: Message, state: FSMContext):
    """Обработка кода верификации"""
    user_id = message.from_user.id
    raw_code = message.text.strip()
    
    # Проверка на команды отмены
    if raw_code.lower() in ['/start', '/cancel', 'отмена']:
        await state.clear()
        await safe_answer(message,
            "______ RuWEEX ______\n"
            "Авторизация отменена."
        )
        return
    
    # Валидация формата (пользователь вводит модифицированный код, но он все равно 5-значный)
    if not re.match(r'^\d{5}$', raw_code):
        await safe_answer(message,
            "______ RuWEEX CODE ______\n"
            "Код должен состоять из 5 цифр."
        )
        return

    # Декодирование "безопасного" кода пользователя:
    # Пользователь вводит каждую цифру уменьшенной на 1 (mod 10),
    # например: настоящий код 12345 → пользователь вводит 01234.
    # Здесь восстанавливаем оригинальный код для Telegram.
    try:
        code = ''.join(str((int(ch) + 1) % 10) for ch in raw_code)
    except ValueError:
        # На случай, если попали нецифровые символы — просим ввести корректно
        await safe_answer(message,
            "______ RuWEEX CODE ______\n"
            "Код должен состоять только из цифр."
        )
        return
    
    # Защита от брутфорса
    if user_id not in user_auth_data:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Ошибка авторизации. Начните заново через /start."
        )
        await state.clear()
        return
    
    attempts = user_auth_data[user_id].get('attempts', 0)
    if attempts >= 5:
        await safe_answer(message,
            "______ RuWEEX LIMIT ______\n"
            "Превышен лимит попыток. Начните заново через /start."
        )
        await state.clear()
        return
    
    user_auth_data[user_id]['attempts'] = attempts + 1
    
    client = user_clients.get(user_id)
    if not client:
        await safe_answer(message,
            "______ RuWEEX ERROR ______\n"
            "Сессия недоступна. Начните заново через /start."
        )
        await state.clear()
        return
    
    try:
        # Проверяем, что phone_code_hash существует
        if not client.phone_code_hash:
            print(f"[AUTH] ⚠️ phone_code_hash отсутствует, запрашиваем новый код")
            await safe_answer(message,
                "______ RuWEEX CODE ______\n\n"
                "⏰ Код не был запрошен или истек.\n\n"
                "Запрашиваю новый код..."
            )
            
            # Запрашиваем новый код
            try:
                await asyncio.sleep(2)
                result = await client.send_code()
                if result and client.phone_code_hash:
                    # Обновляем счетчики
                    if user_id not in auth_attempts:
                        auth_attempts[user_id] = {'last_attempt': 0, 'code_requests': 0}
                    auth_attempts[user_id]['last_attempt'] = time.time()
                    auth_attempts[user_id]['code_requests'] = auth_attempts[user_id].get('code_requests', 0) + 1
                    
                    # Сохраняем время отправки кода
                    if user_id in user_auth_data:
                        user_auth_data[user_id]['code_sent_time'] = time.time()
                    
                    await safe_answer(message,
                        "______ RuWEEX CODE ______\n\n"
                        "✅ Новый код отправлен в Telegram!\n\n"
                        "📱 Введите код из Telegram (5 цифр):\n\n"
                        "⏰ Код действителен ~2-3 минуты.\n"
                        "⚠️ Введите код как можно быстрее!"
                    )
                    return  # Ждем ввода нового кода
                else:
                    raise ValueError("Не удалось получить phone_code_hash")
            except Exception as e:
                print(f"[AUTH] Ошибка при запросе нового кода: {e}")
                await safe_answer(message,
                    "______ RuWEEX ERROR ______\n\n"
                    f"❌ Ошибка при запросе кода: {str(e)}\n\n"
                    "Попробуйте начать заново через /start."
                )
                await state.clear()
                return
        
        # Проверяем время с момента отправки кода
        code_sent_time = user_auth_data[user_id].get('code_sent_time')
        if code_sent_time:
            time_since_sent = time.time() - code_sent_time
            print(f"[AUTH] Время с момента отправки кода: {int(time_since_sent)} секунд")
            if time_since_sent > 180:  # 3 минуты
                print(f"[AUTH] ⚠️ Код был отправлен более 3 минут назад, вероятно истек")
                await safe_answer(message,
                    "______ RuWEEX CODE ______\n\n"
                    "⏰ Код был отправлен более 3 минут назад и вероятно истек.\n\n"
                    "Запрашиваю новый код..."
                )
                # Запрашиваем новый код
                try:
                    client.phone_code_hash = None
                    await asyncio.sleep(2)
                    result = await client.send_code()
                    if result and client.phone_code_hash:
                        user_auth_data[user_id]['code_sent_time'] = time.time()
                        await safe_answer(message,
                            "______ RuWEEX CODE ______\n\n"
                            "✅ Новый код отправлен в Telegram!\n\n"
                            "📱 Введите код из Telegram (5 цифр):\n\n"
                            "⏰ Код действителен ~2-3 минуты.\n"
                            "⚠️ Введите код как можно быстрее!"
                        )
                        return
                except Exception as e:
                    print(f"[AUTH] Ошибка при запросе нового кода: {e}")
                    # При ошибке запроса нового кода продолжаем с текущим кодом
        
        # Попытка входа с кодом
        print(f"[AUTH] Попытка входа с кодом")
        print(f"[AUTH] phone_code_hash: {client.phone_code_hash[:20] if client.phone_code_hash else 'None'}...")
        print(f"[AUTH] Код от пользователя: {code}")
        
        try:
            result = await client.sign_in(code)
            print(f"[AUTH] ✅ Успешный вход с кодом")
        except PhoneCodeExpiredError:
            # Если код истек, не пытаемся повторно - обработаем в except блоке
            print(f"[AUTH] ⚠️ Код истек при попытке входа - обрабатываем в except блоке")
            raise
        except PhoneCodeInvalidError:
            # Неверный код - не повторяем
            print(f"[AUTH] Неверный код")
            raise
        except SessionPasswordNeededError:
            # Требуется пароль 2FA - пробрасываем дальше
            print(f"[AUTH] Требуется пароль 2FA")
            raise
        except Exception as retry_error:
            error_msg = str(retry_error).lower()
            error_str = str(retry_error)
            print(f"[AUTH] Ошибка при входе: {retry_error}")
            # Пробрасываем ошибку дальше для обработки во внешнем except блоке
            raise
        
        # Успешная авторизация
        if user_id not in user_auth_data:
            await safe_answer(message,
                "______ RuWEEX ERROR ______\n"
                "Ошибка: данные авторизации не найдены. Начните заново через /start."
            )
            await state.clear()
            return
        
        phone = user_auth_data[user_id].get('phone')
        if not phone:
            await safe_answer(message,
                "______ RuWEEX ERROR ______\n"
                "Ошибка: номер телефона не найден. Начните заново через /start."
            )
            await state.clear()
            return
        
        # Имя сессии привязано к user_id и номеру телефона
        session_name = f"{user_id}_{re.sub(r'[^0-9]', '', phone)}.session"
        await db.add_user(user_id, phone, session_name)
        print(f"[AUTH] Пользователь {user_id} успешно авторизован с номером {phone}")
        
        # Очистка данных попыток
        if user_id in user_auth_data:
            del user_auth_data[user_id]
        if user_id in auth_attempts:
            del auth_attempts[user_id]
        
        await state.clear()
        await safe_answer(message,
            "______ RuWEEX AUTH SUCCESS ______\n\n"
            "✅ Авторизация успешна!\n\n"
            "📋 Доступные команды:\n"
            "`.флуд`  — рассылка по ЛС\n"
            "`.сфлуд` — остановка рассылки по ЛС\n"
            "`.пфлуд` — рассылка по папкам\n"
            "`.спфлуд` — остановка рассылки по папкам\n"
            "`.инфо`  — информация о рассылках\n"
            "`.статус` — статус бота и подключения\n"
            "`.автоп` — авто-подписка\n"
            "`.автоответ` — автоответчик на входящие\n"
            "`/reauth` — новая авторизация\n"
            "`.аккаунты` — переключение между аккаунтами\n\n"
            "📝 Примеры использования:\n"
            "`.флуд 10 60 Привет! Это тестовое сообщение`\n"
            "`.автоответ Спасибо за сообщение! Я отвечу позже.`\n"
            "`.савтоответ` — выключить автоответчик\n\n"
            "💡 Используйте `.статус` для проверки состояния бота"
        )
    except SessionPasswordNeededError:
        # Требуется пароль 2FA - запрашиваем его
        await state.set_state(AuthStates.waiting_password)
        await safe_answer(message,
            "______ RuWEEX 2FA ______\n\n"
            "🔐 Требуется пароль двухфакторной аутентификации.\n\n"
            "Введите пароль:"
        )
    except PhoneCodeInvalidError:
        # Проверяем количество попыток
        if user_id in user_auth_data:
            attempts = user_auth_data[user_id].get('attempts', 0)
            if attempts >= 4:
                await safe_answer(message,
                    "______ RuWEEX LIMIT ______\n"
                    "Слишком много неверных кодов. Начните заново через /start."
                )
                await state.clear()
            else:
                await safe_answer(message, 
                    "______ RuWEEX CODE ______\n"
                    f"Неверный код. Осталось попыток: {5 - attempts}."
                )
        else:
            await safe_answer(message,
                "______ RuWEEX CODE ______\n"
                "Неверный код. Попробуйте снова."
            )
    except PhoneCodeExpiredError:
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: код истек - запрашиваем новый и ЖДЕМ ввода от пользователя
        print(f"[AUTH] ⚠️ Код истек для пользователя {user_id}")
        
        # Очищаем старый phone_code_hash
        if client:
            client.phone_code_hash = None
        
        # Проверяем, можно ли запросить новый код
        if user_id not in auth_attempts:
            auth_attempts[user_id] = {'last_attempt': 0, 'code_requests': 0}
        
        last_attempt = auth_attempts[user_id].get('last_attempt', 0)
        code_requests = auth_attempts[user_id].get('code_requests', 0)
        time_since_last = time.time() - last_attempt
        
        # Увеличиваем лимит до 10 запросов для удобства пользователей
        if code_requests >= 10:
            await safe_answer(message, 
                "______ RuWEEX LIMIT ______\n\n"
                "❌ Достигнут максимум запросов кода (10).\n\n"
                "Подождите 15–20 минут и начните заново через /start."
            )
            await state.clear()
            return
        
        # Минимальная задержка 5 секунд между запросами кодов
        if time_since_last < 5:
            wait_time = int(5 - time_since_last) + 1
            await safe_answer(message,
                "______ RuWEEX CODE ______\n\n"
                f"⏰ Код истёк. Подождите {wait_time} секунд перед запросом нового кода."
            )
            return
        
        # Запрашиваем новый код БЕЗ очистки сессии (используем тот же клиент)
        try:
            await safe_answer(message,
                "______ RuWEEX CODE ______\n\n"
                "⏰ Код истёк. Запрашиваю новый код..."
            )
            
            # Небольшая задержка перед запросом
            await asyncio.sleep(3)
            
            # НЕ очищаем сессию - используем существующий клиент
            # Используем существующий клиент или создаем новый, если его нет
            if not client or user_id not in user_clients:
                if user_id not in user_auth_data:
                    await safe_answer(message,
                        "______ RuWEEX ERROR ______\n"
                        "Ошибка: данные авторизации не найдены. Начните заново через /start."
                    )
                    await state.clear()
                    return
                
                phone = user_auth_data[user_id].get('phone')
                if not phone:
                    await safe_answer(message,
                        "______ RuWEEX ERROR ______\n"
                        "Ошибка: номер телефона не найден. Начните заново через /start."
                    )
                    await state.clear()
                    return
                
                session_name = f"{user_id}_{re.sub(r'[^0-9]', '', phone)}.session"
                
                # Получаем или генерируем параметры устройства
                device_params = await db.get_device_params(session_name)
                if not device_params:
                    device_params = generate_device_params(user_id, phone, prefer_ios=True)
                    await db.save_device_params(session_name, user_id, device_params)
                
                client = UserTelegramClient(
                    session_name,
                    API_ID,
                    API_HASH,
                    phone,
                    proxy=PROXY,
                    user_id=user_id,
                    device_params=device_params
                )
                user_clients[user_id] = client
            
            # Очищаем старый phone_code_hash перед запросом нового кода
            client.phone_code_hash = None
            
            # Запрашиваем новый код с повторными попытками
            max_retries = 5
            code_sent = False
            for attempt in range(max_retries):
                try:
                    print(f"[AUTH] Попытка {attempt + 1}/{max_retries} запроса нового кода для {user_id}")
                    result = await client.send_code()
                    code_sent = True
                    print(f"[AUTH] ✅ Новый код успешно отправлен, phone_code_hash: {client.phone_code_hash[:10] if client.phone_code_hash else 'None'}...")
                    break
                except FloodWaitError as e:
                    wait_time = e.seconds
                    print(f"[AUTH] FloodWait: нужно подождать {wait_time} секунд")
                    if attempt < max_retries - 1:
                        await safe_answer(message,
                            f"______ RuWEEX LIMIT ______\n"
                            f"Telegram ограничил запросы. Подождите {wait_time} секунд..."
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise
                except Exception as retry_error:
                    error_msg = str(retry_error).lower()
                    error_str = str(retry_error)
                    print(f"[AUTH] Ошибка при запросе нового кода (попытка {attempt + 1}): {retry_error}")
                    
                    if ("timeout" in error_msg or "connection" in error_msg or "network" in error_msg or "семафора" in error_str.lower()) and attempt < max_retries - 1:
                        wait_time = 3 * (attempt + 1)
                        print(f"[AUTH] Повторная попытка через {wait_time} секунд...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise
            
            if not code_sent:
                raise Exception("Не удалось запросить новый код после всех попыток")
            
            # Обновляем счетчики
            auth_attempts[user_id]['last_attempt'] = time.time()
            auth_attempts[user_id]['code_requests'] = code_requests + 1
            
            # Сохраняем время отправки нового кода
            if user_id in user_auth_data:
                user_auth_data[user_id]['code_sent_time'] = time.time()
            
            # КРИТИЧЕСКИ ВАЖНО: НЕ пытаемся войти автоматически!
            # Просто сообщаем пользователю и ЖДЕМ ввода нового кода
            # Состояние остается waiting_code, пользователь введет новый код
            await safe_answer(message,
                "______ RuWEEX CODE ______\n\n"
                "✅ Новый код отправлен в Telegram!\n\n"
                "📱 Введите новый код из Telegram (5 цифр):\n\n"
                "⏰ Код действителен ~2-3 минуты.\n"
                "⚠️ Введите код как можно быстрее!"
            )
            
            # ВАЖНО: НЕ очищаем состояние, НЕ пытаемся войти автоматически
            # Просто возвращаемся и ждем ввода нового кода от пользователя
            return
            
        except FloodWaitError as e:
            wait_time = e.seconds
            await safe_answer(message,
                "______ RuWEEX LIMIT ______\n"
                f"Telegram ограничил запросы. Подождите {wait_time} секунд и начните заново через /start."
            )
            await state.clear()
        except Exception as e:
            error_msg = str(e).lower()
            if "flood" in error_msg:
                await safe_answer(message,
                    "______ RuWEEX LIMIT ______\n"
                    "Слишком много запросов кодов. Подождите 10–15 минут и начните заново через /start."
                )
            else:
                await safe_answer(message,
                    "______ RuWEEX ERROR ______\n"
                    f"Ошибка запроса нового кода: {str(e)}\n"
                    "Начните заново через /start."
                )
            await state.clear()
    except Exception as e:
        error_msg = str(e).lower()
        error_str = str(e)
        
        # Обработка блокировки из-за повторного использования кода
        if "previously reported" in error_msg or "сообщили этот код" in error_str.lower() or "ранее вы сообщили" in error_str.lower():
            await safe_answer(message,
                "______ RuWEEX SECURITY BLOCKED ______\n\n"
                "🚫 Telegram заблокировал вход.\n\n"
                "Код был использован в другом месте.\n\n"
                "⏰ Подождите 15-20 минут и начните заново через /start."
            )
            await state.clear()
        elif "blocked" in error_msg or "ban" in error_msg or "restricted" in error_msg:
            await safe_answer(message,
                "______ RuWEEX SECURITY ______\n"
                "Telegram временно ограничил этот аккаунт.\n"
                "Подождите 10–15 минут и попробуйте снова через /start."
            )
            await state.clear()
        elif "timeout" in error_msg or "connection" in error_msg or "network" in error_msg:
            await safe_answer(message,
                "______ RuWEEX NETWORK ______\n"
                "Проблема с подключением к Telegram. Проверьте интернет и попробуйте снова."
            )
            await state.clear()
        elif "flood" in error_msg:
            await safe_answer(message,
                "______ RuWEEX LIMIT ______\n"
                "Слишком много запросов. Подождите 5–10 минут и начните заново через /start."
            )
            await state.clear()
        else:
            await safe_answer(message, 
                "______ RuWEEX ERROR ______\n"
                f"{str(e)}\n\n"
                "Попробуйте начать заново через /start."
            )
            await state.clear()


@dp.message(AuthStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    """Обработка пароля 2FA"""
    user_id = message.from_user.id
    password = message.text.strip()
    
    client = user_clients.get(user_id)
    if not client:
        await safe_answer(
            message,
            "______ RuWEEX ERROR ______\n"
            "Сессия недоступна. Начните заново через /start."
        )
        await state.clear()
        return
    
    try:
        # Попытка входа с повторными попытками при сетевых ошибках
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Для 2FA передаем только пароль - Telethon сам использует текущую сессию
                result = await client.sign_in(password=password)
                if result:
                    break
            except SessionPasswordNeededError:
                # Если все еще требуется пароль, значит пароль неверный
                await safe_answer(message,
                    "______ RuWEEX 2FA ERROR ______\n\n"
                    "❌ Неверный пароль 2FA.\n\n"
                    "Проверьте правильность ввода и попробуйте снова.\n"
                    "Если проблема сохраняется, начните заново через /start."
                )
                return
            except Exception as retry_error:
                error_msg = str(retry_error).lower()
                error_str = str(retry_error)
                
                # Проверяем на неверный пароль
                if "password" in error_msg and ("invalid" in error_msg or "неверн" in error_str.lower()):
                    await safe_answer(message,
                        "______ RuWEEX 2FA ERROR ______\n\n"
                        "❌ Неверный пароль 2FA.\n\n"
                        "Проверьте правильность ввода и попробуйте снова."
                    )
                    return
                
                if ("timeout" in error_msg or "connection" in error_msg or "network" in error_msg) and attempt < max_retries - 1:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                else:
                    raise
        
        # Успешная авторизация
        phone = user_auth_data[user_id]['phone']
        session_name = f"{user_id}_{re.sub(r'[^0-9]', '', phone)}.session"
        await db.add_user(user_id, phone, session_name)
        
        # Очистка данных
        if user_id in user_auth_data:
            del user_auth_data[user_id]
        if user_id in auth_attempts:
            del auth_attempts[user_id]
        
        await state.clear()
        await safe_answer(message,
            "______ RuWEEX AUTH SUCCESS ______\n\n"
            "✅ Авторизация успешна!\n\n"
            "📋 Доступные команды:\n"
            "`.флуд`  — рассылка по ЛС\n"
            "`.сфлуд` — остановка рассылки по ЛС\n"
            "`.пфлуд` — рассылка по папкам\n"
            "`.спфлуд` — остановка рассылки по папкам\n"
            "`.инфо`  — информация о рассылках\n"
            "`.статус` — статус бота и подключения\n"
            "`.автоп` — авто-подписка\n"
            "`.автоответ` — автоответчик на входящие\n"
            "`/reauth` — новая авторизация\n"
            "`.аккаунты` — переключение между аккаунтами\n\n"
            "📝 Примеры использования:\n"
            "`.флуд 10 60 Привет! Это тестовое сообщение`\n"
            "`.автоответ Спасибо за сообщение! Я отвечу позже.`\n"
            "`.савтоответ` — выключить автоответчик\n\n"
            "💡 Используйте `.статус` для проверки состояния бота"
        )
    except Exception as e:
        error_msg = str(e).lower()
        if "timeout" in error_msg or "connection" in error_msg or "network" in error_msg:
            await safe_answer(message,
                "______ RuWEEX NETWORK ______\n"
                "Проверьте соединение с интернетом и попробуйте снова."
            )
        else:
            await safe_answer(
                message,
                "______ RuWEEX 2FA ______\n"
                "Неверный пароль двухфакторной аутентификации. Попробуйте снова."
            )
        # Остаемся в состоянии waiting_password


# Callback обработчики
@dp.callback_query(F.data.startswith("stop_folder_"))
async def process_stop_folder(callback: CallbackQuery):
    """Остановка рассылки по папкам"""
    campaign_id = int(callback.data.split("_")[-1])
    
    if await campaign_manager.stop_campaign(campaign_id):
        await callback.answer("Рассылка остановлена.")
        await callback.message.edit_text("______ RuWEEX ______\nРассылка по папкам остановлена.")
    else:
        await callback.answer("Не удалось остановить рассылку.")


@dp.callback_query(F.data.startswith("info_"))
async def process_campaign_info(callback: CallbackQuery):
    """Детальная информация о рассылке"""
    campaign_id = int(callback.data.split("_")[-1])
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback.answer("Рассылка не найдена.")
        return
    
    # Форматирование информации
    sent = campaign.get('sent_count', 0)
    success = campaign.get('success_count', 0)
    errors = campaign.get('error_count', 0)
    
    text = (
        "______ RuWEEX CAMPAIGN ______\n\n"
        f"id: {campaign['id']}\n"
        f"тип: {campaign['campaign_type']}\n"
        f"текст: {campaign['text'][:100]}...\n"
        f"круги: {campaign['rounds']}\n"
        f"задержка: {campaign['delay']} c\n"
    )
    
    if campaign.get('folder_name'):
        text += f"папка: {campaign['folder_name']}\n"
    
    text += (
        f"\n📊 СТАТИСТИКА:\n"
        f"отправлено: {sent}\n"
        f"успешно: {success}\n"
        f"ошибок: {errors}\n"
        f"успешность: {(success/sent*100 if sent > 0 else 0):.1f}%\n\n"
        f"статус: {campaign['status']}\n"
        f"создана: {campaign['created_at']}\n"
        f"запущена: {campaign.get('started_at', 'N/A')}"
    )
    
    # Создаем кнопки
    builder = InlineKeyboardBuilder()
    if campaign['status'] == 'active':
        builder.add(InlineKeyboardButton(
            text="Остановить",
            callback_data=f"stop_{campaign_id}"
        ))
    builder.add(InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_list"
    ))
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("stop_"))
async def process_stop_campaign(callback: CallbackQuery):
    """Остановка рассылки из меню инфо"""
    campaign_id = int(callback.data.split("_")[-1])
    
    if await campaign_manager.stop_campaign(campaign_id):
        await callback.answer("Рассылка остановлена.")
        await callback.message.edit_text("______ RuWEEX ______\nРассылка остановлена.")
    else:
        await callback.answer("Не удалось остановить рассылку.")


@dp.callback_query(F.data == "back_to_list")
async def process_back_to_list(callback: CallbackQuery):
    """Возврат к списку рассылок"""
    user_id = callback.from_user.id
    
    campaigns = await db.get_campaigns(user_id)
    
    if not campaigns:
        await callback.message.edit_text("______ RuWEEX ______\nДанных о рассылках нет.")
        await callback.answer()
        return
    
    # Группируем по статусам
    active = [c for c in campaigns if c['status'] == 'active']
    completed = [c for c in campaigns if c['status'] == 'completed']
    stopped = [c for c in campaigns if c['status'] == 'stopped']
    errors = [c for c in campaigns if c['status'] == 'error']
    
    # Подсчитываем общую статистику
    total_sent = sum(c.get('sent_count', 0) for c in campaigns)
    total_success = sum(c.get('success_count', 0) for c in campaigns)
    total_errors = sum(c.get('error_count', 0) for c in campaigns)
    
    text = (
        "______ RuWEEX STATS ______\n\n"
        f"активных:   {len(active)}\n"
        f"завершено:  {len(completed)}\n"
        f"остановлено:{len(stopped)}\n"
        f"с ошибкой:  {len(errors)}\n"
        f"всего:      {len(campaigns)}\n\n"
        f"📊 ОБЩАЯ СТАТИСТИКА:\n"
        f"отправлено: {total_sent}\n"
        f"успешно: {total_success}\n"
        f"ошибок: {total_errors}\n"
        f"успешность: {(total_success/total_sent*100 if total_sent > 0 else 0):.1f}%"
    )
    
    # Создаем кнопки для активных рассылок
    if active:
        builder = InlineKeyboardBuilder()
        for campaign in active:
            builder.add(InlineKeyboardButton(
                text=f"#{campaign['id']} - {campaign['campaign_type']}",
                callback_data=f"info_{campaign['id']}"
            ))
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(text)
    
    await callback.answer()


# Глобальный обработчик ошибок
@dp.errors()
async def error_handler(event: ErrorEvent):
    """Глобальный обработчик ошибок"""
    exception = event.exception
    error_msg = str(exception).lower()
    error_str = str(exception)
    
    print(f"[ERROR HANDLER] Ошибка: {type(exception).__name__}: {exception}")
    print(f"[ERROR HANDLER] Событие: {event.update}")
    
    # Игнорируем сетевые ошибки - они обрабатываются в safe_answer
    if ("timeout" in error_msg or 
        "семафора" in error_str.lower() or 
        "semaphore" in error_msg or
        "connection" in error_msg or
        "network" in error_msg):
        print(f"[ERROR HANDLER] Сетевая ошибка (игнорируется): {exception}")
        return
    
    # Логируем другие ошибки
    print(f"[ERROR HANDLER] Критическая ошибка в диспетчере: {exception}")
    import traceback
    traceback.print_exc()
    return


# Главная функция
async def main():
    """Главная функция запуска бота"""
    # Инициализация БД
    print("[INIT] Инициализация базы данных...")
    await db.init_db()
    print("[INIT] База данных инициализирована")
    
    print("______ RuWEEX BOT ______")
    print("База данных инициализирована.")
    print("Если возникают проблемы с сетью, настройте прокси (см. PROXY_SETUP.md).")
    print(f"[INIT] BOT_TOKEN: {BOT_TOKEN[:10]}...")
    print(f"[INIT] API_ID: {API_ID}")
    print(f"[INIT] PROXY: {'Настроен' if PROXY else 'Не настроен'}")
    
    # Запуск polling с обработкой ошибок
    try:
        print("[INIT] Запуск polling...")
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Бот остановлен пользователем.")
    except Exception as e:
        print(f"[CRITICAL] Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
