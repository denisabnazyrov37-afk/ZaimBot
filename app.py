import os
import sqlite3
import hashlib
import hmac
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MINI_APP_URL = os.getenv("MINI_APP_URL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-this-password")
PORT = int(os.getenv("PORT", "8000"))
DB_PATH = os.path.join(os.path.dirname(__file__), "loan.db")

app = Flask(__name__, template_folder="templates", static_folder="static")


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


def telegram_user_from_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None

    params = {}
    for item in init_data.split("&"):
        if "=" in item:
            k, v = item.split("=", 1)
            params[k] = v

    received_hash = params.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(
        f"{k}={params[k]}" for k in sorted(params)
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    try:
        import urllib.parse
        raw_user = urllib.parse.unquote(params.get("user", ""))
        return json.loads(raw_user)
    except Exception:
        return None


def get_auth_user():
    return telegram_user_from_init_data(
        request.headers.get("X-Telegram-Init-Data", "")
    )


def admin_ok():
    return request.headers.get("X-Admin-Password", "") == ADMIN_PASSWORD


@app.get("/")
def index():
    return render_template("index.html", mini_app_url=MINI_APP_URL)


@app.get("/admin")
def admin():
    return render_template("admin.html")


@app.post("/api/application")
def create_application():
    user = get_auth_user()

    # Для локального браузерного теста разрешаем DEMO_USER.
    if not user:
        user = {"id": "DEMO_USER", "username": "demo"}

    data = request.get_json(force=True)

    required = [
        "firstName", "lastName", "phone", "amount",
        "termDays", "bank", "account", "recipientName"
    ]

    missing = [x for x in required if not data.get(x)]
    if missing:
        return jsonify({
            "error": "Не заполнены обязательные поля",
            "fields": missing
        }), 400

    now = datetime.now(timezone.utc).isoformat()

    conn = db()
    cur = conn.execute("""
        INSERT INTO applications (
            telegram_user_id, username, first_name, last_name, patronymic,
            phone, birth_date, address, amount, term_days,
            bank, account, bik, recipient_name, status, created_at, updated_at
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

    app_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "applicationId": app_id})


@app.get("/api/my-applications")
def my_applications():
    user = get_auth_user()
    user_id = str(user["id"]) if user else "DEMO_USER"

    conn = db()
    rows = conn.execute("""
        SELECT * FROM applications
        WHERE telegram_user_id=?
        ORDER BY id DESC
    """, (user_id,)).fetchall()
    conn.close()

    return jsonify({"applications": [dict(x) for x in rows]})


@app.get("/api/admin/applications")
def admin_applications():
    if not admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    conn = db()
    rows = conn.execute(
        "SELECT * FROM applications ORDER BY id DESC"
    ).fetchall()
    conn.close()

    return jsonify({"applications": [dict(x) for x in rows]})


@app.post("/api/admin/applications/<int:app_id>/status")
def change_status(app_id):
    if not admin_ok():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True)
    status = data.get("status")

    if status not in {"approved", "rejected", "paid"}:
        return jsonify({"error": "Invalid status"}), 400

    now = datetime.now(timezone.utc).isoformat()

    conn = db()
    cur = conn.execute("""
        UPDATE applications
        SET status=?, updated_at=?
        WHERE id=?
    """, (status, now, app_id))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Заявка не найдена"}), 404

    return jsonify({"ok": True})


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Нажмите /start и выберите нужное действие."
    )


def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Заполните .env"
        )

    if not MINI_APP_URL:
        raise RuntimeError(
            "MINI_APP_URL не задан. Заполните .env"
        )

    import threading

    def flask_thread():
        app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False
        )

    threading.Thread(
        target=flask_thread,
        daemon=True
    ).start()

    bot = Application.builder().token(BOT_TOKEN).build()

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("help", help_command))

    print("🤖 Telegram-бот запущен")
    print(f"🌐 Web server: http://127.0.0.1:{PORT}")
    print(f"🖥️ Admin: http://127.0.0.1:{PORT}/admin")

    bot.run_polling()


if __name__ == "__main__":
    init_db()
    run_bot()
