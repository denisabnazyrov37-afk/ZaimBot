
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH = Path(__file__).with_name("loan.db")
DOCUMENT_DIR = Path(__file__).with_name("case_files")

(
    FIRST_NAME, LAST_NAME, PATRONYMIC, PHONE, BIRTH_DATE, ADDRESS,
    PERSON_CONFIRM,
    PASSPORT_SERIES, PASSPORT_NUMBER, PASSPORT_DATE, PASSPORT_DEPARTMENT,
    PASSPORT_ISSUED_BY, REGISTRATION_ADDRESS,
    AMOUNT, TERM, BANK, ACCOUNT, BIK, RECIPIENT,
    PASSPORT_FRONT, PASSPORT_REGISTRATION, SELFIE,
    FINAL_CONFIRM
) = range(23)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    DOCUMENT_DIR.mkdir(exist_ok=True)
    conn = db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id TEXT PRIMARY KEY,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT ''
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT NOT NULL,
        username TEXT DEFAULT '',
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        patronymic TEXT DEFAULT '',
        phone TEXT NOT NULL,
        birth_date TEXT DEFAULT '',
        address TEXT DEFAULT '',
        passport_series TEXT NOT NULL,
        passport_number TEXT NOT NULL,
        passport_date TEXT NOT NULL,
        passport_department TEXT NOT NULL,
        passport_issued_by TEXT NOT NULL,
        registration_address TEXT NOT NULL,
        amount INTEGER NOT NULL,
        term_days INTEGER NOT NULL,
        bank TEXT NOT NULL,
        account TEXT NOT NULL,
        bik TEXT DEFAULT '',
        recipient_name TEXT NOT NULL,
        passport_front_file_id TEXT DEFAULT '',
        passport_registration_file_id TEXT DEFAULT '',
        selfie_file_id TEXT DEFAULT '',
        person_confirmed_at TEXT DEFAULT '',
        final_confirmed_at TEXT DEFAULT '',
        approved_at TEXT DEFAULT '',
        paid_at TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        actor_telegram_id TEXT NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL,
        details TEXT DEFAULT ''
    )
    """)

    conn.commit()
    conn.close()


def main_keyboard():
    return ReplyKeyboardMarkup(
        [["📝 Подать заявку"], ["📋 Мои заявки", "👤 Мой профиль"], ["ℹ️ Помощь"]],
        resize_keyboard=True
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)


def yes_no_keyboard(yes_text, no_text="✏️ Изменить данные"):
    return ReplyKeyboardMarkup(
        [[yes_text], [no_text], ["❌ Отмена"]],
        resize_keyboard=True
    )


def save_user(update):
    user = update.effective_user
    conn = db()
    conn.execute("""
    INSERT INTO users (telegram_id, username, first_name, last_name)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
        username=excluded.username,
        first_name=excluded.first_name,
        last_name=excluded.last_name
    """, (str(user.id), user.username or "", user.first_name or "", user.last_name or ""))
    conn.commit()
    conn.close()


def audit(application_id, actor_id, action, details=""):
    conn = db()
    conn.execute(
        "INSERT INTO audit_log(application_id, actor_telegram_id, action, created_at, details) VALUES (?, ?, ?, ?, ?)",
        (application_id, str(actor_id), action, now_iso(), details)
    )
    conn.commit()
    conn.close()


async def start(update, context):
    save_user(update)
    await update.message.reply_text(
        "👋 Добро пожаловать!\n\n"
        "Здесь заявка заполняется прямо в Telegram.\n"
        "После ввода личных данных будет отдельная кнопка подтверждения, "
        "а перед отправкой заявки — финальное подтверждение.",
        reply_markup=main_keyboard()
    )


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ Заполнение отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


async def begin_application(update, context):
    context.user_data.clear()
    await update.message.reply_text("📝 Заявка на займ\n\nВведите имя:", reply_markup=cancel_keyboard())
    return FIRST_NAME


async def first_name(update, context):
    context.user_data["first_name"] = update.message.text.strip()
    await update.message.reply_text("Введите фамилию:")
    return LAST_NAME


async def last_name(update, context):
    context.user_data["last_name"] = update.message.text.strip()
    await update.message.reply_text("Введите отчество или «-»:")
    return PATRONYMIC


async def patronymic(update, context):
    v = update.message.text.strip()
    context.user_data["patronymic"] = "" if v == "-" else v
    await update.message.reply_text(
        "📱 Отправьте номер телефона кнопкой ниже.",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📱 Отправить номер", request_contact=True)], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True
        )
    )
    return PHONE


async def phone(update, context):
    context.user_data["phone"] = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    await update.message.reply_text("Введите дату рождения, например 01.01.1995:", reply_markup=cancel_keyboard())
    return BIRTH_DATE


async def birth_date(update, context):
    context.user_data["birth_date"] = update.message.text.strip()
    await update.message.reply_text("Введите адрес проживания:")
    return ADDRESS


async def address(update, context):
    context.user_data["address"] = update.message.text.strip()
    d = context.user_data
    text = (
        "👤 ПРОВЕРКА ЛИЧНЫХ ДАННЫХ\n\n"
        f"ФИО: {d['last_name']} {d['first_name']} {d['patronymic'] or '-'}\n"
        f"Телефон: {d['phone']}\n"
        f"Дата рождения: {d['birth_date']}\n"
        f"Адрес проживания: {d['address']}\n\n"
        "Проверьте данные. После нажатия «Подтвердить» они будут зафиксированы "
        "как введённые вами сведения для этой заявки."
    )
    await update.message.reply_text(
        text,
        reply_markup=yes_no_keyboard("✅ Подтвердить личные данные")
    )
    return PERSON_CONFIRM


async def person_confirm(update, context):
    choice = update.message.text.strip()
    if choice == "✏️ Изменить данные":
        return await begin_application(update, context)
    if choice != "✅ Подтвердить личные данные":
        await update.message.reply_text("Нажмите кнопку подтверждения или изменения.")
        return PERSON_CONFIRM

    context.user_data["person_confirmed_at"] = now_iso()
    await update.message.reply_text("🛂 Введите серию паспорта (4 цифры):", reply_markup=cancel_keyboard())
    return PASSPORT_SERIES


async def passport_series(update, context):
    value = update.message.text.strip().replace(" ", "")
    if len(value) != 4 or not value.isdigit():
        await update.message.reply_text("Введите серию из 4 цифр.")
        return PASSPORT_SERIES
    context.user_data["passport_series"] = value
    await update.message.reply_text("Введите номер паспорта (6 цифр):")
    return PASSPORT_NUMBER


async def passport_number(update, context):
    value = update.message.text.strip().replace(" ", "")
    if len(value) != 6 or not value.isdigit():
        await update.message.reply_text("Введите номер из 6 цифр.")
        return PASSPORT_NUMBER
    context.user_data["passport_number"] = value
    await update.message.reply_text("Введите дату выдачи паспорта:")
    return PASSPORT_DATE


async def passport_date(update, context):
    context.user_data["passport_date"] = update.message.text.strip()
    await update.message.reply_text("Введите код подразделения:")
    return PASSPORT_DEPARTMENT


async def passport_department(update, context):
    context.user_data["passport_department"] = update.message.text.strip()
    await update.message.reply_text("Введите, кем выдан паспорт:")
    return PASSPORT_ISSUED_BY


async def passport_issued_by(update, context):
    context.user_data["passport_issued_by"] = update.message.text.strip()
    await update.message.reply_text("Введите адрес регистрации:")
    return REGISTRATION_ADDRESS


async def registration_address(update, context):
    context.user_data["registration_address"] = update.message.text.strip()
    await update.message.reply_text("💰 Какую сумму хотите получить? Например: 30000")
    return AMOUNT


async def amount(update, context):
    value = update.message.text.strip().replace(" ", "")
    try:
        n = int(value)
        if n <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("Введите сумму числом, например 30000.")
        return AMOUNT
    context.user_data["amount"] = n
    await update.message.reply_text("📅 Введите срок: 7, 14, 30 или 60 дней.")
    return TERM


async def term(update, context):
    value = update.message.text.strip()
    if value not in {"7", "14", "30", "60"}:
        await update.message.reply_text("Выберите: 7, 14, 30 или 60.")
        return TERM
    context.user_data["term_days"] = int(value)
    await update.message.reply_text("🏦 Введите название банка:")
    return BANK


async def bank(update, context):
    context.user_data["bank"] = update.message.text.strip()
    await update.message.reply_text("💳 Введите номер счёта/карты:")
    return ACCOUNT


async def account(update, context):
    context.user_data["account"] = update.message.text.strip()
    await update.message.reply_text("Введите БИК или «-»:")
    return BIK


async def bik(update, context):
    v = update.message.text.strip()
    context.user_data["bik"] = "" if v == "-" else v
    await update.message.reply_text("Введите ФИО получателя:")
    return RECIPIENT


async def recipient(update, context):
    context.user_data["recipient_name"] = update.message.text.strip()
    await update.message.reply_text("📷 Отправьте фото первой страницы паспорта.")
    return PASSPORT_FRONT


async def passport_front(update, context):
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте именно фотографию паспорта.")
        return PASSPORT_FRONT
    context.user_data["passport_front_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text("📷 Теперь отправьте фото страницы с регистрацией.")
    return PASSPORT_REGISTRATION


async def passport_registration(update, context):
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию страницы регистрации.")
        return PASSPORT_REGISTRATION
    context.user_data["passport_registration_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text("🤳 Теперь отправьте селфи, на котором вы держите паспорт рядом с лицом.")
    return SELFIE


def summary(d):
    return (
        "🔎 ФИНАЛЬНАЯ ПРОВЕРКА\n\n"
        f"👤 {d['last_name']} {d['first_name']} {d['patronymic'] or '-'}\n"
        f"📱 {d['phone']}\n"
        f"🎂 {d['birth_date']}\n"
        f"🏠 {d['address']}\n\n"
        f"🛂 Паспорт: {d['passport_series']} {d['passport_number']}\n"
        f"📅 Выдан: {d['passport_date']}\n"
        f"🏢 Код: {d['passport_department']}\n"
        f"Кем выдан: {d['passport_issued_by']}\n"
        f"📍 Регистрация: {d['registration_address']}\n\n"
        f"💰 Сумма: {d['amount']:,} ₽\n"
        f"📅 Срок: {d['term_days']} дней\n"
        f"🏦 Банк: {d['bank']}\n"
        f"💳 Реквизиты: {d['account']}\n"
        f"БИК: {d['bik'] or '-'}\n"
        f"Получатель: {d['recipient_name']}\n\n"
        "📷 Фото паспорта: получено\n"
        "📷 Фото регистрации: получено\n"
        "🤳 Селфи: получено\n\n"
        "Подтвердите отправку заявки."
    ).replace(",", " ")


async def selfie(update, context):
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте селфи фотографией.")
        return SELFIE
    context.user_data["selfie_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text(
        summary(context.user_data),
        reply_markup=yes_no_keyboard("✅ Подтвердить и отправить заявку", "✏️ Заполнить заново")
    )
    return FINAL_CONFIRM


def create_application(user, d):
    now = now_iso()
    conn = db()
    cur = conn.execute("""
    INSERT INTO applications (
        telegram_id, username, first_name, last_name, patronymic, phone, birth_date, address,
        passport_series, passport_number, passport_date, passport_department, passport_issued_by,
        registration_address, amount, term_days, bank, account, bik, recipient_name,
        passport_front_file_id, passport_registration_file_id, selfie_file_id,
        person_confirmed_at, final_confirmed_at, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(user.id), user.username or "", d["first_name"], d["last_name"], d["patronymic"],
        d["phone"], d["birth_date"], d["address"], d["passport_series"], d["passport_number"],
        d["passport_date"], d["passport_department"], d["passport_issued_by"],
        d["registration_address"], d["amount"], d["term_days"], d["bank"], d["account"],
        d["bik"], d["recipient_name"], d["passport_front_file_id"],
        d["passport_registration_file_id"], d["selfie_file_id"],
        d["person_confirmed_at"], now, "pending", now, now
    ))
    app_id = cur.lastrowid
    conn.commit()
    conn.close()
    return app_id


