from fastapi import FastAPI, Request, Form, HTTPException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import httpx
import logging
import os
import sqlite3
import uvicorn

app = FastAPI()

# === Настройка логирования ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Переменные окружения (указываются в Render) ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")

if not all([TELEGRAM_TOKEN, WEBHOOK_URL, MERCHANT_USERNAME]):
    raise ValueError("Missing environment variables: TELEGRAM_TOKEN, WEBHOOK_URL, MERCHANT_USERNAME")

# === Инициализация Telegram-бота ===
telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# === База данных SQLite ===
def init_db():
    with sqlite3.connect("users.db") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS paid_users (user_id INTEGER PRIMARY KEY)")
        conn.commit()

def mark_user_paid(user_id: int):
    with sqlite3.connect("users.db") as conn:
        conn.execute("INSERT OR IGNORE INTO paid_users (user_id) VALUES (?)", (user_id,))
        conn.commit()

def is_user_paid(user_id: int) -> bool:
    with sqlite3.connect("users.db") as conn:
        cursor = conn.execute("SELECT 1 FROM paid_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

# === Запуск и остановка бота ===
@app.on_event("startup")
async def startup():
    init_db()
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    logger.info("Bot started, webhook set.")

@app.on_event("shutdown")
async def shutdown():
    await telegram_app.stop()

# === Маршруты ===
@app.get("/")
async def root():
    return {"status": "running"}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False}

# === Обработчики команд ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("💳 Оплатить 0.0005 BTC", callback_data="pay")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Нажмите кнопку ниже, чтобы получить доступ к /random.",
        reply_markup=reply_markup
    )

async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_paid(user_id):
        await update.message.reply_text("🔒 Сначала оплатите через кнопку /start")
        return
    import random
    number = random.randint(1, 100)
    await update.message.reply_text(f"🎉 Ваше число: {number}")

# === Обработка кнопки оплаты ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            payment_data = {
                "merchant_username": MERCHANT_USERNAME,
                "item_description": "Доступ к боту",
                "amount1": "0.0005",
                "currency1": "BTC",
                "currency2": "",
                "custom": str(user_id),
                "callback_url": f"{WEBHOOK_URL}/faucetpay_ipn",
                "success_url": f"{WEBHOOK_URL}/success",
                "cancel_url": f"{WEBHOOK_URL}/cancel",
            }

            resp = await client.post(
                "https://faucetpay.io/merchant/webscr",
                data=payment_data
            )

            payment_url = str(resp.url)

            await query.edit_message_text(
                f"✅ Оплатите:\n\n👉 <a href='{payment_url}'>Перейти к оплате</a>",
                parse_mode="HTML",
                disable_web_page_preview=False
            )
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await query.message.reply_text("❌ Ошибка при создании платежа. Попробуйте позже.")

# === Обработка IPN от FaucetPay ===
@app.post("/faucetpay_ipn")
async def faucetpay_ipn(
    token: str = Form(...),
    merchant_username: str = Form(...),
    custom: str = Form(...),
    status: str = Form(...),
    transaction_id: str = Form(...),
    amount1: str = Form(...),
    currency1: str = Form(...),
):
    logger.info(f"IPN received: {token=}, {custom=}, {status=}")

    if merchant_username != MERCHANT_USERNAME:
        raise HTTPException(status_code=400, detail="Invalid merchant")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"https://faucetpay.io/merchant/get-payment/{token}")
            token_data = resp.json()
            if not token_data.get("valid", False):
                raise HTTPException(status_code=400, detail="Invalid token")
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            raise HTTPException(status_code=400, detail="Token check failed")

    if status.lower() != "completed":
        return {"status": "ok"}

    try:
        user_id = int(custom)
        mark_user_paid(user_id)
        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=f"✅ Оплата {amount1} {currency1} прошла!\n\nТеперь доступен /random 🎲",
            disable_notification=True
        )
        logger.info(f"User {user_id} marked as paid")
    except ValueError:
        logger.error(f"Invalid custom ID: {custom}")
        raise HTTPException(status_code=400, detail="Invalid user ID")
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

    return {"status": "ok"}

# === Регистрация обработчиков ===
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

# === Запуск (для локального теста) ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
