# paper_trader.py
import asyncio
import logging
import os
from datetime import datetime, UTC
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from config import EXCHANGE_FEES, DEPOSIT, EXCHANGES, TOP_SYMBOLS, LOG_DIR

# Налаштування окремого логера
logger = logging.getLogger(__name__)
if not logger.handlers:
    os.makedirs(LOG_DIR, exist_ok=True)
    fh = logging.FileHandler(os.path.join(LOG_DIR, 'paper_trader.log'), encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.propagate = False

# Налаштування часу виконання операцій (у секундах)
TRADE_TIMINGS = {
    'buy': 5,
    'sell': 5,
    'withdraw': 120,
    'deposit': 60,
    'network_fee': {
        'BTC': 1.0,
        'ETH': 0.5,
        'SOL': 0.01,
        'USDT': 0.1,
        'default': 0.1
    }
}

@dataclass
class Balance:
    available: float = 0.0
    locked: float = 0.0

    def total(self) -> float:
        return self.available + self.locked

@dataclass
class ActiveTrade:
    trade_id: str
    symbol: str
    from_exchange: str
    to_exchange: str
    amount: float
    buy_price: float
    sell_price: float
    steps: List[str] = field(default_factory=list)
    current_step: int = 0
    start_time: float = 0
    end_time: Optional[float] = None
    profit_usd: float = 0.0
    status: str = "active"

class PaperTrader:
    def __init__(self):
        self.balances: Dict[str, Dict[str, Balance]] = defaultdict(lambda: defaultdict(Balance))
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.trade_counter: int = 0
        self.lock = asyncio.Lock()
        self._initialize_balances()

    def _initialize_balances(self):
        try:
            coins = set()
            for symbol in TOP_SYMBOLS:
                if '/' in symbol:
                    base = symbol.split('/')[0]
                    coins.add(base)
                elif symbol.endswith('USDT'):
                    base = symbol.replace('USDT', '')
                    coins.add(base)
                elif '-USDT-SWAP' in symbol:
                    base = symbol.replace('-USDT-SWAP', '')
                    coins.add(base)
                elif '_USDT' in symbol:
                    base = symbol.replace('_USDT', '')
                    coins.add(base)
            
            for exchange in EXCHANGES:
                self.balances[exchange]['USDT'] = Balance(available=10.0)
                for coin in coins:
                    if coin != 'USDT':
                        self.balances[exchange][coin] = Balance(available=10.0)
            logger.info(f"PaperTrader: ініціалізовано баланси для {len(EXCHANGES)} бірж, {len(coins)} монет")
        except Exception as e:
            logger.error(f"Помилка ініціалізації балансів: {e}")

    async def process_signal(self, opportunity: dict) -> bool:
        async with self.lock:
            try:
                strategy_type = opportunity.get('type')
                if strategy_type == 'cross_exchange':
                    return await self._handle_cross_exchange(opportunity)
                elif strategy_type == 'spot_futures':
                    return await self._handle_spot_futures(opportunity)
                elif strategy_type == 'triangular':
                    return await self._handle_triangular(opportunity)
                else:
                    logger.warning(f"Невідомий тип стратегії: {strategy_type}")
                    return False
            except Exception as e:
                logger.error(f"Помилка обробки сигналу: {e}")
                return False

    async def _handle_cross_exchange(self, opp: dict) -> bool:
        try:
            buy_ex = opp['buy_exchange']
            sell_ex = opp['sell_exchange']
            symbol = opp['symbol']
            buy_price = opp['buy_price']
            sell_price = opp['sell_price']
            base_coin = self._get_base_coin(symbol)
            if not base_coin:
                return False
            usdt_needed = 10.0
            if self.balances[buy_ex]['USDT'].available < usdt_needed:
                return False
            buy_fee = EXCHANGE_FEES.get(buy_ex, {}).get('spot', {}).get('taker', 0.001)
            sell_fee = EXCHANGE_FEES.get(sell_ex, {}).get('spot', {}).get('taker', 0.001)
            network_fee = TRADE_TIMINGS['network_fee'].get(base_coin, TRADE_TIMINGS['network_fee']['default'])
            base_bought = (usdt_needed * (1 - buy_fee)) / buy_price
            base_after_withdraw = base_bought - network_fee
            usdt_after_sell = base_after_withdraw * sell_price * (1 - sell_fee)
            net_profit = usdt_after_sell - usdt_needed
            if net_profit <= 0:
                return False
            self.balances[buy_ex]['USDT'].available -= usdt_needed
            self.balances[buy_ex]['USDT'].locked += usdt_needed
            self.trade_counter += 1
            trade_id = f"trade_{self.trade_counter}_{int(datetime.now().timestamp())}"
            trade = ActiveTrade(
                trade_id=trade_id,
                symbol=symbol,
                from_exchange=buy_ex,
                to_exchange=sell_ex,
                amount=usdt_needed,
                buy_price=buy_price,
                sell_price=sell_price,
                steps=['buy', 'withdraw', 'deposit', 'sell'],
                start_time=datetime.now().timestamp()
            )
            self.active_trades[trade_id] = trade
            logger.info(f"Запущено арбітражну угоду {trade_id}: {buy_ex} → {sell_ex} ({symbol})")
            return True
        except Exception as e:
            logger.error(f"Помилка обробки cross_exchange: {e}")
            return False

    def _get_base_coin(self, symbol: str) -> Optional[str]:
        try:
            if '/' in symbol:
                return symbol.split('/')[0]
            elif symbol.endswith('USDT'):
                return symbol.replace('USDT', '')
            elif '-USDT-SWAP' in symbol:
                return symbol.replace('-USDT-SWAP', '')
            elif '_USDT' in symbol:
                return symbol.replace('_USDT', '')
            return None
        except Exception as e:
            logger.error(f"Помилка визначення базової валюти для {symbol}: {e}")
            return None

    async def _handle_spot_futures(self, opp: dict) -> bool:
        try:
            exchange = opp['buy_exchange']
            symbol = opp['symbol']
            usdt_needed = 10.0
            if self.balances[exchange]['USDT'].available < usdt_needed:
                return False
            self.balances[exchange]['USDT'].available -= usdt_needed
            self.balances[exchange]['USDT'].locked += usdt_needed
            self.trade_counter += 1
            trade_id = f"trade_{self.trade_counter}_{int(datetime.now().timestamp())}"
            trade = ActiveTrade(
                trade_id=trade_id,
                symbol=symbol,
                from_exchange=exchange,
                to_exchange=exchange,
                amount=usdt_needed,
                buy_price=opp['buy_price'],
                sell_price=opp['sell_price'],
                steps=['buy_spot', 'sell_futures'],
                start_time=datetime.now().timestamp()
            )
            self.active_trades[trade_id] = trade
            logger.info(f"Запущено спот-ф'ючерс угоду {trade_id} на {exchange}")
            return True
        except Exception as e:
            logger.error(f"Помилка обробки spot_futures: {e}")
            return False

    async def _handle_triangular(self, opp: dict) -> bool:
        try:
            exchange = opp['buy_exchange']
            usdt_needed = 10.0
            if self.balances[exchange]['USDT'].available < usdt_needed:
                return False
            self.balances[exchange]['USDT'].available -= usdt_needed
            self.balances[exchange]['USDT'].locked += usdt_needed
            self.trade_counter += 1
            trade_id = f"trade_{self.trade_counter}_{int(datetime.now().timestamp())}"
            trade = ActiveTrade(
                trade_id=trade_id,
                symbol=opp['symbol'],
                from_exchange=exchange,
                to_exchange=exchange,
                amount=usdt_needed,
                buy_price=0,
                sell_price=0,
                steps=['triangular_cycle'],
                start_time=datetime.now().timestamp()
            )
            self.active_trades[trade_id] = trade
            logger.info(f"Запущено трикутну угоду {trade_id} на {exchange}")
            return True
        except Exception as e:
            logger.error(f"Помилка обробки triangular: {e}")
            return False

    async def update_trades(self) -> List[dict]:
        completed_trades = []
        current_time = datetime.now().timestamp()
        async with self.lock:
            trades_to_remove = []
            for trade_id, trade in self.active_trades.items():
                try:
                    elapsed = current_time - trade.start_time
                    if trade.from_exchange == trade.to_exchange:
                        total_time = 15
                    else:
                        total_time = (
                            TRADE_TIMINGS['buy'] + 
                            TRADE_TIMINGS['withdraw'] + 
                            TRADE_TIMINGS['deposit'] + 
                            TRADE_TIMINGS['sell']
                        )
                    if elapsed >= total_time:
                        profit_usd = self._calculate_profit(trade)
                        trade.profit_usd = profit_usd
                        trade.end_time = current_time
                        trade.status = "completed"
                        if trade.from_exchange == trade.to_exchange:
                            self.balances[trade.from_exchange]['USDT'].locked -= trade.amount
                            self.balances[trade.from_exchange]['USDT'].available += (trade.amount + profit_usd)
                        else:
                            self.balances[trade.from_exchange]['USDT'].locked -= trade.amount
                            self.balances[trade.from_exchange]['USDT'].available += (trade.amount + profit_usd)
                        completed_trades.append({
                            'trade_id': trade_id,
                            'profit_usd': profit_usd,
                            'duration': elapsed,
                            'from_exchange': trade.from_exchange,
                            'to_exchange': trade.to_exchange,
                            'symbol': trade.symbol
                        })
                        trades_to_remove.append(trade_id)
                        logger.info(f"Угода {trade_id} завершена. Прибуток: {profit_usd:.4f} USDT за {elapsed:.1f} сек")
                except Exception as e:
                    logger.error(f"Помилка оновлення угоди {trade_id}: {e}")
            for trade_id in trades_to_remove:
                if trade_id in self.active_trades:
                    del self.active_trades[trade_id]
        return completed_trades

    def _calculate_profit(self, trade: ActiveTrade) -> float:
        try:
            if trade.from_exchange == trade.to_exchange:
                if trade.buy_price and trade.sell_price:
                    return trade.amount * (trade.sell_price / trade.buy_price - 1)
                return 0.0
            else:
                base_coin = self._get_base_coin(trade.symbol)
                buy_fee = EXCHANGE_FEES.get(trade.from_exchange, {}).get('spot', {}).get('taker', 0.001)
                sell_fee = EXCHANGE_FEES.get(trade.to_exchange, {}).get('spot', {}).get('taker', 0.001)
                network_fee = TRADE_TIMINGS['network_fee'].get(base_coin, TRADE_TIMINGS['network_fee']['default'])
                base_bought = (trade.amount * (1 - buy_fee)) / trade.buy_price
                base_after_withdraw = base_bought - network_fee
                usdt_after_sell = base_after_withdraw * trade.sell_price * (1 - sell_fee)
                return usdt_after_sell - trade.amount
        except Exception as e:
            logger.error(f"Помилка розрахунку прибутку для угоди: {e}")
            return 0.0

    def get_summary(self) -> dict:
        try:
            total_usdt = 0.0
            for exchange in self.balances:
                if 'USDT' in self.balances[exchange]:
                    total_usdt += self.balances[exchange]['USDT'].total()
            balances_dict = {}
            for ex, coins in self.balances.items():
                coin_dict = {}
                for coin, bal in coins.items():
                    total_bal = bal.total()
                    if total_bal > 0:
                        coin_dict[coin] = total_bal
                if coin_dict:
                    balances_dict[ex] = coin_dict
            return {
                'total_balance_usdt': total_usdt,
                'active_trades': len(self.active_trades),
                'balances': balances_dict
            }
        except Exception as e:
            logger.error(f"Помилка в get_summary: {e}")
            return {
                'total_balance_usdt': 0.0,
                'active_trades': 0,
                'balances': {}
            }