async def final_confirm(update, context):
    choice = update.message.text.strip()
    if choice == "✏️ Заполнить заново":
        return await begin_application(update, context)
    if choice != "✅ Подтвердить и отправить заявку":
        await update.message.reply_text("Нажмите кнопку подтверждения или изменения.")
        return FINAL_CONFIRM

    d = context.user_data
    user = update.effective_user
    app_id = create_application(user, d)
    audit(app_id, user.id, "borrower_confirmed", "Заявка подтверждена заемщиком в Telegram")

    await update.message.reply_text(
        f"✅ Заявка №{app_id} отправлена.\n\n"
        "Статус: 🟡 На рассмотрении.\n"
        "Администратор получил анкету и фотографии.",
        reply_markup=main_keyboard()
    )

    admin_text = (
        f"🆕 НОВАЯ ЗАЯВКА №{app_id}\n\n"
        f"👤 {d['last_name']} {d['first_name']} {d['patronymic'] or '-'}\n"
        f"Telegram ID: {user.id}\nUsername: @{user.username or '-'}\n"
        f"📱 {d['phone']}\n🎂 {d['birth_date']}\n🏠 {d['address']}\n\n"
        f"🛂 Паспорт: {d['passport_series']} {d['passport_number']}\n"
        f"📅 Дата выдачи: {d['passport_date']}\n"
        f"🏢 Код подразделения: {d['passport_department']}\n"
        f"Кем выдан: {d['passport_issued_by']}\n"
        f"📍 Регистрация: {d['registration_address']}\n\n"
        f"💰 Сумма: {d['amount']:,} ₽\n📅 Срок: {d['term_days']} дней\n"
        f"🏦 Банк: {d['bank']}\n💳 Реквизиты: {d['account']}\n"
        f"БИК: {d['bik'] or '-'}\nПолучатель: {d['recipient_name']}\n\n"
        f"🕐 Подтверждение личных данных: {d['person_confirmed_at']}\n"
        f"🕐 Финальное подтверждение: {now_iso()}\n\n"
        f"📌 Статус: pending\n\n"
        f"/approve_{app_id}\n/reject_{app_id}\n/paid_{app_id}\n/case_{app_id}"
    ).replace(",", " ")

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=int(admin_id), text=admin_text)
            await context.bot.send_photo(chat_id=int(admin_id), photo=d["passport_front_file_id"],
                                          caption=f"Заявка №{app_id}: первая страница паспорта")
            await context.bot.send_photo(chat_id=int(admin_id), photo=d["passport_registration_file_id"],
                                          caption=f"Заявка №{app_id}: регистрация")
            await context.bot.send_photo(chat_id=int(admin_id), photo=d["selfie_file_id"],
                                          caption=f"Заявка №{app_id}: селфи")
        except Exception as exc:
            print("Ошибка отправки админу:", exc)

    context.user_data.clear()
    return ConversationHandler.END


