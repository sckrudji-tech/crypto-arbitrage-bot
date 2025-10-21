# strategies/spot_futures_arbitrage.py
import logging
from config import PROFIT_THRESHOLD, DEPOSIT, EXCHANGE_FEES, MIN_VOLUME
from datetime import datetime, UTC

async def check_spot_futures_arbitrage(exchange_id, price_cache, common_symbols):
    """
    Шукає арбітражні можливості між спотовим і ф'ючерсним ринками на ОДНІЙ біржі.
    """
    
    # Визначаємо префікси ф'ючерсів для кожної біржі
    FUTURES_SYMBOLS = {
        'binance': lambda base: f"{base}/USDT:USDT",
        'bybit': lambda base: f"{base}/USDT:USDT",
        'okx': lambda base: f"{base}-USDT-SWAP",
        'bitget': lambda base: f"{base}USDT",
        'gateio': lambda base: f"{base}_USDT"
    }
    
    if exchange_id not in FUTURES_SYMBOLS:
        return
    
    # Фільтруємо тільки спотові пари з USDT
    spot_symbols = [s for s in common_symbols if s.endswith('/USDT')]
    
    if not spot_symbols:
        return
    
    # Отримуємо комісії (з безпечним доступом)
    exchange_fees = EXCHANGE_FEES.get(exchange_id, {})
    fee_taker_spot = exchange_fees.get('spot', {}).get('taker', 0.001)
    fee_taker_futures = exchange_fees.get('futures', {}).get('taker', 0.001)
    
    for spot_symbol in spot_symbols:
        base_asset = spot_symbol.replace('/USDT', '')
        futures_symbol = FUTURES_SYMBOLS[exchange_id](base_asset)
        
        # Перевіряємо наявність обох пар
        if not (spot_symbol in price_cache and exchange_id in price_cache[spot_symbol]):
            continue
            
        if not (futures_symbol in price_cache and exchange_id in price_cache[futures_symbol]):
            continue
        
        spot_data = price_cache[spot_symbol][exchange_id]
        futures_data = price_cache[futures_symbol][exchange_id]
        
        spot_bid = spot_data.get('bid')
        spot_ask = spot_data.get('ask')
        futures_bid = futures_data.get('bid')
        futures_ask = futures_data.get('ask')
        
        if not all([spot_bid, spot_ask, futures_bid, futures_ask]):
            continue
        
        # Розрахунок мінімального обсягу
        min_volume = min(
            spot_data.get('volume', 0),
            futures_data.get('volume', 0)
        )
        
        if min_volume < MIN_VOLUME:
            continue
        
        # === СТРАТЕГІЯ 1: КОНТАНГ (Ф'ючерс дорожчий за спот) ===
        if futures_bid > spot_ask:
            final_amount = (1 / spot_ask) * (1 - fee_taker_spot) * futures_bid * (1 - fee_taker_futures)
            profit = final_amount - 1
            
            if profit >= PROFIT_THRESHOLD:
                basis_spread = ((futures_bid - spot_ask) / spot_ask) * 100
                estimated_earnings = DEPOSIT * profit
                
                message = (
                    f"<b>📈 СПОТ-Ф'ЮЧЕРС АРБІТРАЖ (КОНТАНГ)</b>\n"
                    f"🧭 Біржа: <b>{exchange_id.upper()}</b>\n"
                    f"📊 Актив: <b>{base_asset}</b>\n"
                    f"🔥 Чистий Прибуток: <b>{profit*100:.3f}%</b>\n"
                    f"📈 Базисний спред: <b>{basis_spread:.3f}%</b>\n"
                    f"🔄 Дія: Купити <code>{spot_symbol}</code> (ASK: {spot_ask:.4f}) → "
                    f"Продати <code>{futures_symbol}</code> (BID: {futures_bid:.4f})\n"
                    f"💵 Оціночний заробіток (на {DEPOSIT} USDT): ~<code>{estimated_earnings:.2f} USDT</code>"
                )
                
                yield {
                    'timestamp': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
                    'type': 'spot_futures',
                    'symbol': f"[{exchange_id.upper()}] {base_asset}",
                    'buy_exchange': exchange_id,
                    'sell_exchange': exchange_id,
                    'buy_price': spot_ask,
                    'sell_price': futures_bid,
                    'profit': profit * 100,
                    'volume': min_volume,
                    'path': f"spot_futures:{exchange_id}:{base_asset}:contango",
                    'details': {
                        'strategy': 'contango',
                        'spot_symbol': spot_symbol,
                        'futures_symbol': futures_symbol,
                        'spot_ask': spot_ask,
                        'futures_bid': futures_bid,
                        'basis_spread': basis_spread,
                        'final_amount': final_amount
                    },
                    'earnings': estimated_earnings,
                    'message': message
                }
        
        # === СТРАТЕГІЯ 2: БЕКВАРД (Ф'ючерс дешевший за спот) ===
        if spot_bid > futures_ask:
            final_amount = spot_bid * (1 - fee_taker_spot) * (1 / futures_ask) * (1 - fee_taker_futures)
            profit = final_amount - 1
            
            if profit >= PROFIT_THRESHOLD:
                basis_spread = ((spot_bid - futures_ask) / futures_ask) * 100
                estimated_earnings = DEPOSIT * profit
                
                message = (
                    f"<b>📉 СПОТ-Ф'ЮЧЕРС АРБІТРАЖ (БЕКВАРД)</b>\n"
                    f"🧭 Біржа: <b>{exchange_id.upper()}</b>\n"
                    f"📊 Актив: <b>{base_asset}</b>\n"
                    f"🔥 Чистий Прибуток: <b>{profit*100:.3f}%</b>\n"
                    f"📉 Базисний спред: <b>{basis_spread:.3f}%</b>\n"
                    f"🔄 Дія: Продати <code>{spot_symbol}</code> (BID: {spot_bid:.4f}) → "
                    f"Купити <code>{futures_symbol}</code> (ASK: {futures_ask:.4f})\n"
                    f"💵 Оціночний заробіток (на {DEPOSIT} USDT): ~<code>{estimated_earnings:.2f} USDT</code>"
                )
                
                yield {
                    'timestamp': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
                    'type': 'spot_futures',
                    'symbol': f"[{exchange_id.upper()}] {base_asset}",
                    'buy_exchange': exchange_id,
                    'sell_exchange': exchange_id,
                    'buy_price': futures_ask,
                    'sell_price': spot_bid,
                    'profit': profit * 100,
                    'volume': min_volume,
                    'path': f"spot_futures:{exchange_id}:{base_asset}:backwardation",
                    'details': {
                        'strategy': 'backwardation',
                        'spot_symbol': spot_symbol,
                        'futures_symbol': futures_symbol,
                        'spot_bid': spot_bid,
                        'futures_ask': futures_ask,
                        'basis_spread': basis_spread,
                        'final_amount': final_amount
                    },
                    'earnings': estimated_earnings,
                    'message': message
                }