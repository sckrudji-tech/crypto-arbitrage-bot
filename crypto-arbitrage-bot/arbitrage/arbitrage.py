# arbitrage.py
import asyncio
import csv
import logging
import os 
import time 
from datetime import datetime, UTC
from collections import defaultdict
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationHandlerStop
from telegram.error import RetryAfter, BadRequest

# Імпорт конфігурації
from config import * 
import ccxt.pro as ccxt 
from ccxt.base.errors import InvalidNonce

# *** ІМПОРТ ВСІХ СТРАТЕГІЙ ***
from strategies.cross_exchange import check_cross_exchange_arbitrage
from strategies.triangular import check_triangular_arbitrage 
from strategies.spot_futures_arbitrage import check_spot_futures_arbitrage
from strategies.paper_trader import PaperTrader

# Глобальний стан
bot_running = False
arbitrage_history = {} 
price_cache = {} 
bot = Bot(token=TELEGRAM_TOKEN)
message_tracker = {}
paper_trader = None  # ← ЗМІНЕНО: ініціалізація відкладена

# Нові глобальні змінні для рейт-ліміту та debounce
telegram_message_queue = None
telegram_last_message_time = 0
last_message_update = defaultdict(float)
MIN_UPDATE_INTERVAL = 30
TELEGRAM_MIN_INTERVAL = 2
MAX_ACTIVE_MESSAGES = 8

# --- УТИЛІТНІ ФУНКЦІЇ ---

