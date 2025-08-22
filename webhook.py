import os
import logging
import random
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# ========= CONFIG ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME", "merchant_default")
PORT = int(os.getenv("PORT", 5000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========= TELEGRAM APP ==========
app_telegram: Application | None = None


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Хэндлер /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот.\n"
        "Хочешь случайное число? Используй команду /pay."
    )


async def pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Хэндлер /pay — отдаём ссылку на HTML форму оплаты"""
    chat_id = update.effective_chat.id
    payment_url = f"https://random-number-bot-1.onrender.com/payment?chat_id={chat_id}"
    await update.message.reply_text(
        f"Для генерации случайного числа перейди по ссылке и оплати:\n\n{payment_url}"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просто пример — позже тут можно отдать статус или что-то еще"""
    await update.message.reply_text("✅ Оплата подтверждена! Сейчас сгенерируем число...")


# ========= FASTAPI ==========
app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """Инициализация Telegram application при старте FastAPI."""
    global app_telegram

    logger.info("Initializing Telegram Bot Application...")
    app_telegram = (
        Application.builder()
        .token(TOKEN)
        .parse_mode(ParseMode.HTML)
        .concurrent_updates(True)
        .build()
    )

    # === Регистрируем хэндлеры ===
    app_telegram.add_handler(CommandHandler("start", start_handler))
    app_telegram.add_handler(CommandHandler("pay", pay_handler))

    await app_telegram.initialize()
    logger.info("Telegram Bot initialized ✅")


class TelegramRequest(BaseModel):
    update_id: int | None = None  # dummy поле для валидации


@app.post("/webhook")
async def telegram_webhook(req: Request):
    """Обработка апдейтов от Telegram"""
    try:
        data = await req.json()
        logger.debug(f"Webhook payload: {data}")
        update = Update.de_json(data, app_telegram.bot)
        if update:
            await app_telegram.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        return {"status": "error", "detail": str(e)}


@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h3>Bot is alive 🚀</h3>"


@app.get("/payment")
async def get_payment_page(chat_id: str):
    """Отдаём твою HTML форму оплаты, в custom вставим chat_id"""
    # Просто возвращаем файл, script внутри сам подставит `chat_id`
    return FileResponse("payment.html")


@app.post("/callback")
async def payment_callback(req: Request):
    """
    Callback от FaucetPay после успешного платежа.
    В req.json/req.form должны прийти данные, включая custom (chat_id).
    """
    try:
        form = await req.form()
    except:
        form = {}

    chat_id = form.get("custom")
    status = form.get("status")  # у FaucetPay другое название может быть

    logger.info(f"Payment callback received: {form}")

    if chat_id:
        try:
            random_number = random.randint(1, 1000)
            text = f"💰 Платёж получен!\nТвоё случайное число: <b>{random_number}</b>"
            await app_telegram.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка при попытке ответа пользователю: {e}")

    return {"status": "ok"}


@app.get("/success")
async def success_page():
    return HTMLResponse("<h2>✅ Успешная оплата! Возвращайся в Telegram Бот</h2>")


@app.get("/cancel")
async def cancel_page():
    return HTMLResponse("<h2>❌ Платёж отменён!</h2>")