async def my_applications(update, context):
    conn = db()
    rows = conn.execute("SELECT * FROM applications WHERE telegram_id=? ORDER BY id DESC",
                        (str(update.effective_user.id),)).fetchall()
    conn.close()
    labels = {"pending":"🟡 На рассмотрении","approved":"🟢 Одобрена","rejected":"🔴 Отказана","paid":"💸 Выдана"}
    if not rows:
        await update.message.reply_text("📋 У вас пока нет заявок.", reply_markup=main_keyboard())
        return
    for row in rows:
        await update.message.reply_text(
            f"📋 Заявка №{row['id']}\n\n💰 {row['amount']:,} ₽\n"
            f"📅 {row['term_days']} дней\n📌 {labels.get(row['status'], row['status'])}\n"
            f"📅 {row['created_at'][:10]}".replace(",", " ")
        )


async def profile(update, context):
    user = update.effective_user
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (str(user.id),)).fetchone()
    count = conn.execute("SELECT COUNT(*) c FROM applications WHERE telegram_id=?", (str(user.id),)).fetchone()["c"]
    conn.close()
    await update.message.reply_text(
        "👤 МОЙ ПРОФИЛЬ\n\n"
        f"Имя: {row['first_name'] if row else user.first_name}\n"
        f"Фамилия: {row['last_name'] if row else user.last_name or '-'}\n"
        f"Telegram: @{user.username or '-'}\nЗаявок: {count}",
        reply_markup=main_keyboard()
    )