async def _send_telegram_message_actual(message, details=None, message_id=None):
    keyboard = [[InlineKeyboardButton("Деталі", callback_data='details')]] if details else []
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if bot.token is None: 
            logging.error("Telegram TOKEN не встановлено.")
            return None
            
        if message_id:
            await bot.edit_message_text(
                chat_id=CHAT_ID,
                message_id=message_id,
                text=message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            logging.info(f"Оновлено повідомлення ID {message_id}: {message[:100]}...")
            return message_id
        else:
            sent_message = await bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            logging.info(f"Надіслано нове повідомлення: {message[:100]}...")
            return sent_message.message_id
    except RetryAfter as e:
        logging.warning(f"Telegram флуд-контроль: чекаємо {e.retry_after} секунд")
        await asyncio.sleep(e.retry_after)
        return await _send_telegram_message_actual(message, details, message_id)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logging.debug("Повідомлення не змінено, пропускаємо")
            return message_id
        logging.error(f"BadRequest Telegram: {e} (Повідомлення: {message[:100]}...)")
        return None
    except Exception as e:
        logging.error(f"Помилка Telegram: {e} (Повідомлення: {message[:100]}...)")
        return None

async def send_telegram_message(message, details=None, message_id=None):
    if telegram_message_queue is not None:
        await telegram_message_queue.put({
            'message': message,
            'details': details,
            'message_id': message_id
        })
    else:
        return await _send_telegram_message_actual(message, details, message_id)

async def telegram_message_worker():
    global telegram_last_message_time
    while bot_running:
        try:
            message_data = await telegram_message_queue.get()
            current_time = time.time()
            wait_time = TELEGRAM_MIN_INTERVAL - (current_time - telegram_last_message_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            await _send_telegram_message_actual(**message_data)
            telegram_last_message_time = time.time()
            telegram_message_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Помилка в telegram_message_worker: {e}")

def save_to_csv(arbitrage_data):
    # Переконуємося, що каталог існує
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    
    fieldnames = ['timestamp', 'type', 'symbol', 'buy_exchange', 'sell_exchange', 'buy_price', 'sell_price', 'profit', 'volume', 'path', 'details', 'earnings']
    file_exists = os.path.exists(OUTPUT_CSV)
    try:
        with open(OUTPUT_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            data_to_save = {k: v for k, v in arbitrage_data.items() if k != 'message'}
            writer.writerow(data_to_save)
            arbitrage_history[arbitrage_data['timestamp']] = data_to_save
        logging.info(f"Записано в CSV: {arbitrage_data['symbol']} з прибутком {arbitrage_data['profit']:.4f}%")
    except Exception as e:
         logging.error(f"Помилка збереження в CSV: {e}")

def get_exchange_config(exchange_id):
    exchange_config = {
        'apiKey': globals().get(f"{exchange_id.upper()}_API_KEY"),
        'secret': globals().get(f"{exchange_id.upper()}_SECRET_KEY"),
        'enableRateLimit': True,
    }
    if exchange_id == 'bybit':
        exchange_config['options'] = {'recvWindow': RECV_WINDOW}
    elif exchange_id == 'okx':
        exchange_config['options'] = {'defaultType': 'spot'}
    return exchange_config

def split_symbols_by_type(symbols):
    spot = []
    futures = []
    for s in symbols:
        if ':USDT' in s or s.endswith('USD') or 'USD_' in s:
            futures.append(s)
        else:
            spot.append(s)
    return spot, futures

async def data_streamer(exchange_id, symbols):
    global price_cache, bot_running
    exchange_config = get_exchange_config(exchange_id)
    if not exchange_config.get('apiKey') or not exchange_config.get('secret'):
        logging.warning(f"Пропущено {exchange_id.upper()} - відсутні ключі API.")
        return
    exchange = None
    try:
        exchange = getattr(ccxt, exchange_id)(exchange_config)
        logging.info(f"Стрімер {exchange_id.upper()} запущено для {len(symbols)} пар.")
        for symbol in symbols:
            if symbol not in price_cache:
                price_cache[symbol] = {}
            price_cache[symbol][exchange_id] = {'bid': None, 'ask': None, 'volume': MIN_VOLUME}
        while bot_running:
            try:
                tickers = await exchange.watch_tickers(symbols) 
                if isinstance(tickers, list):
                    tickers = {t['symbol']: t for t in tickers if t and t.get('symbol')}
                for symbol, ticker in tickers.items():
                    if not ticker:
                        continue
                    bid = ticker.get('bid')
                    ask = ticker.get('ask')
                    volume = ticker.get('quoteVolume', MIN_VOLUME)
                    if bid is not None and ask is not None:
                        try:
                            price_cache[symbol][exchange_id] = {
                                'bid': float(bid),
                                'ask': float(ask),
                                'volume': float(volume) if volume is not None else MIN_VOLUME
                            }
                        except (TypeError, ValueError) as e:
                            logging.warning(f"Некоректні дані для {symbol} на {exchange_id}: {e}")
                    else:
                        logging.debug(f"Пропущено неповні дані для {symbol} на {exchange_id}: bid={bid}, ask={ask}")
            except (ccxt.NetworkError, ccxt.DDoSProtection) as e:
                logging.warning(f"Мережева помилка {exchange_id.upper()}: {e}. Перепідключення через 5с.")
                await asyncio.sleep(5)
            except InvalidNonce as e:
                logging.error(f"Помилка синхронізації часу {exchange_id.upper()}: {e}")
                await send_telegram_message(f"⚠️ {exchange_id.upper()}: Проблема з часом. Перевірте системний час!")
                break
            except Exception as e:
                logging.error(f"Критична помилка стримера {exchange_id.upper()}: {e}")
                await send_telegram_message(f"🚨 Критична помилка стримера {exchange_id.upper()}: {e}")
                break
    except Exception as e:
        logging.error(f"Помилка ініціалізації стримера {exchange_id.upper()}: {e}")
    finally:
        logging.info(f"Стрімер {exchange_id.upper()} зупинено.")
        if exchange:
            await exchange.close()

async def arbitrage_calculator():
    global bot_running, price_cache, message_tracker, last_message_update, paper_trader
    strategies = {
        'cross_exchange': check_cross_exchange_arbitrage,
        'triangular': check_triangular_arbitrage,
        'spot_futures': check_spot_futures_arbitrage,
    }
    MESSAGE_TIMEOUT = 300
    while bot_running:
        start_time = time.time()
        try:
            if not price_cache:
                await asyncio.sleep(1)
                continue

            current_opportunities = {}
            
            # 1. Міжбіржовий арбітраж
            for symbol in price_cache.keys():
                try:
                    async for opportunity in strategies['cross_exchange'](symbol, price_cache, list(price_cache.keys())):
                        if opportunity.get('profit') is not None:
                            trade_started = await paper_trader.process_signal(opportunity)
                            if trade_started:
                                current_opportunities[opportunity['path']] = opportunity
                except Exception as e:
                    logging.error(f"Помилка в cross_exchange для {symbol}: {e}")

            # 2. Трикутний арбітраж
            for exchange_id in EXCHANGES:
                try:
                    async for opportunity in strategies['triangular'](exchange_id, price_cache, list(price_cache.keys())):
                        if opportunity.get('profit') is not None:
                            trade_started = await paper_trader.process_signal(opportunity)
                            if trade_started:
                                current_opportunities[opportunity['path']] = opportunity
                except Exception as e:
                    logging.error(f"Помилка в triangular для {exchange_id}: {e}")

            # 3. Спот-ф'ючерс арбітраж
            for exchange_id in EXCHANGES:
                try:
                    async for opportunity in strategies['spot_futures'](exchange_id, price_cache, list(price_cache.keys())):
                        if opportunity.get('profit') is not None:
                            trade_started = await paper_trader.process_signal(opportunity)
                            if trade_started:
                                current_opportunities[opportunity['path']] = opportunity
                except Exception as e:
                    logging.error(f"Помилка в spot_futures для {exchange_id}: {e}")

            # Оновлення завершених угод
            completed_trades = await paper_trader.update_trades()
            for trade in completed_trades:
                logging.info(f"Завершено угоду: {trade['profit_usd']:.4f} USDT за {trade['duration']:.1f} сек")

            current_time = time.time()
            for path, opportunity in current_opportunities.items():
                should_update = False
                if path not in message_tracker:
                    should_update = True
                else:
                    old_profit = message_tracker[path]['data']['profit']
                    new_profit = opportunity['profit']
                    profit_change = abs(new_profit - old_profit)
                    status_changed = (old_profit >= PROFIT_THRESHOLD * 100) != (new_profit >= PROFIT_THRESHOLD * 100)
                    if (profit_change > 0.1 or status_changed) and (current_time - last_message_update[path] >= MIN_UPDATE_INTERVAL):
                        should_update = True
                if should_update:
                    if path not in message_tracker and len(message_tracker) >= MAX_ACTIVE_MESSAGES:
                        oldest_path = min(message_tracker.keys(), key=lambda x: message_tracker[x]['last_updated'])
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=message_tracker[oldest_path]['message_id'])
                            logging.info(f"Видалено найстаріше повідомлення для {oldest_path} через ліміт")
                            del message_tracker[oldest_path]
                            if oldest_path in last_message_update:
                                del last_message_update[oldest_path]
                        except Exception as e:
                            logging.error(f"Помилка видалення найстарішого повідомлення: {e}")
                    status = "Актуально ✅" if opportunity['profit'] >= PROFIT_THRESHOLD * 100 else "Не актуально ❌"
                    message = f"{opportunity['message']}\n<b>Статус: {status}</b>"
                    if path in message_tracker:
                        message_id = message_tracker[path]['message_id']
                        new_message_id = await send_telegram_message(message, opportunity['details'], message_id)
                        if new_message_id:
                            message_tracker[path]['message_id'] = new_message_id
                            message_tracker[path]['data'] = opportunity
                            message_tracker[path]['last_updated'] = current_time
                            last_message_update[path] = current_time
                    else:
                        message_id = await send_telegram_message(message, opportunity['details'])
                        if message_id:
                            message_tracker[path] = {
                                'message_id': message_id,
                                'last_updated': current_time,
                                'data': opportunity
                            }
                            last_message_update[path] = current_time
                            save_to_csv(opportunity)

            # Очищення застарілих
            for path in list(message_tracker.keys()):
                if path not in current_opportunities:
                    opportunity = message_tracker[path]['data']
                    status = "Не актуально ❌"
                    message = f"{opportunity['message']}\n<b>Статус: {status}</b>"
                    message_id = message_tracker[path]['message_id']
                    await send_telegram_message(message, opportunity['details'], message_id)
                    message_tracker[path]['last_updated'] = current_time
                if current_time - message_tracker[path]['last_updated'] > MESSAGE_TIMEOUT:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=message_tracker[path]['message_id'])
                        logging.info(f"Видалено застаріле повідомлення для {path}")
                    except Exception as e:
                        logging.error(f"Помилка видалення повідомлення для {path}: {e}")
                    del message_tracker[path]
                    if path in last_message_update:
                        del last_message_update[path]

            elapsed_time = time.time() - start_time
            wait_time = max(2.0, ARBITRAGE_LOOP_DELAY - elapsed_time)
            await asyncio.sleep(wait_time) 

        except Exception as e:
            logging.error(f"Загальна помилка в arbitrage_calculator: {e}")
            await send_telegram_message(f"⚠️ Критична помилка калькулятора: {str(e)}")
            await asyncio.sleep(5)

# *** ГОЛОВНИЙ ЦИКЛ ЗАПУСКУ ***
async def find_arbitrage(application):
    global bot_running, telegram_message_queue, paper_trader
    telegram_message_queue = asyncio.Queue()
    telegram_worker_task = asyncio.create_task(telegram_message_worker())
    
    # Ініціалізуємо PaperTrader ПІСЛЯ налаштування логування
    paper_trader = PaperTrader()

    # Завантажуємо символи для кожної біржі окремо
    exchange_symbols = {}
    for ex_id in EXCHANGES:
        try:
            config = get_exchange_config(ex_id)
            if not config.get('apiKey'):
                logging.warning(f"Конфігурація для {ex_id} не знайдена. Пропускаємо.")
                continue
            exchange = getattr(ccxt, ex_id)(config)
            markets = await exchange.load_markets()
            
            if ex_id == 'bybit':
                symbols = [
                    s for s in TOP_SYMBOLS 
                    if s in markets 
                    and markets[s].get('active')
                    and (s.endswith('/USDT') or ':USDT' in s or s.endswith('USDT'))
                ]
            else:
                symbols = [s for s in TOP_SYMBOLS if s in markets and markets[s].get('active')]
                
            exchange_symbols[ex_id] = symbols
            logging.info(f"Біржа {ex_id}: знайдено {len(symbols)} активних символів")
            await exchange.close()
        except Exception as e:
            logging.error(f"Помилка завантаження символів для {ex_id}: {e}")
            exchange_symbols[ex_id] = []

    stream_tasks = []
    
    for exchange_id in EXCHANGES:
        symbols = exchange_symbols.get(exchange_id, [])
        if not symbols:
            continue
            
        if exchange_id == 'binance':
            spot_syms, futures_syms = split_symbols_by_type(symbols)
            if spot_syms:
                stream_tasks.append(asyncio.create_task(data_streamer('binance', spot_syms), name='Binance_Spot'))
            if futures_syms:
                stream_tasks.append(asyncio.create_task(data_streamer('binance', futures_syms), name='Binance_Futures'))
                
        elif exchange_id == 'bybit':
            batch_size = 10
            batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
            for i, batch in enumerate(batches):
                stream_tasks.append(asyncio.create_task(
                    data_streamer('bybit', batch), 
                    name=f'Bybit_Streamer_{i+1}'
                ))
                
        else:
            stream_tasks.append(asyncio.create_task(data_streamer(exchange_id, symbols), name=f'{exchange_id.capitalize()}_Streamer'))
    
    calc_task = asyncio.create_task(arbitrage_calculator(), name='Arbitrage_Calculator')
    all_tasks = stream_tasks + [calc_task]
    
    try:
        await asyncio.gather(*all_tasks, telegram_worker_task)
    except Exception as e:
        logging.error(f"Помилка в asyncio.gather: {e}")
    finally:
        bot_running = False
        if telegram_worker_task and not telegram_worker_task.done():
            telegram_worker_task.cancel()
        telegram_message_queue = None

# --- ТЕЛЕГРАМ-КОМАНДИ ---
async def start(update, context):
    global bot_running
    if bot_running:
        await update.message.reply_text("Бот вже запущено. ✅")
        raise ApplicationHandlerStop 
    bot_running = True
    await update.message.reply_text("Бот запущено! Аналізую всі біржі та стратегії. 🟢")
    asyncio.create_task(find_arbitrage(context.application))

async def stop(update, context):
    global bot_running
    bot_running = False
    await update.message.reply_text("Бот зупинено. 🔴 Очікування завершення поточних завдань.")

async def set_profit(update, context):
    try:
        global PROFIT_THRESHOLD
        if not context.args:
            await update.message.reply_text(f"Поточний поріг: {PROFIT_THRESHOLD*100:.4f}%. Введіть нове значення: /set_profit 0.05 (для 0.05%)")
            return
        new_threshold = float(context.args[0]) / 100
        PROFIT_THRESHOLD = new_threshold
        await update.message.reply_text(f"Новий поріг прибутку: {new_threshold*100:.4f}%. ✅")
    except Exception as e:
        await update.message.reply_text(f"Помилка: Невірний формат. Введіть число. Наприклад: /set_profit 0.05 ❌")

async def history(update, context):
    if not arbitrage_history:
        await update.message.reply_text("Історія арбітражів порожня. Спробуйте пізніше.")
        return
    latest_entries = sorted(arbitrage_history.items(), key=lambda item: item[0], reverse=True)[:5]
    message_lines = ["<b>🔥 Остання Історія Арбітражу (5) 🔥</b>"]
    for timestamp, data in latest_entries:
        line = (
            f"💰 <b>{data['profit']:.3f}%</b> | "
            f"🔄 {data['type'].upper()} | "
            f"📊 {data['symbol']} | "
            f"💵 ~{data['earnings']:.2f} USDT"
        )
        message_lines.append(line)
    message = "\n".join(message_lines)
    await update.message.reply_text(message, parse_mode='HTML')

async def balance(update, context):
    summary = paper_trader.get_summary()
    message = (
        f"<b>📊 Paper Trading Статистика</b>\n"
        f"💰 Загальний баланс: <b>{summary['total_balance_usdt']:.2f} USDT</b>\n"
        f"🔄 Активних угод: <b>{summary['active_trades']}</b>\n\n"
        f"<b>Баланси за біржами:</b>\n"
    )
    for ex, coins in summary['balances'].items():
        if coins:
            coins_str = ", ".join([f"{c}: {v:.2f}" for c, v in coins.items()])
            message += f"• <b>{ex.upper()}</b>: {coins_str}\n"
    await update.message.reply_text(message, parse_mode='HTML')