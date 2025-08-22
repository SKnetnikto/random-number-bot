import logging
import os
import random
import httpx
from fastapi import FastAPI, Request, Form
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Defaults
from telegram.constants import ParseMode

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("bot")

# Переменные окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")
API_KEY = os.getenv("FAUCETPAY_API_KEY")  # создается в FaucetPay Merchant

# FastAPI app
app = FastAPI()

# Telegram Application
telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Простая память пользователей (id -> True если оплатил)
paid_users = {}


# ---------- Команды ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Это бот с генератором случайных чисел 🎲\n\n"
        "👉 Чтобы пользоваться генератором, оплатите доступ через FaucetPay.\n\n"
        "Нажмите кнопку ниже для оплаты."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 Оплатить через FaucetPay", callback_data="pay")]]
    )
    await update.message.reply_text(text, reply_markup=keyboard)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "pay":
        user_id = query.from_user.id

        # создаём платеж через FaucetPay Merchant
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://faucetpay.io/merchant/create-payment",
                data={
                    "merchant_username": MERCHANT_USERNAME,
                    "item_description": "Доступ к генератору случайных чисел",
                    "amount1": "0.0005",   # сумма (например BTC)
                    "currency1": "BTC",    # валюта, которую принимает продавец
                    "custom": str(user_id),  # передаем ID пользователя
                    "callback_url": f"{WEBHOOK_URL}/faucetpay_ipn",  # куда придет оплата
                    "success_url": f"{WEBHOOK_URL}/success",
                    "cancel_url": f"{WEBHOOK_URL}/cancel",
                    "api_key": API_KEY,
                },
            )
        
        data = resp.json()
        if data.get("status") == 200:
            payment_url = data["data"]["link"]
            await query.edit_message_text(
                f"✅ Ссылка для оплаты создана!\n\n👉 <a href='{payment_url}'>Перейдите сюда для оплаты</a>",
                parse_mode="HTML",
            )
        else:
            await query.edit_message_text("❌ Ошибка при создании платежа.")


async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if paid_users.get(user_id):
        number = random.randint(1, 100)
        await update.message.reply_text(f"🎲 Твоё случайное число: <b>{number}</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("🚫 Сначала оплатите доступ через /start.")


async def coinflip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(["Орел 🦅", "Решка 👑"])
    await update.message.reply_text(f"🪙 Монетка показала: {result}")


# ---------- Обработчики ----------
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CommandHandler("coinflip", coinflip))
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(button_handler)
)


# ---------- IPN от FaucetPay ----------
@app.post("/faucetpay_ipn")
async def faucetpay_ipn(
    merchant_username: str = Form(...),
    custom: str = Form(...),
    status: str = Form(...),
    transaction_id: str = Form(...),
    amount1: str = Form(...),
    currency1: str = Form(...),
):
    """
    Callback от FaucetPay после платежа.
    Custom = ID пользователя Telegram.
    Status = completed при успешной оплате.
    """
    if merchant_username == MERCHANT_USERNAME and status.lower() == "completed":
        try:
            user_id = int(custom)
            paid_users[user_id] = True
            # уведомим пользователя в телеге
            await telegram_app.bot.send_message(
                chat_id=user_id,
                text=f"✅ Оплата {amount1} {currency1} получена!\n\nТеперь доступен /random 🎲",
            )
        except Exception as e:
            logger.error(f"Ошибка IPN: {e}")

    return {"status": "ok"}


# ---------- Webhook от Telegram ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


# Startup / Shutdown
@app.on_event("startup")
async def on_startup():
    await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot started and webhook set.")


@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.stop()
    await telegram_app.shutdown()
