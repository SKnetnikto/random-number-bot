import logging
import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Defaults
from telegram.constants import ParseMode

# Логирование, чтобы видеть логи в Render
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("webhook")

# Получаем токен бота и URL из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # типа https://myapp.onrender.com/webhook

# Создаём приложение FastAPI
app = FastAPI()

# Создаём Telegram Application (замена Updater в новой версии PTB)
telegram_app = (
    ApplicationBuilder()
    .token(TELEGRAM_TOKEN)
    .defaults(Defaults(parse_mode=ParseMode.HTML))
    .build()
)


# ----------------- Команды -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Бот на Render работает 🚀")


telegram_app.add_handler(CommandHandler("start", start))


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
    logger.info("Initializing Telegram Bot Application...")
    # Устанавливаем webhook у Telegram
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await telegram_app.bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")
    await telegram_app.initialize()
    await telegram_app.start()


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down Telegram Bot Application...")
    await telegram_app.stop()
    await telegram_app.shutdown()
