from flask import Flask, request, send_file
from telegram.ext import Application
import requests
import random
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Токен от @BotFather
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")  # karolev
app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

@app.route('/callback', methods=['POST'])
async def callback():
    token = request.form.get('token')
    chat_id = request.form.get('custom')
    if token and chat_id:
        response = requests.get(f"https://faucetpay.io/merchant/get-payment/{token}")
        payment_info = response.json()
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
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))