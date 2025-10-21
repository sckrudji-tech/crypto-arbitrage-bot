# config.py
import os
from dotenv import load_dotenv

# Завантаження змінних із .env
load_dotenv()

# Базовий каталог проекту
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Каталоги для логів і даних
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Налаштування логування
LOG_FILE = os.path.join(LOG_DIR, 'arbitrage.log')
LOG_MAX_BYTES = 10_000_000
LOG_BACKUP_COUNT = 5

# Налаштування бота
MIN_VOLUME = 5000
DEPOSIT = 100
OUTPUT_CSV = os.path.join(DATA_DIR, "arbitrage_history.csv")
FLASK_PORT = 5000
DEPTH_LEVELS = 10
PROFIT_THRESHOLD = 0.002  # 0.02%
ARBITRAGE_LOOP_DELAY = 2.0
BYBIT_BATCH_SIZE = 10

# Біржі
EXCHANGES = ['binance', 'bybit', 'okx', 'bitget', 'gateio']
RECV_WINDOW = 30000

# Комісії
EXCHANGE_FEES = {
    'binance': {
        'spot': {'maker': 0.00075, 'taker': 0.00075},
        'futures': {'maker': 0.0002, 'taker': 0.0004}
    },
    'bybit': {
        'spot': {'maker': 0.001, 'taker': 0.001},
        'futures': {'maker': 0.0001, 'taker': 0.0006}
    },
    'okx': {
        'spot': {'maker': 0.0008, 'taker': 0.001},
        'futures': {'maker': 0.0002, 'taker': 0.0005}
    },
    'bitget': {
        'spot': {'maker': 0.001, 'taker': 0.001},
        'futures': {'maker': 0.0002, 'taker': 0.0006}
    },
    'gateio': {
        'spot': {'maker': 0.002, 'taker': 0.002},
        'futures': {'maker': 0.00015, 'taker': 0.0005}
    },
}

# Ключі API
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_SECRET_KEY = os.getenv("BYBIT_SECRET_KEY")
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
GATEIO_API_KEY = os.getenv("GATEIO_API_KEY")
GATEIO_SECRET_KEY = os.getenv("GATEIO_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "640473693")

# Список торгових пар
TOP_SYMBOLS = [
    # Спот
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 
    'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'TRX/USDT', 'LTC/USDT', 'BCH/USDT',
    'MATIC/USDT', 'LINK/USDT', 'NEAR/USDT', 'ATOM/USDT', 'UNI/USDT', 'ETC/USDT', 
    'FIL/USDT', 'XLM/USDT', 'EGLD/USDT', 'FTM/USDT', 'HBAR/USDT', 'ICP/USDT', 
    'AAVE/USDT', 'SAND/USDT', 'MANA/USDT', 'AXS/USDT', 'GALA/USDT', 'ENS/USDT',
    
    # Binance ф'ючерси
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'BNB/USDT:USDT', 'SOL/USDT:USDT', 
    'XRP/USDT:USDT', 'ADA/USDT:USDT', 'AVAX/USDT:USDT', 'DOGE/USDT:USDT',
    'DOT/USDT:USDT', 'TRX/USDT:USDT', 'LTC/USDT:USDT', 'BCH/USDT:USDT',
    'MATIC/USDT:USDT', 'LINK/USDT:USDT', 'NEAR/USDT:USDT', 'ATOM/USDT:USDT',
    
    # OKX SWAP
    'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'BNB-USDT-SWAP', 'SOL-USDT-SWAP',
    'XRP-USDT-SWAP', 'ADA-USDT-SWAP', 'AVAX-USDT-SWAP', 'DOGE-USDT-SWAP',
    'DOT-USDT-SWAP', 'TRX-USDT-SWAP', 'LTC-USDT-SWAP', 'BCH-USDT-SWAP',
    'MATIC-USDT-SWAP', 'LINK-USDT-SWAP', 'NEAR-USDT-SWAP', 'ATOM-USDT-SWAP',
    
    # Bitget
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
    'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT', 'LTCUSDT', 'BCHUSDT',
    'MATICUSDT', 'LINKUSDT', 'NEARUSDT', 'ATOMUSDT',
    
    # Gate.io
    'BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'SOL_USDT', 'XRP_USDT', 'ADA_USDT',
    'AVAX_USDT', 'DOGE_USDT', 'DOT_USDT', 'TRX_USDT', 'LTC_USDT', 'BCH_USDT',
    'MATIC_USDT', 'LINK_USDT', 'NEAR_USDT', 'ATOM_USDT',
    
    # Трикутний арбітраж
    'BTC/ETH', 'ETH/BTC', 'SOL/BTC', 'XRP/BTC', 'ADA/BTC', 'DOT/BTC', 'LTC/BTC',
    'SOL/ETH', 'XRP/ETH', 'ADA/ETH', 'DOT/ETH', 'LTC/ETH'
]