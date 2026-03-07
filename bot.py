import os
import ccxt
import telebot
import pandas as pd
import time
import threading
from datetime import datetime

# ================== إعدادات البيئة ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("MEXC_API_KEY")
SECRET = os.getenv("MEXC_SECRET")
USER_ID = int(os.getenv("MY_USER_ID"))

if not all([TELEGRAM_TOKEN, API_KEY, SECRET, USER_ID]):
    raise Exception("❌ تأكد من ضبط متغيرات البيئة")

# ================== إعدادات التداول ==================
TIMEFRAME = '3m'           # سكالب سريع
FIXED_TRADE_USDT = 5       # 5$ لكل صفقة
MAX_POSITIONS = 10         # 10 صفقات متزامنة
BATCH_SIZE = 10            # يفحص 10 عملات في كل مرة

# كل العملات (مختارة للسرعة)
COINS = [
"BTC","ETH","SOL","ADA","AVAX","MATIC","NEAR","INJ","ARB","OP",
"SUI","APT","SEI","TIA","FET","RNDR","AGIX","OCEAN","IMX","STX",
"PEPE","BONK","WIF","ORDI","PYTH","JUP","ONDO","PENDLE"
]

# ================== تهيئة البوت ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

exchange = ccxt.mexc({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

positions = {}
bot_running = True
total_pnl = 0.0

# ================== أدوات مساعدة ==================
def get_balance():
    try:
        balance = exchange.fetch_balance()
        return balance['free'].get('USDT', 0)
    except:
        return 0

def format_message(title, body):
    return f"""
╔══════════════════════╗
║   🚀 {title}
╠══════════════════════╣
{body}
╚══════════════════════╝
"""

# ================== فلتر السوق (BTC) ==================
def market_safe():
    """يتحقق أن BTC فوق EMA200"""
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '5m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['ema200'] = df['c'].ewm(span=200).mean()
        return df.iloc[-1].c > df.iloc[-1].ema200
    except:
        return False

# ================== حساب قوة الزخم ==================
def momentum_score(symbol):
    """يحسب قوة الاختراق"""
    try:
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=30)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        
        if len(df) < 5:
            return 0
        
        # تغير السعر آخر 3 شموع
        change = ((df['c'].iloc[-1] - df['c'].iloc[-3]) / df['c'].iloc[-3]) * 100
        
        # انفجار الحجم
        vol_avg = df['v'].rolling(10).mean().iloc[-1]
        vol_spike = df['v'].iloc[-1] / vol_avg if vol_avg > 0 else 1
        
        return change * vol_spike
    except:
        return 0

# ================== إدارة الصفقات ==================
def calculate_sl_tp(price):
    """SL 3% / TP 6%"""
    sl = price * 0.97
    tp = price * 1.06
    return sl, tp

def execute_buy(symbol, price, amount):
    """تنفيذ شراء"""
    try:
        exchange.create_market_buy_order(f"{symbol}/USDT", amount)
        sl, tp = calculate_sl_tp(price)
        positions[symbol] = {
            "entry": price,
            "sl": sl,
            "tp": tp,
            "size": amount,
            "entry_time": datetime.now()
        }
        return True
    except Exception as e:
        print(f"Buy Error {symbol}: {e}")
        return False

def execute_sell(symbol, price, size):
    """تنفيذ بيع"""
    try:
        exchange.create_market_sell_order(f"{symbol}/USDT", size)
        if symbol in positions:
            entry = positions[symbol]['entry']
            profit = ((price - entry) / entry) * 100
            positions.pop(symbol, None)
            return True, profit
        return True, 0
    except Exception as e:
        print(f"Sell Error {symbol}: {e}")
        return False, 0

# ================== مراقبة المراكز ==================
def monitor():
    """يراقب المراكز ويطبق SL/TP/Trailing"""
    global total_pnl
    
    while True:
        if not bot_running:
            time.sleep(5)
            continue
        
        try:
            for symbol in list(positions.keys()):
                try:
                    ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                    price = ticker['last']
                    pos = positions[symbol]
                    
                    entry = pos['entry']
                    sl = pos['sl']
                    tp = pos['tp']
                    size = pos['size']
                    
                    profit = ((price - entry) / entry) * 100
                    
                    # Trailing Stop Logic
                    if profit >= 2:
                        new_sl = entry * 1.01
                        if new_sl > sl:
                            pos['sl'] = new_sl
                    
                    if profit >= 4:
                        new_sl = entry * 1.03
                        if new_sl > sl:
                            pos['sl'] = new_sl
                    
                    # Exit Conditions
                    if price <= pos['sl'] or price >= tp:
                        success, pnl = execute_sell(symbol, price, size)
                        if success:
                            total_pnl += pnl
                            status = "✅ TP" if price >= tp else "🛑 SL"
                            bot.send_message(USER_ID, 
                                format_message(status,
                                    f"{symbol}\nالسعر: {price:.4f}\nالربح: {pnl:.2f}%"))
                            
                except Exception as e:
                    print(f"Monitor Error {symbol}: {e}")
                    
        except Exception as e:
            print(f"Monitor Loop Error: {e}")
        
        time.sleep(3)

# ================== ماسح الإشارات ==================
def scanner():
    """يبحث عن إشارات الشراء"""
    while True:
        if not bot_running:
            time.sleep(10)
            continue
        
        try:
            # حد أقصى للمراكز
            if len(positions) >= MAX_POSITIONS:
                time.sleep(10)
                continue
            
            # فلتر السوق (BTC يجب أن يكون فوق EMA200)
            if not market_safe():
                time.sleep(30)
                continue
            
            # التحقق من الرصيد
            balance = get_balance()
            if balance < 20:
                time.sleep(30)
                continue
            
            # جمع نقاط كل العملات (على دفعات)
            scores = []
            
            for i in range(0, len(COINS), BATCH_SIZE):
                batch = COINS[i:i+BATCH_SIZE]
                
                for coin in batch:
                    if coin in positions:
                        continue
                    try:
                        score = momentum_score(coin)
                        scores.append((coin, score))
                    except:
                        continue
                
                time.sleep(1)  # تجنب Rate Limit
            
            # اختيار أقوى 3 عملات فقط
            scores.sort(key=lambda x: x[1], reverse=True)
            top_coins = [c[0] for c in scores[:3] if c[1] > 0]
            
            # محاولة الشراء
            for coin in top_coins:
                if len(positions) >= MAX_POSITIONS:
                    break
                
                try:
                    ticker = exchange.fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
                    amount = FIXED_TRADE_USDT / price
                    
                    # التحقق من الحد الأدنى
                    market = exchange.market(f"{coin}/USDT")
                    min_amount = market['limits']['amount']['min']
                    
                    if amount >= min_amount:
                        if execute_buy(coin, price, amount):
                            bot.send_message(USER_ID,
                                format_message("🟢 شراء",
                                    f"{coin}\nالسعر: {price:.4f}\nالكمية: {amount:.6f}"))
                            time.sleep(2)
                            
                except Exception as e:
                    print(f"Buy Error {coin}: {e}")
                    
        except Exception as e:
            print(f"Scanner Error: {e}")
        
        time.sleep(15)

# ================== أوامر التليجرام ==================
@bot.message_handler(commands=['start'])
def start(msg):
    if msg.chat.id != USER_ID:
        return
    
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 الحالة"),
        telebot.types.KeyboardButton("💰 المراكز"),
        telebot.types.KeyboardButton("🚨 بيع الكل"),
        telebot.types.KeyboardButton("📈 الإحصائيات"),
        telebot.types.KeyboardButton("⏸ إيقاف/تشغيل")
    )
    
    bot.send_message(msg.chat.id,
        format_message("ULTIMATE BOT 3M",
            "✅ النظام يعمل\n⚡ سكalp سريع 3 دقائق\n💰 صفقة: 5$\n🎯 أقصى: 10 صفقات"),
        reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def commands(msg):
    if msg.chat.id != USER_ID:
        return
    
    text = msg.text
    
    if text == "📊 الحالة":
        balance = get_balance()
        bot.send_message(msg.chat.id,
            format_message("📊 الحالة",
                f"💰 الرصيد: {balance:.2f} USDT\n📈 المراكز: {len(positions)}/10\n🚀 البوت: {'يعمل' if bot_running else 'متوقف'}"))
    
    elif text == "💰 المراكز":
        if not positions:
            bot.send_message(msg.chat.id, "❌ لا توجد مراكز مفتوحة")
            return
        
        msg_text = ""
        for symbol, pos in positions.items():
            try:
                ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                current = ticker['last']
                profit = ((current - pos['entry']) / pos['entry']) * 100
                msg_text += f"{symbol}: {profit:+.2f}%\n"
            except:
                msg_text += f"{symbol}: --\n"
        
        bot.send_message(msg.chat.id,
            format_message("💰 المراكز المفتوحة", msg_text))
    
    elif text == "🚨 بيع الكل":
        if not positions:
            bot.send_message(msg.chat.id, "❌ لا توجد مراكز لبيعها")
            return
        
        count = 0
        for symbol in list(positions.keys()):
            try:
                ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                size = positions[symbol]['size']
                success, _ = execute_sell(symbol, ticker['last'], size)
                if success:
                    count += 1
            except:
                pass
        
        bot.send_message(msg.chat.id,
            format_message("🚨 بيع الكل",
                f"تم بيع {count} مركز\nمن أصل {len(positions)}"))
    
    elif text == "📈 الإحصائيات":
        # حساب أداء اليوم
        today = datetime.now().date()
        bot.send_message(msg.chat.id,
            format_message("📈 إحصائيات",
                f"💰 الرصيد الحالي: {get_balance():.2f} USDT\n"
                f"📊 المراكز المفتوحة: {len(positions)}\n"
                f"🎯 أقصى مراكز: {MAX_POSITIONS}\n"
                f"💵 قيمة الصفقة: {FIXED_TRADE_USDT}$\n"
                f"📅 تاريخ التشغيل: {today}"))
    
    elif text == "⏸ إيقاف/تشغيل":
        global bot_running
        bot_running = not bot_running
        status = "✅ يعمل" if bot_running else "⏸ متوقف"
        bot.send_message(msg.chat.id,
            format_message("الحالة", status))

# ================== تشغيل البوت ==================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ULTIMATE TRADING BOT 3M")
    print("=" * 60)
    print("✅ البوت يعمل من خلال تليجرام فقط")
    print(f"💰 صفقة: {FIXED_TRADE_USDT}$")
    print(f"🎯 أقصى مراكز: {MAX_POSITIONS}")
    print(f"📊 العملات: {len(COINS)} عملة")
    print("=" * 60)
    print("👨‍💻 أرسل /start في تليجرام")
    print("=" * 60)
    
    # بدء الخيوط
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    
    # تشغيل البوت
    bot.infinity_polling()