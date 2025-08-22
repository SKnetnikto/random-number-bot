from flask import Flask, request, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import random
import os
from dotenv import load_dotenv
import asyncio
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')  # Логи будут записываться в файл app.log
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")
PORT = int(os.getenv("PORT", 5000))

logger.info(f"TELEGRAM_TOKEN: {'Set' if TELEGRAM_TOKEN else 'Not set'}")
logger.info(f"MERCHANT_USERNAME: {'Set' if MERCHANT_USERNAME else 'Not set'}")
logger.info(f"Starting application on port {PORT}")

try:
    app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()
    logger.info("Application initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Application: {str(e)}")
    raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processing /start command for chat_id: {update.message.chat_id}")
    await update.message.reply_text(
        "Добро пожаловать! Используйте /pay, чтобы оплатить генерацию случайного числа."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"Processing /pay command for chat_id: {chat_id}")
    payment_url = f"https://random-number-bot-1.onrender.com/payment.html?chat_id={chat_id}"
    keyboard = [[InlineKeyboardButton("Оплатить", url=payment_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите кнопку для оплаты генерации случайного числа:",
        reply_markup=reply_markup
    )

try:
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("pay", pay))
    logger.info("Command handlers added successfully")
except Exception as e:
    logger.error(f"Failed to add command handlers: {str(e)}")
    raise

@app.route('/')
def health_check():
    logger.info(f"Health check requested on port {PORT}")
    return "OK", 200

@app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        data = request.get_json(silent=True)
        logger.info(f"Webhook received: {data}")
        if not data:
            logger.warning("Received empty or invalid JSON data")
            return "Invalid JSON", 400
        update = Update.de_json(data, app_telegram.bot)
        if update:
            logger.info(f"Processing update: {update.to_dict()}")
            await app_telegram.process_update(update)
            logger.info("Update processed successfully")
        else:
            logger.warning("No update object created from webhook data")
            return "No update", 400
        return "OK", 200
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        return "Error", 500

@app.route('/callback', methods=['POST'])
async def callback():
    try:
        logger.info(f"Callback received: {request.form.to_dict()}")
        token = request.form.get('token')
        chat_id = request.form.get('custom')
        if token and chat_id:
            response = requests.get(f"https://faucetpay.io/merchant/get-payment/{token}")
            payment_info = response.json()
            logger.info(f"Payment info: {payment_info}")
            if payment_info.get('valid') and payment_info['merchant_username'] == MERCHANT_USERNAME:
                random_number = random.randint(1, 100)
                await app_telegram.bot.send_message(
                    chat_id=chat_id,
                    text=f"Платёж получен! Случайное число: {random_number}"
                )
                return "OK", 200
            else:
                await app_telegram.bot.send_message(
                    chat_id=chat_id,
                    text="Ошибка: Платёж не подтверждён или неверный merchant_username."
                )
                return "Invalid", 400
        logger.warning("Missing token or chat_id in callback")
        return "Error", 400
    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        return "Error", 500

@app.route('/success')
def success():
    logger.info(f"Success route accessed on port {PORT}")
    return "Payment successful! Return to Telegram."

@app.route('/cancel')
def cancel():
    logger.info(f"Cancel route accessed on port {PORT}")
    return "Payment cancelled. Return to Telegram."

@app.route('/payment.html')
def payment():
    logger.info(f"Payment.html route accessed on port {PORT}")
    return send_file('static/payment.html')

if __name__ == '__main__':
    logger.info(f"Starting Flask on port {PORT}")
    try:
        asyncio.run(app_telegram.initialize())
        logger.info("Application initialized for local run")
        app.run(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Failed to start Flask: {str(e)}")
        raise
