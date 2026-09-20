import os
import sqlite3
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler

load_dotenv()

BOT_TOKEN = os.getenv("8972994110:AAEnae91uH3w57YZnqLvpU-LLe2SkyBsRCM", "").strip()
MINI_APP_URL = os.getenv("https://zaimbot-y3cs.onrender.com", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN123", "change-this-password")
PORT = int(os.getenv("PORT", "10000"))

DB_PATH = os.path.join(os.path.dirname(__file__), "loan.db")

app = Flask(__name__, template_folder="templates", static_folder="static")

telegram_app = None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_user_id TEXT NOT NULL,
        username TEXT DEFAULT '',
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        patronymic TEXT DEFAULT '',
        phone TEXT NOT NULL,
        birth_date TEXT DEFAULT '',
        address TEXT DEFAULT '',
        amount INTEGER NOT NULL,
        term_days INTEGER NOT NULL,
        bank TEXT NOT NULL,
        account TEXT NOT NULL,
        bik TEXT DEFAULT '',
        recipient_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()


def telegram_user_from_init_data(init_data):
    if not init_data or not BOT_TOKEN:
        return None

    params = {}
    for item in init_data.split("&"):
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value

    received_hash = params.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(
        f"{key}={params[key]}"
        for key in sorted(params)
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated = hmac.new(
        secret_key,
        check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        return None

    try:
        raw_user = urllib.parse.unquote(params.get("user", ""))
        return json.loads(raw_user)
    except Exception:
        return None


def current_user():
    return telegram_user_from_init_data(
        request.headers.get("X-Telegram-Init-Data", "")
    )


def admin_ok():
    return hmac.compare_digest(
        request.headers.get("X-Admin-Password", ""),
        ADMIN_PASSWORD
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/admin")
def admin():
    return render_template("admin.html")


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/setup-webhook")
def setup_webhook():
    if not BOT_TOKEN:
        return jsonify({"error": "BOT_TOKEN is not configured"}), 500

    if not MINI_APP_URL.startswith("https://"):
        return jsonify({
            "error": "MINI_APP_URL must be an HTTPS Render URL"
        }), 400

    import asyncio

    async def set_hook():
        tg = Application.builder().token(BOT_TOKEN).build()
        await tg.bot.set_webhook(
            url=f"{MINI_APP_URL.rstrip('/')}/telegram/webhook",
            allowed_updates=Update.ALL_TYPES
        )
        await tg.shutdown()

    asyncio.run(set_hook())

    return jsonify({
        "ok": True,
        "webhook": f"{MINI_APP_URL.rstrip('/')}/telegram/webhook"
    })


@app.post("/telegram/webhook")
def telegram_webhook():
    global telegram_app

    if telegram_app is None:
        return jsonify({"error": "Bot application is not initialized"}), 503

    update = Update.de_json(
        request.get_json(force=True),
        telegram_app.bot
    )

    import asyncio
    asyncio.run(telegram_app.process_update(update))

    return "OK"


@app.post("/api/application")
def create_application():
    user = current_user()

    # Разрешаем браузерный DEMO-режим, чтобы интерфейс можно было проверить
    # без запуска Telegram. В реальном production его следует убрать.
    if not user:
        user = {
            "id": "DEMO_USER",
            "username": "demo"
        }

    data = request.get_json(force=True)

    required = [
        "firstName", "lastName", "phone",
        "amount", "termDays", "bank",
        "account", "recipientName"
    ]

    missing = [field for field in required if not data.get(field)]

    if missing:
        return jsonify({
            "error": "Заполните обязательные поля",
            "fields": missing
        }), 400

    now = datetime.now(timezone.utc).isoformat()

    conn = db()

    cursor = conn.execute("""
        INSERT INTO applications (
            telegram_user_id, username,
            first_name, last_name, patronymic,
            phone, birth_date, address,
            amount, term_days,
            bank, account, bik, recipient_name,
            status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    """, (
        str(user["id"]),
        user.get("username", ""),
        data["firstName"],
        data["lastName"],
        data.get("patronymic", ""),
        data["phone"],
        data.get("birthDate", ""),
        data.get("address", ""),
        int(data["amount"]),
        int(data["termDays"]),
        data["bank"],
        data["account"],
        data.get("bik", ""),
        data["recipientName"],
        now,
        now
    ))

    application_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "applicationId": application_id
    })


@app.get("/api/my-applications")
def my_applications():
    user = current_user()
    user_id = str(user["id"]) if user else "DEMO_USER"

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM applications
        WHERE telegram_user_id=?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    conn.close()

    return jsonify({
        "applications": [dict(row) for row in rows]
    })


@app.get("/api/admin/applications")
def admin_applications():
    if not admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    conn = db()
    rows = conn.execute(
        "SELECT * FROM applications ORDER BY id DESC"
    ).fetchall()
    conn.close()

    return jsonify({
        "applications": [dict(row) for row in rows]
    })


@app.post("/api/admin/applications/<int:application_id>/status")
def change_status(application_id):
    if not admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    status = data.get("status")

    if status not in {
        "approved",
        "rejected",
        "paid"
    }:
        return jsonify({"error": "Invalid status"}), 400

    now = datetime.now(timezone.utc).isoformat()

    conn = db()

    cursor = conn.execute("""
        UPDATE applications
        SET status=?, updated_at=?
        WHERE id=?
    """, (
        status,
        now,
        application_id
    ))

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Заявка не найдена"}), 404

    return jsonify({"ok": True})


async def start(update, context):
    text = (
        "👋 Добро пожаловать!\n\n"
        "Здесь можно заполнить заявку и отслеживать её статус.\n\n"
        "⚠️ Демонстрационный прототип."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📝 Получить займ",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ],
        [
            InlineKeyboardButton(
                "👤 Личный кабинет",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update, context):
    await update.message.reply_text(
        "Нажмите /start и выберите действие."
    )


def create_telegram_application():
    global telegram_app

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")

    if not MINI_APP_URL:
        raise RuntimeError("MINI_APP_URL не задан")

    telegram_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CommandHandler("help", help_command)
    )

    return telegram_app


# Инициализация при импорте Gunicorn.
init_db()

if BOT_TOKEN and MINI_APP_URL:
    try:
        create_telegram_application()
        print("Telegram application initialized")
    except Exception as exc:
        print("Telegram initialization warning:", exc)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