async def help_command(update, context):
    await update.message.reply_text(
        "ℹ️ Помощь\n\n"
        "📝 Подать заявку — анкета, паспортные данные и фото.\n"
        "После личных данных есть отдельное подтверждение.\n"
        "Перед отправкой — финальное подтверждение.\n"
        "📋 Мои заявки — статусы.\n"
        "👤 Мой профиль — профиль.\n\n"
        "Для разработки используйте тестовые данные. Не загружайте реальные паспорта "
        "в тестовую среду без необходимых мер защиты и правовых оснований.",
        reply_markup=main_keyboard()
    )


def is_admin(update):
    return str(update.effective_user.id) in ADMIN_IDS


async def admin(update, context):
    if not is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    conn = db()
    rows = conn.execute("SELECT * FROM applications ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Заявок нет.")
        return
    for row in rows:
        await update.message.reply_text(
            f"📋 Заявка №{row['id']}\n👤 {row['last_name']} {row['first_name']}\n"
            f"💰 {row['amount']:,} ₽\n📅 {row['term_days']} дней\n📌 {row['status']}\n\n"
            f"/approve_{row['id']}\n/reject_{row['id']}\n/paid_{row['id']}\n/case_{row['id']}".replace(",", " ")
        )


def make_case_text(row, logs):
    lines = [
        f"ДЕЛО ПО ЗАЯВКЕ №{row['id']}",
        f"Статус: {row['status']}",
        f"Создано: {row['created_at']}",
        f"Обновлено: {row['updated_at']}",
        "",
        f"Заемщик: {row['last_name']} {row['first_name']} {row['patronymic'] or '-'}",
        f"Telegram ID: {row['telegram_id']}",
        f"Username: @{row['username'] or '-'}",
        f"Телефон: {row['phone']}",
        f"Дата рождения: {row['birth_date']}",
        f"Адрес: {row['address']}",
        "",
        f"Паспорт: {row['passport_series']} {row['passport_number']}",
        f"Дата выдачи: {row['passport_date']}",
        f"Код подразделения: {row['passport_department']}",
        f"Кем выдан: {row['passport_issued_by']}",
        f"Регистрация: {row['registration_address']}",
        "",
        f"Сумма: {row['amount']} RUB",
        f"Срок: {row['term_days']} дней",
        f"Банк: {row['bank']}",
        f"Счет/карта: {row['account']}",
        f"БИК: {row['bik'] or '-'}",
        f"Получатель: {row['recipient_name']}",
        "",
        f"Подтверждение личных данных: {row['person_confirmed_at']}",
        f"Финальное подтверждение: {row['final_confirmed_at']}",
        f"Одобрение: {row['approved_at'] or '-'}",
        f"Выдача: {row['paid_at'] or '-'}",
        "",
        "ЖУРНАЛ ДЕЙСТВИЙ:",
    ]
    for log in logs:
        lines.append(f"{log['created_at']} | {log['actor_telegram_id']} | {log['action']} | {log['details']}")
    lines += [
        "",
        "ВАЖНО: этот файл является технической выпиской системы, а не юридическим заключением "
        "и не гарантирует взыскание долга."
    ]
    return "\n".join(lines)


