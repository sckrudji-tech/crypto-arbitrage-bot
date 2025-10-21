# strategies/cross_exchange.py
import logging
from config import PROFIT_THRESHOLD, DEPOSIT, EXCHANGE_FEES, MIN_VOLUME
from datetime import datetime, UTC

async def check_cross_exchange_arbitrage(symbol, price_cache, common_symbols):
    """
    Аналіз міжбіржового арбітражу (купівля на X, продаж на Y)
    з використанням price_cache.
    
    Повертає генератор знайдених можливостей.
    """
    
    exchanges_data = price_cache.get(symbol, {})
    
    if len(exchanges_data) < 2:
        return

    best_buy = {'exchange': None, 'price': float('inf'), 'fee_taker': 0, 'fee_maker': 0, 'volume': 0}
    best_sell = {'exchange': None, 'price': 0, 'fee_taker': 0, 'fee_maker': 0, 'volume': 0}

    for ex_id, data in exchanges_data.items():
        bid, ask = data.get('bid'), data.get('ask')
        volume = data.get('volume', MIN_VOLUME)
        # ВИПРАВЛЕНО: отримання комісій для споту
        exchange_fees = EXCHANGE_FEES.get(ex_id, {})
        spot_fees = exchange_fees.get('spot', {'maker': 0, 'taker': 0})
        
        if bid and bid > best_sell['price']:
            best_sell = {'exchange': ex_id, 'price': bid, 'fee_taker': spot_fees['taker'], 'fee_maker': spot_fees['maker'], 'volume': volume}
        
        if ask and ask < best_buy['price']:
            best_buy = {'exchange': ex_id, 'price': ask, 'fee_taker': spot_fees['taker'], 'fee_maker': spot_fees['maker'], 'volume': volume}

    if best_buy['exchange'] == best_sell['exchange']:
        return

    # --- ВИПРАВЛЕНИЙ РОЗРАХУНОК ЧИСТОГО ПРИБУТКУ ---
    # Net Profit = ((1 / ASK_buy) * (1 - Fee_buy_taker) * BID_sell * (1 - Fee_sell_taker)) - 1
    base_units_after_buy = (1 / best_buy['price']) * (1 - best_buy['fee_taker'])
    final_capital = base_units_after_buy * best_sell['price'] * (1 - best_sell['fee_taker'])
    net_profit = final_capital - 1
    # ----------------------------------------------------

    if net_profit >= PROFIT_THRESHOLD:
        
        effective_volume = min(best_buy.get('volume', DEPOSIT), best_sell.get('volume', DEPOSIT))
        volume_used = min(DEPOSIT, effective_volume)
        estimated_earnings = DEPOSIT * net_profit if effective_volume >= DEPOSIT else volume_used * net_profit
        
        # ВИПРАВЛЕННЯ: Перехід на HTML-форматування
        message = (
            f"<b>💰 АРБІТРАЖ ЗНАЙДЕНО</b>\n"
            f"📈 Пара: <b>{symbol}</b>\n"
            f"🛒 Купити на <b>{best_buy['exchange'].upper()}</b> за <code>{best_buy['price']:.8f}</code> (Коміс.: {best_buy['fee_taker']*100:.2f}%)\n"
            f"💰 Продати на <b>{best_sell['exchange'].upper()}</b> за <code>{best_sell['price']:.8f}</code> (Коміс.: {best_sell['fee_taker']*100:.2f}%)\n"
            f"🔥 Чистий Прибуток: <b>{net_profit*100:.3f}%</b>\n"
            f"💼 Обсяг: ~<code>{volume_used:.2f} USDT</code>\n"
            f"💵 Оціночний заробіток: ~<code>{estimated_earnings:.2f} USDT</code>"
        )
        
        yield {
            'timestamp': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S'),
            'type': 'cross_exchange',
            'symbol': symbol,
            'buy_exchange': best_buy['exchange'],
            'sell_exchange': best_sell['exchange'],
            'buy_price': best_buy['price'],
            'sell_price': best_sell['price'],
            'profit': net_profit * 100,
            'volume': volume_used,
            'path': f"cross:{best_buy['exchange']}->{best_sell['exchange']}:{symbol}",
            'details': 'cross_exchange',
            'earnings': estimated_earnings,
            'message': message
        }