from fastapi import FastAPI, Request, Form, HTTPException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import httpx
import logging
import os
import sqlite3

app = FastAPI()

# Настройка переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")

# Проверка переменных окружения
if not all([TELEGRAM_TOKEN, WEBHOOK_URL, MERCHANT_USERNAME]):
    missing = [var for var, val in [
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("WEBHOOK_URL", WEBHOOK_URL),
        ("MERCHANT_USERNAME", MERCHANT_USERNAME),
    ] if not val]
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Telegram-бота
telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Инициализация SQLite
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS paid_users (user_id INTEGER PRIMARY KEY, paid BOOLEAN)")
    conn.commit()
    conn.close()

def mark_user_paid(user_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO paid_users (user_id, paid) VALUES (?, ?)", (user_id, True))
    conn.commit()
    conn.close()

def is_user_paid(user_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT paid FROM paid_users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result and result[0]

# События запуска и остановки
@app.on_event("startup")
async def on_startup():
    try:
        init_db()
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        logger.info(f"Bot started and webhook set to {WEBHOOK_URL}/webhook")
    except Exception as e:
        logger.error(f"Failed to start bot or set webhook: {str(e)}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.stop()

# Маршруты
@app.get("/")
async def root():
    return {"message": "Bot is running"}

@app.get("/success")
async def success():
    return {"message": "Payment successful! Return to Telegram."}

@app.get("/cancel")
async def cancel():
    return {"message": "Payment cancelled. Return to Telegram."}

@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await telegram_app.process_update(Update.de_json(update, telegram_app.bot))
    return {"ok": True}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Оплатить через FaucetPay", callback_data="pay")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Оплатите, чтобы разблокировать функции.",
        reply_markup=reply_markup,
    )

# Команда /random
async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_paid(user_id):
        await update.message.reply_text("Пожалуйста, оплатите, чтобы использовать /random.")
        return
    import random
    number = random.randint(1, 100)
    await update.message.reply_text(f"Ваше случайное число: {number}")

# Обработка кнопки оплаты
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "pay":
        user_id = query.from_user.id
        logger.info(f"Processing payment request for user_id: {user_id}")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://faucetpay.io/merchant/webscr",
                    data={
                        "merchant_username": MERCHANT_USERNAME,
                        "item_description": "Доступ к генератору случайных чисел",
                        "amount1": "0.0005",
                        "currency1": "BTC",
                        "currency2": "",
                        "custom": str(user_id),
                        "callback_url": f"{WEBHOOK_URL}/faucetpay_ipn",
                        "success_url": f"{WEBHOOK_URL}/success",
                        "cancel_url": f"{WEBHOOK_URL}/cancel",
                    },
                )
                try:
                    data = resp.json()
                    logger.info(f"FaucetPay response: {data}")
                    if data.get("status") == 200 and data.get("data", {}).get("link"):
                        payment_url = data["data"]["link"]
                    else:
                        logger.error(f"FaucetPay error: {data.get('message', 'Unknown error')}")
                        await query.edit_message_text("❌ Ошибка при создании платежа.")
                        return
                except ValueError:
                    payment_url = str(resp.url)  # Редирект на страницу оплаты
                await query.edit_message_text(
                    f"✅ Ссылка для оплаты создана!\n\n👉 <a href='{payment_url}'>Перейдите сюда для оплаты</a>",
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"Error creating payment for user_id {user_id}: {str(e)}")
            await query.edit_message_text("❌ Ошибка сервера при создании платежа.")

# Обработка IPN Callback
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
    logger.info(f"FaucetPay IPN received: merchant_username={merchant_username}, custom={custom}, status={status}")
    if merchant_username != MERCHANT_USERNAME:
        logger.warning(f"Invalid merchant_username: {merchant_username}")
        raise HTTPException(status_code=400, detail="Invalid merchant_username")
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://faucetpay.io/merchant/get-payment/{token}")
        token_data = resp.json()
        logger.info(f"Token validation response: {token_data}")
        if not token_data.get("valid", False):
            logger.warning("Invalid token")
            raise HTTPException(status_code=400, detail="Invalid token")
    
    if status.lower() != "completed":
        logger.warning(f"Payment not completed: status={status}")
        return {"status": "ok"}

    try:
        user_id = int(custom)
        mark_user_paid(user_id)
        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=f"✅ Оплата {amount1} {currency1} получена!\n\nТеперь доступен /random 🎲",
        )
        logger.info(f"User {user_id} marked as paid")
    except ValueError:
        logger.error(f"Invalid custom field: {custom}")
        raise HTTPException(status_code=400, detail="Invalid user_id")
    except Exception as e:
        logger.error(f"Error processing IPN for user_id {custom}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "ok"}

# Регистрация обработчиков
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