async def case_command(update, context):
    if not is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    try:
        app_id = int(update.message.text.split("_", 1)[1])
    except Exception:
        await update.message.reply_text("Использование: /case_ID")
        return

    conn = db()
    row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    logs = conn.execute("SELECT * FROM audit_log WHERE application_id=? ORDER BY id", (app_id,)).fetchall()
    conn.close()

    if not row:
        await update.message.reply_text("Заявка не найдена.")
        return

    path = DOCUMENT_DIR / f"case_{app_id}.txt"
    path.write_text(make_case_text(row, logs), encoding="utf-8")

    # Отправляем текстовый пакет. Фото остаются в Telegram как file_id.
    await update.message.reply_document(
        document=str(path),
        caption=f"Техническая выписка по заявке №{app_id}"
    )


async def admin_action(update, context):
    if not is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    command = update.message.text.strip()
    try:
        app_id = int(command.split("_")[1])
    except Exception:
        await update.message.reply_text("Неверный номер заявки.")
        return

    if command.startswith("/approve_"):
        status, message, action = "approved", "🟢 Заявка одобрена.", "approved"
    elif command.startswith("/reject_"):
        status, message, action = "rejected", "🔴 Заявка отклонена.", "rejected"
    elif command.startswith("/paid_"):
        status, message, action = "paid", "💸 Заявка отмечена как выданная.", "paid"
    else:
        return

    now = now_iso()
    conn = db()
    row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("Заявка не найдена.")
        return

    if status == "approved":
        conn.execute("UPDATE applications SET status=?, approved_at=?, updated_at=? WHERE id=?",
                     (status, now, now, app_id))
    elif status == "paid":
        conn.execute("UPDATE applications SET status=?, paid_at=?, updated_at=? WHERE id=?",
                     (status, now, now, app_id))
    else:
        conn.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?",
                     (status, now, app_id))
    conn.commit()
    conn.close()

    audit(app_id, update.effective_user.id, action, message)
    await update.message.reply_text(message)

    try:
        await context.bot.send_message(chat_id=int(row["telegram_id"]),
                                       text=f"📋 Заявка №{app_id}\n\n{message}")
    except Exception as exc:
        print("Не удалось уведомить клиента:", exc)


