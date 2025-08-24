from fastapi import FastAPI, Request, Form, HTTPException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import httpx
import logging
import os
import sqlite3
import json

# === Настройка логирования: МАКСИМАЛЬНЫЙ уровень детализации ===
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s() | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("faucetpay-bot")

# === Переменные окружения ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
MERCHANT_USERNAME = os.getenv("MERCHANT_USERNAME")

if not TELEGRAM_TOKEN:
    logger.critical("❌ ОШИБКА: Не задан TELEGRAM_TOKEN")
    raise ValueError("TELEGRAM_TOKEN не найден в переменных окружения")
if not WEBHOOK_URL:
    logger.critical("❌ ОШИБКА: Не задан WEBHOOK_URL")
    raise ValueError("WEBHOOK_URL не найден в переменных окружения")
if not MERCHANT_USERNAME:
    logger.critical("❌ ОШИБКА: Не задан MERCHANT_USERNAME")
    raise ValueError("MERCHANT_USERNAME не найден в переменных окружения")

logger.info(f"✅ Переменные окружения загружены. MERCHANT_USERNAME={MERCHANT_USERNAME}")

# === Инициализация Telegram-бота ===
try:
    telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    logger.info("✅ Telegram-бот инициализирован")
except Exception as e:
    logger.critical(f"❌ Ошибка инициализации бота: {e}")
    raise

# === База данных SQLite ===
def init_db():
    try:
        with sqlite3.connect("users.db") as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS paid_users (user_id INTEGER PRIMARY KEY, paid_at TEXT DEFAULT (datetime('now')))")
            conn.commit()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации БД: {e}")

def mark_user_paid(user_id: int):
    try:
        with sqlite3.connect("users.db") as conn:
            conn.execute("INSERT OR IGNORE INTO paid_users (user_id) VALUES (?)", (user_id,))
            conn.commit()
        logger.info(f"✅ Пользователь {user_id} помечен как оплативший")
    except Exception as e:
        logger.error(f"❌ Ошибка при записи в БД для user_id={user_id}: {e}")

