from flask import Flask, request, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import random
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
app = Flask(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")
app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Используйте /pay, чтобы оплатить генерацию случайного числа."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    payment_url = f"https://oplata-bot.onrender.com/payment.html?chat_id={chat_id}"
    keyboard = [[InlineKeyboardButton("Оплатить", url=payment_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите кнопку для оплаты генерации случайного числа:",
        reply_markup=reply_markup
    )

app_telegram.add_handler(CommandHandler("start", start))
app_telegram.add_handler(CommandHandler("pay", pay))

@app.route('/')
def health_check():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
async def webhook():
    update = Update.de_json(request.get_json(force=True), app_telegram.bot)
    await app_telegram.process_update(update)
    return "OK", 200

@app.route('/callback', methods=['POST'])
async def callback():
    token = request.form.get('token')
    chat_id = request.form.get('custom')
    print(f"Callback received: {request.form}")
    if token and chat_id:
        response = requests.get(f"https://faucetpay.io/merchant/get-payment/{token}")
        payment_info = response.json()
        print(f"Payment info: {payment_info}")
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
    return "Error", 400

@app.route('/success')
def success():
    return "Payment successful! Return to Telegram."

@app.route('/cancel')
def cancel():
    return "Payment cancelled. Return to Telegram."

@app.route('/payment.html')
def payment():
    return send_file('static/payment.html')

if __name__ == '__main__':
    asyncio.run(app_telegram.initialize())
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
