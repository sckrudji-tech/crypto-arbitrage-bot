import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template
import threading
from telegram.ext import Application, CommandHandler, ApplicationHandlerStop
from config import *
# ДОДАНО: імпорт balance
from arbitrage.arbitrage import find_arbitrage, start, stop, set_profit, history, balance

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# main.py (додатково)
logging.info("=== СИСТЕМНА ІНФОРМАЦІЯ ===")
logging.info(f"Робочий каталог: {os.getcwd()}")
logging.info(f"Шлях до лог-файлу: {LOG_FILE}")
logging.info(f"Шлях до CSV: {OUTPUT_CSV}")
logging.info("=== БОТ ГОТОВИЙ ДО РОБОТИ ===")

# Ініціалізація Flask
app = Flask(__name__)

# Flask-дашборд
@app.route('/')
def dashboard():
    try:
        import pandas as pd
        import plotly.express as px
        df = pd.read_csv(OUTPUT_CSV, encoding='utf-8')
        fig = px.line(df, x='timestamp', y='profit', color='symbol', title='Історія арбітражу')
        graph_html = fig.to_html(full_html=False)
        return render_template('dashboard.html', graph=graph_html)
    except Exception as e:
        return f"Помилка дашборду: {str(e)}"

# Шаблон HTML для дашборду
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Арбітражний Дашборд</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { text-align: center; }
    </style>
</head>
<body>
    <h1>Арбітражні зв’язки (Binance/Bybit)</h1>
    {{ graph | safe }}
</body>
</html>
"""

def setup_telegram_bot():
    """Налаштовує обробники команд Telegram."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("set_profit", set_profit))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("balance", balance))  # ДОДАНО
    return application

def run_flask():
    """Запускає веб-сервер Flask."""
    os.makedirs('templates', exist_ok=True)
    with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(DASHBOARD_HTML)
    app.run(port=FLASK_PORT, debug=False, use_reloader=False)

def main():
    logging.info("Головний цикл запуску бота")
    application = setup_telegram_bot()
    
    # Запуск Flask у фоновому потоці
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logging.info("Запуск Telegram Polling...")
        application.run_polling()

    except KeyboardInterrupt:
        logging.info("Програма зупинена користувачем (Ctrl+C).")
    except Exception as e:
        logging.error(f"Фатальна помилка в main: {e}")
    finally:
        logging.info("Головний потік завершує роботу.")

if __name__ == '__main__':
    main()