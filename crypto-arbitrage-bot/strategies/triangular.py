import logging
from config import PROFIT_THRESHOLD, DEPOSIT, EXCHANGE_FEES, MIN_VOLUME
from datetime import datetime, UTC

async def check_triangular_arbitrage(exchange_id, price_cache, common_symbols):
    """
    Шукає трикутний арбітраж на ОДНІЙ біржі (заданій exchange_id).
    Підтримує будь-які базові валюти, не тільки USDT.
    """
    
    # Фільтруємо пари тільки для поточної біржі
    exchange_pairs = {}
    for symbol in common_symbols:
        if exchange_id in price_cache.get(symbol, {}):
            pair_data = price_cache[symbol][exchange_id]
            # Перевіряємо наявність даних та мінімальний обсяг
            if (pair_data.get('ask') and pair_data.get('bid') and 
                pair_data.get('volume', 0) >= MIN_VOLUME):
                exchange_pairs[symbol] = pair_data
    
    if len(exchange_pairs) < 3:
        return

    # Будуємо множину всіх валют
    all_currencies = set()
    for pair in exchange_pairs.keys():
        try:
            base, quote = pair.split('/')
            all_currencies.add(base)
            all_currencies.add(quote)
        except ValueError:
            continue

    if len(all_currencies) < 3:
        return

    # ВИПРАВЛЕНО: отримання комісій для споту
    exchange_fees = EXCHANGE_FEES.get(exchange_id, {})
    fee_taker = exchange_fees.get('spot', {}).get('taker', 0.001)
    
    # Перетворюємо на список для індексації
    currencies = list(all_currencies)
    n = len(currencies)
    
    # Шукаємо всі можливі трикутники
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                A, B, C = currencies[i], currencies[j], currencies[k]
                
                # Перевіряємо всі 6 можливих напрямків для трикутника A-B-C
                triangles = [
                    # A → B → C → A
                    [(A, B), (B, C), (C, A)],
                    # A → C → B → A  
                    [(A, C), (C, B), (B, A)],
                    # B → A → C → B
                    [(B, A), (A, C), (C, B)],
                    # B → C → A → B
                    [(B, C), (C, A), (A, B)],
                    # C → A → B → C
                    [(C, A), (A, B), (B, C)],
                    # C → B → A → C
                    [(C, B), (B, A), (A, C)]
                ]
                
                for triangle in triangles:
                    try:
                        # Отримуємо потрібні пари
                        pair1 = f"{triangle[0][1]}/{triangle[0][0]}"  # Для A→B потрібна пара B/A (ask)
                        pair2 = f"{triangle[1][1]}/{triangle[1][0]}"  # Для B→C потрібна пара C/B (ask)  
                        pair3 = f"{triangle[2][0]}/{triangle[2][1]}"  # Для C→A потрібна пара C/A (bid)
                        
                        if not all(p in exchange_pairs for p in [pair1, pair2, pair3]):
                            continue
                        
                        # Отримуємо ціни
                        ask1 = exchange_pairs[pair1]['ask']
                        ask2 = exchange_pairs[pair2]['ask'] 
                        bid3 = exchange_pairs[pair3]['bid']
                        
                        if not (ask1 and ask2 and bid3 and ask1 > 0 and ask2 > 0 and bid3 > 0):
                            continue
                        
                        # Розрахунок з комісіями
                        amount = 1.0
                        amount = amount / ask1 * (1 - fee_taker)  # A → B
                        amount = amount / ask2 * (1 - fee_taker)  # B → C
                        amount = amount * bid3 * (1 - fee_taker)  # C → A
                        
                        profit = amount - 1.0
                        
                        if profit >= PROFIT_THRESHOLD:
                            path = f"{triangle[0][0]}→{triangle[0][1]}→{triangle[1][1]}→{triangle[0][0]}"
                            path_details = (
                                f"{triangle[0][0]}/{triangle[0][1]} (ASK:{ask1:.8f}) → "
                                f"{triangle[1][0]}/{triangle[1][1]} (ASK:{ask2:.8f}) → "
                                f"{triangle[2][0]}/{triangle[2][1]} (BID:{bid3:.8f})"
                            )
                            estimated_earnings = DEPOSIT * profit
                            
                            message = (
                                f"<b>🔺 ТРИКУТНИЙ АРБІТРАЖ ЗНАЙДЕНО</b>\n"
                                f"🧭 Біржа: <b>{exchange_id.upper()}</b>\n"
                                f"🔥 Чистий Прибуток: <b>{profit*100:.3f}%</b>\n"
                                f"🔄 Шлях: <code>{path}</code>\n"
                                f"📊 Деталі: <code>{path_details}</code>\n"
                                f"💵 Оціночний заробіток (на {DEPOSIT} USDT): ~<code>{estimated_earnings:.2f} USDT</code>"
                            )
                            
                            yield {
                                'timestamp': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
                                'type': 'triangular',
                                'symbol': f"[{exchange_id.upper()}] {path}",
                                'buy_exchange': exchange_id,
                                'sell_exchange': exchange_id,
                                'buy_price': ask1,
                                'sell_price': bid3,
                                'profit': profit * 100,
                                'volume': min(
                                    exchange_pairs[pair1].get('volume', 0),
                                    exchange_pairs[pair2].get('volume', 0),
                                    exchange_pairs[pair3].get('volume', 0)
                                ),
                                'path': path_details,
                                'details': {
                                    'triangle': [triangle[0][0], triangle[0][1], triangle[1][1]],
                                    'pairs': [pair1, pair2, pair3],
                                    'prices': [ask1, ask2, bid3],
                                    'final_amount': amount
                                },
                                'earnings': estimated_earnings,
                                'message': message
                            }
                            
                    except (ZeroDivisionError, TypeError, ValueError, KeyError) as e:
                        continue