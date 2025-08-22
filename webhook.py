import logging
import os
import random
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Defaults
from telegram.constants import ParseMode

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("bot")

# Переменные окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # например https://имя.onrender.com
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")  # твой FaucetPay merchant tag

# Создаём приложение FastAPI
app = FastAPI()

# Telegram Application
telegram_app = (
    ApplicationBuilder()
    .token(TELEGRAM_TOKEN)
    .defaults(Defaults(parse_mode=ParseMode.HTML))
    .build()
)

# Простая память оплативших (id -> True)
paid_users = {}


# ----------------- Команды -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Это бот с функцией генерации случайного числа 🎲\n\n"
        "Чтобы пользоваться генератором, нужно сначала оплатить доступ через FaucetPay.\n\n"
        f"👉 Отправь оплату на мерчант-аккаунт: <b>{MERCHANT_USERNAME}</b>\n\n"
        "После этого введи команду /confirm, чтобы подтвердить оплату."
    )
    await update.message.reply_text(text)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фиктивное подтверждение оплаты (на деле здесь надо интегрировать FaucetPay API)."""
    user_id = update.effective_user.id
    paid_users[user_id] = True
    await update.message.reply_text("✅ Оплата подтверждена! Теперь можешь пользоваться /random и /coinflip.")


async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация случайного числа доступна только оплатившим."""
    user_id = update.effective_user.id
    if paid_users.get(user_id):
        number = random.randint(1, 100)
        await update.message.reply_text(f"🎲 Твоё случайное число: <b>{number}</b>")
    else:
        await update.message.reply_text("🚫 Доступ закрыт. Сначала оплати через FaucetPay командой /start.")


async def coinflip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подбрасывание монетки (бесплатная фича)."""
    result = random.choice(["Орел 🦅", "Решка 👑"])
    await update.message.reply_text(f"🪙 Монетка показала: {result}")


# ----------------- Роуты бота -----------------
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("confirm", confirm))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CommandHandler("coinflip", coinflip))


# ----------------- Webhook -----------------
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


# ----------------- Startup -----------------
@app.on_event("startup")
async def on_startup():
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await telegram_app.bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")
    await telegram_app.initialize()
    await telegram_app.start()


@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.stop()
    await telegram_app.shutdown()
