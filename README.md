# Telegram Loan Mini App — Render version

Эта версия подготовлена специально для Render.

Архитектура:
- Flask + Gunicorn — веб-сервер и Mini App
- Telegram Bot API Webhook — бот
- SQLite — демо-база
- веб-админка

## Render

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Environment Variables:
BOT_TOKEN = токен от BotFather
ADMIN_PASSWORD = пароль админки
PORT = 10000
MINI_APP_URL = URL Render, например https://loan-telegram-bot.onrender.com

После первого деплоя:
1. Скопируйте выданный Render URL.
2. Поставьте его в MINI_APP_URL.
3. Сделайте redeploy.
4. Откройте `/setup-webhook` один раз в браузере.
5. Откройте Telegram и отправьте боту /start.

Важно:
- Render filesystem не предназначен для постоянного хранения SQLite на production.
- Для настоящего сервиса используйте PostgreSQL.
- Этот проект не делает реальных переводов через СБП.
- Юридически значимое подписание договора и реальные финансовые операции не реализованы.
- Не храните реальные банковские реквизиты клиентов в этой демо-базе без отдельной защищённой архитектуры.
