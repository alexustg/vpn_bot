import asyncio
import os
import logging
from datetime import datetime, timedelta

import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
YUMONEY_PHONE = os.getenv("YUMONEY_PHONE", "79139571457")

from aiogram.client.session.aiohttp import AiohttpSession
session = AiohttpSession(timeout=60.0)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"), session=session)
dp = Dispatcher()

DB_PATH = "bot.db"

# ---------- Тарифы ----------
TARIFFS = {
    "1m":  {"title": "1 месяц",    "price_rub": 150, "days": 30},
    "3m":  {"title": "3 месяца",   "price_rub": 400, "days": 90},
    "6m":  {"title": "6 месяцев",  "price_rub": 750, "days": 180},
}

# ---------- База ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER,
            tariff TEXT,
            expires_at TEXT,
            vpn_key TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        await db.commit()

async def save_user(tg_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username) VALUES (?, ?)",
            (tg_id, username)
        )
        await db.commit()

async def add_subscription(tg_id: int, tariff: str, days: int):
    expires = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO subscriptions (tg_id, tariff, expires_at) VALUES (?, ?, ?)",
            (tg_id, tariff, expires)
        )
        await db.commit()
    return expires

async def set_key(tg_id: int, vpn_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET vpn_key=? "
            "WHERE id = (SELECT id FROM subscriptions "
            "           WHERE tg_id=? AND vpn_key IS NULL "
            "           ORDER BY id DESC LIMIT 1)",
            (vpn_key, tg_id)
        )
        await db.commit()

async def get_last_sub(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vpn_key, expires_at FROM subscriptions "
            "WHERE tg_id=? ORDER BY id DESC LIMIT 1",
            (tg_id,)
        ) as cur:
            return await cur.fetchone()

# ---------- Клавиатуры ----------
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="mykeys")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="help")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
    ])

def tariffs_kb():
    buttons = [
        [InlineKeyboardButton(
            text=f"{t['title']} — {t['price_rub']} ₽",
            callback_data=f"tariff:{key}"
        )]
        for key, t in TARIFFS.items()
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def yumoney_kb(tariff_key: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"paid_ym:{tariff_key}"
        )],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_main")],
    ])

# ---------- Хэндлеры ----------
@dp.message(Command("start"))
async def cmd_start(m: Message):
    await save_user(m.from_user.id, m.from_user.username)
    await m.answer(
        "Привет! Это бот для покупки быстрого VPN 🚀\n"
        "Выбери действие в меню ниже.",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "back_main")
async def cb_back_main(c: CallbackQuery):
    await c.message.edit_text(
        "Главное меню. Выбери действие:",
        reply_markup=main_menu()
    )
    await c.answer()

@dp.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await c.message.answer(
        "📖 <b>Инструкция</b>\n\n"
        "1. Скачай приложение <b>Hiddify</b> (в Google Play или App Store).\n"
        "2. Скопируй свой ключ из «Мои ключи».\n"
        "3. В приложении Hiddify нажми «+» и выбери «Импорт из буфера обмена».\n"
        "4. Подключись и пользуйся."
    )
    await c.answer()

@dp.callback_query(F.data == "support")
async def cb_support(c: CallbackQuery):
    await c.message.answer("🆘 Напиши нам: @alexvpnsupportt")
    await c.answer()

@dp.callback_query(F.data == "buy")
async def cb_buy(c: CallbackQuery):
    await c.message.edit_text("Выбери тариф:", reply_markup=tariffs_kb())
    await c.answer()

@dp.callback_query(F.data.startswith("tariff:"))
async def cb_choose_tariff(c: CallbackQuery):
    key = c.data.split(":")[1]
    t = TARIFFS.get(key)
    if not t:
        await c.answer("Тариф не найден", show_alert=True)
        return

    await c.message.edit_text(
        f"💳 <b>Оплата на ЮMoney</b>\n\n"
        f"Тариф: <b>{t['title']}</b> — <b>{t['price_rub']} ₽</b>\n\n"
        f"Переведи сумму на номер:\n"
        f"<code>{YUMONEY_PHONE}</code>\n\n"
        f"📌 <b>Важно:</b> в комментарии к переводу обязательно укажи свой Telegram ID:\n"
        f"<code>{c.from_user.id}</code>\n\n"
        f"После перевода нажми «Я оплатил». Ключ выдаётся в течение 15–30 минут.",
        reply_markup=yumoney_kb(key)
    )
    await c.answer()

@dp.callback_query(F.data.startswith("paid_ym:"))
async def cb_paid_yumoney(c: CallbackQuery):
    key = c.data.split(":")[1]
    t = TARIFFS[key]

    expires = await add_subscription(c.from_user.id, key, t["days"])

    await c.message.edit_text(
        f"✅ Заявка принята!\n"
        f"Тариф: {t['title']}\n"
        f"Действует до: {expires}\n\n"
        f"После проверки оплаты ключ придёт сюда (обычно 15–30 минут).\n\n"
        f"⚠️ <b>Пока ждёшь, скачай приложение Hiddify</b> (в Google Play или App Store) — "
        f"оно понадобится для подключения VPN."
    )

    if ADMIN_ID:
        uname = f"@{c.from_user.username}" if c.from_user.username else "—"
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Заявка на оплату ЮMoney</b>\n"
            f"Пользователь: {uname} (id <code>{c.from_user.id}</code>)\n"
            f"Тариф: {t['title']} — {t['price_rub']} ₽\n\n"
            f"Проверь поступление на {YUMONEY_PHONE}.\n"
            f"Если деньги пришли — выдай ключ:\n"
            f"<code>/give {c.from_user.id} ТВОЙ_КЛЮЧ</code>"
        )
    await c.answer()

@dp.callback_query(F.data == "mykeys")
async def cb_mykeys(c: CallbackQuery):
    row = await get_last_sub(c.from_user.id)
    if not row:
        await c.message.answer("У тебя пока нет подписки. Нажми «Купить VPN».")
    else:
        vpn_key, expires = row
        if vpn_key:
            await c.message.answer(
                f"🔑 <b>Твой ключ</b>\n<code>{vpn_key}</code>\n\n"
                f"Действует до: {expires}\n\n"
                f"Как подключить: скопируй ключ, открой Hiddify, нажми «+» -> «Импорт из буфера»."
            )
        else:
            await c.message.answer(
                f"Подписка активна до {expires}, ключ ещё не выдан. "
                f"Обычно это до 30 минут."
            )
    await c.answer()

@dp.message(Command("give"))
async def cmd_give(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        await m.answer("Формат: /give <tg_id> <ключ>")
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        await m.answer("tg_id должен быть числом")
        return
    vpn_key = parts[2]
    await set_key(tg_id, vpn_key)
    await bot.send_message(
        tg_id,
        f"🔑 <b>Твой ключ готов!</b>\n<code>{vpn_key}</code>\n\n"
        f"Инструкция по подключению — в меню «Инструкция»."
    )
    await m.answer("Ключ выдан ✅")

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("Бот запущен. Ctrl+C для остановки.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