def is_user_paid(user_id: int) -> bool:
    try:
        with sqlite3.connect("users.db") as conn:
            cursor = conn.execute("SELECT 1 FROM paid_users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
        logger.debug(f"🔍 Проверка оплаты для user_id={user_id}: {'оплатил' if result else 'не оплатил'}")
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке оплаты user_id={user_id}: {e}")
        return False

# === FastAPI приложение ===
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Запуск бота...")
    init_db()
    try:
        await telegram_app.initialize()
        await telegram_app.start()
        webhook_url = f"{WEBHOOK_URL}/webhook"
        await telegram_app.bot.set_webhook(webhook_url)
        logger.info(f"✅ Вебхук установлен: {webhook_url}")
    except Exception as e:
        logger.critical(f"❌ Ошибка при запуске бота или установке вебхука: {e}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("🛑 Остановка бота...")
    await telegram_app.stop()

# === Маршруты ===
@app.get("/")
async def root():
    logger.debug("🌐 GET / — проверка работоспособности")
    return {"status": "running", "message": "Bot is online"}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        json_data = await request.json()
        logger.info(f"📥 ПОЛУЧЕН ВЕБХУК: {json.dumps(json_data, ensure_ascii=False, indent=2)}")
        update = Update.de_json(json_data, telegram_app.bot)
        await telegram_app.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ ОШИБКА обработки вебхука: {e}")
        return {"ok": False}

# === Команда /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"👤 Пользователь {update.effective_user.id} ({update.effective_user.full_name}) вызвал /start")
    keyboard = [[InlineKeyboardButton("💳 Оплатить 0.0005 BTC", callback_data="pay")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Нажмите кнопку ниже, чтобы получить доступ к /random.",
        reply_markup=reply_markup
    )
    logger.debug("📤 Отправлена кнопка оплаты")

# === Команда /random ===
async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"🎲 Пользователь {user_id} запросил /random")
    if not is_user_paid(user_id):
        logger.warning(f"🔒 Пользователь {user_id} не оплатил — доступ запрещён")
        await update.message.reply_text("🔒 Сначала оплатите через кнопку /start")
        return
    import random
    number = random.randint(1, 100)
    await update.message.reply_text(f"🎉 Ваше число: {number}")
    logger.info(f"✅ Выдано число {number} для user_id={user_id}")

# === Обработка кнопки оплаты ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.full_name
    logger.info(f"🖱️ Пользователь {user_id} ({username}) нажал кнопку: {query.data}")

    if query.data != "pay":
        logger.warning(f"⚠️ Неизвестная кнопка: {query.data}")
        await query.message.reply_text("❌ Неизвестная команда")
        return

    logger.info(f"💸 Формирование платежа для user_id={user_id}")
    try:
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
        logger.debug(f"📤 Отправка данных платежа: {payment_data}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.post(
                "https://faucetpay.io/merchant/webscr",
                data=payment_data
            )
            logger.info(f"🏦 Ответ от FaucetPay: статус={resp.status_code}")
            logger.debug(f"📥 Тело ответа: {resp.text[:500]}...")

            if resp.status_code != 200:
                logger.error(f"❌ FaucetPay вернул статус {resp.status_code}")
                await query.edit_message_text("❌ Ошибка: не удалось создать платёж. Попробуйте позже.")
                return

            payment_url = str(resp.url)
            logger.info(f"✅ Ссылка на оплату создана: {payment_url}")

            try:
                await query.edit_message_text(
                    f"✅ Перейдите для оплаты:\n\n👉 <a href='{payment_url}'>Оплатить</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=False
                )
                logger.info(f"📤 Ссылка отправлена пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Не удалось обновить сообщение: {e}")
                await query.message.reply_text(
                    f"✅ Ссылка для оплаты:\n\n👉 <a href='{payment_url}'>Оплатить</a>",
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.critical(f"💥 ФАТАЛЬНАЯ ОШИБКА при создании платежа для user_id={user_id}: {type(e).__name__}: {e}")
        try:
            await query.message.reply_text("❌ Серверная ошибка. Попробуйте позже.")
        except:
            pass

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
    logger.info(f"🔔 ПОЛУЧЕН IPN: token={token}, custom={custom}, status={status}, amount={amount1} {currency1}")
    logger.debug(f"📋 Все данные IPN: merchant={merchant_username}, txid={transaction_id}")

    # Проверка мерчанта
    if merchant_username != MERCHANT_USERNAME:
        logger.error(f"❌ IPN: Неверный мерчант: {merchant_username}")
        raise HTTPException(status_code=400, detail="Invalid merchant")

    # Проверка токена
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_check_url = f"https://faucetpay.io/merchant/get-payment/{token}"
            logger.debug(f"🔍 Проверка токена: GET {token_check_url}")
            resp = await client.get(token_check_url)
            logger.debug(f"📥 Ответ на проверку токена: {resp.text}")
            token_data = resp.json()
            if not token_data.get("valid", False):
                logger.error(f"❌ Недействительный токен: {token}")
                raise HTTPException(status_code=400, detail="Invalid token")
            logger.info("✅ Токен подтверждён")
    except Exception as e:
        logger.critical(f"💥 Ошибка проверки токена: {e}")
        raise HTTPException(status_code=400, detail="Token check failed")

    # Проверка статуса
    if status.lower() != "completed":
        logger.warning(f"⚠️ Платёж не завершён: статус={status}")
        return {"status": "ok"}

    # Обработка оплаты
    try:
        user_id = int(custom)
        logger.info(f"💰 Подтверждён платёж для user_id={user_id}")
        mark_user_paid(user_id)
        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=f"✅ Оплата {amount1} {currency1} прошла!\n\nТеперь доступен /random 🎲",
            disable_notification=True
        )
        logger.info(f"✅ Уведомление отправлено пользователю {user_id}")
    except ValueError:
        logger.error(f"❌ IPN: Неверный custom ID: {custom}")
        raise HTTPException(status_code=400, detail="Invalid user_id")
    except Exception as e:
        logger.critical(f"💥 Ошибка при отправке сообщения: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

    return {"status": "ok"}

# === Регистрация обработчиков ===
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("random", random_number))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

# === Запуск (для локального теста) ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
