"""Модуль для работы с базой данных SQLite"""
import aiosqlite
from datetime import datetime, timedelta
import json
from config import DATABASE_PATH


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self):
        self.db_path = DATABASE_PATH
    
    async def init_db(self):
        """Инициализация БД, создание таблиц"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    phone_number TEXT NOT NULL,
                    session_file TEXT NOT NULL,
                    free_days INTEGER DEFAULT 1,
                    subscription_until TEXT,
                    auto_subscribe INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    used_phones TEXT
                )
            """)
            
            # Таблица рассылок
            await db.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    campaign_type TEXT NOT NULL,
                    text TEXT,
                    rounds INTEGER NOT NULL,
                    delay INTEGER NOT NULL,
                    folder_name TEXT,
                    status TEXT DEFAULT 'active',
                    started_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    sent_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Миграция: добавляем колонки статистики, если их нет
            for col in ['sent_count', 'success_count', 'error_count']:
                try:
                    await db.execute(f"ALTER TABLE campaigns ADD COLUMN {col} INTEGER DEFAULT 0")
                except Exception:
                    pass  # Колонка уже есть

            # Миграция для старых баз: добавляем колонку used_phones, если её нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN used_phones TEXT")
            except Exception:
                # Колонка уже есть — игнорируем ошибку
                pass
            
            # Таблица автоответчиков
            await db.execute("""
                CREATE TABLE IF NOT EXISTS auto_responses (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    response_text TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Таблица платежей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    invoice_id INTEGER UNIQUE NOT NULL,
                    days INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    paid_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Таблица параметров устройств (антидетект)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS device_params (
                    session_file TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    device_model TEXT NOT NULL,
                    system_version TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    lang_code TEXT NOT NULL,
                    system_lang_code TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            await db.commit()
    
    async def add_user(self, user_id: int, phone_number: str, session_file: str):
        """Добавление / обновление пользователя и списка телефонов"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Получаем текущие данные, чтобы не затирать free_days / subscription_until
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()

            if row:
                data = dict(row)
                used_phones_raw = data.get("used_phones")
                phones = []
                if used_phones_raw:
                    try:
                        phones = json.loads(used_phones_raw)
                    except Exception:
                        phones = []
                if phone_number not in phones:
                    phones.append(phone_number)

                await db.execute(
                    """
                    UPDATE users
                    SET phone_number = ?, session_file = ?, used_phones = ?
                    WHERE user_id = ?
                    """,
                    (phone_number, session_file, json.dumps(phones), user_id),
                )
            else:
                phones = [phone_number]
                await db.execute(
                    """
                    INSERT INTO users (user_id, phone_number, session_file, free_days,
                                       subscription_until, auto_subscribe, used_phones)
                    VALUES (?, ?, ?, 1, NULL, 0, ?)
                    """,
                    (user_id, phone_number, session_file, json.dumps(phones)),
                )

            await db.commit()
    
    async def get_user(self, user_id: int):
        """Получение данных пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_auto_subscribe(self, user_id: int, enabled: bool):
        """Обновление настройки авто-подписки"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE users SET auto_subscribe = ? WHERE user_id = ?
            """, (1 if enabled else 0, user_id))
            await db.commit()

    async def update_subscription(self, user_id: int, days: int):
        """Выдать или продлить подписку на days дней"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT subscription_until FROM users WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()

            now = datetime.now()
            base = now
            if row and row["subscription_until"]:
                try:
                    current = datetime.fromisoformat(row["subscription_until"])
                    if current > now:
                        base = current
                except Exception:
                    base = now

            new_until = base + timedelta(days=days)

            await db.execute(
                "UPDATE users SET subscription_until = ? WHERE user_id = ?",
                (new_until.isoformat(), user_id),
            )
            await db.commit()

    async def clear_subscription(self, user_id: int):
        """Сброс подписки пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET subscription_until = NULL WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    async def get_all_users(self):
        """Получить всех пользователей (для админ-панели)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_users_stats(self):
        """Статистика по пользователям для RuWEEX admin"""
        users = await self.get_all_users()
        now = datetime.now()

        total_users = len(users)
        active_subscriptions = 0
        active_trials = 0
        sessions = 0

        for user in users:
            if user.get("session_file"):
                sessions += 1

            sub_until = user.get("subscription_until")
            if sub_until:
                try:
                    if datetime.fromisoformat(sub_until) > now:
                        active_subscriptions += 1
                except Exception:
                    pass

            free_days = user.get("free_days") or 0
            created_at = user.get("created_at")
            if created_at and free_days > 0:
                try:
                    created_dt = datetime.fromisoformat(created_at)
                    if created_dt + timedelta(days=free_days) > now:
                        # Считаем триал только если нет активной подписки
                        if not sub_until or datetime.fromisoformat(sub_until) <= now:
                            active_trials += 1
                except Exception:
                    pass

        return {
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "active_trials": active_trials,
            "sessions": sessions,
        }
    
    async def add_campaign(self, user_id: int, campaign_type: str, text: str, 
                          rounds: int, delay: int, folder_name: str = None):
        """Добавление рассылки, возвращает campaign_id"""
        started_at = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO campaigns (user_id, campaign_type, text, rounds, delay, folder_name, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, campaign_type, text, rounds, delay, folder_name, started_at))
            await db.commit()
            return cursor.lastrowid
    
    async def get_campaigns(self, user_id: int, status: str = None):
        """Получение рассылок пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                async with db.execute("""
                    SELECT * FROM campaigns WHERE user_id = ? AND status = ?
                    ORDER BY created_at DESC
                """, (user_id, status)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
            else:
                async with db.execute("""
                    SELECT * FROM campaigns WHERE user_id = ?
                    ORDER BY created_at DESC
                """, (user_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
    
    async def get_campaign(self, campaign_id: int):
        """Получение конкретной рассылки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_campaign_status(self, campaign_id: int, status: str):
        """Обновление статуса рассылки"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE campaigns SET status = ? WHERE id = ?
            """, (status, campaign_id))
            await db.commit()
    
    async def update_campaign_stats(self, campaign_id: int, sent: int = 0, success: int = 0, error: int = 0):
        """Обновление статистики рассылки"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE campaigns 
                SET sent_count = sent_count + ?,
                    success_count = success_count + ?,
                    error_count = error_count + ?
                WHERE id = ?
            """, (sent, success, error, campaign_id))
            await db.commit()
    
    async def get_active_campaigns(self, user_id: int):
        """Получение активных рассылок пользователя"""
        return await self.get_campaigns(user_id, status='active')
    
    async def set_auto_response(self, user_id: int, enabled: bool, response_text: str = None):
        """Установка автоответчика"""
        async with aiosqlite.connect(self.db_path) as db:
            if enabled and response_text:
                await db.execute("""
                    INSERT OR REPLACE INTO auto_responses (user_id, enabled, response_text, updated_at)
                    VALUES (?, 1, ?, CURRENT_TIMESTAMP)
                """, (user_id, response_text))
            else:
                # Используем INSERT OR REPLACE для гарантии, что запись будет создана/обновлена
                await db.execute("""
                    INSERT OR REPLACE INTO auto_responses (user_id, enabled, response_text, updated_at)
                    VALUES (?, 0, ?, CURRENT_TIMESTAMP)
                """, (user_id, response_text or ''))
            await db.commit()
    
    async def get_auto_response(self, user_id: int):
        """Получение настроек автоответчика"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM auto_responses WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_all_auto_responses(self):
        """Получение всех активных автоответчиков"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM auto_responses WHERE enabled = 1"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def save_device_params(self, session_file: str, user_id: int, device_params: dict):
        """Сохранение параметров устройства для сессии"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO device_params 
                (session_file, user_id, device_model, system_version, app_version, lang_code, system_lang_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_file,
                user_id,
                device_params['device_model'],
                device_params['system_version'],
                device_params['app_version'],
                device_params['lang_code'],
                device_params['system_lang_code']
            ))
            await db.commit()
    
    async def get_device_params(self, session_file: str):
        """Получение параметров устройства для сессии"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM device_params WHERE session_file = ?",
                (session_file,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'device_model': row['device_model'],
                        'system_version': row['system_version'],
                        'app_version': row['app_version'],
                        'lang_code': row['lang_code'],
                        'system_lang_code': row['system_lang_code']
                    }
                return None