import asyncio
import os
import pyotp
import logging
import subprocess
import warnings
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

warnings.filterwarnings("ignore", category=UserWarning)

# --- НАСТРОЙКИ ---
TOKEN = "8491051329:AAGqgej7e5rrpe779XlTCJ4u0VPNQdg00lg"
GOSKEY_PASS = "1234xcvb" # Твой новый пароль

ADB_CONF = {
    "pass_field": "532 391",
    "login_btn": "558 752",
    "new_sign": "132 334",
    "contract": "431 356",
    "confirm": "949 1517",
    "final_sign": "557 1798"
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class Order(StatesGroup):
    operator = State()
    gu_select = State()

# --- ФУНКЦИЯ ПОИСКА ДАННЫХ В ФАЙЛЕ ---
def get_data_from_pool(year_filter):
    if not os.path.exists("sim_pool.txt"):
        return None
    with open("sim_pool.txt", "r", encoding="utf-8") as f:
        for line in f:
            if year_filter in line:
                # Разделяем строку Номер:Пароль:Год:Секрет
                parts = line.strip().split(":")
                if len(parts) >= 4:
                    return parts
    return None

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Активировать SIM", callback_data="act_sim")
    kb.adjust(1)
    await message.answer(f"<b>Привет, Егор!</b>\n@{message.from_user.username} | ID: {message.from_user.id}\n\nВыбери действие:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "act_sim")
async def choose_op(call: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    for op in ["Tele2", "Мегафон", "МТС", "Билайн"]:
        kb.button(text=op, callback_data=f"op_{op}")
    kb.adjust(2)
    await call.message.edit_text("Выбери оператора:", reply_markup=kb.as_markup())
    await state.set_state(Order.operator)

@dp.callback_query(F.data.startswith("op_"))
async def choose_gu(call: types.CallbackQuery, state: FSMContext):
    op = call.data.split("_")[1]
    await state.update_data(operator=op)
    
    kb = InlineKeyboardBuilder()
    if os.path.exists("gu_data.txt"):
        with open("gu_data.txt", "r", encoding="utf-8") as f:
            for line in f:
                # Читаем: 1985г | 0/5 | 5$
                kb.button(text=line.strip(), callback_data=f"gu_{line.split('|')[0].strip()}")
    kb.adjust(1)
    await call.message.edit_text("Выбери ГУ:", reply_markup=kb.as_markup())
    await state.set_state(Order.gu_select)

@dp.callback_query(F.data.startswith("gu_"))
async def finalize(call: types.CallbackQuery, state: FSMContext):
    year = call.data.split("_")[1]
    
    # ИЩЕМ РЕАЛЬНЫЕ ДАННЫЕ В sim_pool.txt
    sim_data = get_data_from_pool(year)
    
    if not sim_data:
        await call.message.answer("❌ Данные для этого года не найдены в sim_pool.txt")
        return

    num, pwd, yr, secret = sim_data
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Получить код TOTP", callback_data=f"totp_{secret}")
    
    await call.message.edit_text(
        f"✅ Данные получены!\n\n📱 <code>{num}</code>\n🔑 <code>{pwd}</code>\n📅 {yr}\n\n🚀 Ожидаю входа!",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("totp_"))
async def send_totp(call: types.CallbackQuery):
    secret = call.data.split("_")[1]
    
    # Генерация кода из секретного ключа в файле
    try:
        code = pyotp.TOTP(secret).now()
    except Exception:
        code = "Ошибка ключа!"

    await call.message.answer(f"🔐 Ваш код TOTP: <code>{code}</code>\n\nЖду вашей подписи...")
    
    # ЗАПУСК ADB
    # 1. Запуск приложения (универсальный способ)
    subprocess.run("adb shell monkey -p ru.gosuslugi.goskey -c android.intent.category.LAUNCHER 1", shell=True)
    await asyncio.sleep(6)
    
    # 2.Ввод пароля
    subprocess.run(f"adb shell input tap {ADB_CONF['pass_field']}", shell=True)
    await asyncio.sleep(1)
    subprocess.run(f"adb shell input text {GOSKEY_PASS}", shell=True)
    await asyncio.sleep(1)
    subprocess.run(f"adb shell input tap {ADB_CONF['login_btn']}", shell=True)
    
    # Далее твои координаты...
    await asyncio.sleep(8)
    subprocess.run(f"adb shell input tap {ADB_CONF['new_sign']}", shell=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")