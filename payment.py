"""Модуль для работы с CryptoBot API"""
import aiohttp
import asyncio
from typing import Optional, Dict
import aiosqlite


CRYPTOBOT_API_TOKEN = "521692:AAflSSjYASfUVwJZBQccg7FVY7OVfzsgXCv"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"

# Цены подписки (в USDT)
SUBSCRIPTION_PRICES = {
    30: 5.0,  # 30 дней за 5 USDT
    90: 12.0,  # 90 дней за 12 USDT
    180: 20.0,  # 180 дней за 20 USDT
    365: 35.0,  # 365 дней за 35 USDT
}


async def create_invoice(user_id: int, days: int, amount: float) -> Optional[Dict]:
    """Создание инвойса для оплаты"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{CRYPTOBOT_API_URL}/createInvoice"
            headers = {
                "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN
            }
            data = {
                "asset": "USDT",
                "amount": str(amount),
                "description": f"Подписка RuWEEX на {days} дней",
                "hidden_message": f"user_id:{user_id}|days:{days}",
                "paid_btn_name": "callback",
                "paid_btn_url": "https://t.me/ruweex",
                "expires_in": 3600  # 1 час
            }
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        invoice = result.get("result")
                        # Сохраняем инвойс в БД
                        await save_invoice(user_id, invoice["invoice_id"], days, amount)
                        return invoice
                return None
    except Exception as e:
        print(f"[PAYMENT] Ошибка создания инвойса: {e}")
        return None


async def check_invoice(invoice_id: int) -> Optional[Dict]:
    """Проверка статуса инвойса"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{CRYPTOBOT_API_URL}/getInvoices"
            headers = {
                "Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN
            }
            params = {
                "invoice_ids": str(invoice_id)
            }
            
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok") and result.get("result", {}).get("items"):
                        return result["result"]["items"][0]
                return None
    except Exception as e:
        print(f"[PAYMENT] Ошибка проверки инвойса: {e}")
        return None


async def save_invoice(user_id: int, invoice_id: int, days: int, amount: float):
    """Сохранение инвойса в БД"""
    try:
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO payments (user_id, invoice_id, days, amount, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
            """, (user_id, invoice_id, days, amount))
            await db.commit()
    except Exception as e:
        print(f"[PAYMENT] Ошибка сохранения инвойса: {e}")


async def update_invoice_status(invoice_id: int, status: str):
    """Обновление статуса инвойса"""
    try:
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE payments SET status = ? WHERE invoice_id = ?
            """, (status, invoice_id))
            await db.commit()
    except Exception as e:
        print(f"[PAYMENT] Ошибка обновления статуса: {e}")


async def get_user_pending_invoices(user_id: int):
    """Получение активных инвойсов пользователя"""
    try:
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM payments 
                WHERE user_id = ? AND status = 'pending'
                ORDER BY created_at DESC
            """, (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        print(f"[PAYMENT] Ошибка получения инвойсов: {e}")
        return []


async def activate_subscription(user_id: int, days: int, db_instance=None):
    """Активация подписки пользователю"""
    if db_instance is None:
        from database import Database
        db_instance = Database()
    await db_instance.update_subscription(user_id, days)
