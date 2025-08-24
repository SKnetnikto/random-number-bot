import logging
import os
import random
import httpx
from fastapi import FastAPI, Request, Form, HTTPException
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, Defaults
from telegram.constants import ParseMode

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("bot")

# Проверка переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://random-number-bot-1.onrender.com
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")
API_KEY = os.getenv("FAUCETPAY_API_KEY")

if not all([TELEGRAM_TOKEN, WEBHOOK_URL, MERCHANT_USERNAME, API_KEY]):
    missing = [var for var, val in [
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("WEBHOOK_URL", WEBHOOK_URL),
        ("MERCHANT_USERNAME", MERCHANT_USERNAME),
        ("API_KEY", API_KEY)
    ] if not val]
    logger.error(f"Missing environment variables: {', '.join(missing)}")
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# FastAPI app
app = FastAPI()

# Telegram Application
defaults = Defaults(parse_mode=ParseMode.HTML)
telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).defaults(defaults).build()

# Простая память пользователей (id -> True если оплатил)
paid_users = {}

# ---------- Команды ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processing /start command for chat_id: {update.effective_user.id}")
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
        logger.info(f"Processing payment request for user_id: {user_id}")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://faucetpay.io/merchant/create-payment",
                    data={
                        "merchant_username": MERCHANT_USERNAME,
                        "item_description": "Доступ к генератору случайных чисел",
                        "amount1": "0.0005",
                        "currency1": "BTC",
                        "custom": str(user_id),
                        "callback_url": f"{WEBHOOK_URL}/faucetpay_ipn",
                        "success_url": f"{WEBHOOK_URL}/success",
                        "cancel_url": f"{WEBHOOK_URL}/cancel",
                        "api_key": API_KEY,
                    },
                )
                data = resp.json()
                logger.info(f"FaucetPay response: {data}")
                if data.get("status") == 200 and data.get("data", {}).get("link"):
                    payment_url = data["data"]["link"]
                    await query.edit_message_text(
                        f"✅ Ссылка для оплаты создана!\n\n👉 <a href='{payment_url}'>Перейдите сюда для оплаты</a>",
                    )
                else:
                    logger.error(f"FaucetPay error: {data.get('message', 'Unknown error')}")
                    await query.edit_message_text("❌ Ошибка при создании платежа.")
        except Exception as e:
            logger.error(f"Error creating payment for user_id {user_id}: {str(e)}")
            await query.edit_message_text("❌ Ошибка сервера при создании платежа.")

async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Processing /random command for user_id: {user_id}")
    if paid_users.get(user_id):
        number = random.randint(1, 100)
        await update.message.reply_text(f"🎲 Твоё случайное число: <b>{number}</b>")
    else:
        await update.message.reply_text("🚫 Сначала оплатите доступ через /start.")

async def coinflip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processing /coinflip command for user_id: {update.effective_user.id}")
    result = random.choice(["Орел 🦅", "Решка 👑"])
    await update.message.reply_text(f"🪙 Монетка показала: {result}")

# ---------- Обработчики ----------
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CommandHandler("coinflip", coinflip))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

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
    logger.info(f"FaucetPay IPN received: merchant_username={merchant_username}, custom={custom}, status={status}")
    if merchant_username != MERCHANT_USERNAME:
        logger.warning(f"Invalid merchant_username: {merchant_username}")
        raise HTTPException(status_code=400, detail="Invalid merchant_username")
    if status.lower() != "completed":
        logger.warning(f"Payment not completed: status={status}")
        return {"status": "ok"}

    try:
        user_id = int(custom)
        paid_users[user_id] = True
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

# ---------- Webhook от Telegram ----------
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Webhook received: {data}")
        update = Update.de_json(data, telegram_app.bot)
        if update:
            await telegram_app.process_update(update)
            logger.info("Update processed successfully")
        else:
            logger.warning("Invalid update data")
            return {"ok": False}, 400
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        return {"ok": False}, 500

# ---------- Маршруты для FaucetPay ----------
@app.get("/success")
async def success():
    return {"message": "Payment successful! Return to Telegram."}

@app.get("/cancel")
async def cancel():
    return {"message": "Payment cancelled. Return to Telegram."}

@app.get("/")
async def root():
    return {"message": "Bot is running"}

# Startup / Shutdown
@app.on_event("startup")
async def on_startup():
    try:
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        logger.info(f"Bot started and webhook set to {WEBHOOK_URL}/webhook")
    except Exception as e:
        logger.error(f"Failed to start bot or set webhook: {str(e)}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Bot stopped and shutdown")
    except Exception as e:
        logger.error(f"Failed to stop bot: {str(e)}")