async def error_handler(update, context):
    print("BOT ERROR:", context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Добавьте его в Environment Variables Render.")
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Подать заявку$"), begin_application)],
        states={
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name)],
            PATRONYMIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, patronymic)],
            PHONE: [MessageHandler((filters.CONTACT | filters.TEXT) & ~filters.COMMAND, phone)],
            BIRTH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, birth_date)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, address)],
            PERSON_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, person_confirm)],
            PASSPORT_SERIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, passport_series)],
            PASSPORT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, passport_number)],
            PASSPORT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, passport_date)],
            PASSPORT_DEPARTMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, passport_department)],
            PASSPORT_ISSUED_BY: [MessageHandler(filters.TEXT & ~filters.COMMAND, passport_issued_by)],
            REGISTRATION_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_address)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount)],
            TERM: [MessageHandler(filters.TEXT & ~filters.COMMAND, term)],
            BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank)],
            ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, account)],
            BIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, bik)],
            RECIPIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recipient)],
            PASSPORT_FRONT: [MessageHandler(filters.PHOTO, passport_front)],
            PASSPORT_REGISTRATION: [MessageHandler(filters.PHOTO, passport_registration)],
            SELFIE: [MessageHandler(filters.PHOTO, selfie)],
            FINAL_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, final_confirm)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(MessageHandler(filters.Regex(r"^/(approve|reject|paid)_\d+$"), admin_action))
    application.add_handler(MessageHandler(filters.Regex(r"^/case_\d+$"), case_command))
    application.add_handler(conversation)
    application.add_handler(MessageHandler(filters.Regex("^📋 Мои заявки$"), my_applications))
    application.add_handler(MessageHandler(filters.Regex("^👤 Мой профиль$"), profile))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ Помощь$"), help_command))
    application.add_error_handler(error_handler)

    print("🤖 Telegram bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
