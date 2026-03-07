import os
import ccxt
import telebot
import time
import threading
from datetime import datetime
from collections import deque

# ================== ⚙️ إعدادات البيئة ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("MEXC_API_KEY")
SECRET = os.getenv("MEXC_SECRET")
USER_ID = int(os.getenv("MY_USER_ID"))

if not all([TELEGRAM_TOKEN, API_KEY, SECRET, USER_ID]):
    raise Exception("❌ تأكد من ضبط متغيرات البيئة")

# ================== 📊 إعدادات التداول ==================
TIMEFRAME = '3m'
FIXED_TRADE_USDT = 5
MAX_POSITIONS = 10
BATCH_SIZE = 10
MIN_BALANCE = 20

# ================== 🪙 قائمة العملات ==================
COINS = [
    "BTC", "ETH", "SOL", "ADA", "AVAX", "MATIC", "NEAR", "INJ", "ARB", "OP",
    "SUI", "APT", "SEI", "TIA", "FET", "RNDR", "AGIX", "OCEAN", "IMX", "STX",
    "PEPE", "BONK", "WIF", "ORDI", "PYTH", "JUP", "ONDO", "PENDLE"
]

# ================== 🤖 تهيئة البوت ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

exchange = ccxt.mexc({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

# ================== 📁 إدارة البيانات ==================
positions = {}
bot_running = True
total_pnl = 0.0
trade_history = deque(maxlen=100)
stats = {
    'total_trades': 0,
    'winning_trades': 0,
    'losing_trades': 0,
    'total_profit': 0.0
}

# ================== 💎 أدوات مساعدة ==================
def get_balance():
    try:
        balance = exchange.fetch_balance()
        return float(balance['free'].get('USDT', 0))
    except Exception as e:
        print(f"Balance Error: {e}")
        return 0.0

def format_message(title, body, emoji="🚀"):
    return f"""
╔══════════════════════════════════╗
║  {emoji} *{title}* 
╠══════════════════════════════════╣
║
║  {body}
║
╚══════════════════════════════════╝
"""

def format_table(data):
    if not data:
        return "📭 لا توجد بيانات"
    result = "```\n"
    result += f"{'العملة':<8} {'الدخول':<10} {'الآن':<10} {'الربح':<8}\n"
    result += "─" * 40 + "\n"
    for symbol, pos in data.items():
        try:
            ticker = exchange.fetch_ticker(f"{symbol}/USDT")
            current = ticker['last']
            profit = ((current - pos['entry']) / pos['entry']) * 100
            result += f"{symbol:<8} {pos['entry']:<10.4f} {current:<10.4f} {profit:>+6.2f}%\n"
        except:
            result += f"{symbol:<8} {'—':<10} {'—':<10} {'—':<8}\n"
    result += "```"
    return result

# ================== 🔍 فلتر السوق (بدون pandas) ==================
def market_safe():
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '5m', limit=50)
        closes = [x[4] for x in ohlcv]
        if len(closes) < 20:
            return True
        sma20 = sum(closes[-20:]) / 20
        current_price = closes[-1]
        return current_price > sma20
    except Exception as e:
        print(f"Market Safe Error: {e}")
        return False

# ================== ⚡ حساب قوة الزخم (بدون pandas) ==================
def momentum_score(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=30)
        if len(ohlcv) < 5:
            return 0
        closes = [x[4] for x in ohlcv]
        volumes = [x[5] for x in ohlcv]
        
        price_change = ((closes[-1] - closes[-3]) / closes[-3]) * 100
        recent_vol = volumes[-10:] if len(volumes) >= 10 else volumes
        avg_vol = sum(recent_vol) / len(recent_vol)
        current_vol = volumes[-1]
        volume_spike = current_vol / avg_vol if avg_vol > 0 else 1
        score = price_change * volume_spike
        return score
    except Exception as e:
        print(f"Momentum Score Error {symbol}: {e}")
        return 0

# ================== باقي الكود (كما هو بدون أي تغيير) ==================
# (كل الدوال execute_buy, execute_sell, monitor, scanner, الأوامر التليجرام ... إلخ)
# انسخ باقي الكود من الملف القديم اللي عندك بعد الدالة momentum_score

# ================== 🚀 تشغيل البوت ==================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ULTIMATE TRADING BOT 3M - بدون pandas")
    print("=" * 60)
    print("✅ البوت شغال الآن")
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"Bot Error: {e}")
        time.sleep(5)