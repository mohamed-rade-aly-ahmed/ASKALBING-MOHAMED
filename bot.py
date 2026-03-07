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
USER_ID = int(os.getenv("MY_USER_ID") or 0)

if not all([TELEGRAM_TOKEN, API_KEY, SECRET, USER_ID]):
    raise Exception("❌ تأكد من ضبط متغيرات البيئة (TELEGRAM_TOKEN, MEXC_API_KEY, MEXC_SECRET, MY_USER_ID)")

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

try:
    exchange.load_markets()
except Exception as e:
    print(f"خطأ في تحميل الأسواق: {e}")

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
            profit = ((current - pos['entry']) / pos['entry']) * 100 if pos['entry'] > 0 else 0
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
        
        price_change = ((closes[-1] - closes[-3]) / closes[-3]) * 100 if closes[-3] > 0 else 0
        recent_vol = volumes[-10:] if len(volumes) >= 10 else volumes
        avg_vol = sum(recent_vol) / len(recent_vol) if recent_vol else 1
        current_vol = volumes[-1]
        volume_spike = current_vol / avg_vol if avg_vol > 0 else 1
        score = price_change * volume_spike
        return score
    except Exception as e:
        print(f"Momentum Score Error {symbol}: {e}")
        return 0

# ================== مراقبة المراكز (placeholder بسيط) ==================
def monitor():
    while bot_running:
        try:
            if positions:
                print(f"Monitor: {len(positions)} مركز مفتوح حاليًا")
                # هنا يمكن إضافة منطق trailing stop أو إغلاق تلقائي لاحقًا
            time.sleep(60)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(120)

# ================== مسح السوق بحثًا عن فرص (placeholder بسيط) ==================
def scanner():
    while bot_running:
        try:
            if get_balance() < MIN_BALANCE:
                print("رصيد منخفض، توقف المسح مؤقتًا")
                time.sleep(300)
                continue

            if not market_safe():
                print("السوق غير آمن حاليًا (BTC تحت SMA20)")
                time.sleep(60)
                continue

            print("Scanner: جاري فحص العملات...")
            # هنا يمكن إضافة منطق الشراء التلقائي لاحقًا
            time.sleep(15)
        except Exception as e:
            print(f"Scanner error: {e}")
            time.sleep(60)

# ================== 🚀 تشغيل البوت ==================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ULTIMATE TRADING BOT 3M - نسخة نظيفة بدون pandas")
    print("=" * 60)
    print(f"  رصيد USDT المتاح: {get_balance():.2f}")
    print(f"  عدد العملات: {len(COINS)}")
    print(f"  حالة البوت: {'شغال' if bot_running else 'متوقف'}")
    print("=" * 60)

    # تشغيل الخيوط (الآن موجودة ومعرفة)
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"خطأ في تشغيل البوت: {e}")
        time.sleep(10)